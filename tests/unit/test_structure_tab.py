# tests/unit/test_structure_tab.py
"""Structure tab (North Star card 1e): song parts as colored cards with
transition chips, master grid below, part inspector on the right.

Covers the card strip anatomy, click-to-select, every inspector editor
writing through to the ShowPart model, add/delete/reorder, and the
playback card highlight - i.e. everything the old structure table did,
now through the 1e layout.
"""

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import Configuration, Show, ShowPart, TimelineData


def make_config():
    """Config with one show: Intro (red) and Verse (green) parts."""
    config = Configuration()
    config.shows["Demo"] = Show(
        name="Demo",
        parts=[
            ShowPart(name="Intro", color="#FF0000", signature="4/4",
                     bpm=120.0, num_bars=4, transition="instant"),
            ShowPart(name="Verse", color="#00FF00", signature="4/4",
                     bpm=140.0, num_bars=8, transition="gradual"),
        ],
        effects=[],
        timeline_data=TimelineData(),
    )
    return config


@pytest.fixture
def tab(qapp):
    from gui.tabs.structure_tab import StructureTab

    with patch("utils.midi_utils.discover_midi_profiles", return_value=[]):
        tab = StructureTab(make_config(), parent=None)
    tab.update_from_config()
    yield tab
    tab.cleanup()
    tab.deleteLater()


@pytest.fixture
def empty_tab(qapp):
    """Tab with a config that has no shows at all."""
    from gui.tabs.structure_tab import StructureTab

    with patch("utils.midi_utils.discover_midi_profiles", return_value=[]):
        tab = StructureTab(Configuration(), parent=None)
    tab.update_from_config()
    yield tab
    tab.cleanup()
    tab.deleteLater()


# ---------------------------------------------------------------------------
# Card strip anatomy
# ---------------------------------------------------------------------------
class TestPartsStrip:
    def test_one_card_per_part(self, tab):
        assert len(tab._cards) == 2

    def test_card_shows_caps_name(self, tab):
        assert tab._cards[0].name_label.text() == "INTRO"
        assert tab._cards[1].name_label.text() == "VERSE"

    def test_card_shows_bars_and_signature_readout(self, tab):
        assert tab._cards[0].meta_label.text() == "4 BARS · 4/4"
        assert tab._cards[1].meta_label.text() == "8 BARS · 4/4"

    def test_card_shows_bpm_readout(self, tab):
        assert tab._cards[0].bpm_label.text() == "120.0 BPM"
        assert tab._cards[1].bpm_label.text() == "140.0 BPM"

    def test_card_width_matches_mockup(self, tab):
        assert all(card.width() == 190 for card in tab._cards)

    def test_card_tint_and_top_bar_use_part_color(self, tab):
        sheet = tab._cards[0].styleSheet()
        assert "border-top: 3px solid #ff0000" in sheet
        assert "rgba(255, 0, 0" in sheet

    def test_transition_chip_between_cards(self, tab):
        # Chip after card N shows part N's transition (transition out).
        assert len(tab._chips) == 1
        assert tab._chips[0].text() == "INSTANT"

    def test_micro_caption_present(self, tab):
        assert tab.parts_caption.text().startswith("PARTS")

    def test_grid_caption_totals(self, tab):
        # 4 + 8 bars; 4 bars @ 120 = 8 s, 8 bars @ 140 ~ 13.7 s -> 00:21
        assert tab.grid_caption.text().startswith("MASTER GRID · 12 BARS ·")


# ---------------------------------------------------------------------------
# Selection + inspector
# ---------------------------------------------------------------------------
class TestSelection:
    def test_first_part_selected_on_load(self, tab):
        assert tab._selected_index == 0
        assert tab._cards[0].property("selected") == "true"
        assert tab._cards[1].property("selected") == "false"

    def test_click_selects_card(self, tab):
        tab._cards[1].clicked.emit(1)
        assert tab._selected_index == 1
        assert tab._cards[1].property("selected") == "true"
        assert tab._cards[0].property("selected") == "false"

    def test_inspector_shows_selected_part(self, tab):
        tab._select_part(1)
        assert tab.inspector_title.text() == "VERSE"
        assert tab.part_name_edit.text() == "Verse"
        assert tab.bpm_spin.value() == 140.0
        assert tab.signature_widget.get_signature() == "4/4"
        assert tab.bars_spin.value() == 8
        assert tab.transition_combo.currentText() == "gradual"
        assert tab.part_color_btn.get_color().lower() == "#00ff00"

    def test_inspector_duration_readout(self, tab):
        # Intro: 4 bars of 4/4 at 120 BPM = 8 s
        assert tab.duration_label.text() == "8.00 s"

    def test_move_buttons_reflect_position(self, tab):
        assert not tab.move_left_btn.isEnabled()   # first part
        assert tab.move_right_btn.isEnabled()
        tab._select_part(1)
        assert tab.move_left_btn.isEnabled()
        assert not tab.move_right_btn.isEnabled()  # last part

    def test_inspector_disabled_without_show(self, empty_tab):
        assert empty_tab._selected_index == -1
        assert empty_tab.inspector_title.text() == "NO PART SELECTED"
        for widget in (empty_tab.part_name_edit, empty_tab.bpm_spin,
                       empty_tab.bars_spin, empty_tab.transition_combo,
                       empty_tab.part_color_btn, empty_tab.delete_part_btn):
            assert not widget.isEnabled()

    def test_empty_tab_has_no_cards(self, empty_tab):
        assert empty_tab._cards == []
        assert empty_tab._chips == []


