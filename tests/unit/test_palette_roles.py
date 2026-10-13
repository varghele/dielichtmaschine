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


class TestPaletteRepaintsEveryTaggedBlock:
    """Editing the palette re-resolves role-tagged blocks across the
    WHOLE song, so every block widget has to repaint - not just the one
    whose dialog was open.

    Found 2026-08-09 while writing up the desktop check: the sublane
    dialog called self.update_display(), which repaints only itself, so
    a second block sharing the role kept showing its old colour until a
    scroll or a song switch forced a repaint."""

    def test_apply_palette_reaches_blocks_in_other_lanes(self):
        """The data half: one palette edit, several lanes affected."""
        from config.models import LightBlock, LightLane, TimelineData
        a = ColourBlock(start_time=0, end_time=4, palette_role="primary")
        b = ColourBlock(start_time=0, end_time=4, palette_role="primary")
        lanes = [
            LightLane(name="L1", fixture_targets=["G1"], light_blocks=[
                LightBlock(start_time=0.0, end_time=8.0, effect_name="x",
                           colour_blocks=[a])]),
            LightLane(name="L2", fixture_targets=["G2"], light_blocks=[
                LightBlock(start_time=0.0, end_time=8.0, effect_name="x",
                           colour_blocks=[b])]),
        ]
        song = Song(name="S", timeline_data=TimelineData(lanes=lanes),
                    palette={"primary": [240, 86, 46]})
        assert song.apply_palette() == 2
        for cb in (a, b):
            assert (cb.red, cb.green, cb.blue) == (240.0, 86.0, 46.0)

    def test_repaint_helper_walks_to_the_host_and_updates_all(self):
        """The view half, driven through the plain helper."""
        from timeline_ui.light_block_widget import (
            repaint_block_widgets_from)

        class FakeWidget:
            def __init__(self):
                self.updated = 0

            def update(self):
                self.updated += 1

        class FakeLane:
            def __init__(self, widgets):
                self.light_block_widgets = widgets

        class FakeHost:
            def __init__(self, lanes):
                self.lane_widgets = lanes

        painted = [FakeWidget(), FakeWidget(), FakeWidget()]
        lanes = [FakeLane(painted[:2]), FakeLane(painted[2:])]

        class FakeLaneWidget:
            def __init__(self, host):
                self._host = host

            def parent(self):
                return self._host

        assert repaint_block_widgets_from(
            FakeLaneWidget(FakeHost(lanes))) is True
        assert [w.updated for w in painted] == [1, 1, 1]

    def test_repaint_helper_degrades_without_a_host(self):
        """A lane widget with no Shows tab above it must not crash."""
        from timeline_ui.light_block_widget import (
            repaint_block_widgets_from)

        class Solo:
            def __init__(self):
                self.updated = 0

            def update(self):
                self.updated += 1

            def parent(self):
                return None

        assert repaint_block_widgets_from(None) is False
        assert repaint_block_widgets_from(Solo()) is False


class TestRolePicksUpItsColour:
    """Reported 2026-08-09: tagging a block "Secondary" (green) left it
    white. The dialog treated the role as intent metadata only, so the
    literals stood until the palette editor was next accepted - which
    reads as the role simply not working."""

    def _dialog(self, qapp, block, song):
        from timeline_ui.colour_block_dialog import ColourBlockDialog
        return ColourBlockDialog(block, parent=None, song=song)

    def _song(self, *blocks, palette=None):
        return _song_with_blocks(*blocks, palette=palette)

    def test_selecting_a_role_resolves_the_colour_on_accept(self, qapp):
        cb = ColourBlock(start_time=0, end_time=4, red=255, green=255,
                         blue=255)
        song = self._song(cb, palette={"secondary": [0, 200, 0]})
        dlg = self._dialog(qapp, cb, song)
        dlg.role_combo.setCurrentIndex(dlg.role_combo.findData("secondary"))
        dlg.accept()
        assert cb.palette_role == "secondary"
        assert (cb.red, cb.green, cb.blue) == (0.0, 200.0, 0.0)
        dlg.deleteLater()

    def test_the_sliders_preview_the_role_immediately(self, qapp):
        """You should see the colour before pressing OK."""
        cb = ColourBlock(start_time=0, end_time=4, red=255, green=255,
                         blue=255)
        song = self._song(cb, palette={"secondary": [0, 200, 0]})
        dlg = self._dialog(qapp, cb, song)
        dlg.role_combo.setCurrentIndex(dlg.role_combo.findData("secondary"))
        assert dlg.sliders["red"][0].value() == 0
        assert dlg.sliders["green"][0].value() == 200
        assert dlg.sliders["blue"][0].value() == 0
        dlg.deleteLater()

    def test_a_brand_new_role_leaves_the_literals_alone(self, qapp):
        """Nothing to resolve to yet - keep what the user picked."""
        cb = ColourBlock(start_time=0, end_time=4, red=10, green=20,
                         blue=30)
        song = self._song(cb, palette={"secondary": [0, 200, 0]})
        dlg = self._dialog(qapp, cb, song)
        index = dlg.role_combo.count() - 1        # "New role..."
        dlg.role_combo.setCurrentIndex(index)
        dlg.new_role_edit.setText("tertiary")
        dlg.accept()
        assert cb.palette_role == "tertiary"
        assert (cb.red, cb.green, cb.blue) == (10.0, 20.0, 30.0)
        dlg.deleteLater()

    def test_going_back_to_literal_keeps_the_colour(self, qapp):
        cb = ColourBlock(start_time=0, end_time=4, red=10, green=20,
                         blue=30, palette_role="secondary")
        song = self._song(cb, palette={"secondary": [0, 200, 0]})
        dlg = self._dialog(qapp, cb, song)
        dlg.role_combo.setCurrentIndex(0)          # LITERAL
        dlg.accept()
        assert cb.palette_role == ""
        assert (cb.red, cb.green, cb.blue) == (10.0, 20.0, 30.0)
        dlg.deleteLater()

    def test_without_a_song_the_role_is_still_recorded(self, qapp):
        from timeline_ui.colour_block_dialog import ColourBlockDialog
        cb = ColourBlock(start_time=0, end_time=4, red=1, green=2, blue=3)
        dlg = ColourBlockDialog(cb, parent=None, song=None)
        index = dlg.role_combo.count() - 1
        dlg.role_combo.setCurrentIndex(index)
        dlg.new_role_edit.setText("primary")
        dlg.accept()
        assert cb.palette_role == "primary"
        assert (cb.red, cb.green, cb.blue) == (1.0, 2.0, 3.0)
        dlg.deleteLater()
