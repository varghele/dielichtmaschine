# tests/unit/test_colour_role_picker.py
"""The colour block editor's palette-role picker + the song palette
editor (v1.5 phase 0 leftover): the ROLE combo round-trips
ColourBlock.palette_role (existing roles, literal, free-text new role),
and the EDIT PALETTE dialog writes Song.palette and re-resolves every
role-tagged block via apply_palette - changing 'primary' re-skins the
tagged blocks' literal RGB. Offscreen; QColorDialog never opens (tests
drive the plain methods)."""

import pytest

from config.models import (ColourBlock, LightBlock, LightLane, Song,
                           TimelineData)


def _song(palette=None, *colour_blocks):
    lane = LightLane(name="L", fixture_targets=["G"], light_blocks=[
        LightBlock(start_time=0.0, end_time=8.0, effect_name="x",
                   colour_blocks=list(colour_blocks))])
    return Song(name="S", timeline_data=TimelineData(lanes=[lane]),
                palette=palette or {})


def _dialog(block, song):
    from timeline_ui.colour_block_dialog import ColourBlockDialog
    return ColourBlockDialog(block, song=song)


class TestRoleCombo:
    def test_combo_lists_literal_palette_roles_and_new(self, qapp):
        block = ColourBlock(start_time=0, end_time=4)
        song = _song({"primary": [240, 86, 46], "accent": [0, 0, 255]},
                     block)
        dlg = _dialog(block, song)
        data = [dlg.role_combo.itemData(i)
                for i in range(dlg.role_combo.count())]
        assert data == ["", "primary", "accent", None]
        # Literal preselected on a role-less block.
        assert dlg.role_combo.currentIndex() == 0

    def test_role_round_trip(self, qapp):
        block = ColourBlock(start_time=0, end_time=4, red=10.0)
        song = _song({"primary": [240, 86, 46]}, block)
        dlg = _dialog(block, song)
        dlg.role_combo.setCurrentIndex(dlg.role_combo.findData("primary"))
        dlg.accept()
        assert block.palette_role == "primary"

        # Reopen: the block's role is preselected.
        again = _dialog(block, song)
        assert again.role_combo.currentData() == "primary"

        # Back to literal.
        again.role_combo.setCurrentIndex(again.role_combo.findData(""))
        again.accept()
        assert block.palette_role == ""

    def test_block_role_missing_from_palette_is_still_listed(self, qapp):
        block = ColourBlock(start_time=0, end_time=4,
                            palette_role="tertiary")
        song = _song({"primary": [1, 2, 3]}, block)
        dlg = _dialog(block, song)
        assert dlg.role_combo.currentData() == "tertiary"

    def test_free_text_new_role(self, qapp):
        block = ColourBlock(start_time=0, end_time=4)
        song = _song({"primary": [1, 2, 3]}, block)
        dlg = _dialog(block, song)
        new_index = dlg.role_combo.count() - 1
        assert dlg.role_combo.itemData(new_index) is None
        assert not dlg.new_role_edit.isVisibleTo(dlg)
        dlg.role_combo.setCurrentIndex(new_index)
        assert dlg.new_role_edit.isVisibleTo(dlg)   # free-text revealed
        dlg.new_role_edit.setText("  wash  ")
        dlg.accept()
        assert block.palette_role == "wash"

    def test_without_song_only_literal_and_free_text(self, qapp):
        block = ColourBlock(start_time=0, end_time=4)
        dlg = _dialog(block, None)
        data = [dlg.role_combo.itemData(i)
                for i in range(dlg.role_combo.count())]
        assert data == ["", None]
        assert not dlg.edit_palette_btn.isEnabled()


