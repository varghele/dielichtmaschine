# tests/unit/test_live_busk_layer.py
"""utils/artnet/live_layer.py - the Live busk surface as an arbiter
layer (phase 3 of docs/output-sync-plan.md): the first pass where the
busk programmer makes actual light.

Covers the claim rules (colour groups claim dimmer + colour + shutter,
flash-only claims dimmer only, untouched groups claim nothing), the
group_level_local resolve (pre-grandmaster), split-swatch alternation,
dimmerless colour scaling and white-flash, the wall-clock strobe chop,
RELEASE ALL fall-through against a playback layer underneath, the
busk-over-show merge precedence, arbiter-forwarded fixture maps, and
the grandmaster/DBO stage capping the busk output. Socket-free.

Fixture layout (shared mock def, base address 0): dimmer 0, RGBW 1-4,
pan 5, tilt 6, fines 7-8, gobo 9.
"""

import pytest

from config.models import (
    Configuration, Fixture, FixtureGroup, FixtureMode, Universe,
)
from gui.tabs.live_tab import COLOUR_SWATCHES, LiveState
from utils.artnet.arbiter import IDLE_BLACKOUT, OutputArbiter
from utils.artnet.dmx_manager import FixtureChannelMap
from utils.artnet.live_layer import LiveBuskLayer

DIMMER, RED, GREEN, BLUE, WHITE, PAN = 0, 1, 2, 3, 4, 5


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
