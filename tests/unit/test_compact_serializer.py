"""Tests for config.compact_serializer two-level deduplication."""
import pytest
from copy import deepcopy
from config.compact_serializer import compact_serialize, expand_compact, _content_key, SUBLANE_EXCLUDE_FIELDS


def _make_dimmer(start, end, intensity=255.0, effect_type="static", effect_speed="1",
                 strobe_speed=0.0, iris=255.0, modified=False):
    return {
        "start_time": start, "end_time": end,
        "intensity": intensity, "strobe_speed": strobe_speed,
        "iris": iris, "effect_type": effect_type,
        "effect_speed": effect_speed, "modified": modified,
    }


def _make_colour(start, end, red=255.0, green=255.0, blue=255.0, **kwargs):
    base = {
        "start_time": start, "end_time": end,
        "color_mode": "RGB",
        "red": red, "green": green, "blue": blue,
        "white": 0.0, "amber": 0.0, "cyan": 0.0,
        "magenta": 0.0, "yellow": 0.0, "uv": 0.0, "lime": 0.0,
        "hue": 0.0, "saturation": 0.0, "value": 0.0,
        "color_wheel_position": 0, "modified": False,
    }
    base.update(kwargs)
    return base


def _make_movement(start, end, pan=127.5, tilt=127.5, effect_type="static", **kwargs):
    base = {
        "start_time": start, "end_time": end,
        "pan": pan, "tilt": tilt,
        "pan_fine": 0.0, "tilt_fine": 0.0,
        "speed": 255.0, "interpolate_from_previous": True,
        "effect_type": effect_type, "effect_speed": "1",
        "pan_min": 0.0, "pan_max": 255.0,
        "tilt_min": 0.0, "tilt_max": 255.0,
        "pan_amplitude": 50.0, "tilt_amplitude": 50.0,
        "lissajous_ratio": "1:2",
        "phase_offset_enabled": False, "phase_offset_degrees": 0.0,
        "target_spot_name": None, "modified": False,
    }
    base.update(kwargs)
    return base


def _make_special(start, end, gobo_index=0, focus=127.5, zoom=127.5):
    return {
        "start_time": start, "end_time": end,
        "gobo_index": gobo_index, "gobo_rotation": 0.0,
        "focus": focus, "zoom": zoom,
        "prism_enabled": False, "prism_rotation": 0.0,
        "modified": False,
    }


def _make_lightblock(start, end, effect_name="bars.static", dimmer_blocks=None,
                     colour_blocks=None, movement_blocks=None, special_blocks=None,
                     name=None, riff_source=None, riff_version=None):
    return {
        "start_time": start, "end_time": end,
        "effect_name": effect_name,
        "modified": False,
        "dimmer_blocks": dimmer_blocks or [_make_dimmer(start, end)],
        "colour_blocks": colour_blocks or [_make_colour(start, end)],
        "movement_blocks": movement_blocks or [_make_movement(start, end)],
        "special_blocks": special_blocks or [_make_special(start, end)],
        "riff_source": riff_source,
        "riff_version": riff_version,
        "name": name,
        "duration": end - start,
        "parameters": {},
    }


def _make_lane(light_blocks, name="Lane 1", fixture_targets=None):
    return {
        "name": name,
        "fixture_targets": fixture_targets or ["MH"],
        "muted": False,
        "solo": False,
        "light_blocks": light_blocks,
    }


def _make_config_with_shows(shows_dict):
    """Wrap shows dict in a full config structure."""
    return {
        "fixtures": [],
        "groups": {},
        "universes": {},
        "songs": shows_dict,
        "spots": {},
        "workspace_path": None,
        "shows_directory": None,
    }


def _make_show(lanes, parts=None):
    return {
        "parts": parts or [],
        "effects": [],
        "timeline_data": {
            "lanes": lanes,
            "audio_file_path": None,
        },
    }


