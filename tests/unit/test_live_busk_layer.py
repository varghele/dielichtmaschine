# tests/unit/test_live_busk_layer.py
"""utils/artnet/live_layer.py - the Live busk surface as an arbiter
layer (phase 3 of docs/output-sync-plan.md): the first pass where the
busk programmer makes actual light.

Covers the claim rules (colour groups claim dimmer + colour + shutter,
flash-only claims dimmer only, untouched groups claim nothing), the
group_level_local resolve (pre-grandmaster), split-swatch alternation,
dimmerless colour scaling and white-flash, the wall-clock strobe chop,
RELEASE ALL fall-through against a playback layer underneath, the
busk-over-show merge precedence, arbiter-forwarded fixture maps, the
grandmaster/DBO stage capping the busk output, and the per-group
position palettes (pan/tilt claims aimed by calculate_pan_tilt at the
definition's physical ranges). Socket-free.

Fixture layout (shared mock def, base address 0): dimmer 0, RGBW 1-4,
pan 5, tilt 6, fines 7-8, gobo 9.
"""

import pytest

from config.models import (
    Configuration, Fixture, FixtureGroup, FixtureMode, Spot, Universe,
)
from gui.tabs.live_tab import COLOUR_SWATCHES, LiveState
from utils.artnet.arbiter import IDLE_BLACKOUT, OutputArbiter
from utils.artnet.dmx_manager import FixtureChannelMap
from utils.artnet.live_layer import LiveBuskLayer
from utils.orientation import calculate_pan_tilt, pan_tilt_to_dmx16

DIMMER, RED, GREEN, BLUE, WHITE, PAN = 0, 1, 2, 3, 4, 5
TILT, PAN_FINE, TILT_FINE, GOBO = 6, 7, 8, 9


def _fixture(name, address, x=0.0, model="TestModel"):
    return Fixture(
        universe=1, address=address, manufacturer="TestMfr", model=model,
        name=name, group="G", current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
        type="MH", x=x,
    )


@pytest.fixture
def rgb_par_def():
    """No dimmer channel: colour is the intensity."""
    return {
        "manufacturer": "TestMfr", "model": "ParModel",
        "channels": [
            {"name": "Red", "preset": "IntensityRed", "group": "Colour",
             "capabilities": []},
            {"name": "Green", "preset": "IntensityGreen", "group": "Colour",
             "capabilities": []},
            {"name": "Blue", "preset": "IntensityBlue", "group": "Colour",
             "capabilities": []},
        ],
        "modes": [{"name": "Standard", "channels": [
            {"number": 0, "name": "Red"},
            {"number": 1, "name": "Green"},
            {"number": 2, "name": "Blue"},
        ]}],
    }


@pytest.fixture
def wheel_spot_def():
    """A wheel-only mover (the Hero Spot 60 shape): dimmer, shutter and
    a colour WHEEL - no RGB emitters. Unless the busk layer steers the
    wheel, such a fixture can never show a busked colour (the phase 0
    root cause in docs/live-output-plan.md: swatches lit the bench rig
    white at best)."""
    return {
        "manufacturer": "TestMfr", "model": "WheelModel",
        "channels": [
            {"name": "Dimmer", "preset": "IntensityMasterDimmer",
             "group": "Intensity", "capabilities": []},
            {"name": "Shutter", "preset": "ShutterStrobeOpen",
             "group": "Shutter", "capabilities": []},
            {"name": "Colour Wheel", "preset": "ColorWheel",
             "group": "Colour", "capabilities": []},
        ],
        "modes": [{"name": "Standard", "channels": [
            {"number": 0, "name": "Dimmer"},
            {"number": 1, "name": "Shutter"},
            {"number": 2, "name": "Colour Wheel"},
        ]}],
    }


def _setup(mock_fixture_def, fixtures=None, groups=None):
    """(state, layer, config, maps) for a config; default one two-mover
    group."""
    fixtures = fixtures if fixtures is not None else [
        _fixture("MH1", 1, x=-1.0), _fixture("MH2", 11, x=1.0)]
    groups = groups or {"Movers": FixtureGroup(name="Movers",
                                               fixtures=fixtures)}
    config = Configuration(
        fixtures=fixtures, groups=groups,
        universes={1: Universe(id=1, name="U1", output={})},
    )
    maps = {f.name: FixtureChannelMap(f, mock_fixture_def, config)
            for f in fixtures if f.model == "TestModel"}
    state = LiveState()
    state.update_from_config(groups.keys())
    layer = LiveBuskLayer(state, config_provider=lambda: config,
                          swatches=COLOUR_SWATCHES)
    layer.set_fixture_maps(maps)
    return state, layer, config, maps


