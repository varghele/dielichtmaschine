# tests/unit/test_preflight_layer.py
"""utils/artnet/preflight_layer.py - the pre-flight rig-driving layer
(design doc 7.2, v1.5b phase 5), modeled on the Live busk layer.

Covers the per-drive-state channel claims (flash_full full white,
aim_spot pan/tilt+fines at the definition ranges plus full white,
rgb_steps stepping pure R/G/B, special_steps stepping the gobo wheel,
hold_aim_for_capture with live focus/zoom trim only where the
definition maps those channels), the one-item-at-a-time arm/disarm
contract with mask fall-through on release, and the exclusive
playback-slot attach/detach that never stops a loop another producer
streams through. Socket-free.

Fixture layout (shared mock def, base address 0): dimmer 0, RGBW 1-4,
pan 5, tilt 6, fines 7-8, gobo 9.
"""

import pytest

from config.models import (
    Configuration, Fixture, FixtureGroup, FixtureMode, Spot, Universe,
)
from utils.artnet.arbiter import IDLE_BLACKOUT, OutputArbiter
from utils.artnet.dmx_manager import FixtureChannelMap
from utils.artnet.preflight_layer import (
    PreflightRigLayer, RGB_STEPS, SLOT_OWNER, special_step_value,
)
from utils.orientation import calculate_pan_tilt, pan_tilt_to_dmx16

DIMMER, RED, GREEN, BLUE, WHITE, PAN = 0, 1, 2, 3, 4, 5
TILT, PAN_FINE, TILT_FINE, GOBO = 6, 7, 8, 9


def _fixture(name, address, x=0.0, model="TestModel"):
    return Fixture(
        universe=1, address=address, manufacturer="TestMfr", model=model,
        name=name, group="Movers", current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
        type="MH", x=x,
    )


def _setup(fixture_def, fixtures=None, spots=None):
    fixtures = fixtures if fixtures is not None else [
        _fixture("MH1", 1, x=-1.0), _fixture("MH2", 11, x=1.0)]
    config = Configuration(
        fixtures=fixtures,
        groups={"Movers": FixtureGroup(name="Movers", fixtures=fixtures)},
        universes={1: Universe(id=1, name="U1", output={})},
    )
    config.spots = spots or {}
    maps = {f.name: FixtureChannelMap(f, fixture_def, config)
            for f in fixtures}
    layer = PreflightRigLayer(config_provider=lambda: config,
                              fixture_maps=maps)
    return layer, config, maps


def _expected_aim16(fixture, target, config,
                    pan_range=540.0, tilt_range=270.0):
    """Reference 16-bit aim - the same primary-group orientation
    resolve the layer (and the busk layer) uses."""
    primary = config.groups.get(fixture.group) if fixture.group else None
    mounting, yaw, pitch, roll = fixture.get_effective_orientation(primary)
    pan_deg, tilt_deg = calculate_pan_tilt(
        fixture_x=fixture.x, fixture_y=fixture.y,
        fixture_z=fixture.get_effective_z(primary),
        target_x=target[0], target_y=target[1], target_z=target[2],
        mounting=mounting, yaw=yaw, pitch=pitch, roll=roll,
        pan_range=pan_range, tilt_range=tilt_range,
    )
    return pan_tilt_to_dmx16(pan_deg, tilt_deg, pan_range, tilt_range)


class TestArmDisarm:
    def test_disarmed_renders_nothing(self, qapp, mock_fixture_def):
        layer, _, _ = _setup(mock_fixture_def)
        assert layer.render(0.0) == {}

    def test_disarm_is_mask_fall_through(self, qapp, mock_fixture_def):
        layer, _, _ = _setup(mock_fixture_def)
        layer.arm({"group": "Movers", "action": "flash_full"})
        assert layer.render(0.0)
        layer.disarm()
        assert layer.render(0.0) == {}

    def test_arming_replaces_the_previous_item(self, qapp,
                                               mock_fixture_def):
        layer, _, _ = _setup(mock_fixture_def)
        layer.arm({"group": "Movers", "action": "rgb_steps"})
        layer.set_rgb_step(2)
        layer.arm({"group": "Movers", "action": "rgb_steps"})
        assert layer.rgb_step == 0            # steps reset on re-arm

    def test_unknown_group_or_action_claims_nothing(self, qapp,
                                                    mock_fixture_def):
        layer, _, _ = _setup(mock_fixture_def)
        layer.arm({"group": "Ghost", "action": "flash_full"})
        assert layer.render(0.0) == {}
        layer.arm({"song": "S", "action": "scrub"})
        assert layer.render(0.0) == {}


