# tests/unit/test_dmx_masks.py
"""Phase 0 of docs/output-sync-plan.md: the per-universe channel claim
mask in DMXManager.

The mask is what the output arbiter merges by: 1 = this renderer
deliberately drives the channel this frame (a written 0 is a claim to
zero), 0 = unclaimed, falls through to the layer below. clear_all_dmx
resets values AND claims; update_dmx starts every frame from that
reset, so after update_dmx the mask is exact for the frame.

Uses the shared mock fixture definition (tests/conftest.py): mode
"Standard", 10 channels at address 1 (0-indexed base 0) - dimmer 0,
RGBW 1-4, pan 5, tilt 6, pan/tilt fine 7-8, gobo 9. The mock def has
no shutter and no colour wheel, so the safe idle state claims exactly
pan/tilt (+fine).
"""

import pytest

from config.models import (
    Configuration, DimmerBlock, ColourBlock, Fixture, FixtureGroup,
    FixtureGroupCapabilities, FixtureMode, Universe,
)
from utils.artnet.dmx_manager import DMXManager


@pytest.fixture
def fixture_defs(mock_fixture_def):
    return {"TestMfr_TestModel": mock_fixture_def}


@pytest.fixture
def test_fixture():
    return Fixture(
        universe=0, address=1, manufacturer="TestMfr", model="TestModel",
        name="MH1", group="TestGroup", current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
        type="MH", x=1.0, y=2.0, z=3.0,
    )


@pytest.fixture
def test_config(test_fixture):
    group = FixtureGroup(
        name="TestGroup", fixtures=[test_fixture],
        capabilities=FixtureGroupCapabilities(
            has_dimmer=True, has_colour=True, has_movement=True,
        ),
    )
    return Configuration(
        fixtures=[test_fixture],
        groups={"TestGroup": group},
        universes={0: Universe(id=0, name="Universe 0", output={})},
    )


@pytest.fixture
def manager(test_config, fixture_defs):
    return DMXManager(test_config, fixture_defs)


def claimed(manager, universe=0):
    """The set of claimed channel numbers, for readable asserts."""
    return {ch for ch, bit in enumerate(manager.get_touched_mask(universe))
            if bit}


# The mock fixture's channel layout (base address 0).
DIMMER = 0
RGBW = {1, 2, 3, 4}
PAN_TILT = {5, 6, 7, 8}   # incl. fine
GOBO = 9
# What the safe idle state claims for this def. Pan/tilt centering,
# PLUS the RGBW channels: get_channels_by_property matches by preset
# OR group, the RGBW channels carry group "Colour", and "Colour" is in
# FixtureChannelMap's colour-wheel property list - so the "colour
# wheel to open" idle write (value 0) lands on them. Long-standing
# behaviour, invisible on the wire before masks existed; kept in
# phase 0 (no behaviour change), revisit with the arbiter if a lower
# layer's colour must show through idle playback.
SAFE_IDLE = PAN_TILT | RGBW


class TestClaims:
    def test_starts_unclaimed(self, manager):
        assert claimed(manager) == set()

    def test_write_claims_the_channel(self, manager):
        manager.set_dmx_value(0, 5, 200)
        assert claimed(manager) == {5}
        assert manager.get_dmx_data(0)[5] == 200

    def test_zero_write_is_a_claim_to_zero(self, manager):
        manager.set_dmx_value(0, 7, 0)
        assert claimed(manager) == {7}
        assert manager.get_dmx_data(0)[7] == 0

    def test_clear_all_drops_values_and_claims(self, manager):
        manager.set_dmx_value(0, 5, 200)
        manager.clear_all_dmx()
        assert claimed(manager) == set()
        assert manager.get_dmx_data(0) == bytes(512)

    def test_unknown_universe_write_ignored(self, manager):
        manager.set_dmx_value(99, 0, 100)  # must not raise
        assert manager.get_touched_mask(99) == bytes(512)

    def test_get_frame_pairs_values_and_mask(self, manager):
        manager.set_dmx_value(0, 3, 128)
        values, mask = manager.get_frame(0)
        assert (values[3], mask[3]) == (128, 1)
        assert (values[4], mask[4]) == (0, 0)
        assert len(values) == len(mask) == 512

    def test_get_frame_unknown_universe(self, manager):
        assert manager.get_frame(99) == (bytes(512), bytes(512))

    def test_rebuilt_universe_gets_a_mask(self, manager, test_config):
        test_config.fixtures[0].universe = 2
        manager.rebuild_fixture_maps()
        manager.set_dmx_value(2, 0, 10)
        assert claimed(manager, universe=2) == {0}


class TestFrameMasks:
    def test_idle_frame_claims_safe_state_only(self, manager):
        # No active blocks: update_dmx applies only the safe idle state
        # (see SAFE_IDLE above). The dimmer stays unclaimed.
        manager.update_dmx(0.0)
        assert claimed(manager) == SAFE_IDLE

    def test_dimmer_block_adds_its_channel(self, manager, test_config):
        block = DimmerBlock(start_time=0.0, end_time=10.0, intensity=255.0,
                            effect_type="static")
        manager.block_started("lane", test_config.fixtures, block,
                              "dimmer", 0.0)
        manager.update_dmx(1.0)
        assert DIMMER in claimed(manager)
        assert manager.get_dmx_data(0)[DIMMER] == 255

    def test_colour_block_adds_colour_channels(self, manager, test_config):
        block = ColourBlock(start_time=0.0, end_time=10.0,
                            color_mode="RGB", red=255.0)
        manager.block_started("lane", test_config.fixtures, block,
                              "colour", 0.0)
        manager.update_dmx(1.0)
        assert RGBW <= claimed(manager)

    def test_block_end_releases_its_claims(self, manager, test_config):
        block = DimmerBlock(start_time=0.0, end_time=10.0, intensity=255.0,
                            effect_type="static")
        manager.block_started("lane", test_config.fixtures, block,
                              "dimmer", 0.0)
        manager.update_dmx(1.0)
        assert DIMMER in claimed(manager)
        manager.block_ended("lane", "dimmer")
        manager.update_dmx(2.0)
        # Next frame recomputes from scratch: the dimmer claim is gone,
        # the safe idle claims remain.
        assert claimed(manager) == SAFE_IDLE

    def test_unmapped_address_space_stays_unclaimed(self, manager,
                                                    test_config):
        block = DimmerBlock(start_time=0.0, end_time=10.0, intensity=255.0,
                            effect_type="static")
        manager.block_started("lane", test_config.fixtures, block,
                              "dimmer", 0.0)
        manager.update_dmx(1.0)
        # The fixture occupies channels 0-9; nothing above is claimed.
        assert all(ch <= GOBO for ch in claimed(manager))

    def test_fixtures_visible_claims_look_channels(self, manager):
        manager.set_fixtures_visible()
        # Visible idle drives dimmer, RGBW and pan/tilt centering (the
        # mock def has no shutter / colour wheel channels to claim).
        assert claimed(manager) == {DIMMER} | RGBW | PAN_TILT
