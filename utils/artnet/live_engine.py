# utils/artnet/live_engine.py
"""The Live tab's clock-driven playback engine
(docs/live-output-plan.md phase 2).

The engine does NOT reimplement effects. Each SLOT ("effect",
"intensity", "movement") owns a PRIVATE DMXManager (created through the
injected factory with ``emit_safe_idle=False``, so it claims ONLY what
its staged blocks drive) fed with SYNTHETIC lanes - plain LightBlocks
whose sublane blocks the existing playback resolve renders. A looping
beat clock replays them forever:

- The loop position advances in BEATS at the LIVE bpm
  (:meth:`set_bpm`, fed from LiveState/TAP), incrementally per render
  tick - a tempo change rescales playback speed without a phase jump
  and WITHOUT rebuilding the staged lanes.
- The staged blocks keep their own seconds timescale: they were built
  against ``build_bpm`` (the tempo at staging time), so the virtual
  time handed to update_dmx is ``beat_pos * 60 / build_bpm``. The
  private manager's song structure carries the same build tempo, so
  bar-relative effect speeds stay consistent with the block times.
- Scheduling per render is stateless: the active sublane block per
  type at the virtual time is installed via block_started (latest
  start wins inside a lane, mirroring playback LTP), everything else
  is dropped. Loop wrap-around therefore needs no bookkeeping.

Slots run concurrently; their frames merge in SLOT order with later
slots overriding earlier ones per claimed channel ("effect" under
"intensity" under "movement"). The merged frame is meant to sit UNDER
the busk layer's explicit writes (a touched swatch beats a running
riff) - that composition happens in the busk layer, not here.

``pause`` freezes the slot's frame (the exact frame keeps streaming,
the clock stops); ``kill`` drops the slot and its claims. ``stage`` on
an occupied slot replaces it (newest wins).
"""

from typing import Callable, Dict, List, Optional, Tuple

Frame = Dict[int, Tuple[bytes, bytes]]

#: Slot CATEGORIES, in merge order. A slot key is either a bare
#: category ("intensity", "movement") or a namespaced
#: "category:suffix" ("effect:Front Pars" - the per-group effects,
#: 2026-07-22): every group runs its own slot with its own loop
#: length, clock and pause flag, so different riffs coexist and
#: pausing one never freezes another.
SLOTS = ("effect", "intensity", "movement")


def _slot_category(slot: str) -> str:
    return slot.split(":", 1)[0]

_SUBLANES = ("dimmer", "colour", "movement", "special")


class OnePartStructure:
    """A constant-tempo stand-in for SongStructure: the one method the
    block resolve consumes (get_bpm_at_time) at a fixed bpm. Used both
    for the private managers and by callers building synthetic lanes
    via Riff.to_light_block."""

    def __init__(self, bpm: float) -> None:
        self.bpm = float(bpm)

    def get_bpm_at_time(self, _time: float) -> float:
        return self.bpm


class _Slot:
    def __init__(self, manager, lanes, loop_beats: float,
                 build_bpm: float) -> None:
        self.manager = manager
        # [(fixtures, [LightBlock, ...]), ...] - fixtures pre-resolved
        # by the caller (riff scoping happens at stage time).
        self.lanes = list(lanes)
        self.loop_beats = float(loop_beats)
        self.build_bpm = float(build_bpm)
        self.beat_pos = 0.0
        self.last_now: Optional[float] = None
        self.paused = False
        self.frozen_frame: Optional[Frame] = None