class TestClaimRules:
    def test_untouched_programmer_renders_nothing(self, qapp,
                                                  mock_fixture_def):
        state, layer, _, _ = _setup(mock_fixture_def)
        assert layer.render(0.0) == {}

    def test_colour_group_claims_dimmer_colour_and_shutter(
            self, qapp, mock_fixture_def):
        state, layer, _, _ = _setup(mock_fixture_def)
        state.selected = {"Movers"}
        state.stage_colour("red")            # FF2850
        frame = layer.render(0.0)
        values, mask = frame[1]
        assert mask[DIMMER] and values[DIMMER] == 255   # submaster 100
        assert values[RED] == 0xFF
        assert values[GREEN] == 0x28
        assert values[BLUE] == 0x50
        assert mask[WHITE] and values[WHITE] == 0       # claim to zero
        assert mask[PAN] == 0                            # never pan/tilt

    def test_submaster_scales_the_dimmer_not_the_colour(
            self, qapp, mock_fixture_def):
        state, layer, _, _ = _setup(mock_fixture_def)
        state.selected = {"Movers"}
        state.stage_colour("red")
        state.set_submaster("Movers", 50)
        values, _ = layer.render(0.0)[1]
        assert values[DIMMER] == 128
        assert values[RED] == 0xFF

    def test_grandmaster_does_not_scale_the_layer(self, qapp,
                                                  mock_fixture_def):
        # group_level_local excludes GM - the arbiter's post-merge
        # stage owns it (also capping playback).
        state, layer, _, _ = _setup(mock_fixture_def)
        state.selected = {"Movers"}
        state.stage_colour("white")
        state.set_grandmaster(10)
        values, _ = layer.render(0.0)[1]
        assert values[DIMMER] == 255

    def test_flash_only_claims_dimmer_but_not_colour(self, qapp,
                                                     mock_fixture_def):
        state, layer, _, _ = _setup(mock_fixture_def)
        state.set_flash("Movers", True)
        values, mask = layer.render(0.0)[1]
        assert mask[DIMMER] and values[DIMMER] == 255   # flash forces full
        assert mask[RED] == 0                            # show colour survives

    def test_split_swatch_alternates_by_stage_x(self, qapp,
                                                mock_fixture_def):
        state, layer, _, _ = _setup(mock_fixture_def)
        state.selected = {"Movers"}
        state.stage_colour("red_cyan")       # FF2850 / 4ECBD4
        values, _ = layer.render(0.0)[1]
        # MH1 (x=-1, address 1, base 0) gets the primary red...
        assert values[0 + RED] == 0xFF
        # ...MH2 (x=+1, address 11, base 10) the secondary cyan.
        assert values[10 + RED] == 0x4E
        assert values[10 + GREEN] == 0xCB
        assert values[10 + BLUE] == 0xD4

    def test_release_all_clears_every_claim(self, qapp, mock_fixture_def):
        state, layer, _, _ = _setup(mock_fixture_def)
        state.selected = {"Movers"}
        state.stage_colour("red")
        assert layer.render(0.0)
        state.release_all()
        assert layer.render(0.0) == {}


