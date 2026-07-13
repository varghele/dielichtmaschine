# tests/unit/test_output_arbiter.py
"""utils/artnet/arbiter.py - the single output arbiter (phase 1 of
docs/output-sync-plan.md).

Covers the pure merge core (compose: priority-LTP, dimmer-only HTP
between layers, floor fall-through without HTP, claim-to-zero,
grandmaster/DBO on the per-fixture intensity masks incl. the
no-dimmer RGB-par fallback), the channel-class mask builder, the
visible/blackout idle floors, and the OutputArbiter dispatch
(universe mapping, local callback, layer exception isolation, slot
precedence, loop start/stop smoke). Socket-free throughout.
"""

import time

import pytest

from config.models import Configuration, Fixture, FixtureMode, Universe
from utils.artnet.arbiter import (
    IDLE_BLACKOUT, IDLE_VISIBLE, OutputArbiter, build_channel_class_masks,
    compose, render_visible_floor,
)
from utils.artnet.dmx_manager import FixtureChannelMap


# ---------------------------------------------------------------------------
# Frame helpers
# ---------------------------------------------------------------------------

def frame(universe, **channels):
    """A single-universe layer frame claiming exactly **channels
    (ch<N>=value)."""
    values = bytearray(512)
    mask = bytearray(512)
    for key, value in channels.items():
        ch = int(key[2:])
        values[ch] = value
        mask[ch] = 1
    return {universe: (bytes(values), bytes(mask))}


def htp_on(universe, *chs):
    mask = bytearray(512)
    for ch in chs:
        mask[ch] = 1
    return {universe: mask}


# ---------------------------------------------------------------------------
# compose()
# ---------------------------------------------------------------------------

class TestCompose:
    def test_upper_layer_wins_ltp(self, ):
        out = compose([1], {}, [frame(1, ch5=100), frame(1, ch5=30)],
                      htp_masks={})
        assert out[1][5] == 30

    def test_unclaimed_falls_through_to_lower_layer(self):
        out = compose([1], {}, [frame(1, ch5=100), frame(1, ch6=40)],
                      htp_masks={})
        assert out[1][5] == 100
        assert out[1][6] == 40

    def test_floor_shows_only_where_nothing_claims(self):
        floor = frame(1, ch0=255, ch1=255)
        out = compose([1], floor, [frame(1, ch1=10)], htp_masks={})
        assert out[1][0] == 255   # floor falls through
        assert out[1][1] == 10    # layer overrides floor

    def test_floor_never_htps(self):
        # Visible floor has the dimmer at 255; a playing layer's dimmer
        # 10 must WIN, not max() - the floor is fall-through only.
        floor = frame(1, ch0=255)
        out = compose([1], floor, [frame(1, ch0=10)],
                      htp_masks=htp_on(1, 0))
        assert out[1][0] == 10

    def test_dimmer_htp_between_layers(self):
        out = compose([1], {}, [frame(1, ch0=200), frame(1, ch0=80)],
                      htp_masks=htp_on(1, 0))
        assert out[1][0] == 200   # max, not last

    def test_non_dimmer_channel_is_ltp_between_layers(self):
        out = compose([1], {}, [frame(1, ch1=200), frame(1, ch1=80)],
                      htp_masks=htp_on(1, 0))
        assert out[1][1] == 80    # colour: upper layer wins outright

    def test_claim_to_zero_beats_floor_and_lower_layers(self):
        floor = frame(1, ch1=255)
        out = compose([1], floor, [frame(1, ch1=200), frame(1, ch1=0)],
                      htp_masks={})
        assert out[1][1] == 0

    def test_grandmaster_scales_gm_channels_only(self):
        out = compose([1], {}, [frame(1, ch0=200, ch5=200)],
                      htp_masks={}, grandmaster=50, gm_masks=htp_on(1, 0))
        assert out[1][0] == 100   # intensity scaled
        assert out[1][5] == 200   # pan untouched

    def test_grandmaster_scales_the_floor_too(self):
        floor = frame(1, ch0=255)
        out = compose([1], floor, [], htp_masks={}, grandmaster=40,
                      gm_masks=htp_on(1, 0))
        assert out[1][0] == 102   # 255 * 40 // 100

    def test_dbo_zeroes_gm_channels(self):
        out = compose([1], {}, [frame(1, ch0=200, ch5=200)],
                      htp_masks={}, dbo=True, gm_masks=htp_on(1, 0))
        assert out[1][0] == 0
        assert out[1][5] == 200   # non-intensity survives DBO

    def test_dbo_beats_grandmaster(self):
        out = compose([1], {}, [frame(1, ch0=200)], htp_masks={},
                      grandmaster=80, dbo=True, gm_masks=htp_on(1, 0))
        assert out[1][0] == 0

    def test_universes_without_frames_still_output(self):
        out = compose([1, 2], {}, [frame(1, ch0=10)], htp_masks={})
        assert out[2] == bytearray(512)

    def test_layer_only_universe_is_included(self):
        out = compose([1], {}, [frame(7, ch0=10)], htp_masks={})
        assert out[7][0] == 10


