# tests/integration/test_artnet_output.py
"""Integration test for the ArtNet output path (docs/output-sync-plan.md
phase 1): ShowsArtNetController rendering as the arbiter's playback
layer, merged over the idle floor and dispatched through the sender.

Socket-free: the sender is a stub; frames are driven with
arbiter.tick_once() instead of the 44 Hz thread.

Run with: pytest tests/integration/test_artnet_output.py -v -m integration
"""

import pytest

pytestmark = pytest.mark.integration

from config.models import (
    Configuration, DimmerBlock, Fixture, FixtureGroup, FixtureMode,
    Universe,
)


class StubSender:
    def __init__(self, target_ip="255.255.255.255", target_port=6454):
        self.target_ip = target_ip
        self.sent = []

    def send_dmx(self, universe, dmx_data, force=False):
        self.sent.append((universe, bytes(dmx_data), force))
        return True

    def close(self):
        pass


@pytest.fixture
def config(mock_fixture_def):
    fixture = Fixture(
        universe=1, address=1, manufacturer="TestMfr", model="TestModel",
        name="MH1", group="G", current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
        type="MH",
    )
    return Configuration(
        fixtures=[fixture],
        groups={"G": FixtureGroup(name="G", fixtures=[fixture])},
        universes={1: Universe(id=1, name="Universe 1", output={})},
    )


@pytest.fixture
def controller(qapp, config, mock_fixture_def):
    from utils.artnet import OutputArbiter, ShowsArtNetController

    sender = StubSender()
    arbiter = OutputArbiter(config=config, sender=sender)
    controller = ShowsArtNetController(
        config=config,
        fixture_definitions={"TestMfr_TestModel": mock_fixture_def},
        arbiter=arbiter,
    )
    yield controller, sender
    controller.cleanup()


class TestArtNetOutput:
    def test_controller_creation(self, controller):
        ctrl, _ = controller
        assert ctrl.arbiter is not None
        assert "MH1" in ctrl.dmx_manager.fixture_maps

    def test_idle_tick_streams_visible_floor(self, controller):
        # Editor idle policy: not playing, the merged frame carries the
        # visible floor (dimmer full) mapped to the 0-based wire.
        ctrl, sender = controller
        merged = ctrl.arbiter.tick_once(0.0)
        assert merged[1][0] == 255            # dimmer channel of MH1
        assert sender.sent[-1][0] == 0        # config universe 1 -> wire 0
        assert sender.sent[-1][2] is True     # loop forces past rate limit

    def test_playback_block_overrides_floor(self, controller):
        ctrl, sender = controller
        block = DimmerBlock(start_time=0.0, end_time=10.0, intensity=128,
                            effect_type="static")
        ctrl.dmx_manager.block_started(
            "lane", list(ctrl.config.fixtures), block, "dimmer", 0.0)
        ctrl.enable_output()
        ctrl.arbiter.stop(blackout=False)     # drive ticks manually
        ctrl.start_playback()
        merged = ctrl.arbiter.tick_once(1.0)
        # Playback claims the dimmer at the block's value; the floor's
        # 255 does not HTP over it (floor is fall-through only).
        assert merged[1][0] == 128

    def test_stop_returns_to_floor(self, controller):
        ctrl, sender = controller
        block = DimmerBlock(start_time=0.0, end_time=10.0, intensity=128,
                            effect_type="static")
        ctrl.dmx_manager.block_started(
            "lane", list(ctrl.config.fixtures), block, "dimmer", 0.0)
        ctrl.enable_output()
        ctrl.arbiter.stop(blackout=False)
        ctrl.start_playback()
        ctrl.arbiter.tick_once(1.0)
        ctrl.stop_playback()
        merged = ctrl.arbiter.tick_once(2.0)
        assert merged[1][0] == 255            # visible floor again