class TestDimmerlessFixtures:
    def _par_setup(self, mock_fixture_def, rgb_par_def):
        par1 = _fixture("PAR1", 100, x=-1.0, model="ParModel")
        par2 = _fixture("PAR2", 110, x=1.0, model="ParModel")
        config = Configuration(
            fixtures=[par1, par2],
            groups={"Pars": FixtureGroup(name="Pars",
                                         fixtures=[par1, par2])},
            universes={1: Universe(id=1, name="U1", output={})},
        )
        maps = {f.name: FixtureChannelMap(f, rgb_par_def, config)
                for f in (par1, par2)}
        state = LiveState()
        state.update_from_config(["Pars"])
        layer = LiveBuskLayer(state, config_provider=lambda: config,
                              swatches=COLOUR_SWATCHES)
        layer.set_fixture_maps(maps)
        return state, layer

    def test_colour_scales_with_the_level(self, qapp, mock_fixture_def,
                                          rgb_par_def):
        state, layer = self._par_setup(mock_fixture_def, rgb_par_def)
        state.selected = {"Pars"}
        state.stage_colour("red")
        state.set_submaster("Pars", 50)
        values, mask = layer.render(0.0)[1]
        assert values[99 + 0] == round(0xFF * 0.5)     # red at abs 99
        assert mask[99 + 1] and values[99 + 1] == round(0x28 * 0.5)

    def test_flash_only_reads_as_white_flash(self, qapp, mock_fixture_def,
                                             rgb_par_def):
        state, layer = self._par_setup(mock_fixture_def, rgb_par_def)
        state.set_flash("Pars", True)
        values, mask = layer.render(0.0)[1]
        assert values[99 + 0] == 255
        assert values[99 + 1] == 255
        assert values[99 + 2] == 255


class TestWheelOnlyFixtures:
    """Wheel-only movers show a busked colour on the WHEEL channel via
    the same rgb_to_color_wheel mapping playback uses; fixtures with
    RGB emitters keep their wheel untouched."""

    DIM, SHUTTER, WHEEL = 0, 1, 2

    def _wheel_setup(self, wheel_spot_def):
        mh = _fixture("WMH1", 1, model="WheelModel")
        config = Configuration(
            fixtures=[mh],
            groups={"Spots": FixtureGroup(name="Spots", fixtures=[mh])},
            universes={1: Universe(id=1, name="U1", output={})},
        )
        maps = {"WMH1": FixtureChannelMap(mh, wheel_spot_def, config)}
        # The channel buckets under its preset AND its group (the
        # get_channels_by_property quirk pinned in test_dmx_masks.py),
        # so compare as sets.
        assert set(maps["WMH1"].color_wheel_channels) == {self.WHEEL}
        assert not maps["WMH1"].red_channels
        state = LiveState()
        state.update_from_config(["Spots"])
        layer = LiveBuskLayer(state, config_provider=lambda: config,
                              swatches=COLOUR_SWATCHES)
        layer.set_fixture_maps(maps)
        return state, layer

    def test_swatch_steers_the_colour_wheel(self, qapp, wheel_spot_def):
        from utils.artnet.dmx_manager import rgb_to_color_wheel
        state, layer = self._wheel_setup(wheel_spot_def)
        state.selected = {"Spots"}
        state.stage_colour("red")            # FF2850
        values, mask = layer.render(0.0)[1]
        assert mask[self.DIM] and values[self.DIM] == 255
        assert mask[self.SHUTTER] and values[self.SHUTTER] == 255
        assert mask[self.WHEEL]
        assert values[self.WHEEL] == rgb_to_color_wheel(0xFF, 0x28, 0x50)
        assert values[self.WHEEL] == 37      # the red slot, not white

    def test_flash_only_leaves_the_wheel_to_the_show(self, qapp,
                                                     wheel_spot_def):
        state, layer = self._wheel_setup(wheel_spot_def)
        state.set_flash("Spots", True)
        values, mask = layer.render(0.0)[1]
        assert mask[self.DIM] and values[self.DIM] == 255
        assert mask[self.WHEEL] == 0         # show colour survives

    def test_rgb_fixture_wheel_write_is_guarded(self, qapp,
                                                mock_fixture_def):
        # The shared mock def's RGBW channels sit in group "Colour" so
        # they ALSO bucket into color_wheel_channels (the
        # get_channels_by_property quirk pinned in test_dmx_masks.py).
        # Without the red/green/blue guard the wheel write would
        # clobber the just-written swatch RGB with a wheel slot value.
        state, layer, _, maps = _setup(mock_fixture_def)
        assert set(maps["MH1"].color_wheel_channels) \
            >= set(maps["MH1"].red_channels)
        state.selected = {"Movers"}
        state.stage_colour("red")
        values, mask = layer.render(0.0)[1]
        assert values[RED] == 0xFF           # swatch RGB, not slot 37
        assert values[GREEN] == 0x28
        assert values[BLUE] == 0x50
        assert mask[GOBO] == 0