# ---------------------------------------------------------------------------
# Channel-class masks + floors (real FixtureChannelMaps)
# ---------------------------------------------------------------------------

def _fixture(name, address, universe=1, model="TestModel"):
    return Fixture(
        universe=universe, address=address, manufacturer="TestMfr",
        model=model, name=name, group="G", current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
        type="MH",
    )


@pytest.fixture
def rgb_par_def():
    """A fixture definition with NO dimmer channel - colour is the
    only intensity (the grandmaster fallback case)."""
    return {
        "manufacturer": "TestMfr",
        "model": "ParModel",
        "channels": [
            {"name": "Red", "preset": "IntensityRed", "group": "Colour",
             "capabilities": []},
            {"name": "Green", "preset": "IntensityGreen", "group": "Colour",
             "capabilities": []},
            {"name": "Blue", "preset": "IntensityBlue", "group": "Colour",
             "capabilities": []},
        ],
        "modes": [
            {"name": "Standard", "channels": [
                {"number": 0, "name": "Red"},
                {"number": 1, "name": "Green"},
                {"number": 2, "name": "Blue"},
            ]},
        ],
    }


@pytest.fixture
def config_one_mover():
    fixture = _fixture("MH1", address=1)
    return Configuration(
        fixtures=[fixture],
        universes={1: Universe(id=1, name="U1", output={})},
    )


@pytest.fixture
def mover_maps(config_one_mover, mock_fixture_def):
    fixture = config_one_mover.fixtures[0]
    return {"MH1": FixtureChannelMap(fixture, mock_fixture_def,
                                     config_one_mover)}


class TestChannelClassMasks:
    def test_mover_dimmer_is_htp_and_gm(self, mover_maps):
        htp, gm = build_channel_class_masks(mover_maps)
        assert htp[1][0] == 1      # dimmer at abs channel 0
        assert gm[1][0] == 1
        assert htp[1][1] == 0      # red is neither HTP nor GM here
        assert gm[1][1] == 0

    def test_rgb_par_falls_back_to_colour_gm(self, rgb_par_def,
                                             config_one_mover):
        par = _fixture("PAR1", address=100, model="ParModel")
        maps = {"PAR1": FixtureChannelMap(par, rgb_par_def,
                                          config_one_mover)}
        htp, gm = build_channel_class_masks(maps)
        assert 1 not in htp or not any(htp[1])   # no dimmer -> no HTP class
        # GM scales the RGB channels (abs 99, 100, 101).
        assert gm[1][99] == 1 and gm[1][100] == 1 and gm[1][101] == 1

    def test_visible_floor_matches_fixtures_visible(self, mover_maps,
                                                    config_one_mover,
                                                    mock_fixture_def):
        floor = render_visible_floor(mover_maps)
        values, mask = floor[1]
        assert values[0] == 255 and mask[0]       # dimmer full
        assert values[5] == 127 and mask[5]       # pan centered
        assert mask[9] == 0                       # gobo unclaimed
        # The floor must be byte-for-byte what set_fixtures_visible
        # writes - including the group-"Colour" quirk where the RGBW
        # channels sit in the colour-wheel class, so the wheel-open 0
        # lands after the RGBW 255 and wins. Prove equivalence against
        # the real thing rather than encoding assumptions:
        from utils.artnet.dmx_manager import DMXManager
        mgr = DMXManager(config_one_mover,
                         {"TestMfr_TestModel": mock_fixture_def})
        mgr.set_fixtures_visible()
        reference_values, reference_mask = mgr.get_frame(1)
        assert values == reference_values
        assert mask == reference_mask


# ---------------------------------------------------------------------------
# OutputArbiter dispatch
# ---------------------------------------------------------------------------