class TestEmptyAndNoTimeline:
    def test_empty_config(self):
        """Roundtrip with empty config (no shows)."""
        data = _make_config_with_shows({})
        compact = compact_serialize(data)
        assert 'block_defs' not in compact
        # expand_compact should pass through since no block_defs
        result = expand_compact(compact)
        assert result['songs'] == {}

    def test_no_timeline_data(self):
        """Show with no timeline_data passes through unchanged."""
        data = _make_config_with_shows({
            "MyShow": {"parts": [], "effects": [], "timeline_data": None}
        })
        compact = compact_serialize(data)
        assert 'block_defs' not in compact

    def test_empty_lanes(self):
        """Show with empty lanes passes through unchanged."""
        data = _make_config_with_shows({
            "MyShow": _make_show(lanes=[])
        })
        compact = compact_serialize(data)
        assert 'block_defs' not in compact


class TestBackwardCompat:
    def test_no_block_defs_passes_through(self):
        """Dict without block_defs passes through expand_compact unchanged."""
        data = _make_config_with_shows({
            "MyShow": _make_show(lanes=[
                _make_lane([_make_lightblock(0, 10)])
            ])
        })
        result = expand_compact(data)
        # Should be identical - no transformation
        assert result == data

    def test_old_format_load(self):
        """Old inline format loads correctly without block_defs."""
        lb = _make_lightblock(5.0, 15.0)
        data = _make_config_with_shows({
            "S1": _make_show(lanes=[_make_lane([lb])])
        })
        result = expand_compact(data)
        assert result['songs']['S1']['timeline_data']['lanes'][0]['light_blocks'][0] == lb


class TestSingleLightBlock:
    def test_single_block_roundtrip(self):
        """Single LightBlock serializes and deserializes correctly."""
        lb = _make_lightblock(2.0, 12.0)
        data = _make_config_with_shows({
            "S1": _make_show(lanes=[_make_lane([lb])])
        })
        original = deepcopy(data)

        compact = compact_serialize(data)
        assert 'block_defs' in compact
        assert 'light_block_defs' in compact
        assert 'lb0' in compact['light_block_defs']

        # Verify lane now has ref+start+end entries
        lane = compact['songs']['S1']['timeline_data']['lanes'][0]
        assert len(lane['light_blocks']) == 1
        assert lane['light_blocks'][0]['ref'] == 'lb0'
        assert lane['light_blocks'][0]['start'] == 2.0
        assert lane['light_blocks'][0]['end'] == 12.0

        # Roundtrip back
        expanded = expand_compact(compact)
        exp_lb = expanded['songs']['S1']['timeline_data']['lanes'][0]['light_blocks'][0]

        # Compare key fields
        assert exp_lb['start_time'] == 2.0
        assert exp_lb['end_time'] == 12.0
        assert exp_lb['effect_name'] == 'bars.static'
        assert len(exp_lb['dimmer_blocks']) == 1
        assert exp_lb['dimmer_blocks'][0]['start_time'] == 2.0
        assert exp_lb['dimmer_blocks'][0]['end_time'] == 12.0
        assert exp_lb['dimmer_blocks'][0]['intensity'] == 255.0


class TestSublaneDedup:
    def test_identical_dimmers_deduped(self):
        """Identical DimmerBlocks across different LightBlocks share one template."""
        lb1 = _make_lightblock(0, 10)
        lb2 = _make_lightblock(20, 30)  # Same content, different times
        data = _make_config_with_shows({
            "S1": _make_show(lanes=[_make_lane([lb1, lb2])])
        })
        compact = compact_serialize(data)

        # Should have only one dimmer template
        assert len(compact['block_defs']['dimmer']) == 1
        assert 'd0' in compact['block_defs']['dimmer']

    def test_different_dimmers_separate(self):
        """Different sublane blocks produce different templates."""
        lb1 = _make_lightblock(0, 10, dimmer_blocks=[_make_dimmer(0, 10, intensity=255.0)])
        lb2 = _make_lightblock(20, 30, dimmer_blocks=[_make_dimmer(20, 30, intensity=128.0)])
        data = _make_config_with_shows({
            "S1": _make_show(lanes=[_make_lane([lb1, lb2])])
        })
        compact = compact_serialize(data)

        assert len(compact['block_defs']['dimmer']) == 2
        assert 'd0' in compact['block_defs']['dimmer']
        assert 'd1' in compact['block_defs']['dimmer']