class TestScenePool:
    """Phase 1 of docs/live-output-plan.md: the active scene claims its
    listed groups like an applied colour - selection-independent,
    below explicit swatches, released on second touch (state contract:
    set_scene(None))."""

    def _scene(self, color="#4ECBD4", groups=("Left",)):
        from config.models import Scene
        return Scene(name="Wash", category="general", color=color,
                     groups=list(groups))

    def _two_group_setup(self, mock_fixture_def, scene):
        mh1 = _fixture("MH1", 1, x=-1.0)
        mh2 = _fixture("MH2", 11, x=1.0)
        groups = {"Left": FixtureGroup(name="Left", fixtures=[mh1]),
                  "Right": FixtureGroup(name="Right", fixtures=[mh2])}
        config = Configuration(
            fixtures=[mh1, mh2], groups=groups,
            universes={1: Universe(id=1, name="U1", output={})},
        )
        maps = {f.name: FixtureChannelMap(f, mock_fixture_def, config)
                for f in (mh1, mh2)}
        state = LiveState()
        state.update_from_config(groups.keys())
        provider = lambda key: scene if key == "general/Wash" else None
        layer = LiveBuskLayer(state, config_provider=lambda: config,
                              swatches=COLOUR_SWATCHES,
                              scene_provider=provider)
        layer.set_fixture_maps(maps)
        return state, layer

    def test_scene_lights_its_groups_without_selection(
            self, qapp, mock_fixture_def):
        scene = self._scene(groups=("Left",))
        state, layer = self._two_group_setup(mock_fixture_def, scene)
        state.set_scene("general/Wash")
        values, mask = layer.render(0.0)[1]
        # Left (base 0): dimmer at the submaster, the scene hex 4ECBD4.
        assert mask[DIMMER] and values[DIMMER] == 255
        assert values[RED] == 0x4E
        assert values[GREEN] == 0xCB
        assert values[BLUE] == 0xD4
        # Right is not in the scene: nothing claimed.
        assert mask[10 + DIMMER] == 0

    def test_swatch_overrides_scene_per_group(self, qapp,
                                              mock_fixture_def):
        scene = self._scene(groups=("Left", "Right"))
        state, layer = self._two_group_setup(mock_fixture_def, scene)
        state.set_scene("general/Wash")
        state.selected = {"Left"}
        state.stage_colour("red")            # FF2850
        values, _ = layer.render(0.0)[1]
        assert values[RED] == 0xFF           # the swatch wins on Left
        assert values[10 + RED] == 0x4E      # the scene holds Right

    def test_scene_release_falls_through(self, qapp, mock_fixture_def):
        scene = self._scene(groups=("Left",))
        state, layer = self._two_group_setup(mock_fixture_def, scene)
        state.set_scene("general/Wash")
        assert layer.render(0.0)
        state.set_scene(None)                # second touch releases
        assert layer.render(0.0) == {}

    def test_unknown_key_or_colourless_scene_renders_nothing(
            self, qapp, mock_fixture_def):
        scene = self._scene(color="", groups=("Left",))
        state, layer = self._two_group_setup(mock_fixture_def, scene)
        state.set_scene("general/Wash")      # scene has no colour
        assert layer.render(0.0) == {}
        state.set_scene("general/Ghost")     # provider returns None
        assert layer.render(0.0) == {}

    def test_scene_ghost_group_is_ignored(self, qapp, mock_fixture_def):
        scene = self._scene(groups=("Left", "Ghost"))
        state, layer = self._two_group_setup(mock_fixture_def, scene)
        state.set_scene("general/Wash")
        values, mask = layer.render(0.0)[1]
        assert mask[DIMMER]                  # Left still lights
        assert mask[10 + DIMMER] == 0        # no stray claims

    def test_scene_takes_the_group_level_and_strobe(self, qapp,
                                                    mock_fixture_def):
        scene = self._scene(groups=("Left",))
        state, layer = self._two_group_setup(mock_fixture_def, scene)
        state.set_scene("general/Wash")
        state.set_submaster("Left", 50)
        values, _ = layer.render(0.0)[1]
        assert values[DIMMER] == 128         # same resolve as swatches
        state.set_strobe_on(True)
        state.set_strobe_rate(0)             # 1 Hz chop
        assert layer.render(0.75)[1][0][DIMMER] == 0