class StubSender:
    def __init__(self):
        self.sent = []
        self.closed = False
        self.target_ip = "255.255.255.255"

    def send_dmx(self, universe, dmx_data, force=False):
        self.sent.append((universe, bytes(dmx_data), force))
        return True

    def close(self):
        self.closed = True


class StaticLayer:
    def __init__(self, frames):
        self.frames = frames
        self.render_calls = 0

    def render(self, now):
        self.render_calls += 1
        return self.frames


class ExplodingLayer:
    def render(self, now):
        raise RuntimeError("boom")


@pytest.fixture
def arbiter_config():
    return Configuration(
        universes={1: Universe(id=1, name="U1", output={}),
                   2: Universe(id=2, name="U2", output={})},
    )


class TestOutputArbiter:
    def test_tick_sends_every_universe_mapped(self, arbiter_config):
        sender = StubSender()
        arbiter = OutputArbiter(config=arbiter_config, sender=sender)
        arbiter.set_idle_policy(IDLE_BLACKOUT)
        arbiter.tick_once(0.0)
        wire = sorted(u for u, _, _ in sender.sent)
        assert wire == [0, 1]                     # 1-based -> 0-based
        assert all(force for _, _, force in sender.sent)

    def test_custom_universe_mapping(self, arbiter_config):
        sender = StubSender()
        arbiter = OutputArbiter(config=arbiter_config, sender=sender)
        arbiter.set_universe_mapping({1: 4, 2: 7})
        arbiter.tick_once(0.0)
        assert sorted(u for u, _, _ in sender.sent) == [4, 7]

    def test_local_callback_gets_config_ids_and_merged_bytes(
            self, arbiter_config):
        sender = StubSender()
        arbiter = OutputArbiter(config=arbiter_config, sender=sender)
        arbiter.set_playback_layer(StaticLayer(frame(1, ch3=99)))
        received = []
        arbiter.set_local_dmx_callback(
            lambda u, data: received.append((u, data)))
        arbiter.tick_once(0.0)
        by_universe = dict(received)
        assert sorted(by_universe) == [1, 2]      # config ids, not wire
        assert by_universe[1][3] == 99

    def test_callback_exception_does_not_kill_the_tick(self,
                                                       arbiter_config):
        sender = StubSender()
        arbiter = OutputArbiter(config=arbiter_config, sender=sender)

        def bad_callback(universe, data):
            raise RuntimeError("visualizer unhappy")

        arbiter.set_local_dmx_callback(bad_callback)
        arbiter.tick_once(0.0)                    # must not raise
        assert len(sender.sent) == 2

    def test_layer_exception_loses_only_its_frame(self, arbiter_config):
        sender = StubSender()
        arbiter = OutputArbiter(config=arbiter_config, sender=sender)
        arbiter.set_playback_layer(ExplodingLayer())
        arbiter.set_live_layer(StaticLayer(frame(1, ch3=42)))
        merged = arbiter.tick_once(0.0)           # must not raise
        assert merged[1][3] == 42

    def test_live_overrides_playback(self, arbiter_config):
        arbiter = OutputArbiter(config=arbiter_config, sender=StubSender())
        arbiter.set_playback_layer(StaticLayer(frame(1, ch3=10)))
        arbiter.set_live_layer(StaticLayer(frame(1, ch3=200)))
        assert arbiter.tick_once(0.0)[1][3] == 200

    def test_pause_look_sits_under_playback(self, arbiter_config):
        arbiter = OutputArbiter(config=arbiter_config, sender=StubSender())
        arbiter.set_pause_look_layer(StaticLayer(frame(1, ch3=66, ch4=66)))
        arbiter.set_playback_layer(StaticLayer(frame(1, ch3=10)))
        merged = arbiter.tick_once(0.0)
        assert merged[1][3] == 10                 # playback wins
        assert merged[1][4] == 66                 # pause look falls through

    def test_grandmaster_and_dbo_apply(self, arbiter_config,
                                       config_one_mover, mock_fixture_def,
                                       mover_maps):
        sender = StubSender()
        arbiter = OutputArbiter(config=config_one_mover, sender=sender)
        arbiter.set_fixture_maps(mover_maps)
        arbiter.set_idle_policy(IDLE_BLACKOUT)
        arbiter.set_playback_layer(StaticLayer(frame(1, ch0=200)))
        arbiter.set_grandmaster(50)
        assert arbiter.tick_once(0.0)[1][0] == 100
        arbiter.set_dbo(True)
        assert arbiter.tick_once(0.0)[1][0] == 0

    def test_idle_policy_switches_floor(self, config_one_mover,
                                        mover_maps):
        arbiter = OutputArbiter(config=config_one_mover,
                                sender=StubSender())
        arbiter.set_fixture_maps(mover_maps)
        assert arbiter.tick_once(0.0)[1][0] == 255     # visible default
        arbiter.set_idle_policy(IDLE_BLACKOUT)
        assert arbiter.tick_once(0.0)[1][0] == 0
        arbiter.set_idle_policy(IDLE_VISIBLE)
        assert arbiter.tick_once(0.0)[1][0] == 255

    def test_loop_smoke(self, arbiter_config):
        sender = StubSender()
        arbiter = OutputArbiter(config=arbiter_config, sender=sender,
                                tick_hz=200)
        arbiter.start()
        assert arbiter.running
        deadline = time.time() + 2.0
        while not sender.sent and time.time() < deadline:
            time.sleep(0.01)
        arbiter.stop(blackout=True)
        assert not arbiter.running
        assert sender.sent, "loop never ticked"
        # The stop blackout is the last thing on the wire.
        assert sender.sent[-1][1] == bytes(512)

    def test_shutdown_closes_sender(self, arbiter_config):
        sender = StubSender()
        arbiter = OutputArbiter(config=arbiter_config, sender=sender)
        arbiter.shutdown()
        assert sender.closed

    def test_status_snapshot(self, arbiter_config):
        arbiter = OutputArbiter(config=arbiter_config, sender=StubSender())
        status = arbiter.status()
        assert status["running"] is False
        assert status["frames_sent"] == 0
        assert status["universe_mapping"] == {1: 0, 2: 1}
        arbiter.tick_once(0.0)
        arbiter.tick_once(1.0)
        assert arbiter.status()["frames_sent"] == 2


