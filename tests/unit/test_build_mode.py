# tests/unit/test_build_mode.py
"""The shared build-look synthesizer (visualizer/build_mode.py): ONE
table + ONE synthesizer used by both the embedded preview's build mode
and the standalone viewer's BUILD chip, so the two looks cannot drift."""

from visualizer.build_mode import BUILD_MODE_DEFAULTS, build_mode_buffers


class TestDefaults:
    def test_the_look_is_full_white_open_and_centred(self):
        assert BUILD_MODE_DEFAULTS["dimmer"] == 255
        assert BUILD_MODE_DEFAULTS["red"] == 255
        assert BUILD_MODE_DEFAULTS["shutter"] == 255
        assert BUILD_MODE_DEFAULTS["pan"] == 128
        assert BUILD_MODE_DEFAULTS["tilt"] == 128
        assert "gobo" not in BUILD_MODE_DEFAULTS   # artefact channels stay 0
        assert "strobe" not in BUILD_MODE_DEFAULTS


class TestBuildModeBuffers:
    def test_one_buffer_per_universe(self):
        buffers = build_mode_buffers([
            {"universe": 1, "address": 1, "channel_mapping": {"0": "dimmer"}},
            {"universe": 3, "address": 1, "channel_mapping": {"0": "dimmer"}},
        ])
        assert sorted(buffers) == [1, 3]
        assert all(len(b) == 512 for b in buffers.values())

    def test_values_land_at_address_plus_offset(self):
        buffers = build_mode_buffers([
            {"universe": 1, "address": 100,
             "channel_mapping": {"0": "dimmer", "1": "pan", "2": "gobo"}},
        ])
        buf = buffers[1]
        assert buf[99] == 255    # dimmer at 1-based address 100
        assert buf[100] == 128   # pan centred
        assert buf[101] == 0     # unknown-to-the-look function stays 0

    def test_string_channel_keys_from_json_round_trip(self):
        # JSON turns int keys into strings; both must work.
        for key in (5, "5"):
            buffers = build_mode_buffers([
                {"universe": 1, "address": 1,
                 "channel_mapping": {key: "dimmer"}}])
            assert buffers[1][5] == 255

    def test_garbage_is_skipped_not_fatal(self):
        buffers = build_mode_buffers([
            {"universe": 1, "address": 1,
             "channel_mapping": {"not-a-number": "dimmer", "600": "dimmer"}},
            {"universe": 1, "address": 1, "channel_mapping": None},
            {"universe": 1, "address": 1},
        ])
        assert buffers[1] == bytes(512)

    def test_empty_rig_yields_no_buffers(self):
        assert build_mode_buffers([]) == {}

    def test_overlapping_fixtures_share_the_universe_buffer(self):
        buffers = build_mode_buffers([
            {"universe": 1, "address": 1, "channel_mapping": {"0": "dimmer"}},
            {"universe": 1, "address": 8, "channel_mapping": {"0": "red"}},
        ])
        assert buffers[1][0] == 255 and buffers[1][7] == 255