class TestFlashFull:
    def test_flash_claims_full_white_on_the_whole_group(
            self, qapp, mock_fixture_def):
        layer, _, _ = _setup(mock_fixture_def)
        layer.arm({"group": "Movers", "action": "flash_full"})
        values, mask = layer.render(0.0)[1]
        for base in (0, 10):                  # MH1 addr 1, MH2 addr 11
            assert mask[base + DIMMER] and values[base + DIMMER] == 255
            assert values[base + RED] == 255
            assert values[base + GREEN] == 255
            assert values[base + BLUE] == 255
            assert mask[base + WHITE] and values[base + WHITE] == 255
        # No aim, no gobo: a flash test claims intensity/colour only.
        assert mask[PAN] == 0 and mask[TILT] == 0
        assert mask[GOBO] == 0


class TestAimSpot:
    def test_aim_claims_pan_tilt_fines_and_full_white(
            self, qapp, mock_fixture_def):
        spots = {"Centre": Spot(name="Centre", x=0.0, y=0.0, z=1.0)}
        layer, config, _ = _setup(mock_fixture_def, spots=spots)
        layer.arm({"group": "Movers", "action": "aim_spot",
                   "spot": "Centre"})
        values, mask = layer.render(0.0)[1]
        for fixture, base in ((config.fixtures[0], 0),
                              (config.fixtures[1], 10)):
            pan_c, pan_f, tilt_c, tilt_f = _expected_aim16(
                fixture, (0.0, 0.0, 1.0), config)
            assert mask[base + PAN] and values[base + PAN] == pan_c
            assert mask[base + TILT] and values[base + TILT] == tilt_c
            assert values[base + PAN_FINE] == pan_f
            assert values[base + TILT_FINE] == tilt_f
            # Full white so the operator sees where the beams land.
            assert values[base + DIMMER] == 255
            assert values[base + WHITE] == 255

    def test_unknown_spot_still_flashes_but_never_aims(
            self, qapp, mock_fixture_def):
        layer, _, _ = _setup(mock_fixture_def, spots={})
        layer.arm({"group": "Movers", "action": "aim_spot",
                   "spot": "Ghost"})
        values, mask = layer.render(0.0)[1]
        assert mask[DIMMER] and values[DIMMER] == 255
        assert mask[PAN] == 0 and mask[TILT] == 0


class TestRgbSteps:
    def test_steps_pure_red_green_blue(self, qapp, mock_fixture_def):
        layer, _, _ = _setup(mock_fixture_def)
        layer.arm({"group": "Movers", "action": "rgb_steps"})
        for index, (red, green, blue) in enumerate(RGB_STEPS):
            layer.set_rgb_step(index)
            values, mask = layer.render(0.0)[1]
            assert (values[RED], values[GREEN], values[BLUE]) == \
                (red, green, blue)
            # The unused colour channels are CLAIMED (to zero) so the
            # show below cannot tint the sanity check.
            assert mask[RED] and mask[GREEN] and mask[BLUE]
            assert mask[WHITE] and values[WHITE] == 0
            assert values[DIMMER] == 255

    def test_step_index_wraps(self, qapp, mock_fixture_def):
        layer, _, _ = _setup(mock_fixture_def)
        layer.set_rgb_step(4)
        assert layer.rgb_step == 1


class TestSpecialSteps:
    def test_gobo_channel_steps_through_wheel_positions(
            self, qapp, mock_fixture_def):
        layer, _, _ = _setup(mock_fixture_def)
        layer.arm({"group": "Movers", "action": "special_steps"})
        values, mask = layer.render(0.0)[1]
        assert mask[GOBO] and values[GOBO] == 0          # step 0 = open
        assert values[DIMMER] == 255                     # lit to see it
        layer.set_special_step(3)
        values, _ = layer.render(0.0)[1]
        assert values[GOBO] == special_step_value(3) == 109
        layer.set_special_step(7)
        assert layer.render(0.0)[1][0][GOBO] == 255


