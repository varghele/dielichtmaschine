# tests/unit/test_auto_dmx_controller.py
"""AutoDMXController as an arbiter playback layer (phase 2 of
docs/output-sync-plan.md).

Covers: rendering through the exclusive playback slot, the
timeline-XOR-auto refusal against a real ShowsArtNetController on one
SHARED arbiter, universe remap equivalence with the pre-arbiter
behaviour (config universe -> ArtNet wire universe), the blackout-idle
policy, the broadcast mirror delegation, and that stopping a
never-started Auto controller does not kill a shared arbiter's
running stream. Socket-free."""

import pytest

from config.models import (
    Configuration, Fixture, FixtureGroup, FixtureMode, Universe,
)
from auto.dmx_output import AutoDMXController
from utils.artnet.arbiter import OutputArbiter


class StubSender:
    def __init__(self, target_ip="255.255.255.255", target_port=6454):
        self.target_ip = target_ip
        self.sent = []
        self.closed = False

    def send_dmx(self, universe, dmx_data, force=False):
        self.sent.append((universe, bytes(dmx_data)))
        return True

    def close(self):
        self.closed = True


class StubEngine:
    """Minimal AutoShowEngine stand-in: records lifecycle + ticks
    (the real engine registers blocks with the DMX manager, which
    update_dmx then renders - the pipeline itself is covered by the
    DMXManager and integration tests)."""

    def __init__(self):
        self.dmx_manager = None
        self.started = False
        self.ticks = 0

    def set_dmx_manager(self, manager):
        self.dmx_manager = manager

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def tick(self, now):
        self.ticks += 1


def _config():
    fixtures = [
        Fixture(universe=1, address=1, manufacturer="TestMfr",
                model="TestModel", name="MH1", group="G",
                current_mode="Standard",
                available_modes=[FixtureMode(name="Standard", channels=10)],
                type="MH"),
        Fixture(universe=2, address=1, manufacturer="TestMfr",
                model="TestModel", name="MH2", group="G",
                current_mode="Standard",
                available_modes=[FixtureMode(name="Standard", channels=10)],
                type="MH"),
    ]
    return Configuration(
        fixtures=fixtures,
        groups={"G": FixtureGroup(name="G", fixtures=fixtures)},
        universes={1: Universe(id=1, name="U1", output={}),
                   2: Universe(id=2, name="U2", output={})},
    )


@pytest.fixture
def defs(mock_fixture_def):
    return {"TestMfr_TestModel": mock_fixture_def}


def _controller(config, defs, arbiter=None, callback=None):
    sender = StubSender()
    if arbiter is None:
        arbiter = OutputArbiter(config=config, sender=sender)
    controller = AutoDMXController(
        config, defs, target_ip="10.0.0.7",
        local_dmx_callback=callback, arbiter=arbiter)
    return controller, arbiter, sender