class TestStrobe:
    def test_strobe_chops_the_dimmer_against_the_clock(
            self, qapp, mock_fixture_def):
        state, layer, _, _ = _setup(mock_fixture_def)
        state.selected = {"Movers"}
        state.stage_colour("white")
        state.set_strobe_on(True)
        state.set_strobe_rate(0)             # 1 Hz chop, 50% duty
        on_values, _ = layer.render(0.25)[1]     # first half: open
        off_values, _ = layer.render(0.75)[1]    # second half: dark
        assert on_values[DIMMER] == 255
        assert off_values[DIMMER] == 0
        # The colour stays claimed through the dark phase (claim to
        # zero happens on the dimmer, not by dropping the frame).
        assert off_values[RED] == 255


class TestBuskOverShow:
    """End-to-end through compose: the busk layer over a playback
    layer over the floor."""

    def _arbitered(self, mock_fixture_def, playback_frame):
        state, layer, config, maps = _setup(mock_fixture_def)

        class StubSender:
            def __init__(self):
                self.sent = []

            def send_dmx(self, universe, dmx_data, force=False):
                self.sent.append((universe, bytes(dmx_data)))
                return True

            def close(self):
                pass

        class ShowLayer:
            def render(self, now):
                return playback_frame

        arbiter = OutputArbiter(config=config, sender=StubSender())
        arbiter.set_fixture_maps(maps)
        arbiter.set_idle_policy(IDLE_BLACKOUT)
        arbiter.set_playback_layer(ShowLayer())
        arbiter.set_live_layer(layer)
        return state, arbiter

    @staticmethod
    def _show_frame(**channels):
        values = bytearray(512)
        mask = bytearray(512)
        for key, value in channels.items():
            ch = int(key[2:])
            values[ch] = value
            mask[ch] = 1
        return {1: (bytes(values), bytes(mask))}

    def test_busk_colour_beats_show_colour(self, qapp, mock_fixture_def):
        show = self._show_frame(ch1=0, ch2=0, ch3=255, ch0=80)  # blue show
        state, arbiter = self._arbitered(mock_fixture_def, show)
        state.selected = {"Movers"}
        state.stage_colour("red")
        merged = arbiter.tick_once(0.0)
        assert merged[1][RED] == 0xFF
        assert merged[1][BLUE] == 0x50     # busk's claim-to-value wins
        # Dimmer merges HTP: busk 255 vs show 80 -> 255.
        assert merged[1][DIMMER] == 255

    def test_show_dimmer_wins_htp_when_brighter(self, qapp,
                                                mock_fixture_def):
        show = self._show_frame(ch0=200)
        state, arbiter = self._arbitered(mock_fixture_def, show)
        state.selected = {"Movers"}
        state.stage_colour("red")
        state.set_submaster("Movers", 20)   # busk dimmer 51
        merged = arbiter.tick_once(0.0)
        assert merged[1][DIMMER] == 200     # HTP keeps the show's level

    def test_release_all_falls_through_to_the_show(self, qapp,
                                                   mock_fixture_def):
        show = self._show_frame(ch0=80, ch3=255)
        state, arbiter = self._arbitered(mock_fixture_def, show)
        state.selected = {"Movers"}
        state.stage_colour("red")
        assert arbiter.tick_once(0.0)[1][RED] == 0xFF
        state.release_all()
        merged = arbiter.tick_once(1.0)
        assert merged[1][RED] == 0          # busk claim gone
        assert merged[1][BLUE] == 255       # the show is back
        assert merged[1][DIMMER] == 80

    def test_live_grandmaster_and_dbo_cap_everything(self, qapp,
                                                     mock_fixture_def):
        show = self._show_frame(ch0=200)
        state, arbiter = self._arbitered(mock_fixture_def, show)
        # The gui wiring pushes LiveState masters into the arbiter;
        # simulate it directly here.
        arbiter.set_grandmaster(50)
        merged = arbiter.tick_once(0.0)
        assert merged[1][DIMMER] == 100     # the SHOW is capped too
        arbiter.set_dbo(True)
        assert arbiter.tick_once(0.0)[1][DIMMER] == 0

    def test_arbiter_forwards_maps_to_the_live_layer(self, qapp,
                                                     mock_fixture_def):
        state, layer, config, maps = _setup(mock_fixture_def)
        layer.set_fixture_maps({})           # start map-less

        class StubSender:
            def send_dmx(self, universe, dmx_data, force=False):
                return True

            def close(self):
                pass

        arbiter = OutputArbiter(config=config, sender=StubSender())
        arbiter.set_live_layer(layer)
        state.selected = {"Movers"}
        state.stage_colour("red")
        assert layer.render(0.0) == {}       # no maps yet
        arbiter.set_fixture_maps(maps)       # playback registers maps
        assert layer.render(0.0)             # busk lights up