class LiveEngine:
    """One looping-clock engine for the Live pools.

    ``manager_factory(song_structure, config_override)`` returns a
    fresh private DMXManager for a slot - the gui wires it with the
    real config (or the override when given) and fixture definitions
    and MUST pass ``emit_safe_idle=False``; tests inject stubs. A
    fresh manager per stage() keeps the claims exactly as wide as the
    staged lanes and follows config changes naturally.
    """

    def __init__(self, manager_factory: Callable) -> None:
        self._manager_factory = manager_factory
        self._slots: Dict[str, _Slot] = {}
        self._bpm = 120.0

    # -- staging ----------------------------------------------------------

    def stage(self, slot: str, lanes, loop_beats: float,
              bpm: float, config_override=None,
              stage_planes=None, phase_from: Optional[str] = None) -> None:
        """Stage synthetic lanes into a slot, replacing what ran there.

        ``slot`` is a bare category or "category:suffix" (see SLOTS).
        ``lanes``: iterable of (fixtures, light_blocks) pairs;
        ``loop_beats``: loop length in beats; ``bpm``: the tempo the
        blocks' second-times were built against (usually the live bpm
        at staging time). The loop starts at beat 0 on the next render.
        ``config_override`` is handed to the manager factory (a
        transient view of the config, never the saved one).
        ``stage_planes`` (name -> StagePlane) go to the private
        manager's world-space movement path - the movement binder's
        orbit planes live here, one per fixture, so shapes trace in
        METERS around their anchor instead of raw DMX amplitude.
        ``phase_from`` names an existing slot whose clock the new slot
        adopts - a group JOINING an already-running riff starts in
        phase with it instead of at beat 0 (paused donors freeze the
        joiner at the same pose: the binder re-applies the paused flag
        right after staging).
        """
        if _slot_category(slot) not in SLOTS:
            raise ValueError(f"unknown live slot: {slot!r}")
        if loop_beats <= 0 or bpm <= 0:
            raise ValueError("loop_beats and bpm must be positive")
        manager = self._manager_factory(OnePartStructure(bpm),
                                        config_override)
        if stage_planes:
            manager.set_stage_planes(dict(stage_planes))
        record = _Slot(manager, lanes, loop_beats, bpm)
        donor = self._slots.get(phase_from) if phase_from else None
        if donor is not None:
            # Same riff, hence same loop length; the modulo makes a
            # mismatch safe rather than wrong.
            record.beat_pos = donor.beat_pos % record.loop_beats
            record.last_now = None if donor.paused else donor.last_now
        self._slots[slot] = record

    def kill(self, slot: str) -> None:
        """Drop a slot: its claims vanish on the next render."""
        self._slots.pop(slot, None)

    def kill_prefix(self, prefix: str) -> None:
        """Drop the bare ``prefix`` slot and every ``prefix:...``
        slot (the per-group effects family in one sweep)."""
        for key in [k for k in self._slots
                    if k == prefix or k.startswith(prefix + ":")]:
            del self._slots[key]

    def kill_all(self) -> None:
        self._slots.clear()

    def pause(self, slot: str, paused: bool = True) -> None:
        """Freeze (or resume) a slot's clock. While paused the last
        frame keeps streaming - a paused chase holds its pose instead
        of going dark. Idempotent: repeating the current flag is a
        no-op (the state binder calls this on every state change, and
        an unchanged flag must not re-anchor the running clock)."""
        record = self._slots.get(slot)
        if record is None or record.paused == bool(paused):
            return
        record.paused = bool(paused)
        if not paused:
            # Resuming: drop the freeze and re-anchor the clock so the
            # pause duration does not advance the loop.
            record.frozen_frame = None
            record.last_now = None

    def set_bpm(self, bpm: float) -> None:
        """The LIVE tempo every slot's clock advances at (TAP feeds
        this). Takes effect from the next render tick - phase
        continuous, no lane rebuild."""
        if bpm > 0:
            self._bpm = float(bpm)

    # -- introspection ----------------------------------------------------

    def is_active(self, slot: str) -> bool:
        return slot in self._slots

    def active_slots(self) -> List[str]:
        return self._ordered_slots()

    def _ordered_slots(self) -> List[str]:
        """Deterministic total merge order: categories in SLOTS order
        (intensity still overrides effect on shared channels), the
        bare slot before its group slots, group slots sorted by name -
        matching the old sorted-lane order, so shared-fixture
        conflicts resolve exactly as before."""
        return sorted(self._slots,
                      key=lambda s: (SLOTS.index(_slot_category(s)), s))

    # -- rendering ---------------------------------------------------------

    def render(self, now: float) -> Frame:
        """The merged (values, mask) frame across all slots at wall
        time ``now`` - later entries in the slot order override
        earlier ones per claimed channel."""
        frames = []
        for slot_name in self._ordered_slots():
            record = self._slots.get(slot_name)
            if record is None:
                continue
            if record.paused:
                if record.frozen_frame is None:
                    record.frozen_frame = self._render_slot(record)
                frames.append(record.frozen_frame)
                continue
            if record.last_now is not None:
                elapsed = max(0.0, now - record.last_now)
                record.beat_pos = (record.beat_pos
                                   + elapsed * self._bpm / 60.0) \
                    % record.loop_beats
            record.last_now = now
            frames.append(self._render_slot(record))
        return self._merge(frames)

    def _render_slot(self, record: _Slot) -> Frame:
        t = record.beat_pos * 60.0 / record.build_bpm
        loop_seconds = record.loop_beats * 60.0 / record.build_bpm
        manager = record.manager
        # Lanes may carry a per-lane TIME OFFSET as an optional third
        # element (the movement binder's stagger): update_dmx evaluates
        # every active block at ONE time, so offset groups render in
        # separate passes whose frames merge. Per-fixture lanes claim
        # disjoint channels, so pass order cannot conflict.
        by_offset: Dict[float, list] = {}
        for entry in record.lanes:
            fixtures, light_blocks = entry[0], entry[1]
            offset = float(entry[2]) if len(entry) > 2 else 0.0
            by_offset.setdefault(offset, []).append(
                (fixtures, light_blocks))
        frames = []
        for offset in sorted(by_offset):
            t_lane = (t + offset) % loop_seconds if loop_seconds > 0 \
                else t
            frames.append(self._render_lanes(manager,
                                             by_offset[offset], t_lane))
        return self._merge(frames)

    @staticmethod
    def _render_lanes(manager, lanes, t: float) -> Frame:
        manager.clear_active_blocks()
        for index, (fixtures, light_blocks) in enumerate(lanes):
            lane_key = f"live_lane_{index}"
            for light_block in light_blocks:
                for block_type in _SUBLANES:
                    blocks = getattr(light_block, f"{block_type}_blocks",
                                     None) or []
                    active = [b for b in blocks
                              if b.start_time <= t < b.end_time]
                    if active:
                        # Latest start wins - the playback LTP call.
                        block = max(active, key=lambda b: b.start_time)
                        manager.block_started(lane_key, fixtures, block,
                                              block_type, t)
        manager.update_dmx(t)
        frame: Frame = {}
        for universe in manager.dmx_state:
            values, mask = manager.get_frame(universe)
            if any(mask):
                frame[universe] = (values, mask)
        return frame

    @staticmethod
    def merge_frames(frames: List[Frame]) -> Frame:
        """Public alias of the slot merge - later frames override
        earlier ones per claimed channel."""
        return LiveEngine._merge(frames)

    @staticmethod
    def _merge(frames: List[Frame]) -> Frame:
        if not frames:
            return {}
        if len(frames) == 1:
            return frames[0]
        values: Dict[int, bytearray] = {}
        masks: Dict[int, bytearray] = {}
        for frame in frames:
            for universe, (frame_values, frame_mask) in frame.items():
                if universe not in values:
                    values[universe] = bytearray(512)
                    masks[universe] = bytearray(512)
                out_v, out_m = values[universe], masks[universe]
                for channel in range(512):
                    if frame_mask[channel]:
                        out_v[channel] = frame_values[channel]
                        out_m[channel] = 1
        return {u: (bytes(values[u]), bytes(masks[u])) for u in values}


