# tests/unit/test_palette_roles.py
"""Colour palette roles (v1.5 phase 0, decided 2026-07-15): the role is
intent metadata on ColourBlock; Song.palette + apply_palette() re-resolve
role-tagged blocks into literals at the realization boundary; consumers
keep reading literals; literal-only blocks are never touched. Plus lane
stable ids (same phase)."""

from config.models import (ColourBlock, LightBlock, LightLane, Song,
                           TimelineData)


def _song_with_blocks(*colour_blocks, palette=None):
    lane = LightLane(name="L", fixture_targets=["G"], light_blocks=[
        LightBlock(start_time=0.0, end_time=8.0, effect_name="x",
                   colour_blocks=list(colour_blocks))])
    return Song(name="S", timeline_data=TimelineData(lanes=[lane]),
                palette=palette or {})


class TestPaletteRoles:
    def test_apply_palette_rewrites_role_tagged_blocks(self):
        cb = ColourBlock(start_time=0, end_time=4, red=1, green=2, blue=3,
                         palette_role="primary")
        song = _song_with_blocks(cb, palette={"primary": [240, 86, 46]})
        assert song.apply_palette() == 1
        assert (cb.red, cb.green, cb.blue) == (240.0, 86.0, 46.0)
        assert cb.palette_role == "primary"  # intent survives

    def test_literal_blocks_are_never_touched(self):
        cb = ColourBlock(start_time=0, end_time=4, red=10, green=20, blue=30)
        song = _song_with_blocks(cb, palette={"primary": [1, 2, 3]})
        assert song.apply_palette() == 0
        assert (cb.red, cb.green, cb.blue) == (10, 20, 30)

    def test_unknown_role_left_alone(self):
        cb = ColourBlock(start_time=0, end_time=4, red=10, green=20, blue=30,
                         palette_role="tertiary")
        song = _song_with_blocks(cb, palette={"primary": [1, 2, 3]})
        assert song.apply_palette() == 0
        assert (cb.red, cb.green, cb.blue) == (10, 20, 30)

    def test_role_and_palette_round_trip(self):
        cb = ColourBlock(start_time=0, end_time=4, red=1, green=2, blue=3,
                         palette_role="accent")
        song = _song_with_blocks(cb, palette={"accent": [9, 8, 7]})
        data = song.to_dict()
        loaded = Song.from_dict("S", data)
        block = loaded.timeline_data.lanes[0].light_blocks[0].colour_blocks[0]
        assert block.palette_role == "accent"
        assert loaded.palette == {"accent": [9, 8, 7]}

    def test_literal_block_serializes_without_the_key(self):
        cb = ColourBlock(start_time=0, end_time=4)
        assert "palette_role" not in cb.to_dict()
        song = _song_with_blocks(cb)
        assert "palette" not in song.to_dict()


class TestLaneIds:
    def test_lanes_get_unique_persistent_ids(self):
        a, b = LightLane(name="x"), LightLane(name="x")
        assert a.lane_id and a.lane_id != b.lane_id
        assert LightLane.from_dict(a.to_dict()).lane_id == a.lane_id

    def test_legacy_lane_gets_an_id_on_load(self):
        lane = LightLane.from_dict({"name": "old", "fixture_targets": ["G"]})
        assert len(lane.lane_id) == 32