def _expected_aim16(fixture, target, pan_range=540.0, tilt_range=270.0):
    """Reference 16-bit pan/tilt DMX for a fixture aimed at a
    stage-space target - the calculate_pan_tilt/pan_tilt_to_dmx16
    contract of the busk layer's position claims (no group in these
    configs, so orientation comes from the fixture's own fields).
    Returns (pan_coarse, pan_fine, tilt_coarse, tilt_fine)."""
    mounting, yaw, pitch, roll = fixture.get_effective_orientation(None)
    pan_deg, tilt_deg = calculate_pan_tilt(
        fixture_x=fixture.x, fixture_y=fixture.y,
        fixture_z=fixture.get_effective_z(None),
        target_x=target[0], target_y=target[1], target_z=target[2],
        mounting=mounting, yaw=yaw, pitch=pitch, roll=roll,
        pan_range=pan_range, tilt_range=tilt_range,
    )
    return pan_tilt_to_dmx16(pan_deg, tilt_deg, pan_range, tilt_range)


def _expected_aim(fixture, target, pan_range=540.0, tilt_range=270.0):
    """The coarse bytes only, for tests that assert just pan/tilt."""
    pan_c, _, tilt_c, _ = _expected_aim16(fixture, target,
                                          pan_range, tilt_range)
    return pan_c, tilt_c


