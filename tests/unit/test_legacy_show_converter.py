# tests/unit/test_legacy_show_converter.py
"""Unit tests for the legacy effects -> modern timeline conversion."""

import pytest

from config.models import Song, ShowPart, ShowEffect
from utils.legacy_show_converter import (
    convert_legacy_show, convert_show_in_place, LEGACY_EFFECT_MAP,
)


def _show():
    """A tiny two-part legacy show exercising dimmer, colour, and movement."""
    parts = [
        ShowPart(name="intro", color="#000", signature="4/4", bpm=120, num_bars=4, transition="instant"),
        ShowPart(name="chorus", color="#000", signature="4/4", bpm=120, num_bars=4, transition="instant"),
    ]
    effects = [
        # intro: BARS with a colour + a wave dimmer
        ShowEffect(show_part="intro", fixture_group="BARS", effect="bars.wave",
                   speed="1", color="#FF0000", intensity=200, spot=""),
        # intro: MH movement pointing at a spot
        ShowEffect(show_part="intro", fixture_group="MH", effect="moving_heads.whirl",
                   speed="2", color="", intensity=255, spot="CenterSpot"),
        # chorus: BARS empty effect -> static dimmer at intensity
        ShowEffect(show_part="chorus", fixture_group="BARS", effect="",
                   speed="1", color="", intensity=180, spot=""),
    ]
    return Song(name="t", parts=parts, effects=effects)


class TestConvertLegacyShow:

    def test_lane_per_group(self):
        td = convert_legacy_show(_show())
        names = sorted(l.name for l in td.lanes)
        assert names == ["BARS", "MH"]

    def test_dimmer_effect_mapped(self):
        td = convert_legacy_show(_show())
        bars = next(l for l in td.lanes if l.name == "BARS")
        intro = next(b for b in bars.light_blocks if b.name == "intro")
        assert intro.dimmer_blocks and intro.dimmer_blocks[0].effect_type == "wave"
        assert intro.dimmer_blocks[0].intensity == 200.0

    def test_colour_block_from_hex(self):
        td = convert_legacy_show(_show())
        bars = next(l for l in td.lanes if l.name == "BARS")
        intro = next(b for b in bars.light_blocks if b.name == "intro")
        assert intro.colour_blocks
        c = intro.colour_blocks[0]
        assert (c.red, c.green, c.blue) == (255.0, 0.0, 0.0)

    def test_movement_effect_and_spot(self):
        td = convert_legacy_show(_show())
        mh = next(l for l in td.lanes if l.name == "MH")
        blk = mh.light_blocks[0]
        assert blk.movement_blocks
        mv = blk.movement_blocks[0]
        assert mv.effect_type == "circle"  # whirl -> circle
        assert mv.target_spot_name == "CenterSpot"
        # movement fixtures still get a lit dimmer so they're visible
        assert blk.dimmer_blocks and blk.dimmer_blocks[0].intensity == 255.0

    def test_empty_effect_is_static_dimmer(self):
        td = convert_legacy_show(_show())
        bars = next(l for l in td.lanes if l.name == "BARS")
        chorus = next(b for b in bars.light_blocks if b.name == "chorus")
        assert chorus.dimmer_blocks[0].effect_type == "static"
        assert chorus.dimmer_blocks[0].intensity == 180.0

    def test_block_times_follow_structure(self):
        # instant transitions, 4 bars @ 120 BPM 4/4 = 8s per part.
        td = convert_legacy_show(_show())
        bars = next(l for l in td.lanes if l.name == "BARS")
        chorus = next(b for b in bars.light_blocks if b.name == "chorus")
        assert chorus.start_time == pytest.approx(8.0)
        assert chorus.end_time == pytest.approx(16.0)

    def test_convert_in_place_sets_timeline_and_audio(self):
        show = _show()
        convert_show_in_place(show, audio_file_path="clip.mp3")
        assert show.timeline_data is not None
        assert show.timeline_data.audio_file_path == "clip.mp3"
        assert show.effects  # legacy data left intact

    def test_mapping_targets_are_known_effect_types(self):
        """Every mapped modern effect_type must exist in its registry."""
        from effects import DIMMER_REGISTRY, MOVEMENT_REGISTRY
        for legacy, (sublane, etype, _dir) in LEGACY_EFFECT_MAP.items():
            reg = DIMMER_REGISTRY if sublane == "dimmer" else MOVEMENT_REGISTRY
            assert etype in reg, f"{legacy} -> {etype} missing from {sublane} registry"
