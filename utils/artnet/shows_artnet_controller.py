# utils/artnet/shows_artnet_controller.py
# Timeline playback as an output-arbiter layer (docs/output-sync-plan.md
# phase 1). Public API kept from the pre-arbiter controller so the
# Shows tab wiring is unchanged.

import threading
from PyQt6.QtCore import QObject
from typing import Optional, Dict, Tuple, List, Callable

from config.models import Configuration
from utils.target_resolver import resolve_targets_unique
from .arbiter import Frame, IDLE_VISIBLE, OutputArbiter
from .dmx_manager import DMXManager
from .sender import ArtNetSender

# Debug flag - set to False to disable verbose prints
DEBUG_PRINTS = False

# The playback-slot owner tag; Auto mode uses "auto".
SLOT_OWNER = "timeline"

# Playback layer states. Stopped renders nothing (the arbiter floor
# shows through - "fixtures visible" in the editor, exactly the old
# stop_playback behaviour but continuously refreshed). Paused holds
# and keeps re-sending the last rendered frame instead of dropping to
# the floor mid-song.
_STOPPED = "stopped"
_PLAYING = "playing"
_PAUSED = "paused"


class ShowsArtNetController(QObject):
    """
    Timeline playback producer for the Shows tab.

    Since the arbiter pass this no longer owns a socket or a send
    thread: it renders (values, mask) frames on demand as the
    arbiter's PLAYBACK layer, at the arbiter's 44 Hz cadence (the old
    private loop ran at 30). The DMXManager stays the renderer; block
    scheduling from the light lanes is unchanged.

    The arbiter is created here (private) in phase 1; phase 2 shares
    one arbiter between timeline and Auto via the ``arbiter`` kwarg.
    """

    def __init__(self, config: Configuration, fixture_definitions: dict,
                 song_structure=None, target_ip: str = "255.255.255.255",
                 local_dmx_callback: Optional[Callable[[int, bytes], None]] = None,
                 arbiter: Optional[OutputArbiter] = None):
        """
        Args:
            config: Configuration with fixtures and universes
            fixture_definitions: Dictionary of parsed fixture definitions
            song_structure: Optional SongStructure for BPM-aware timing
            target_ip: Target IP for ArtNet packets (default: broadcast)
            local_dmx_callback: Optional callback ``(universe, dmx_bytes)``
                invoked with each post-merge frame. Lets the embedded
                in-process visualizer mirror what's on the wire.
            arbiter: Optional shared OutputArbiter. When omitted a
                private one is created (owning its own ArtNetSender at
                ``target_ip``).
        """
        super().__init__()

        self.config = config
        self.fixture_definitions = fixture_definitions

        # Renderer (no socket): DMX state + channel maps + block engine.
        self.dmx_manager = DMXManager(config, fixture_definitions, song_structure)

        # The arbiter owns the sender and the 44 Hz loop. The sender is
        # constructed HERE from this module's namespace so tests can
        # monkeypatch shows_artnet_controller.ArtNetSender.
        self._owns_arbiter = arbiter is None
        if arbiter is None:
            arbiter = OutputArbiter(
                config=config, sender=ArtNetSender(target_ip=target_ip))
        self.arbiter = arbiter
        # Kept for introspection/back-compat (the arbiter owns it).
        self.artnet_sender = arbiter._sender

        self.arbiter.set_fixture_maps(self.dmx_manager.fixture_maps)
        self.arbiter.set_local_dmx_callback(local_dmx_callback)

        # Output enabled flag (mirrors arbiter.running).
        self.output_enabled = False

        # Playback state consumed by render() on the arbiter thread;
        # the render lock serialises it against UI-thread mutations.
        self._render_lock = threading.RLock()
        self._state = _STOPPED
        self._last_frames: Frame = {}

        # Current playback time (set from ShowsTab or callback)
        self.current_time = 0.0

        # Position callback for getting fresh audio position each frame.
        self._position_callback: Optional[Callable[[], float]] = None

        # Track active blocks per lane - used for detecting block endings
        # lane_key -> {sublane_type -> set of block ids}
        self.active_block_ids: Dict[str, Dict[str, set]] = {}

        # Reference to light lanes (set from ShowsTab)
        self.light_lanes = []

        # PERFORMANCE: Cache resolved fixtures per lane
        # lane_id -> (targets_tuple, resolved_fixtures, sorted_fixtures)
        self._resolved_fixtures_cache: Dict[int, Tuple[tuple, List, List]] = {}

        # Track fixture fingerprint to avoid redundant rebuilds
        self._last_fixture_fingerprint = self._get_fixture_fingerprint()

        print("ShowsArtNet Controller initialized (arbiter layer)")

    # -- wiring ------------------------------------------------------------

    def set_position_callback(self, callback: Callable[[], float]):
        """Set callback for sample-accurate audio position; render()
        pulls it every frame."""
        self._position_callback = callback

    def set_song_structure(self, song_structure):
        """Update song structure for BPM-aware calculations."""
        self.dmx_manager.set_song_structure(song_structure)

    def set_light_lanes(self, lanes: list):
        """Set light lanes for processing."""
        with self._render_lock:
            self.light_lanes = lanes
            self._resolved_fixtures_cache.clear()

    def set_local_dmx_callback(
        self, callback: Optional[Callable[[int, bytes], None]]
    ) -> None:
        """Update or clear the embedded-visualizer DMX callback."""
        self.arbiter.set_local_dmx_callback(callback)

    def set_target_ip(self, ip: str):
        """Set target IP address for ArtNet packets."""
        self.arbiter.set_target_ip(ip)
        print(f"ArtNet target IP set to: {ip}")

    def _get_fixture_fingerprint(self) -> str:
        """Fingerprint of current fixtures for change detection."""
        parts = []
        for f in self.config.fixtures:
            parts.append(f"{f.name}:{f.universe}:{f.address}:{f.current_mode}")
        return "|".join(sorted(parts))

    def update_fixtures(self, force: bool = False):
        """Rebuild fixture mappings when fixtures are added, removed,
        or modified; the arbiter refreshes its floor and class masks
        from the new maps."""
        current_fingerprint = self._get_fixture_fingerprint()
        if not force and current_fingerprint == self._last_fixture_fingerprint:
            return

        self._last_fixture_fingerprint = current_fingerprint
        with self._render_lock:
            self.dmx_manager.rebuild_fixture_maps()
            self._resolved_fixtures_cache.clear()
        self.arbiter.set_fixture_maps(self.dmx_manager.fixture_maps)
        print(f"ShowsArtNet: Fixture mappings updated ({len(self.config.fixtures)} fixtures)")

    # -- output / transport ------------------------------------------------

    def enable_output(self) -> bool:
        """Enable output: start the arbiter loop as the MASTER output
        switch (the idle floor and the Live busk layer stream). The
        exclusive playback slot is deliberately NOT claimed here -
        enabling output to busk must not lock Auto mode out; the
        timeline claims the slot when it actually PLAYS."""
        # The Shows tab is an editor context: idle keeps the rig
        # visible for authoring. Only a PRIVATE arbiter takes its
        # policy from the producer - on the shared one the shell owns
        # the policy (it follows the active nav section).
        if self._owns_arbiter:
            self.arbiter.set_idle_policy(IDLE_VISIBLE)
        self.output_enabled = True
        self.arbiter.start()
        print("ArtNet output enabled")
        return True

    def disable_output(self):
        """Disable output: release the slot (if playing) and stop the
        loop with one blackout. On a SHARED arbiter the loop is only
        stopped when no OTHER producer holds the playback slot - never
        out from under a running Auto mode."""
        self.output_enabled = False
        with self._render_lock:
            self._state = _STOPPED
            self._last_frames = {}
        self.arbiter.release_playback_slot(SLOT_OWNER)
        if self._owns_arbiter \
                or self.arbiter.playback_slot_owner() is None:
            self.arbiter.stop(blackout=True)
        print("ArtNet output disabled")

    def start_playback(self) -> bool:
        """Playback started: claim the exclusive playback slot and
        render fresh frames. Returns False - and renders nothing -
        when Auto mode holds the slot (timeline XOR auto applies at
        PLAY time; the transport itself may keep running without
        DMX)."""
        if not self.output_enabled:
            return True   # nothing streams; nothing to claim
        if not self.arbiter.acquire_playback_slot(self, SLOT_OWNER):
            print("ArtNet playback refused: Auto mode holds the playback slot")
            return False
        with self._render_lock:
            self._state = _PLAYING
        print("ArtNet output started")
        return True

    def pause_playback(self):
        """Playback paused: hold (and keep refreshing) the last frame
        instead of dropping to the idle floor mid-song. The slot stays
        claimed - a paused show still owns the rig."""
        with self._render_lock:
            if self._state == _PLAYING:
                self._state = _PAUSED
        print("ArtNet output paused")

    def stop_playback(self):
        """Playback stopped: clear block tracking, stop rendering and
        release the playback slot - the arbiter floor takes over
        (visible in the editor) and Auto may claim the slot."""
        with self._render_lock:
            self._state = _STOPPED
            self._last_frames = {}
            self.active_block_ids.clear()
            self.dmx_manager.clear_active_blocks()
        self.arbiter.release_playback_slot(SLOT_OWNER)
        print("ArtNet output stopped - idle floor takes over")

    def update_position(self, position: float):
        """Update current playback position (from ShowsTab). With a
        position callback set, block processing happens in render()
        with fresh audio position instead."""
        self.current_time = position
        if self.light_lanes and not self._position_callback:
            with self._render_lock:
                self._process_lane_blocks()

    def cleanup(self):
        """Cleanup resources. A private arbiter is shut down (socket
        closed); a shared one is released, and stopped only when no
        OTHER producer still holds the playback slot."""
        with self._render_lock:
            self._state = _STOPPED
            self._last_frames = {}
        was_enabled = self.output_enabled
        self.output_enabled = False
        self.arbiter.release_playback_slot(SLOT_OWNER)
        if self._owns_arbiter:
            self.arbiter.shutdown()
        elif was_enabled and self.arbiter.playback_slot_owner() is None:
            self.arbiter.stop(blackout=True)
        print("ShowsArtNet Controller cleaned up")

    # -- the arbiter layer contract -----------------------------------------

    def render(self, now: float) -> Frame:
        """One playback frame for the arbiter merge.

        Stopped: {} (floor shows through). Paused: the cached last
        frames, re-sent so the wire keeps refreshing. Playing: pull
        fresh audio position, process lane blocks, recompute DMX and
        return per-universe (values, mask) pairs.
        """
        with self._render_lock:
            if self._state == _STOPPED:
                return {}
            if self._state == _PAUSED:
                return self._last_frames

            if self._position_callback:
                try:
                    self.current_time = self._position_callback()
                except Exception:
                    pass  # keep last known position

            if self.light_lanes:
                self._process_lane_blocks()

            self.dmx_manager.update_dmx(self.current_time)

            frames: Frame = {}
            for universe_id in self.config.universes.keys():
                universe_int = int(universe_id)
                frames[universe_int] = self.dmx_manager.get_frame(universe_int)
            self._last_frames = frames
            return frames

    # -- lane block scheduling (unchanged behaviour) -------------------------

    def _get_resolved_fixtures_cached(self, lane) -> Tuple[List, List]:
        """Resolved and sorted fixtures for a lane, cached per targets."""
        lane_id = id(lane)

        targets = getattr(lane, 'fixture_targets', [])
        if not targets and hasattr(lane, 'fixture_group') and lane.fixture_group:
            targets = [lane.fixture_group]

        targets_tuple = tuple(targets)

        if lane_id in self._resolved_fixtures_cache:
            cached_targets, resolved, sorted_fixtures = self._resolved_fixtures_cache[lane_id]
            if cached_targets == targets_tuple:
                return resolved, sorted_fixtures

        resolved = resolve_targets_unique(targets, self.config)
        sorted_fixtures = sorted(resolved, key=lambda f: f.x) if resolved else []
        self._resolved_fixtures_cache[lane_id] = (targets_tuple, resolved, sorted_fixtures)
        return resolved, sorted_fixtures

    def _process_lane_blocks(self):
        """Process blocks for all lanes at current time."""
        for lane in self.light_lanes:
            if lane.muted:
                continue

            resolved_fixtures, _ = self._get_resolved_fixtures_cached(lane)
            if not resolved_fixtures:
                continue

            targets = getattr(lane, 'fixture_targets', [])
            if not targets and hasattr(lane, 'fixture_group') and lane.fixture_group:
                targets = [lane.fixture_group]

            # Unique lane key - id + name (multiple lanes can share a name).
            lane_key = f"{id(lane)}_{lane.name}" if lane.name else f"{id(lane)}_{targets[0]}" if targets else f"{id(lane)}_unknown"

            if lane_key not in self.active_block_ids:
                self.active_block_ids[lane_key] = {
                    'dimmer': set(), 'colour': set(),
                    'movement': set(), 'special': set(),
                }

            currently_active = {
                'dimmer': set(), 'colour': set(),
                'movement': set(), 'special': set(),
            }

            for light_block in lane.light_blocks:
                for sublane_type, sub_blocks in (
                    ('dimmer', light_block.dimmer_blocks),
                    ('colour', light_block.colour_blocks),
                    ('movement', light_block.movement_blocks),
                    ('special', light_block.special_blocks),
                ):
                    for sub_block in sub_blocks:
                        block_id = id(sub_block)
                        if sub_block.start_time <= self.current_time < sub_block.end_time:
                            currently_active[sublane_type].add(block_id)
                            if block_id not in self.active_block_ids[lane_key][sublane_type]:
                                if DEBUG_PRINTS:
                                    print(f"[{self.current_time:.2f}s] Starting {sublane_type} block on lane {lane.name}")
                                self.dmx_manager.block_started(
                                    lane_key, resolved_fixtures, sub_block,
                                    sublane_type, self.current_time)
                                self.active_block_ids[lane_key][sublane_type].add(block_id)

            # End blocks that are no longer active (granular per sublane)
            for sublane_type in ('dimmer', 'colour', 'movement', 'special'):
                ended_blocks = self.active_block_ids[lane_key][sublane_type] - currently_active[sublane_type]
                if ended_blocks:
                    if not currently_active[sublane_type]:
                        if DEBUG_PRINTS:
                            print(f"[{self.current_time:.2f}s] Ending {sublane_type} blocks on lane {lane.name}")
                        self.dmx_manager.block_ended(lane_key, sublane_type)
                    self.active_block_ids[lane_key][sublane_type] = currently_active[sublane_type]