# ---------------------------------------------------------------------------
# Inspector editing writes through to the model
# ---------------------------------------------------------------------------
class TestEditing:
    def test_name_edit_updates_part_and_card(self, tab):
        tab.part_name_edit.textEdited.emit("Opening")
        part = tab.current_show.parts[0]
        assert part.name == "Opening"
        assert tab._cards[0].name_label.text() == "OPENING"
        assert tab.inspector_title.text() == "OPENING"

    def test_bpm_edit_updates_part_and_duration(self, tab):
        tab.bpm_spin.setValue(60.0)
        part = tab.current_show.parts[0]
        assert part.bpm == 60.0
        # 4 bars of 4/4 at 60 BPM = 16 s
        assert tab.duration_label.text() == "16.00 s"
        assert tab._cards[0].bpm_label.text() == "60.0 BPM"

    def test_bars_edit_updates_part_and_card(self, tab):
        tab.bars_spin.setValue(16)
        part = tab.current_show.parts[0]
        assert part.num_bars == 16
        assert tab._cards[0].meta_label.text() == "16 BARS · 4/4"

    def test_signature_edit_updates_part_and_card(self, tab):
        tab.signature_widget.numerator.setValue(3)
        part = tab.current_show.parts[0]
        assert part.signature == "3/4"
        assert tab._cards[0].meta_label.text() == "4 BARS · 3/4"

    def test_transition_edit_updates_part_and_chip(self, tab):
        tab.transition_combo.setCurrentText("gradual")
        part = tab.current_show.parts[0]
        assert part.transition == "gradual"
        assert tab._chips[0].text() == "GRADUAL"

    def test_color_edit_updates_part_and_card(self, tab):
        tab.part_color_btn.colorChanged.emit("#1234AB")
        part = tab.current_show.parts[0]
        assert part.color == "#1234AB"
        assert "border-top: 3px solid #1234ab" in tab._cards[0].styleSheet()

    def test_edit_recalculates_song_structure(self, tab):
        before = tab.song_structure.get_total_duration()
        tab.bars_spin.setValue(8)
        after = tab.song_structure.get_total_duration()
        assert after > before


# ---------------------------------------------------------------------------
# Add / delete / reorder
# ---------------------------------------------------------------------------
class TestAddDeleteReorder:
    def test_add_part_appends_and_selects(self, tab):
        tab.add_part_btn.click()
        assert len(tab.current_show.parts) == 3
        assert len(tab._cards) == 3
        assert len(tab._chips) == 2
        assert tab._selected_index == 2
        assert tab.current_show.parts[2].name == "Part 3"

    def test_add_tile_also_adds(self, tab):
        tab.add_part_tile.click()
        assert len(tab.current_show.parts) == 3

    def test_delete_part_removes_selected(self, tab, monkeypatch):
        from PyQt6.QtWidgets import QMessageBox
        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
        tab._select_part(1)
        tab.delete_part_btn.click()
        assert len(tab.current_show.parts) == 1
        assert tab.current_show.parts[0].name == "Intro"
        assert len(tab._cards) == 1
        assert len(tab._chips) == 0
        assert tab._selected_index == 0  # clamped

    def test_delete_part_cancel_keeps_part(self, tab, monkeypatch):
        from PyQt6.QtWidgets import QMessageBox
        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
        tab.delete_part_btn.click()
        assert len(tab.current_show.parts) == 2

    def test_move_right_swaps_parts(self, tab):
        tab.move_right_btn.click()
        names = [p.name for p in tab.current_show.parts]
        assert names == ["Verse", "Intro"]
        assert tab._selected_index == 1
        assert tab._cards[0].name_label.text() == "VERSE"

    def test_move_left_swaps_back(self, tab):
        tab._select_part(1)
        tab.move_left_btn.click()
        names = [p.name for p in tab.current_show.parts]
        assert names == ["Verse", "Intro"]
        assert tab._selected_index == 0

    def test_move_past_ends_is_noop(self, tab):
        tab._move_part(-1)  # first part, move left
        names = [p.name for p in tab.current_show.parts]
        assert names == ["Intro", "Verse"]


# ---------------------------------------------------------------------------
# Playback highlight + show lifecycle
# ---------------------------------------------------------------------------
class TestPlaybackAndLifecycle:
    def test_playing_highlight_follows_playhead(self, tab):
        # Intro spans 0-8 s, Verse follows.
        tab.playhead_position = 10.0
        tab._update_playing_highlight()
        assert tab._playing_index == 1

    def test_playing_highlight_boosts_card_tint(self, tab):
        tab.playhead_position = 1.0
        tab._update_playing_highlight()
        assert tab._playing_index == 0
        assert "24%" in tab._cards[0].styleSheet()

    def test_show_combo_populated(self, tab):
        assert tab.show_combo.count() == 1
        assert tab.show_combo.currentText() == "Demo"

    def test_load_unknown_show_clears_strip(self, tab):
        tab._load_show("does not exist")
        assert tab.current_show is None
        assert tab._cards == []
        assert tab._selected_index == -1

    def test_reload_show_rebuilds_cards(self, tab):
        tab._load_show("Demo")
        assert len(tab._cards) == 2
        assert tab._selected_index == 0