class TestPositionClaims:
    def test_mark_claims_pan_tilt_and_fines_only(self, qapp,
                                                 mock_fixture_def):
        state, layer, config, _ = _setup(mock_fixture_def)
        mh1 = config.fixtures[0]
        # A spike mark exactly at MH1's head: the aim degenerates to
        # home -> DMX centre 127/127 (hard anchor, no reference math).
        config.spots = {"On Head": Spot(name="On Head", x=mh1.x,
                                        y=mh1.y, z=mh1.z)}
        state.positions = {"Movers": "mark:On Head"}
        values, mask = layer.render(0.0)[1]
        # 16-bit centre: value16 = 32768 -> coarse 128, fine 0 (the
        # exact 0.5 of full travel; the old 8-bit centre was 127).
        assert mask[PAN] and values[PAN] == 128
        assert mask[TILT] and values[TILT] == 128
        # Fine channels carry the 16-bit remainder (and being claimed
        # keeps a movement block underneath from jittering the aim).
        assert mask[PAN_FINE] and values[PAN_FINE] == 0
        assert mask[TILT_FINE] and values[TILT_FINE] == 0
        # Position claims NO intensity, NO shutter, nothing else: movers
        # can be pre-aimed dark.
        assert mask[DIMMER] == 0
        assert mask[RED] == 0
        assert mask[GOBO] == 0
        # MH2 (base 10) aims at the same mark from its own position,
        # fine bytes included.
        pan_c, pan_f, tilt_c, tilt_f = _expected_aim16(
            config.fixtures[1], (mh1.x, mh1.y, mh1.z))
        assert (values[10 + PAN], values[10 + TILT]) == (pan_c, tilt_c)
        assert (values[10 + PAN_FINE], values[10 + TILT_FINE]) == \
            (pan_f, tilt_f)

    def test_point_preset_converges_pattern_preset_per_fixture(
            self, qapp, mock_fixture_def):
        state, layer, config, _ = _setup(mock_fixture_def)
        # CENTRE: both movers converge on (0, 0, 1.5).
        state.positions = {"Movers": "preset:centre"}
        values, _ = layer.render(0.0)[1]
        for fixture, base in ((config.fixtures[0], 0),
                              (config.fixtures[1], 10)):
            expected = _expected_aim(fixture, (0.0, 0.0, 1.5))
            assert (values[base + PAN], values[base + TILT]) == expected
        # CEILING: each mover derives its own target (x, y, z + 10).
        state.positions = {"Movers": "preset:ceiling"}
        values, _ = layer.render(0.0)[1]
        for fixture, base in ((config.fixtures[0], 0),
                              (config.fixtures[1], 10)):
            expected = _expected_aim(
                fixture, (fixture.x, fixture.y, fixture.z + 10.0))
            assert (values[base + PAN], values[base + TILT]) == expected

    def test_stage_position_drives_the_layer_per_group(self, qapp,
                                                       mock_fixture_def):
        # Through the real mutator: only the selected group aims.
        mh = _fixture("MH1", 1, x=-1.0)
        other = _fixture("MH2", 11, x=1.0)
        groups = {"Left": FixtureGroup(name="Left", fixtures=[mh]),
                  "Right": FixtureGroup(name="Right", fixtures=[other])}
        state, layer, config, _ = _setup(mock_fixture_def,
                                         fixtures=[mh, other],
                                         groups=groups)
        state.set_selection(["Left"])
        state.stage_position("preset:centre", "Centre")
        values, mask = layer.render(0.0)[1]
        assert mask[PAN]                       # Left's mover aims...
        assert mask[10 + PAN] == 0             # ...Right is unaffected

    def test_non_mover_group_never_aims(self, qapp, mock_fixture_def,
                                        rgb_par_def):
        par = _fixture("PAR1", 100, model="ParModel")
        par.type = "PAR"
        config = Configuration(
            fixtures=[par],
            groups={"Pars": FixtureGroup(name="Pars", fixtures=[par])},
            universes={1: Universe(id=1, name="U1", output={})},
        )
        maps = {"PAR1": FixtureChannelMap(par, rgb_par_def, config)}
        state = LiveState()
        state.update_from_config(["Pars"])
        state.positions = {"Pars": "preset:centre"}
        layer = LiveBuskLayer(state, config_provider=lambda: config,
                              swatches=COLOUR_SWATCHES)
        layer.set_fixture_maps(maps)
        assert layer.render(0.0) == {}

    def test_stale_mark_renders_nothing(self, qapp, mock_fixture_def):
        state, layer, config, _ = _setup(mock_fixture_def)
        config.spots = {}
        state.positions = {"Movers": "mark:Ghost"}
        assert layer.render(0.0) == {}

    def test_position_composes_with_colour_claims(self, qapp,
                                                  mock_fixture_def):
        state, layer, config, _ = _setup(mock_fixture_def)
        state.selected = {"Movers"}
        state.stage_colour("red")
        state.stage_position("preset:centre", "Centre")
        values, mask = layer.render(0.0)[1]
        assert mask[DIMMER] and values[DIMMER] == 255
        assert values[RED] == 0xFF
        assert mask[PAN] and mask[TILT]

    def test_release_all_releases_the_aim(self, qapp, mock_fixture_def):
        state, layer, config, _ = _setup(mock_fixture_def)
        state.set_selection(["Movers"])
        state.stage_position("preset:centre", "Centre")
        assert layer.render(0.0)
        state.release_all()
        assert layer.render(0.0) == {}

    def test_definition_ranges_drive_the_aim(self, qapp,
                                             mock_fixture_def):
        # A definition declaring 360/180 physical travel aims through
        # those ranges; the shared mock def (no physical data) falls
        # back to 540/270.
        ranged_def = dict(mock_fixture_def)
        ranged_def["physical"] = {"pan_max": 360.0, "tilt_max": 180.0}
        state, layer, config, maps = _setup(ranged_def)
        assert maps["MH1"].pan_range == 360.0
        assert maps["MH1"].tilt_range == 180.0
        state.positions = {"Movers": "preset:centre"}
        values, _ = layer.render(0.0)[1]
        expected = _expected_aim(config.fixtures[0], (0.0, 0.0, 1.5),
                                 pan_range=360.0, tilt_range=180.0)
        assert (values[PAN], values[TILT]) == expected
        # And the fallback contract on the plain def:
        _, _, _, plain_maps = _setup(mock_fixture_def)
        assert plain_maps["MH1"].pan_range == 540.0
        assert plain_maps["MH1"].tilt_range == 270.0