class TestHoldAimForCapture:
    @pytest.fixture
    def focus_zoom_def(self, mock_fixture_def):
        """The shared def plus mapped focus/zoom channels (10, 11)."""
        definition = dict(mock_fixture_def)
        definition["channels"] = list(definition["channels"]) + [
            {"name": "Focus", "preset": "BeamFocusNearFar",
             "group": "Beam", "capabilities": []},
            {"name": "Zoom", "preset": "BeamZoomSmallBig",
             "group": "Beam", "capabilities": []},
        ]
        definition["modes"] = [{
            "name": "Standard",
            "channels": definition["modes"][0]["channels"] + [
                {"number": 10, "name": "Focus"},
                {"number": 11, "name": "Zoom"},
            ]}]
        return definition

    def test_holds_the_first_spot_when_none_named(self, qapp,
                                                  mock_fixture_def):
        spots = {"B Spot": Spot(name="B Spot", x=1.0, y=0.0, z=0.0),
                 "A Spot": Spot(name="A Spot", x=-1.0, y=0.0, z=0.0)}
        layer, config, _ = _setup(mock_fixture_def, spots=spots)
        layer.arm({"group": "Movers", "action": "hold_aim_for_capture"})
        values, mask = layer.render(0.0)[1]
        pan_c, _, tilt_c, _ = _expected_aim16(
            config.fixtures[0], (-1.0, 0.0, 0.0),   # sorted -> "A Spot"
            config)
        assert mask[PAN] and values[PAN] == pan_c
        assert values[TILT] == tilt_c
        assert values[DIMMER] == 255

    def test_capture_levels_drive_mapped_focus_zoom(self, qapp,
                                                    focus_zoom_def):
        # One fixture only: a 12-channel footprint at address 11 would
        # overlap MH1's focus/zoom channels.
        layer, _, maps = _setup(focus_zoom_def,
                                fixtures=[_fixture("MH1", 1)])
        assert maps["MH1"].focus_channels == [10]
        assert maps["MH1"].zoom_channels == [11]
        layer.arm({"group": "Movers", "action": "hold_aim_for_capture"})
        values, mask = layer.render(0.0)[1]
        assert mask[10] == 0 and mask[11] == 0   # untouched until trimmed
        layer.set_capture_levels(focus=132, zoom=90)
        values, mask = layer.render(0.0)[1]
        assert mask[10] and values[10] == 132
        assert mask[11] and values[11] == 90

    def test_no_mapped_channels_drives_nothing_extra(self, qapp,
                                                     mock_fixture_def):
        # The shared def has no focus/zoom channels: the sliders drive
        # nothing on the wire; CAPTURE still records the values (the
        # dialog's write into Fixture.calibration, tested there).
        layer, _, maps = _setup(mock_fixture_def)
        assert maps["MH1"].focus_channels == []
        layer.arm({"group": "Movers", "action": "hold_aim_for_capture"})
        before = layer.render(0.0)
        layer.set_capture_levels(focus=200, zoom=10)
        assert layer.render(0.0) == before


class StubSender:
    def send_dmx(self, universe, dmx_data, force=False):
        return True

    def close(self):
        pass


class TestArbiterAttachment:
    """The exclusive playback slot + the never-stop-anothers-loop rule
    (docs/output-sync-plan.md; CLAUDE.md arbiter notes)."""

    def _arbiter(self, config):
        return OutputArbiter(config=config, sender=StubSender())

    def test_attach_claims_the_playback_slot(self, qapp,
                                             mock_fixture_def):
        layer, config, _ = _setup(mock_fixture_def)
        arbiter = self._arbiter(config)
        assert layer.attach(arbiter) is True
        assert arbiter.playback_slot_owner() == SLOT_OWNER
        layer.detach()
        assert arbiter.playback_slot_owner() is None

    def test_attach_refused_while_a_show_plays(self, qapp,
                                               mock_fixture_def):
        layer, config, _ = _setup(mock_fixture_def)
        arbiter = self._arbiter(config)
        assert arbiter.acquire_playback_slot(object(), "timeline")
        assert layer.attach(arbiter) is False
        assert arbiter.playback_slot_owner() == "timeline"
        layer.detach()                       # no-op, never attached
        assert arbiter.playback_slot_owner() == "timeline"

    def test_detach_stops_only_a_loop_it_started(self, qapp,
                                                 mock_fixture_def):
        layer, config, _ = _setup(mock_fixture_def)
        arbiter = self._arbiter(config)
        assert not arbiter.running
        layer.attach(arbiter)
        assert arbiter.running               # we started it
        layer.detach()
        assert not arbiter.running           # so we stop it

    def test_detach_never_stops_anothers_loop(self, qapp,
                                              mock_fixture_def):
        layer, config, _ = _setup(mock_fixture_def)
        arbiter = self._arbiter(config)
        arbiter.start()                      # OUTPUT already on
        try:
            layer.attach(arbiter)
            layer.detach()
            assert arbiter.running           # the busk stream survives
        finally:
            arbiter.stop(blackout=False)

    def test_detach_disarms_the_item(self, qapp, mock_fixture_def):
        layer, config, _ = _setup(mock_fixture_def)
        arbiter = self._arbiter(config)
        layer.attach(arbiter)
        layer.arm({"group": "Movers", "action": "flash_full"})
        layer.detach()
        assert not layer.armed
        assert layer.render(0.0) == {}

    def test_release_falls_through_to_the_show_below(self, qapp,
                                                     mock_fixture_def):
        # End to end through compose: preflight in the playback slot,
        # disarm = the floor (blackout here) shows through again.
        layer, config, maps = _setup(mock_fixture_def)
        arbiter = self._arbiter(config)
        arbiter.set_fixture_maps(maps)
        arbiter.set_idle_policy(IDLE_BLACKOUT)
        arbiter.set_playback_layer(layer)
        layer.arm({"group": "Movers", "action": "flash_full"})
        merged = arbiter.tick_once(0.0)
        assert merged[1][DIMMER] == 255
        layer.disarm()
        merged = arbiter.tick_once(1.0)
        assert merged[1][DIMMER] == 0
