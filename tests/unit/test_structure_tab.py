# tests/unit/test_structure_tab.py
"""Structure tab (reference screen 05): action strip with the audio
readout + AUTOGENERATE button, song parts as colored cards with
transition chips, master grid below, 400px part inspector on the right
(stat tiles + editors + AUDIO ANALYSIS rows), mono status strip.

Covers the card strip anatomy, click-to-select, every inspector editor
writing through to the ShowPart model, add/delete/reorder, the playback
card highlight, the read-out strips and the autogenerate wiring.
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
        # Value and unit are separate labels (two colors in the reference).
        assert tab._cards[0].bpm_label.text() == "120.0"
        assert tab._cards[0].bpm_unit_label.text() == "BPM"
        assert tab._cards[1].bpm_label.text() == "140.0"

    def test_card_width_matches_mockup(self, tab):
        assert all(card.width() == 190 for card in tab._cards)

    def test_card_tint_and_top_bar_use_part_color(self, tab):
        sheet = tab._cards[0].styleSheet()
        assert "border-top: 3px solid #ff0000" in sheet
        assert "rgba(255, 0, 0" in sheet

    def test_selected_card_tint_alpha_matches_reference(self, tab):
        # 0.14 selected / 0.12 idle in the reference.
        assert "14%" in tab._cards[0].styleSheet()
        assert "12%" in tab._cards[1].styleSheet()

    def test_selected_card_title_is_accent(self, tab):
        from gui.theme_tokens import THEMES
        accent = THEMES["dark"]["accent_line"]
        assert f"QLabel#PartCardName {{ color: {accent};" \
            in tab._cards[0].styleSheet()

    def test_add_tile_uses_theme_add_tile_role(self, tab):
        assert tab.add_part_tile.property("role") == "add-tile"
        assert tab.add_part_tile.size().width() == 44
        assert tab.add_part_tile.size().height() == 44

    def test_transition_chip_between_cards(self, tab):
        # Chip after card N shows part N's transition (transition out),
        # literally from the model - no invented crossfade lengths.
        assert len(tab._chips) == 1
        assert tab._chips[0].text() == "INSTANT"

    def test_micro_caption_present(self, tab):
        assert tab.parts_caption.text().startswith("PARTS")

    def test_parts_caption_advertises_drag_reorder(self, tab):
        # Cards reorder by drag-and-drop; the caption says so.
        assert "DRAG" in tab.parts_caption.text()

    def test_grid_caption_totals(self, tab):
        # 4 + 8 bars; 4 bars @ 120 = 8 s, 8 bars @ 140 ~ 13.7 s -> 00:21
        assert tab.grid_caption.text().startswith("MASTER GRID · 12 BARS ·")

    def test_grid_hint_row(self, tab):
        # Sentence case survives (plain QLabel, not a caps MicroLabel).
        assert tab.grid_hint.text().startswith("Every downstream feature")
        assert tab.grid_hint.property("role") == "micro"


# ---------------------------------------------------------------------------
# Action strip + status strip
# ---------------------------------------------------------------------------
class TestStrips:
    def test_status_strip_summary(self, tab):
        assert tab.status_summary.text().startswith("2 PARTS · 12 BARS ·")

    def test_status_strip_singular_part(self, tab, monkeypatch):
        from PyQt6.QtWidgets import QMessageBox
        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
        tab._select_part(1)
        tab.delete_part_btn.click()
        assert tab.status_summary.text().startswith("1 PART ·")

    def test_status_strip_has_no_saved_timestamp(self, tab):
        assert "SAVED" not in tab.status_summary.text()

    def test_audio_readout_without_audio(self, tab):
        assert tab.audio_readout.text() == "no audio loaded"
        assert not tab.audio_status.isVisible()

    def test_audio_readout_with_audio(self, tab):
        tab.current_show.timeline_data.audio_file_path = "neon_ruinen.wav"
        tab._update_audio_readout()
        assert tab.audio_readout.text().startswith("neon_ruinen.wav · ")

    def test_audio_status_green_when_analyzed(self, tab):
        from gui.theme_tokens import THEMES

        class _Report:
            sections = []

        tab.current_show.timeline_data.audio_file_path = "neon_ruinen.wav"
        tab._autogen_report = _Report()
        tab._update_audio_readout()
        assert tab.audio_status.text() == "ANALYZED"
        assert THEMES["dark"]["success"] in tab.audio_status.styleSheet()

    def test_autogen_button_caps_label(self, tab):
        assert tab.autogen_btn.text() == "AUTOGENERATE SHOW..."


# ---------------------------------------------------------------------------
# Autogenerate wiring (same dialog flow as the Timeline tab)
# ---------------------------------------------------------------------------
class TestAutogenerate:
    def test_delegates_to_sibling_shows_tab(self, tab, monkeypatch):
        calls = []

        class _ShowsTab:
            def _on_autogenerate(self):
                calls.append(True)

        monkeypatch.setattr(tab, "_shows_tab_delegate",
                            lambda: _ShowsTab())
        tab.autogen_btn.click()
        assert calls == [True]

    def test_emits_signal_when_connected(self, tab, monkeypatch):
        seen = []
        monkeypatch.setattr(tab, "_shows_tab_delegate", lambda: None)
        monkeypatch.setattr(tab, "_open_autogen_dialog",
                            lambda: seen.append("dialog"))
        tab.autogenerate_requested.connect(lambda name: seen.append(name))
        tab.autogen_btn.click()
        assert seen == ["Demo"]  # signal handled it, no direct dialog

    def test_direct_dialog_path_when_unconnected(self, tab, monkeypatch):
        seen = []
        monkeypatch.setattr(tab, "_shows_tab_delegate", lambda: None)
        monkeypatch.setattr(tab, "_open_autogen_dialog",
                            lambda: seen.append("dialog"))
        tab.autogen_btn.click()
        assert seen == ["dialog"]

    def test_no_show_warns(self, empty_tab, monkeypatch):
        from PyQt6.QtWidgets import QMessageBox
        warnings = []
        monkeypatch.setattr(
            QMessageBox, "warning",
            staticmethod(lambda *a, **k: warnings.append(a[1])))
        empty_tab.autogen_btn.click()
        assert warnings == ["No Show Selected"]


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

    def test_inspector_stat_tiles(self, tab):
        # Intro: 4 bars of 4/4 at 120 BPM = 8 s
        assert tab.stat_bpm.value_label.text() == "120.0"
        assert tab.stat_signature.value_label.text() == "4/4"
        assert tab.stat_bars.value_label.text() == "4"
        assert tab.stat_duration.value_label.text() == "8.0 s"

    def test_inspector_panel_width(self, tab):
        assert tab.inspector_title.parent().width() == 400

    def test_inspector_title_uses_part_color(self, tab):
        assert "#ff0000" in tab.inspector_title.styleSheet().lower()

    def test_analysis_rows_are_placeholders_without_report(self, tab):
        for row in (tab.analysis_energy, tab.analysis_vocals,
                    tab.analysis_contrast):
            assert row.value_label.text() == "-"
            assert row.value_label.toolTip() == \
                "Available after Autogenerate analysis"

    def test_analysis_rows_render_report_values(self, tab):
        class _Section:
            name = "Intro"
            relative_energy = 0.82
            vocal_presence = 0.7
            spectral_contrast = 0.64

        class _Report:
            sections = [_Section()]

        tab._autogen_report = _Report()
        tab._refresh_inspector()
        assert tab.analysis_energy.value_label.text() == "0.82 HIGH"
        assert tab.analysis_vocals.value_label.text() == "PRESENT"
        assert tab.analysis_contrast.value_label.text() == "0.64 RICH"

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
        assert tab.stat_duration.value_label.text() == "16.0 s"
        assert tab.stat_bpm.value_label.text() == "60.0"
        assert tab._cards[0].bpm_label.text() == "60.0"

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
    def test_add_tile_appends_and_selects(self, tab):
        tab.add_part_tile.click()
        assert len(tab.current_show.parts) == 3
        assert len(tab._cards) == 3
        assert len(tab._chips) == 2
        assert tab._selected_index == 2
        assert tab.current_show.parts[2].name == "Part 3"

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

    def test_reorder_part_moves_and_selects(self, tab):
        # Drag "Intro" (0) onto the "Verse" card (1): Intro moves after it.
        tab._reorder_part(0, 1)
        names = [p.name for p in tab.current_show.parts]
        assert names == ["Verse", "Intro"]
        assert tab._selected_index == 1
        assert tab._cards[1].name_label.text() == "INTRO"

    def test_reorder_part_same_index_is_noop(self, tab):
        tab._reorder_part(1, 1)
        assert [p.name for p in tab.current_show.parts] == ["Intro", "Verse"]

    def test_part_card_is_a_drag_source_and_drop_target(self, tab):
        from gui.tabs.structure_tab import PART_MIME_TYPE
        from PyQt6.QtCore import QMimeData

        assert tab._cards[0].acceptDrops()
        # A drop carrying source index 0 onto card 1 asks to reorder (0 -> 1).
        got = []
        tab._cards[1].reorder_requested.connect(
            lambda s, t: got.append((s, t)))
        mime = QMimeData()
        mime.setData(PART_MIME_TYPE, b"0")

        class _Drop:
            def mimeData(self):
                return mime

            def acceptProposedAction(self):
                pass

        tab._cards[1].dropEvent(_Drop())
        assert got == [(0, 1)]

    def test_part_card_ignores_a_foreign_drop(self, tab):
        from PyQt6.QtCore import QMimeData

        got = []
        tab._cards[1].reorder_requested.connect(
            lambda s, t: got.append((s, t)))
        mime = QMimeData()
        mime.setData("application/x-something-else", b"0")

        class _Drop:
            def mimeData(self):
                return mime

            def acceptProposedAction(self):
                pass

        tab._cards[1].dropEvent(_Drop())
        assert got == []


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

    def test_show_management_and_transport_stay_reachable(self, tab):
        for widget in (tab.show_combo, tab.new_show_btn, tab.rename_show_btn,
                       tab.delete_show_btn, tab.set_directory_btn,
                       tab.trigger_device_combo, tab.trigger_channel_spin,
                       tab.pause_enable_cb, tab.pause_color_btn,
                       tab.play_btn, tab.stop_btn, tab.position_slider):
            assert widget is not None


# ---------------------------------------------------------------------------
# Theme contract + text hygiene (never assert font().family(): polish race)
# ---------------------------------------------------------------------------
class TestThemeContract:
    def test_roles_used_by_the_tab_exist_in_the_theme(self):
        from gui.theme_tokens import render_theme

        qss = render_theme("dark")
        for rule in ('QPushButton[role="add-tile"]',
                     'QWidget[role="card"]',
                     'QWidget[role="inspector"]',
                     'QLabel[role="chip-label"]',
                     'QLabel[role="micro"]',
                     'QPushButton[role="destructive"]',
                     'QPushButton[role="primary"]'):
            assert rule in qss

    def test_ui_text_has_no_glyphs_barlow_lacks(self, tab):
        forbidden = "▾⚙＋½¼—–"
        texts = [tab.autogen_btn.text(), tab.add_part_tile.text(),
                 tab.parts_caption.text(), tab.grid_caption.text(),
                 tab.grid_hint.text(), tab.status_summary.text(),
                 tab.audio_readout.text(), tab.audio_status.text(),
                 tab.delete_part_btn.text()]
        for text in texts:
            assert not any(ch in text for ch in forbidden), text