class TestLightBlockDedup:
    def test_identical_lightblocks_deduped(self):
        """Identical LightBlocks at different times share one template."""
        lb1 = _make_lightblock(0, 10)
        lb2 = _make_lightblock(20, 30)
        data = _make_config_with_shows({
            "S1": _make_show(lanes=[_make_lane([lb1, lb2])])
        })
        compact = compact_serialize(data)

        # Should have one LightBlock template, two entries sharing same ref
        assert len(compact['light_block_defs']) == 1
        lane = compact['songs']['S1']['timeline_data']['lanes'][0]
        assert len(lane['light_blocks']) == 2
        assert lane['light_blocks'][0] == {'ref': 'lb0', 'start': 0, 'end': 10}
        assert lane['light_blocks'][1] == {'ref': 'lb0', 'start': 20, 'end': 30}

    def test_different_lightblocks_separate(self):
        """LightBlocks with different content produce different templates."""
        lb1 = _make_lightblock(0, 10, effect_name="bars.static")
        lb2 = _make_lightblock(20, 30, effect_name="bars.pulse")
        data = _make_config_with_shows({
            "S1": _make_show(lanes=[_make_lane([lb1, lb2])])
        })
        compact = compact_serialize(data)

        assert len(compact['light_block_defs']) == 2
        lane = compact['songs']['S1']['timeline_data']['lanes'][0]
        assert len(lane['light_blocks']) == 2


class TestOrderPreservation:
    def test_non_chronological_order_preserved(self):
        """Blocks not in chronological order are preserved in original order."""
        lb_a = _make_lightblock(20, 30, effect_name="bars.static")
        lb_b = _make_lightblock(0, 10, effect_name="bars.pulse")
        lb_a2 = _make_lightblock(40, 50, effect_name="bars.static")
        data = _make_config_with_shows({
            "S1": _make_show(lanes=[_make_lane([lb_a, lb_b, lb_a2])])
        })
        original = deepcopy(data)
        compact = compact_serialize(data)
        expanded = expand_compact(compact)

        exp_blocks = expanded['songs']['S1']['timeline_data']['lanes'][0]['light_blocks']
        assert len(exp_blocks) == 3
        # Order must match original, not chronological
        assert exp_blocks[0]['start_time'] == 20.0
        assert exp_blocks[1]['start_time'] == 0.0
        assert exp_blocks[2]['start_time'] == 40.0


class TestDurationScaling:
    def test_same_template_different_durations(self):
        """Same template at different durations correctly restores absolute times."""
        lb1 = _make_lightblock(0, 10)  # 10 seconds
        lb2 = _make_lightblock(50, 70)  # 20 seconds, same relative content
        data = _make_config_with_shows({
            "S1": _make_show(lanes=[_make_lane([lb1, lb2])])
        })
        compact = compact_serialize(data)
        expanded = expand_compact(compact)

        blocks = expanded['songs']['S1']['timeline_data']['lanes'][0]['light_blocks']
        assert len(blocks) == 2

        # First block: 0-10
        assert blocks[0]['start_time'] == 0.0
        assert blocks[0]['end_time'] == 10.0
        assert blocks[0]['dimmer_blocks'][0]['start_time'] == 0.0
        assert blocks[0]['dimmer_blocks'][0]['end_time'] == 10.0

        # Second block: 50-70
        assert blocks[1]['start_time'] == 50.0
        assert blocks[1]['end_time'] == 70.0
        assert blocks[1]['dimmer_blocks'][0]['start_time'] == 50.0
        assert blocks[1]['dimmer_blocks'][0]['end_time'] == 70.0