class LiveGroupEffectsBinder:
    """Maps a LiveState PER-GROUP riff mapping (2026-07-22) onto one
    engine slot per group ("<category>:<group>") - different groups
    run different riffs simultaneously, each on its own loop length
    and pause flag. EFFECTS use the defaults; INTENSITY FX reuse the
    class with category="intensity", state_attr="intensities",
    record_kind="intensity" - each group's dimmer pattern runs under
    its colour riff.

    Semantics (the positions pattern): SELECTION scopes STAGING only -
    a staged key keeps running on its group after deselection; silence
    only when no group holds any key. ``sync()`` diffs the full
    mapping against what was last staged: removed groups kill their
    slot, added/changed groups stage a single-group lane (a group
    JOINING a riff already running elsewhere adopts that slot's phase
    via ``phase_from`` - no restart of the groups that did not
    change). An unknown riff key or an empty group silences ONLY its
    own slot. PAUSE maps per running record (one record per distinct
    riff key with its ``groups`` list) onto that record's group slots.
    """

    def __init__(self, state, engine: LiveEngine,
                 config_provider: Callable,
                 riff_provider: Callable,
                 category: str = "effect",
                 state_attr: str = "effects",
                 record_kind: str = "effect") -> None:
        self._state = state
        self._engine = engine
        self._config_provider = config_provider
        self._riff_provider = riff_provider
        self._category = category
        self._state_attr = state_attr
        self._record_kind = record_kind
        self._staged: Dict[str, str] = {}   # group -> ATTEMPTED riff key
        self._dimmer: set = set()           # groups whose riff has dimmers

    def dimmer_groups(self) -> frozenset:
        """Groups whose RUNNING riff drives dimmer sublanes - incl.
        deselected groups still running one (the busk dimmer must
        yield wherever the pattern actually runs). Same contract as
        it always was for the busk layer."""
        return frozenset(self._dimmer)

    def _slot(self, group_name: str) -> str:
        return f"{self._category}:{group_name}"

    def sync(self) -> None:
        state = self._state
        engine = self._engine
        engine.set_bpm(state.bpm)

        effects = dict(getattr(state, self._state_attr, None) or {})

        for group_name in [g for g in self._staged if g not in effects]:
            engine.kill(self._slot(group_name))
            del self._staged[group_name]
            self._dimmer.discard(group_name)

        for group_name in sorted(effects):
            key = effects[group_name]
            if self._staged.get(group_name) == key:
                continue
            lane, loop_beats, has_dimmer = self._build_group_lane(
                key, group_name, state.bpm)
            if lane is not None:
                donor = next(
                    (self._slot(g) for g in sorted(self._staged)
                     if g != group_name and self._staged[g] == key
                     and engine.is_active(self._slot(g))), None)
                engine.stage(self._slot(group_name), [lane], loop_beats,
                             state.bpm, phase_from=donor)
                if has_dimmer:
                    self._dimmer.add(group_name)
                else:
                    self._dimmer.discard(group_name)
            else:
                # Silence is a kill, not an empty stage - and it is
                # scoped to THIS group only.
                engine.kill(self._slot(group_name))
                self._dimmer.discard(group_name)
            # Record the ATTEMPT (also for failed builds): no re-probe
            # of a dead key on every sync, mirroring the old binder.
            self._staged[group_name] = key

        paused: Dict[str, bool] = {}
        for record in state.running:
            if record.get("kind") == self._record_kind:
                for group_name in record.get("groups") or ():
                    paused[group_name] = bool(record.get("paused"))
        for group_name in self._staged:
            engine.pause(self._slot(group_name),
                         paused.get(group_name, False))

    def _build_group_lane(self, key: str, group_name: str, bpm: float):
        """(lane|None, loop_beats, has_dimmer) for ONE group - the
        riff resolved, its fixtures gathered, one synthetic lane."""
        riff = self._riff_provider(key)
        config = self._config_provider()
        if riff is None or config is None:
            return None, 0.0, False
        loop_beats = float(getattr(riff, "length_beats", 0.0) or 0.0)
        if loop_beats <= 0:
            return None, 0.0, False
        group = (getattr(config, "groups", {}) or {}).get(group_name)
        fixtures = list(getattr(group, "fixtures", None) or []) \
            if group is not None else []
        if not fixtures:
            return None, 0.0, False
        structure = OnePartStructure(bpm)
        lane = (fixtures, [riff.to_light_block(0.0, structure)])
        return lane, loop_beats, bool(getattr(riff, "dimmer_blocks",
                                              None))


