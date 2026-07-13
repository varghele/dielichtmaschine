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

SLOTS = ("effect", "intensity", "movement")

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

    ``manager_factory(song_structure)`` returns a fresh private
    DMXManager for a slot - the gui wires it with the real config and
    fixture definitions and MUST pass ``emit_safe_idle=False``; tests
    inject stubs. A fresh manager per stage() keeps the claims exactly
    as wide as the staged lanes and follows config changes naturally.
    """

    def __init__(self, manager_factory: Callable) -> None:
        self._manager_factory = manager_factory
        self._slots: Dict[str, _Slot] = {}
        self._bpm = 120.0

    # -- staging ----------------------------------------------------------

    def stage(self, slot: str, lanes, loop_beats: float,
              bpm: float) -> None:
        """Stage synthetic lanes into a slot, replacing what ran there.

        ``lanes``: iterable of (fixtures, light_blocks) pairs;
        ``loop_beats``: loop length in beats; ``bpm``: the tempo the
        blocks' second-times were built against (usually the live bpm
        at staging time). The loop starts at beat 0 on the next render.
        """
        if slot not in SLOTS:
            raise ValueError(f"unknown live slot: {slot!r}")
        if loop_beats <= 0 or bpm <= 0:
            raise ValueError("loop_beats and bpm must be positive")
        manager = self._manager_factory(OnePartStructure(bpm))
        self._slots[slot] = _Slot(manager, lanes, loop_beats, bpm)

    def kill(self, slot: str) -> None:
        """Drop a slot: its claims vanish on the next render."""
        self._slots.pop(slot, None)

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
        return [s for s in SLOTS if s in self._slots]

    # -- rendering ---------------------------------------------------------

    def render(self, now: float) -> Frame:
        """The merged (values, mask) frame across all slots at wall
        time ``now`` - later SLOTS entries override earlier ones per
        claimed channel."""
        frames = []
        for slot_name in SLOTS:
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
        manager = record.manager
        manager.clear_active_blocks()
        for index, (fixtures, light_blocks) in enumerate(record.lanes):
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


class LiveEffectsBinder:
    """Maps LiveState's EFFECTS staging onto the engine's "effect" slot
    (docs/live-output-plan.md phase 3).

    ``sync()`` is idempotent and cheap; the gui connects it to
    ``LiveState.state_changed`` (Qt main thread - the engine's slot
    swaps are build-then-assign, safe against the arbiter's render
    thread). It:

    - stages the riff behind ``state.effect`` when the key or the
      SELECTION SCOPE changes (riff scoping rule: one synthetic lane
      per selected group, blocks from Riff.to_light_block at the bpm
      current at staging time, loop = riff.length_beats). A restage
      restarts the loop at beat 0 - the plan's "restage on selection
      change" call.
    - follows LiveState.bpm every sync (phase-continuous - the engine
      rescales, the lanes are NOT rebuilt).
    - maps the "effect" running record's paused flag onto the slot
      clock (the queue's pause row freezes the riff mid-pose).
    - kills the slot when the effect clears (second touch, KILL row,
      RELEASE ALL) or when the scope resolves to no fixtures - silence
      is a kill, not an empty stage.
    """

    def __init__(self, state, engine: LiveEngine,
                 config_provider: Callable,
                 riff_provider: Callable) -> None:
        self._state = state
        self._engine = engine
        self._config_provider = config_provider
        self._riff_provider = riff_provider
        # (effect key, frozenset of selected groups) actually staged.
        self._staged: Optional[tuple] = None

    def sync(self) -> None:
        state = self._state
        engine = self._engine
        engine.set_bpm(state.bpm)

        key = getattr(state, "effect", None)
        if not key:
            if self._staged is not None:
                engine.kill("effect")
                self._staged = None
            return

        scope = frozenset(state.selected)
        if (key, scope) != self._staged:
            lanes, loop_beats = self._build_lanes(key, scope, state.bpm)
            if lanes:
                engine.stage("effect", lanes, loop_beats, state.bpm)
            else:
                engine.kill("effect")
            self._staged = (key, scope)

        record = next((r for r in state.running
                       if r.get("kind") == "effect"), None)
        engine.pause("effect", bool(record and record.get("paused")))

    def _build_lanes(self, key: str, scope, bpm: float):
        """(lanes, loop_beats) for a riff key over the selected groups;
        ([], 0) when the riff or every group resolves empty."""
        riff = self._riff_provider(key)
        config = self._config_provider()
        if riff is None or config is None:
            return [], 0.0
        loop_beats = float(getattr(riff, "length_beats", 0.0) or 0.0)
        if loop_beats <= 0:
            return [], 0.0
        structure = OnePartStructure(bpm)
        lanes = []
        for group_name in sorted(scope):
            group = (getattr(config, "groups", {}) or {}).get(group_name)
            fixtures = list(getattr(group, "fixtures", None) or []) \
                if group is not None else []
            if not fixtures:
                continue
            lanes.append((fixtures,
                          [riff.to_light_block(0.0, structure)]))
        return lanes, loop_beats