class TestFractionalSublane:
    def test_sublane_partial_span(self):
        """Sublane that doesn't span the entire LightBlock preserves relative timing."""
        # Dimmer only covers first half of LightBlock
        lb = _make_lightblock(10, 20,
                              dimmer_blocks=[_make_dimmer(10, 15)])
        data = _make_config_with_shows({
            "S1": _make_show(lanes=[_make_lane([lb])])
        })
        compact = compact_serialize(data)

        # Check the template has offset=0.0, end=0.5
        lb_template = compact['light_block_defs']['lb0']
        assert lb_template['dimmer_blocks'][0]['offset'] == 0.0
        assert lb_template['dimmer_blocks'][0]['end'] == 0.5

        # Roundtrip
        expanded = expand_compact(compact)
        exp_lb = expanded['songs']['S1']['timeline_data']['lanes'][0]['light_blocks'][0]
        assert exp_lb['dimmer_blocks'][0]['start_time'] == 10.0
        assert exp_lb['dimmer_blocks'][0]['end_time'] == 15.0

    def test_sublane_middle_portion(self):
        """Sublane covering middle portion of LightBlock."""
        # Colour covers 25%-75% of LightBlock
        lb = _make_lightblock(0, 100,
                              colour_blocks=[_make_colour(25, 75)])
        data = _make_config_with_shows({
            "S1": _make_show(lanes=[_make_lane([lb])])
        })
        compact = compact_serialize(data)
        lb_template = compact['light_block_defs']['lb0']
        assert lb_template['colour_blocks'][0]['offset'] == 0.25
        assert lb_template['colour_blocks'][0]['end'] == 0.75

        expanded = expand_compact(compact)
        exp_lb = expanded['songs']['S1']['timeline_data']['lanes'][0]['light_blocks'][0]
        assert exp_lb['colour_blocks'][0]['start_time'] == 25.0
        assert exp_lb['colour_blocks'][0]['end_time'] == 75.0

    def test_multiple_sublane_blocks(self):
        """Multiple sublane blocks within one LightBlock."""
        lb = _make_lightblock(0, 20,
                              dimmer_blocks=[
                                  _make_dimmer(0, 10, intensity=255.0),
                                  _make_dimmer(10, 20, intensity=128.0),
                              ])
        data = _make_config_with_shows({
            "S1": _make_show(lanes=[_make_lane([lb])])
        })
        compact = compact_serialize(data)
        lb_template = compact['light_block_defs']['lb0']
        assert len(lb_template['dimmer_blocks']) == 2
        assert lb_template['dimmer_blocks'][0] == {'ref': 'd0', 'offset': 0.0, 'end': 0.5}
        assert lb_template['dimmer_blocks'][1] == {'ref': 'd1', 'offset': 0.5, 'end': 1.0}

        expanded = expand_compact(compact)
        exp_lb = expanded['songs']['S1']['timeline_data']['lanes'][0]['light_blocks'][0]
        assert exp_lb['dimmer_blocks'][0]['start_time'] == 0.0
        assert exp_lb['dimmer_blocks'][0]['end_time'] == 10.0
        assert exp_lb['dimmer_blocks'][0]['intensity'] == 255.0
        assert exp_lb['dimmer_blocks'][1]['start_time'] == 10.0
        assert exp_lb['dimmer_blocks'][1]['end_time'] == 20.0
        assert exp_lb['dimmer_blocks'][1]['intensity'] == 128.0