# Movement shapes loop over this many beats: at effect speed "1" the
# registry paces one full shape cycle per 4 bars
# (effects/timing.MOVEMENT_CYCLES_PER_BAR = 0.25), so a 16-beat block
# contains EXACTLY one cycle and the loop wrap is seamless.
SHAPE_LOOP_BEATS = 16.0

# Default orbit radius in METERS. Live shapes trace in stage space
# around their anchor (the world-plane movement path), NOT in raw DMX
# amplitude - 50 DMX was ~106 degrees of pan on a 540-degree head, so
# the orbit dwarfed a nearby target (bench finding 2026-07-13).
# LiveState.shape_size overrides this per session (the S/M/L chips).
SHAPE_ORBIT_RADIUS_M = 0.75
# The world-space movement path reads its amplitude in meters as
# block.pan_amplitude / 20 (dmx_manager._apply_movement_block).
_AMPLITUDE_PER_METER = 20.0


class SpotOverlayConfig:
    """A read-only VIEW of a Configuration with extra transient spots
    overlaid - the movement binder's anchor spots exist for the
    private manager's spot-targeting resolve only and never touch the
    real (saved) config. Everything else delegates to the base."""

    def __init__(self, base, extra_spots) -> None:
        self._base = base
        self.spots = dict(getattr(base, "spots", None) or {})
        self.spots.update(extra_spots)

    def __getattr__(self, name):
        return getattr(self._base, name)