class TestAutoAdapter:
    def test_start_claims_slot_and_streams(self, defs):
        config = _config()
        controller, arbiter, sender = _controller(config, defs)
        arbiter_started = []
        assert controller.start() is True
        assert arbiter.playback_slot_owner() == "auto"
        arbiter.stop(blackout=False)          # drive ticks manually
        merged = arbiter.tick_once(0.0)
        # Running with no active engine blocks: safe idle claims pan/
        # tilt centering over the blackout floor.
        assert merged[1][5] == 127
        assert merged[1][0] == 0              # blackout idle, no visible floor

    def test_idle_policy_is_blackout(self, defs):
        config = _config()
        controller, arbiter, _ = _controller(config, defs)
        # Not running at all: floor only, and the floor is blackout.
        merged = arbiter.tick_once(0.0)
        assert merged[1] == bytearray(512)

    def test_target_ip_reaches_the_sender(self, defs):
        config = _config()
        controller, arbiter, sender = _controller(config, defs)
        assert sender.target_ip == "10.0.0.7"

    def test_universe_mapping_equivalence(self, defs):
        # Pre-arbiter behaviour: default mapping 1-based -> 0-based;
        # a user mapping overrides per universe.
        config = _config()
        controller, arbiter, sender = _controller(config, defs)
        controller.start()
        arbiter.stop(blackout=False)
        sender.sent.clear()
        arbiter.tick_once(0.0)
        assert sorted(u for u, _ in sender.sent) == [0, 1]

        controller.set_universe_mapping({1: 4, 2: 9})
        sender.sent.clear()
        arbiter.tick_once(0.0)
        assert sorted(u for u, _ in sender.sent) == [4, 9]

    def test_local_callback_gets_config_universes(self, defs):
        config = _config()
        received = []
        controller, arbiter, _ = _controller(
            config, defs, callback=lambda u, b: received.append((u, b)))
        controller.start()
        arbiter.stop(blackout=False)
        received.clear()
        arbiter.tick_once(0.0)
        assert sorted(u for u, _ in received) == [1, 2]
        assert all(len(b) == 512 for _, b in received)

    def test_mirror_delegates_to_arbiter(self, defs):
        config = _config()
        controller, arbiter, _ = _controller(config, defs)
        mirror = StubSender()
        arbiter.set_broadcast_mirror(False, sender=mirror)
        controller.set_mirror_to_visualizer(True)
        arbiter.tick_once(0.0)
        assert mirror.sent

    def test_engine_ticks_inside_render(self, defs):
        config = _config()
        controller, arbiter, _ = _controller(config, defs)
        engine = StubEngine()
        controller.set_engine(engine)
        assert engine.dmx_manager is controller.dmx_manager
        controller.start()
        assert engine.started
        arbiter.stop(blackout=False)
        # The loop may have ticked between start() and stop(); assert
        # the delta of one manual tick, not an absolute count.
        ticks_before = engine.ticks
        arbiter.tick_once(1.0)
        assert engine.ticks == ticks_before + 1
        controller.stop()
        assert not engine.started

    def test_stop_blacks_out_and_releases(self, defs):
        # The arbiter is injected here, so the controller treats it as
        # SHARED: stop() blacks out and releases but must not close
        # the socket (the shutdown-on-private path needs a real
        # ArtNetSender construction and is covered by the adapter's
        # owns-arbiter branch in the shows-controller e2e).
        config = _config()
        controller, arbiter, sender = _controller(config, defs)
        controller.start()
        controller.stop()
        assert arbiter.playback_slot_owner() is None
        assert sender.sent[-1][1] == bytes(512)
        assert not sender.closed


class TestSlotExclusivity:
    """timeline XOR auto on ONE shared arbiter, with the real
    ShowsArtNetController on the other side."""

    def _shows_controller(self, config, defs, arbiter):
        from utils.artnet.shows_artnet_controller import ShowsArtNetController
        return ShowsArtNetController(
            config=config, fixture_definitions=defs, arbiter=arbiter)

    def test_auto_refused_while_timeline_enabled(self, defs):
        config = _config()
        sender = StubSender()
        shared = OutputArbiter(config=config, sender=sender)
        shows = self._shows_controller(config, defs, shared)
        assert shows.enable_output() is True
        shared.stop(blackout=False)

        auto = AutoDMXController(config, defs, arbiter=shared)
        assert auto.start() is False
        assert shared.playback_slot_owner() == "timeline"
        # The refused stop() must NOT stop/blackout the shared stream.
        sender.sent.clear()
        auto.stop()
        assert sender.sent == []

    def test_timeline_refused_while_auto_runs(self, defs):
        config = _config()
        shared = OutputArbiter(config=config, sender=StubSender())
        auto = AutoDMXController(config, defs, arbiter=shared)
        assert auto.start() is True
        shared.stop(blackout=False)

        shows = self._shows_controller(config, defs, shared)
        assert shows.enable_output() is False
        assert shared.playback_slot_owner() == "auto"

    def test_slot_frees_after_stop(self, defs):
        config = _config()
        shared = OutputArbiter(config=config, sender=StubSender())
        auto = AutoDMXController(config, defs, arbiter=shared)
        assert auto.start() is True
        shared.stop(blackout=False)
        auto.stop()
        shows = self._shows_controller(config, defs, shared)
        assert shows.enable_output() is True
        shared.stop(blackout=False)