class TestMultipleShows:
    def test_global_templates_across_shows(self):
        """Templates are global across all shows."""
        lb1 = _make_lightblock(0, 10)
        lb2 = _make_lightblock(5, 15)  # Same content as lb1 but different times
        data = _make_config_with_shows({
            "Show1": _make_show(lanes=[_make_lane([lb1])]),
            "Show2": _make_show(lanes=[_make_lane([lb2])]),
        })
        compact = compact_serialize(data)

        # Should share the same templates
        assert len(compact['light_block_defs']) == 1
        assert len(compact['block_defs']['dimmer']) == 1


class TestFloatPrecision:
    def test_epsilon_difference_treated_as_same(self):
        """Blocks differing only at float epsilon are treated as same template."""
        lb1 = _make_lightblock(0, 10,
                               dimmer_blocks=[_make_dimmer(0, 10, intensity=255.0000001)])
        lb2 = _make_lightblock(20, 30,
                               dimmer_blocks=[_make_dimmer(20, 30, intensity=255.0000002)])
        data = _make_config_with_shows({
            "S1": _make_show(lanes=[_make_lane([lb1, lb2])])
        })
        compact = compact_serialize(data)

        # Should dedup to one dimmer template (difference < 1e-6)
        assert len(compact['block_defs']['dimmer']) == 1

    def test_significant_difference_kept_separate(self):
        """Blocks with meaningful float differences stay separate."""
        lb1 = _make_lightblock(0, 10,
                               dimmer_blocks=[_make_dimmer(0, 10, intensity=255.0)])
        lb2 = _make_lightblock(20, 30,
                               dimmer_blocks=[_make_dimmer(20, 30, intensity=254.0)])
        data = _make_config_with_shows({
            "S1": _make_show(lanes=[_make_lane([lb1, lb2])])
        })
        compact = compact_serialize(data)
        assert len(compact['block_defs']['dimmer']) == 2