class LiveMovementBinder:
    """Maps LiveState's PER-GROUP movement shapes (state.shapes:
    group -> MOVEMENT_REGISTRY rudiment id, 2026-07-22) onto one
    engine slot per mover group ("movement:<group>") - each group
    traces its own shape at its own anchor, and a shape keeps running
    after deselection (the effects pattern; docs/live-output-plan.md
    phase 4 for the orbit mechanics).

    Per group, staging builds one synthetic lane PER FIXTURE: a single
    MovementBlock with effect_type = the rudiment and
    target_plane_name = a transient HORIZONTAL ORBIT PLANE centred at
    the fixture's HELD POSITION target (state.positions, falling back
    to the CENTRE preset) resolved through the shared
    resolve_position_target. The world-space movement path then traces
    the shape in METERS on that plane (radius = LiveState.shape_size,
    default SHAPE_ORBIT_RADIUS_M) and aims per fixture through the
    verified solver each frame, so the beam stays within the chosen
    radius of the anchor regardless of throw distance - raw DMX
    amplitude did not (bench finding 2026-07-13). The output arbiter
    applies the hardware yoke conversion on the wire like any aim.
    Non-mover groups holding a shape id stay silent (their slot is
    never staged). Anchor/radius/stagger changes restage only the
    groups they affect (radius/stagger are global, so those restage
    every group). PAUSE maps per running record onto that record's
    group slots.

    Claims are pan/tilt coarse only (the playback movement path) -
    shapes can run dark, and the busk layer suppresses its own static
    position aim for covered groups (active_groups) so the orbit is
    not frozen by the anchor claim.
    """

    def __init__(self, state, engine: LiveEngine,
                 config_provider: Callable) -> None:
        self._state = state
        self._engine = engine
        self._config_provider = config_provider
        # group -> (key, anchor, radius, stagger) actually attempted.
        self._staged: Dict[str, tuple] = {}
        self._covered: set = set()

    def active_groups(self) -> frozenset:
        """Groups a shape currently covers (selected or not) - the
        busk layer suppresses its static position aim for these."""
        return frozenset(self._covered)

    def sync(self) -> None:
        from utils.position_presets import group_has_movers
        state = self._state
        engine = self._engine
        engine.set_bpm(state.bpm)

        config = self._config_provider()
        shapes = dict(getattr(state, "shapes", None) or {})
        radius = float(getattr(state, "shape_size", 0.0)
                       or SHAPE_ORBIT_RADIUS_M)
        stagger = max(0.0, min(1.0, float(
            getattr(state, "shape_stagger", 0)) / 100.0))

        for group_name in [g for g in self._staged if g not in shapes]:
            engine.kill(f"movement:{group_name}")
            del self._staged[group_name]
            self._covered.discard(group_name)

        for group_name in sorted(shapes):
            key = shapes[group_name]
            signature = (key, state.positions.get(group_name, ""),
                         radius, stagger)
            if self._staged.get(group_name) == signature:
                continue
            group = (getattr(config, "groups", {}) or {}).get(group_name)
            lanes, planes = ([], {})
            if group_has_movers(group):
                lanes, planes = self._build_lanes(
                    key, frozenset({group_name}), config, state.bpm,
                    radius, stagger)
            if lanes:
                engine.stage(
                    f"movement:{group_name}", lanes, SHAPE_LOOP_BEATS,
                    state.bpm, stage_planes=planes)
                self._covered.add(group_name)
            else:
                engine.kill(f"movement:{group_name}")
                self._covered.discard(group_name)
            self._staged[group_name] = signature

        paused: Dict[str, bool] = {}
        for record in state.running:
            if record.get("kind") == "shape":
                for group_name in record.get("groups") or ():
                    paused[group_name] = bool(record.get("paused"))
        for group_name in self._staged:
            engine.pause(f"movement:{group_name}",
                         paused.get(group_name, False))

    def _build_lanes(self, key: str, scope, config, bpm: float,
                     radius: float, stagger: float = 0.0):
        """(lanes, orbit_planes) - one lane per mover fixture, each
        with a horizontal orbit plane centred at its resolved anchor.
        ``radius`` is the orbit size in meters (block.pan_amplitude
        carries it as radius * _AMPLITUDE_PER_METER for the world
        path's amplitude_meters conversion). ``stagger`` (0..1)
        spreads the fixtures of each group around the loop: fixture i
        of n (sorted by stage x) leads by stagger * i/n of a full
        cycle via the per-lane time offset - 0 is unison, 1 an even
        fan around the whole shape."""
        from config.models import LightBlock, MovementBlock, StagePlane
        from utils.position_presets import (
            compute_presets, resolve_position_target,
        )
        if config is None or not scope:
            return [], {}
        presets_by_id = {p.preset_id: p for p in compute_presets(config)}
        loop_seconds = SHAPE_LOOP_BEATS * 60.0 / bpm
        amplitude = max(0.0, radius) * _AMPLITUDE_PER_METER
        lanes = []
        planes = {}
        for group_name in sorted(scope):
            group = (getattr(config, "groups", {}) or {}).get(group_name)
            anchor_id = self._state.positions.get(group_name) \
                or "preset:centre"
            fixtures = sorted(getattr(group, "fixtures", None) or [],
                              key=lambda f: f.x)
            total = len(fixtures)
            for index, fixture in enumerate(fixtures):
                target = resolve_position_target(
                    config, presets_by_id, anchor_id, fixture)
                if target is None:      # stale mark: fall back to centre
                    target = resolve_position_target(
                        config, presets_by_id, "preset:centre", fixture)
                if target is None:
                    continue
                plane_name = f"live:shape:{group_name}:{fixture.name}"
                # Horizontal orbit plane: the shape traces on a level
                # disc at the anchor's height (a circle around a spike
                # mark reads as a circle ON the mark).
                planes[plane_name] = StagePlane(
                    name=plane_name, point=tuple(target),
                    normal=(0.0, 0.0, 1.0),
                    u_axis=(1.0, 0.0, 0.0), v_axis=(0.0, 1.0, 0.0))
                block = MovementBlock(
                    start_time=0.0, end_time=loop_seconds,
                    effect_type=key, target_plane_name=plane_name,
                    pan_amplitude=amplitude)
                light_block = LightBlock(start_time=0.0,
                                         end_time=loop_seconds,
                                         effect_name="")
                light_block.movement_blocks.append(block)
                offset = stagger * loop_seconds * index / total \
                    if total > 1 else 0.0
                lanes.append(([fixture], [light_block], offset))
        return lanes, planes
