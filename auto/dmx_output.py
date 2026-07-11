"""
Auto DMX Controller - Auto mode as an output-arbiter layer
(docs/output-sync-plan.md phase 2).

Auto renders through the arbiter's EXCLUSIVE playback slot (timeline
XOR auto - starting one while the other holds the slot is refused,
never silently evicted). The engine tick and DMX computation happen
in ``render()`` at the arbiter's 44 Hz cadence (the old private loop
ran at 30); universe remapping and the broadcast visualizer mirror
are arbiter features now instead of a second private sender.
"""

from typing import Optional, Dict, Callable

from utils.artnet.arbiter import Frame, IDLE_BLACKOUT, OutputArbiter
from utils.artnet.dmx_manager import DMXManager
from utils.artnet.sender import ArtNetSender
from config.models import Configuration
from auto.engine import AutoShowEngine

# The slot owner tag; the Shows controller uses "timeline".
SLOT_OWNER = "auto"


class AutoDMXController:
    """Auto mode's playback-slot adapter."""

    def __init__(self, config: Configuration, fixture_definitions: dict,
                 target_ip: str = "192.168.1.151",
                 local_dmx_callback: Optional[Callable[[int, bytes], None]] = None,
                 arbiter: Optional[OutputArbiter] = None):
        """
        Args:
            config: Fixture configuration from the main app
            fixture_definitions: QLC+ fixture definition dicts
            target_ip: ArtNet target IP address
            local_dmx_callback: Optional ``(universe, dmx_bytes)`` hook
                invoked with each post-merge frame (embedded
                visualizer).
            arbiter: Optional shared OutputArbiter (from MainWindow).
                When omitted a private one is created.
        """
        self.config = config

        # Renderer (no socket).
        self.dmx_manager = DMXManager(config, fixture_definitions)

        self._owns_arbiter = arbiter is None
        if arbiter is None:
            arbiter = OutputArbiter(
                config=config, sender=ArtNetSender(target_ip=target_ip))
        else:
            arbiter.set_target_ip(target_ip)
        self.arbiter = arbiter
        # Kept for introspection/back-compat (the arbiter owns it).
        self.artnet_sender = arbiter._sender

        self.arbiter.set_fixture_maps(self.dmx_manager.fixture_maps)
        self.arbiter.set_local_dmx_callback(local_dmx_callback)

        # Auto is a live context: idle means blackout, not the
        # editor's "fixtures visible" floor. Only a PRIVATE arbiter
        # takes its policy from the producer - on the shared one the
        # shell owns the policy (it follows the active nav section,
        # and Auto lives inside LIVE, which idles to blackout anyway).
        if self._owns_arbiter:
            self.arbiter.set_idle_policy(IDLE_BLACKOUT)

        # Engine reference
        self._engine: Optional[AutoShowEngine] = None
        self._running = False

    # -- wiring ------------------------------------------------------------

    def set_engine(self, engine: AutoShowEngine):
        """Connect the Auto show engine."""
        self._engine = engine
        engine.set_dmx_manager(self.dmx_manager)

    def set_target_ip(self, ip: str):
        """Change ArtNet target IP at runtime."""
        self.arbiter.set_target_ip(ip)

    def set_mirror_to_visualizer(self, enabled: bool):
        """Enable/disable mirroring DMX to broadcast for the visualizer."""
        self.arbiter.set_broadcast_mirror(enabled)

    def set_local_dmx_callback(
        self, callback: Optional[Callable[[int, bytes], None]]
    ) -> None:
        """Update or clear the embedded-visualizer DMX hook after init."""
        self.arbiter.set_local_dmx_callback(callback)

    def set_universe_mapping(self, mapping: Dict[int, int]):
        """Set universe mapping.

        Args:
            mapping: {config_universe_id: artnet_universe_number}
                     e.g. {1: 0, 2: 1} for Enttec ODE port 0 + port 1
        """
        self.arbiter.set_universe_mapping(mapping)

    # -- transport -----------------------------------------------------------

    def start(self) -> bool:
        """Claim the playback slot and start streaming. Returns False
        (and starts nothing) when the timeline holds the slot - the
        caller surfaces that to the user."""
        if self._running:
            return True
        if not self.arbiter.acquire_playback_slot(self, SLOT_OWNER):
            return False

        if self._engine:
            self._engine.start()
        self._running = True
        self.arbiter.start()
        return True

    def stop(self):
        """Stop the engine, release the slot and black out. On a
        SHARED arbiter the loop is only stopped if Auto actually held
        the slot - a failed start must not kill the timeline's
        stream."""
        if self._engine:
            self._engine.stop()
        was_streaming = self._running
        self._running = False
        self.arbiter.release_playback_slot(SLOT_OWNER)
        if self._owns_arbiter:
            self.arbiter.shutdown()
        elif was_streaming:
            self.arbiter.stop(blackout=True)

    # -- the arbiter layer contract -------------------------------------------

    def render(self, now: float) -> Frame:
        """One Auto frame: advance the engine, recompute DMX, return
        per-universe (values, mask) pairs. Empty when not running."""
        if not self._running:
            return {}
        if self._engine:
            self._engine.tick(now)
        self.dmx_manager.update_dmx(now)
        frames: Frame = {}
        for universe_id in self.config.universes.keys():
            universe_int = int(universe_id)
            frames[universe_int] = self.dmx_manager.get_frame(universe_int)
        return frames