class TestFullRoundtrip:
    def test_comprehensive_roundtrip(self):
        """Full roundtrip: save compact -> load -> compare field-by-field."""
        lb1 = _make_lightblock(
            2.31, 23.18,
            effect_name="bars.static",
            dimmer_blocks=[_make_dimmer(2.31, 23.18, intensity=200.0, effect_type="ping_pong")],
            colour_blocks=[_make_colour(2.31, 23.18, red=128.0, green=64.0, blue=32.0)],
            movement_blocks=[_make_movement(2.31, 23.18, pan=100.0, tilt=80.0, effect_type="lissajous")],
            special_blocks=[_make_special(2.31, 23.18, gobo_index=3, focus=200.0)],
            name="my_effect",
            riff_source="builds/strobe",
            riff_version="1.0",
        )
        lb2 = _make_lightblock(
            41.73, 53.33,
            effect_name="bars.static",
            dimmer_blocks=[_make_dimmer(41.73, 53.33, intensity=200.0, effect_type="ping_pong")],
            colour_blocks=[_make_colour(41.73, 53.33, red=128.0, green=64.0, blue=32.0)],
            movement_blocks=[_make_movement(41.73, 53.33, pan=100.0, tilt=80.0, effect_type="lissajous")],
            special_blocks=[_make_special(41.73, 53.33, gobo_index=3, focus=200.0)],
            name="my_effect",
            riff_source="builds/strobe",
            riff_version="1.0",
        )
        lb3 = _make_lightblock(
            60.0, 80.0,
            effect_name="bars.pulse",
            dimmer_blocks=[_make_dimmer(60.0, 80.0, intensity=100.0)],
        )

        data = _make_config_with_shows({
            "Show1": _make_show(
                lanes=[
                    _make_lane([lb1, lb2, lb3], fixture_targets=["MH"]),
                    _make_lane([deepcopy(lb1)], name="Lane 2", fixture_targets=["PAR"]),
                ],
                parts=[{"name": "Intro", "color": "#ff0000", "signature": "4/4",
                        "bpm": 120.0, "num_bars": 8, "transition": "cut"}],
            ),
        })
        original = deepcopy(data)
        compact = compact_serialize(data)

        # Verify dedup happened
        # lb1 and lb2 are identical content -> 1 template, lb3 is different -> 2 total
        assert len(compact['light_block_defs']) == 2

        # Expand back
        expanded = expand_compact(compact)

        # Compare shows structure
        for show_name in original['songs']:
            orig_show = original['songs'][show_name]
            exp_show = expanded['songs'][show_name]

            # Parts unchanged
            assert orig_show['parts'] == exp_show['parts']

            orig_lanes = orig_show['timeline_data']['lanes']
            exp_lanes = exp_show['timeline_data']['lanes']
            assert len(orig_lanes) == len(exp_lanes)

            for orig_lane, exp_lane in zip(orig_lanes, exp_lanes):
                assert orig_lane['name'] == exp_lane['name']
                assert orig_lane['fixture_targets'] == exp_lane['fixture_targets']

                orig_lbs = orig_lane['light_blocks']
                exp_lbs = exp_lane['light_blocks']
                assert len(orig_lbs) == len(exp_lbs)

                for orig_lb, exp_lb in zip(orig_lbs, exp_lbs):
                    assert exp_lb['start_time'] == orig_lb['start_time']
                    assert exp_lb['end_time'] == orig_lb['end_time']
                    assert exp_lb['effect_name'] == orig_lb['effect_name']
                    assert exp_lb['name'] == orig_lb['name']
                    assert exp_lb['riff_source'] == orig_lb['riff_source']
                    assert exp_lb['riff_version'] == orig_lb['riff_version']

                    for key in ['dimmer_blocks', 'colour_blocks', 'movement_blocks', 'special_blocks']:
                        orig_subs = orig_lb[key]
                        exp_subs = exp_lb[key]
                        assert len(orig_subs) == len(exp_subs), f"Mismatch in {key}"
                        for orig_sub, exp_sub in zip(orig_subs, exp_subs):
                            assert exp_sub['start_time'] == pytest.approx(orig_sub['start_time'], abs=1e-5)
                            assert exp_sub['end_time'] == pytest.approx(orig_sub['end_time'], abs=1e-5)
                            # Compare all content fields
                            for field in orig_sub:
                                if field in ('start_time', 'end_time', 'modified'):
                                    continue
                                assert exp_sub[field] == orig_sub[field], \
                                    f"Field {field} mismatch in {key}: {exp_sub[field]} != {orig_sub[field]}"

    def test_roundtrip_with_lane2_placement(self):
        """Lane 2 with same LightBlock at different time roundtrips correctly."""
        lb = _make_lightblock(100, 200)
        data = _make_config_with_shows({
            "S1": _make_show(lanes=[_make_lane([lb])])
        })
        compact = compact_serialize(data)
        expanded = expand_compact(compact)

        result_lb = expanded['songs']['S1']['timeline_data']['lanes'][0]['light_blocks'][0]
        assert result_lb['start_time'] == 100.0
        assert result_lb['end_time'] == 200.0
        assert result_lb['dimmer_blocks'][0]['start_time'] == 100.0
        assert result_lb['dimmer_blocks'][0]['end_time'] == 200.0


class TestContentKey:
    def test_timing_excluded(self):
        """start_time, end_time, modified are excluded from content key."""
        b1 = _make_dimmer(0, 10, intensity=200)
        b2 = _make_dimmer(50, 60, intensity=200)
        assert _content_key(b1, SUBLANE_EXCLUDE_FIELDS) == _content_key(b2, SUBLANE_EXCLUDE_FIELDS)

    def test_content_difference_detected(self):
        b1 = _make_dimmer(0, 10, intensity=200)
        b2 = _make_dimmer(0, 10, intensity=100)
        assert _content_key(b1, SUBLANE_EXCLUDE_FIELDS) != _content_key(b2, SUBLANE_EXCLUDE_FIELDS)
