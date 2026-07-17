# tests/unit/test_pause_layer.py
"""utils/artnet/pause_layer.py - the minimal pause-look engine
(2026-07-17): while the LTC chase is armed and no song plays, the
arbiter's pause slot renders the setlist entry's pause_after. Modes
scene (colour + mover aims through the busk layer's shared aim), warm
white and blackout render; hold_last / ambient_loop stay data-only.
Socket-free; fixture layout = the shared mock def (dimmer 0, RGBW
1-4, pan 5, tilt 6, fines 7-8, gobo 9).
"""

import pytest

from config.models import (
    Configuration, Fixture, FixtureGroup, FixtureMode, PauseLook, Scene,
    Spot, Universe,
)
from utils.artnet.dmx_manager import FixtureChannelMap
from utils.artnet.pause_layer import PauseLookLayer

from .test_live_busk_layer import _expected_aim16

DIMMER, RED, GREEN, BLUE, WHITE, PAN = 0, 1, 2, 3, 4, 5
TILT, PAN_FINE, TILT_FINE, GOBO = 6, 7, 8, 9


def _fixture(name, address, x=0.0):
    # Primary group label "G" stays OUT of config.groups, so effective
    # orientation falls back to the fixture's own fields - the same
    # harness contract as test_live_busk_layer's _expected_aim16.
    return Fixture(
        universe=1, address=address, manufacturer="TestMfr",
        model="TestModel", name=name, group="G",
        current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
        type="MH", x=x,
    )


def _setup(mock_fixture_def, scene=None):
    fixtures = [_fixture("MH1", 1, x=-1.0), _fixture("MH2", 11, x=1.0)]
    config = Configuration(
        fixtures=fixtures,
        groups={"Movers": FixtureGroup(name="Movers", fixtures=fixtures)},
        universes={1: Universe(id=1, name="U1", output={})},
    )
    config.spots = {"Target": Spot(name="Target", x=0.0, y=-2.0, z=0.0)}
    maps = {f.name: FixtureChannelMap(f, mock_fixture_def, config)
            for f in fixtures}
    layer = PauseLookLayer(
        config_provider=lambda: config,
        scene_provider=lambda key: scene
        if scene is not None and key == "pause/Red" else None)
    layer.set_fixture_maps(maps)
    return layer, config


def _red_scene(positions=None, color="#FF2A1E"):
    return Scene(name="Red", category="pause", color=color,
                 groups=["Movers"], positions=dict(positions or {}))


class TestLifecycle:
    def test_inactive_renders_nothing(self, qapp, mock_fixture_def):
        layer, _ = _setup(mock_fixture_def)
        assert layer.render(0.0) == {}
        assert not layer.active

    def test_clear_releases_the_look(self, qapp, mock_fixture_def):
        layer, _ = _setup(mock_fixture_def, scene=_red_scene())
        layer.activate(PauseLook(mode="scene", level=100,
                                 scene="pause/Red"))
        assert layer.active and layer.render(0.0)
        layer.clear()
        assert layer.render(0.0) == {}


class TestSceneMode:
    def test_scene_colour_lands_on_its_groups(self, qapp,
                                              mock_fixture_def):
        layer, _ = _setup(mock_fixture_def, scene=_red_scene())
        layer.activate(PauseLook(mode="scene", level=100,
                                 scene="pause/Red"))
        values, mask = layer.render(0.0)[1]
        for base in (0, 10):
            assert mask[base + DIMMER] and values[base + DIMMER] == 255
            assert values[base + RED] == 0xFF
            assert values[base + GREEN] == 0x2A
            assert values[base + BLUE] == 0x1E

    def test_level_scales_the_dimmer(self, qapp, mock_fixture_def):
        layer, _ = _setup(mock_fixture_def, scene=_red_scene())
        layer.activate(PauseLook(mode="scene", level=50,
                                 scene="pause/Red"))
        values, _ = layer.render(0.0)[1]
        assert values[DIMMER] == 128
        assert values[RED] == 0xFF     # colour full; dimmer carries level

    def test_scene_positions_aim_the_movers(self, qapp,
                                            mock_fixture_def):
        scene = _red_scene(positions={"Movers": "mark:Target"})
        layer, config = _setup(mock_fixture_def, scene=scene)
        layer.activate(PauseLook(mode="scene", level=100,
                                 scene="pause/Red"))
        values, mask = layer.render(0.0)[1]
        for fixture, base in ((config.fixtures[0], 0),
                              (config.fixtures[1], 10)):
            pan_c, pan_f, tilt_c, tilt_f = _expected_aim16(
                fixture, (0.0, -2.0, 0.0))
            assert mask[base + PAN]
            assert (values[base + PAN], values[base + TILT]) == \
                (pan_c, tilt_c)
            assert (values[base + PAN_FINE], values[base + TILT_FINE]) \
                == (pan_f, tilt_f)

    def test_unresolvable_scene_renders_nothing(self, qapp,
                                                mock_fixture_def):
        layer, _ = _setup(mock_fixture_def, scene=None)
        layer.activate(PauseLook(mode="scene", level=100,
                                 scene="pause/Ghost"))
        assert layer.render(0.0) == {}


class TestPlainModes:
    def test_warm_white_lights_the_whole_rig(self, qapp,
                                             mock_fixture_def):
        layer, _ = _setup(mock_fixture_def)
        layer.activate(PauseLook(mode="warm_white", level=20))
        values, mask = layer.render(0.0)[1]
        for base in (0, 10):
            assert mask[base + DIMMER] and values[base + DIMMER] == 51
            assert values[base + RED] == 255      # warm white, full hue

    def test_blackout_claims_zero(self, qapp, mock_fixture_def):
        """A CLAIM to zero - it must beat the editor's full-white
        visible floor, not fall through to it."""
        layer, _ = _setup(mock_fixture_def)
        layer.activate(PauseLook(mode="blackout"))
        values, mask = layer.render(0.0)[1]
        for base in (0, 10):
            assert mask[base + DIMMER] == 1
            assert values[base + DIMMER] == 0
            assert mask[base + RED] == 1 and values[base + RED] == 0

    def test_hold_last_stays_data_only(self, qapp, mock_fixture_def):
        layer, _ = _setup(mock_fixture_def)
        layer.activate(PauseLook(mode="hold_last"))
        assert layer.render(0.0) == {}


class TestArbiterIntegration:
    def test_pause_sits_below_playback(self, qapp, mock_fixture_def):
        """Compose order: a playing song's claims cover the pause look
        on the channels it drives - firing the next song needs no
        explicit pause teardown to win the wire."""
        from utils.artnet.arbiter import OutputArbiter

        class _StubSender:
            target_ip = ""

            def send_dmx(self, *a, **k):
                return True

            def close(self):
                pass

        class _SongLayer:
            def render(self, now):
                values = bytearray(512)
                mask = bytearray(512)
                values[RED] = 7
                mask[RED] = 1
                return {1: (bytes(values), bytes(mask))}

        layer, config = _setup(mock_fixture_def, scene=_red_scene())
        layer.activate(PauseLook(mode="scene", level=100,
                                 scene="pause/Red"))
        arbiter = OutputArbiter(config=config, sender=_StubSender())
        arbiter.set_fixture_maps(
            {f.name: FixtureChannelMap(f, mock_fixture_def, config)
             for f in config.fixtures})
        arbiter.set_pause_look_layer(layer)
        merged = arbiter.tick_once(0.0)
        assert merged[1][RED] == 0xFF          # pause red on the wire
        arbiter.set_playback_layer(_SongLayer())
        merged = arbiter.tick_once(0.1)
        assert merged[1][RED] == 7             # the song covers it