class TestPlaybackSlot:
    """The EXCLUSIVE playback slot: timeline XOR auto (locked
    decision 2026-07-11) - second producer is refused, not evicted."""

    def test_acquire_and_refusal(self, arbiter_config):
        arbiter = OutputArbiter(config=arbiter_config, sender=StubSender())
        timeline = StaticLayer(frame(1, ch0=10))
        auto = StaticLayer(frame(1, ch0=20))
        assert arbiter.acquire_playback_slot(timeline, "timeline") is True
        assert arbiter.playback_slot_owner() == "timeline"
        assert arbiter.acquire_playback_slot(auto, "auto") is False
        # The holder keeps rendering.
        assert arbiter.tick_once(0.0)[1][0] == 10

    def test_same_owner_reacquires(self, arbiter_config):
        arbiter = OutputArbiter(config=arbiter_config, sender=StubSender())
        layer_a = StaticLayer({})
        layer_b = StaticLayer({})
        assert arbiter.acquire_playback_slot(layer_a, "timeline")
        assert arbiter.acquire_playback_slot(layer_b, "timeline")

    def test_release_frees_the_slot(self, arbiter_config):
        arbiter = OutputArbiter(config=arbiter_config, sender=StubSender())
        arbiter.acquire_playback_slot(StaticLayer({}), "timeline")
        arbiter.release_playback_slot("timeline")
        assert arbiter.playback_slot_owner() is None
        assert arbiter.acquire_playback_slot(StaticLayer({}), "auto")

    def test_release_by_non_owner_is_a_no_op(self, arbiter_config):
        arbiter = OutputArbiter(config=arbiter_config, sender=StubSender())
        arbiter.acquire_playback_slot(StaticLayer({}), "timeline")
        arbiter.release_playback_slot("auto")
        assert arbiter.playback_slot_owner() == "timeline"