class TestPaletteEditor:
    def test_accept_writes_palette_and_reskins_tagged_blocks(self, qapp):
        from timeline_ui.colour_block_dialog import PaletteEditorDialog
        tagged = ColourBlock(start_time=0, end_time=4, red=1.0, green=2.0,
                             blue=3.0, palette_role="primary")
        literal = ColourBlock(start_time=4, end_time=8, red=10.0,
                              green=20.0, blue=30.0)
        song = _song({"primary": [1, 2, 3]}, tagged, literal)
        dlg = PaletteEditorDialog(song)
        dlg.set_role_color(0, (240, 86, 46))
        dlg.accept()
        assert song.palette == {"primary": [240, 86, 46]}
        # The whole point: the tagged block's literal RGB re-resolved.
        assert (tagged.red, tagged.green, tagged.blue) == (240.0, 86.0,
                                                           46.0)
        assert tagged.palette_role == "primary"    # intent survives
        # Literal blocks are never touched.
        assert (literal.red, literal.green, literal.blue) == (10.0, 20.0,
                                                              30.0)

    def test_add_and_remove_rows(self, qapp):
        from timeline_ui.colour_block_dialog import PaletteEditorDialog
        song = _song({"primary": [1, 2, 3]})
        dlg = PaletteEditorDialog(song)
        assert dlg.add_role("accent", (9, 8, 7)) == 1
        assert dlg.palette() == {"primary": [1, 2, 3],
                                 "accent": [9, 8, 7]}
        dlg.remove_role(0)                          # drop primary
        assert dlg.palette() == {"accent": [9, 8, 7]}
        dlg.accept()
        assert song.palette == {"accent": [9, 8, 7]}

    def test_blank_role_names_are_skipped(self, qapp):
        from timeline_ui.colour_block_dialog import PaletteEditorDialog
        song = _song({})
        dlg = PaletteEditorDialog(song)
        dlg.add_role("", (5, 5, 5))
        dlg.add_role("solid", (7, 7, 7))
        dlg.accept()
        assert song.palette == {"solid": [7, 7, 7]}

    def test_reject_changes_nothing(self, qapp):
        from timeline_ui.colour_block_dialog import PaletteEditorDialog
        tagged = ColourBlock(start_time=0, end_time=4, red=1.0,
                             palette_role="primary")
        song = _song({"primary": [1, 2, 3]}, tagged)
        dlg = PaletteEditorDialog(song)
        dlg.set_role_color(0, (200, 200, 200))
        dlg.reject()
        assert song.palette == {"primary": [1, 2, 3]}
        assert tagged.red == 1.0


class TestEditPaletteFromBlockDialog:
    def test_palette_edit_refreshes_combo_and_sliders(self, qapp,
                                                      monkeypatch):
        """EDIT PALETTE... from the block editor: the accepted palette
        dialog re-resolves the song, so the block editor reloads the
        block's rewritten literals and lists the new roles."""
        from timeline_ui import colour_block_dialog as mod
        block = ColourBlock(start_time=0, end_time=4, red=1.0, green=2.0,
                            blue=3.0, palette_role="primary")
        song = _song({"primary": [1, 2, 3]}, block)
        dlg = _dialog(block, song)

        def fake_exec(self):
            self.set_role_color(0, (240, 86, 46))
            self.add_role("accent", (9, 8, 7))
            self.accept()
            return 1

        monkeypatch.setattr(mod.PaletteEditorDialog, "exec", fake_exec)
        dlg._edit_palette()

        assert song.palette == {"primary": [240, 86, 46],
                                "accent": [9, 8, 7]}
        # Sliders reloaded from the re-resolved block.
        assert dlg.sliders["red"][1].value() == 240
        assert dlg.sliders["green"][1].value() == 86
        assert dlg.sliders["blue"][1].value() == 46
        # The new role is offered, the current one kept selected.
        data = [dlg.role_combo.itemData(i)
                for i in range(dlg.role_combo.count())]
        assert "accent" in data
        assert dlg.role_combo.currentData() == "primary"
        # Accept keeps the palette colour (sliders were reloaded).
        dlg.accept()
        assert (block.red, block.green, block.blue) == (240.0, 86.0, 46.0)
        assert block.palette_role == "primary"

    def test_owning_song_lookup_by_block_identity(self, qapp):
        """The Shows tab path: the envelope block sits (by identity) in
        the config's song timeline, so the widget resolves the Song
        without any tab plumbing."""
        from timeline_ui.light_block_widget import LightBlockWidget

        block = ColourBlock(start_time=0, end_time=4)
        song = _song({"primary": [1, 2, 3]}, block)
        config = type("Cfg", (), {})()
        config.songs = {"S": song}
        envelope = song.timeline_data.lanes[0].light_blocks[0]

        lane_widget = type("LW", (), {})()
        lane_widget.config = config
        widget = LightBlockWidget.__new__(LightBlockWidget)
        widget.block = envelope
        widget.lane_widget = lane_widget
        assert widget._find_owning_song() is song

        # A block from nowhere resolves to None (dialog degrades to
        # literal + free-text roles).
        widget.block = LightBlock(start_time=0, end_time=4,
                                  effect_name="y")
        assert widget._find_owning_song() is None