class TestBroadcastMirror:
    def test_mirror_repeats_frames_when_enabled(self, arbiter_config):
        sender = StubSender()
        mirror = StubSender()
        arbiter = OutputArbiter(config=arbiter_config, sender=sender)
        arbiter.set_broadcast_mirror(True, sender=mirror)
        arbiter.set_playback_layer(StaticLayer(frame(1, ch0=42)))
        arbiter.tick_once(0.0)
        assert len(mirror.sent) == len(sender.sent) == 2
        assert mirror.sent[0][1] == sender.sent[0][1]

    def test_mirror_silent_when_disabled(self, arbiter_config):
        mirror = StubSender()
        arbiter = OutputArbiter(config=arbiter_config, sender=StubSender())
        arbiter.set_broadcast_mirror(True, sender=mirror)
        arbiter.set_broadcast_mirror(False)
        arbiter.tick_once(0.0)
        assert mirror.sent == []

    def test_blackout_reaches_a_disabled_mirror(self, arbiter_config):
        # A viewer must not hold the last mirrored frame after stop,
        # even if mirroring was toggled off mid-show.
        mirror = StubSender()
        arbiter = OutputArbiter(config=arbiter_config, sender=StubSender())
        arbiter.set_broadcast_mirror(True, sender=mirror)
        arbiter.set_broadcast_mirror(False)
        arbiter.stop(blackout=True)
        assert mirror.sent
        assert all(data == bytes(512) for _, data, _ in mirror.sent)


class TestArtnetTargetFromConfig:
    """The native output's destination comes from the configured
    universes (before 2026-07-13 the universe's Target IP was export-
    only and native output always broadcast, which never reaches a
    node on a secondary NIC)."""

    def _config(self, *universes):
        config = Configuration()
        config.universes = {u.id: u for u in universes}
        return config

    def test_picks_the_first_artnet_universe_ip(self):
        from utils.artnet.arbiter import artnet_target_from_config
        config = self._config(
            Universe(id=1, name="U1", output={
                "plugin": "ArtNet", "line": "0",
                "parameters": {"ip": "2.0.0.1", "subnet": "0",
                               "universe": "0"}}),
            Universe(id=2, name="U2", output={
                "plugin": "ArtNet", "line": "0",
                "parameters": {"ip": "10.0.0.9", "subnet": "0",
                               "universe": "1"}}),
        )
        assert artnet_target_from_config(config) == "2.0.0.1"

    def test_skips_non_artnet_universes(self):
        from utils.artnet.arbiter import artnet_target_from_config
        config = self._config(
            Universe(id=1, name="U1", output={
                "plugin": "E1.31", "line": "0",
                "parameters": {"ip": "239.255.0.1", "universe": "1"}}),
            Universe(id=2, name="U2", output={
                "plugin": "ArtNet", "line": "0",
                "parameters": {"ip": "2.0.0.1", "subnet": "0",
                               "universe": "1"}}),
        )
        assert artnet_target_from_config(config) == "2.0.0.1"

    def test_broadcast_when_nothing_configured(self):
        from utils.artnet.arbiter import (
            BROADCAST_IP, artnet_target_from_config,
        )
        empty_ip = self._config(Universe(id=1, name="U1", output={
            "plugin": "ArtNet", "line": "0",
            "parameters": {"ip": "", "subnet": "0", "universe": "0"}}))
        assert artnet_target_from_config(empty_ip) == BROADCAST_IP
        assert artnet_target_from_config(Configuration()) == BROADCAST_IP


class TestBuildFixtureMapsStandalone:
    """DMXManager.build_fixture_maps: the arbiter gets channel maps from
    the config directly, so the visible idle floor lights the rig when
    OUTPUT is toggled with nothing playing (it used to stream an
    all-zero floor until a playback controller registered maps - found
    live against the NET-2, 2026-07-13)."""

    def test_builds_the_same_maps_playback_would(self, config_one_mover,
                                                 mock_fixture_def):
        from utils.artnet.dmx_manager import DMXManager
        maps = DMXManager.build_fixture_maps(
            config_one_mover,
            {"TestMfr_TestModel": mock_fixture_def})
        assert set(maps) == {"MH1"}
        assert maps["MH1"].pan_channels or maps["MH1"].dimmer_channels

    def test_visible_floor_lights_up_from_standalone_maps(
            self, config_one_mover, mock_fixture_def):
        from utils.artnet.dmx_manager import DMXManager
        maps = DMXManager.build_fixture_maps(
            config_one_mover,
            {"TestMfr_TestModel": mock_fixture_def})
        floor = render_visible_floor(maps)
        assert floor, "floor must not be empty with maps present"
        values, mask = floor[1]
        assert any(values), "visible floor must carry non-zero values"
        assert any(mask)

    def test_missing_definition_is_skipped_not_fatal(self,
                                                     config_one_mover):
        from utils.artnet.dmx_manager import DMXManager
        maps = DMXManager.build_fixture_maps(config_one_mover, {})
        assert maps == {}
