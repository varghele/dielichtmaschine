# tests/unit/test_structure_tab.py
"""Structure tab (reference screen 05b): action strip with the
directory chip, audio readout + AUTOGENERATE button; the song title
row (condensed caps name, mono meta line, RENAME SONG / DELETE
chips); song parts as colored cards with clickable transition chips;
the master grid behind its 150px MASTER / AUDIO header column with a
compact transport row; the 340px inspector on the right (S2c: SONG
trigger section, AFTER THE SONG pause look, PART stat tiles + editors,
AUDIO ANALYSIS meter bars, pinned DELETE PART); mono status strip;
330px setlist rail on the left.

Covers the card strip anatomy, click-to-select, every inspector editor
writing through to the ShowPart model, add/delete/reorder, the playback
card highlight, the read-out strips, the autogenerate wiring, the
setlist rail, the S2b contracts (title row, transition chip menu,
master grid header, legacy chrome gone) and the S2c contracts (trigger
segment two-way mapping, per-mode editors, timecode validation, LEARN
placeholder, unlisted-song hint, pause-look editing with live rail
refresh, analysis bars vs the honest empty state).
"""

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import (Configuration, Song, ShowPart, TimelineData,
                           Setlist, SetlistEntry, SongTrigger, PauseLook)


def make_config():
    """Config with one show: Intro (red) and Verse (green) parts."""
    config = Configuration()
    config.songs["Demo"] = Song(
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


def one_part_song(name, bars=8, color="#4ECBD4"):
    """A song of one 4/4 part at 120 BPM: duration = bars * 2 seconds."""
    return Song(
        name=name,
        parts=[ShowPart(name="Intro", color=color, signature="4/4",
                        bpm=120.0, num_bars=bars, transition="instant")],
        effects=[],
        timeline_data=TimelineData(),
    )


def make_setlist_config():
    """Three songs in a named setlist with mixed triggers and distinct
    pause looks (the S2a scenario)."""
    config = Configuration()
    config.songs["Neon Ruinen"] = one_part_song("Neon Ruinen", bars=8,
                                                color="#4ECBD4")   # 16 s
    config.songs["Monsters"] = one_part_song("Monsters", bars=4,
                                             color="#8D9299")      # 8 s
    config.songs["Schwarzes Gold"] = one_part_song("Schwarzes Gold", bars=8,
                                                   color="#C95FD0")  # 16 s
    config.setlist = Setlist(
        name="Demo Tour",
        sync_mode="midi",
        entries=[
            SetlistEntry(
                song="Neon Ruinen",
                trigger=SongTrigger(mode="midi_pc", value=5, channel=1),
                pause_after=PauseLook(mode="warm_white", level=20,
                                      until="trigger")),
            SetlistEntry(
                song="Monsters",
                trigger=SongTrigger(mode="midi_note", value=36, channel=1),
                pause_after=PauseLook(mode="hold_last", until="trigger")),
            SetlistEntry(
                song="Schwarzes Gold",
                trigger=SongTrigger(mode="follow"),
                pause_after=PauseLook(mode="blackout", until="duration",
                                      duration_s=30.0)),
        ],
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


@pytest.fixture
def setlist_tab(qapp):
    """Tab on the three-song setlist config. The combo sorts song names,
    so the open song on load is "Monsters" (setlist entry 2)."""
    from gui.tabs.structure_tab import StructureTab

    with patch("utils.midi_utils.discover_midi_profiles", return_value=[]):
        tab = StructureTab(make_setlist_config(), parent=None)
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

    def test_card_shows_bpm_and_duration_readout(self, tab):
        # Value and tail are separate labels (two colors in the
        # reference); the tail carries the part duration from the same
        # SongStructure math the master grid uses.
        assert tab._cards[0].bpm_label.text() == "120.0"
        assert tab._cards[0].bpm_unit_label.text() == "BPM · 8.0 s"
        assert tab._cards[1].bpm_label.text() == "140.0"
        verse = tab.current_show.parts[1]
        assert tab._cards[1].bpm_unit_label.text() == \
            f"BPM · {verse.duration:.1f} s"

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
        # literally from the model, plus the ↓ menu indicator.
        assert len(tab._chips) == 1
        assert tab._chips[0].text() == "INSTANT ↓"
        assert tab._chips[0].index == 0

    def test_selected_card_shows_accent_check(self, tab):
        # The mock's small accent check top-right on the selected card.
        assert not tab._cards[0].check_label.isHidden()
        assert tab._cards[1].check_label.isHidden()
        tab._select_part(1)
        assert tab._cards[0].check_label.isHidden()
        assert not tab._cards[1].check_label.isHidden()

    def test_micro_caption_present(self, tab):
        assert tab.parts_caption.text().startswith("PARTS")

    def test_parts_caption_advertises_drag_reorder(self, tab):
        # Cards reorder by drag-and-drop; the caption says so.
        assert "DRAG" in tab.parts_caption.text()

    def test_grid_caption_totals(self, tab):
        # The MASTER header cell: bars only, the duration lives in the
        # title row's meta line now.
        assert tab.grid_caption.text() == "MASTER · 12 BARS"

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
        assert tab.autogen_btn.text() == "AUTOGENERATE SONG..."


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
        assert warnings == ["No Song Selected"]


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
        # S2c narrowed the inspector to the mock's 340px column. The
        # title now sits inside a scrolled section, so walk up to the
        # panel by object name.
        panel = tab.inspector_title.parent()
        while panel is not None and panel.objectName() != "PartInspector":
            panel = panel.parent()
        assert panel is not None
        assert panel.width() == 340

    def test_inspector_title_uses_part_color(self, tab):
        assert "#ff0000" in tab.inspector_title.styleSheet().lower()

    def test_analysis_rows_hidden_behind_empty_state_without_report(
            self, tab):
        # No generation report: the bars hide and the honest empty
        # state shows instead of fake meters.
        for row in (tab.analysis_energy, tab.analysis_vocals,
                    tab.analysis_contrast):
            assert row.isHidden()
        assert not tab.analysis_empty_hint.isHidden()
        assert tab.analysis_empty_hint.text() == \
            "No analysis yet · runs with autogen"

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
        assert tab.analysis_empty_hint.isHidden()
        for row in (tab.analysis_energy, tab.analysis_vocals,
                    tab.analysis_contrast):
            assert not row.isHidden()
        assert tab.analysis_energy.value_label.text() == "0.82 HIGH"
        assert tab.analysis_vocals.value_label.text() == "PRESENT"
        assert tab.analysis_contrast.value_label.text() == "0.64 RICH"

    def test_analysis_bars_carry_fractions_and_leading_accent(self, tab):
        class _Section:
            name = "Intro"
            relative_energy = 0.82
            vocal_presence = 0.7
            spectral_contrast = 0.64

        class _Report:
            sections = [_Section()]

        tab._autogen_report = _Report()
        tab._refresh_inspector()
        assert tab.analysis_energy.bar._fraction == pytest.approx(0.82)
        assert tab.analysis_vocals.bar._fraction == pytest.approx(0.7)
        assert tab.analysis_contrast.bar._fraction == pytest.approx(0.64)
        # Energy is the strongest metric: accent fill, the rest stay
        # in the secondary tone.
        assert tab.analysis_energy._leading
        assert not tab.analysis_vocals._leading
        assert not tab.analysis_contrast._leading

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
        assert tab._chips[0].text() == "GRADUAL ↓"

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

    def test_transport_stays_reachable(self, tab):
        # The transport is the only way to audition a song from this
        # tab (it drives audio, playheads, the playing-card highlight):
        # kept, compact, under the master grid.
        for widget in (tab.play_btn, tab.stop_btn, tab.time_label,
                       tab.position_slider, tab.total_time_label):
            assert widget is not None


# ---------------------------------------------------------------------------
# S2b: song title row
# ---------------------------------------------------------------------------
class TestSongTitleRow:
    def test_title_shows_open_song_in_caps(self, setlist_tab):
        assert setlist_tab.song_title.text() == "MONSTERS"

    def test_meta_line_composition(self, setlist_tab):
        # Leading part's BPM/signature + total bars + total duration
        # (Monsters: one 4-bar 4/4 part at 120 BPM = 8 s).
        assert setlist_tab.song_meta.text() == \
            "120.0 BPM · 4/4 · 4 BARS · 00:08"

    def test_meta_line_follows_part_edits(self, setlist_tab):
        setlist_tab.bars_spin.setValue(8)
        assert setlist_tab.song_meta.text() == \
            "120.0 BPM · 4/4 · 8 BARS · 00:16"

    def test_title_follows_rail_selection(self, setlist_tab):
        setlist_tab._rail_cards[2].clicked.emit("Schwarzes Gold")
        assert setlist_tab.song_title.text() == "SCHWARZES GOLD"

    def test_rename_chip_wired_to_rename_flow(self, setlist_tab,
                                              monkeypatch):
        from PyQt6.QtWidgets import QInputDialog, QMessageBox
        monkeypatch.setattr(
            QInputDialog, "getText",
            staticmethod(lambda *a, **k: ("Renamed", True)))
        monkeypatch.setattr(
            QMessageBox, "information",
            staticmethod(lambda *a, **k: None))
        setlist_tab.rename_show_btn.click()
        assert "Renamed" in setlist_tab.config.songs
        assert setlist_tab.song_title.text() == "RENAMED"

    def test_delete_chip_wired_to_delete_flow(self, setlist_tab,
                                              monkeypatch):
        from PyQt6.QtWidgets import QMessageBox
        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
        monkeypatch.setattr(
            QMessageBox, "information",
            staticmethod(lambda *a, **k: None))
        setlist_tab.delete_show_btn.click()
        assert "Monsters" not in setlist_tab.config.songs

    def test_chips_disabled_without_song(self, empty_tab):
        assert empty_tab.song_title.text() == "NO SONG"
        assert empty_tab.song_meta.text() == "no song loaded"
        assert not empty_tab.rename_show_btn.isEnabled()
        assert not empty_tab.delete_show_btn.isEnabled()

    def test_delete_chip_is_a_destructive_outline(self, tab):
        # The theme's destructive-outline role (red border, transparent
        # fill); no widget-local stylesheet needed anymore.
        assert tab.delete_show_btn.property("role") == "destructive-outline"
        assert tab.delete_show_btn.styleSheet() == ""
        assert tab.rename_show_btn.property("role") == "cta-outline"

    def test_destructive_outline_role_in_theme(self):
        from gui.theme_tokens import render_theme
        qss = render_theme("dark")
        assert 'QPushButton[role="destructive-outline"]' in qss

    def test_song_combo_alive_but_hidden(self, setlist_tab):
        # gui.py and the rail cards still drive song switching through
        # the combo; the visible selector is the setlist rail.
        assert setlist_tab.show_combo.isHidden()
        assert setlist_tab.show_combo.count() == 3
        setlist_tab.show_combo.setCurrentText("Neon Ruinen")
        assert setlist_tab.current_song_name == "Neon Ruinen"


# ---------------------------------------------------------------------------
# S2b: transition chip menu
# ---------------------------------------------------------------------------
class TestTransitionChipMenu:
    def test_chip_click_emits_its_part_index(self, tab):
        got = []
        tab._chips[0].clicked.connect(got.append)
        from PyQt6.QtCore import QPointF, Qt as QtNS
        from PyQt6.QtGui import QMouseEvent
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress, QPointF(2, 2),
            QtNS.MouseButton.LeftButton, QtNS.MouseButton.LeftButton,
            QtNS.KeyboardModifier.NoModifier)
        tab._chips[0].mousePressEvent(event)
        assert got == [0]

    def test_menu_lists_the_combo_options_with_current_checked(self, tab):
        menu = tab._build_transition_menu(0)
        actions = menu.actions()
        assert [a.text() for a in actions] == ["INSTANT", "GRADUAL"]
        assert [a.isChecked() for a in actions] == [True, False]

    def test_menu_action_writes_through_to_the_model(self, tab):
        menu = tab._build_transition_menu(0)
        gradual = menu.actions()[1]
        gradual.trigger()
        assert tab.current_show.parts[0].transition == "gradual"
        assert tab._chips[0].text() == "GRADUAL ↓"
        # Part 0 is the selected part: the inspector combo follows.
        assert tab.transition_combo.currentText() == "gradual"

    def test_set_transition_out_of_range_is_noop(self, tab):
        tab._set_transition_out(5, "gradual")
        assert [p.transition for p in tab.current_show.parts] == \
            ["instant", "gradual"]


# ---------------------------------------------------------------------------
# S2b: master grid header column
# ---------------------------------------------------------------------------
class TestMasterGridHeader:
    def test_grid_builtin_header_column_is_hidden(self, tab):
        # The mock's 150px MASTER / AUDIO cells replace the grid's own
        # timeline lane controls on this tab.
        assert tab.timeline_grid.headers_scroll.isHidden()

    def test_header_column_width_matches_mock(self, tab):
        assert tab._grid_header_col.width() == 150

    def test_cells_mirror_the_grid_row_heights(self, tab):
        master_stripe = tab.master_timeline.timeline_widget
        audio_stripe = tab.audio_lane.timeline_widget
        assert tab._master_header_cell.height() == \
            master_stripe.maximumHeight()
        assert tab._audio_header_cell.height() == \
            audio_stripe.maximumHeight()

    def test_master_cell_carries_the_bars_caption(self, tab):
        assert tab.grid_caption.text() == "MASTER · 12 BARS"
        assert tab.grid_caption.parent() is tab._master_header_cell

    def test_audio_cell_placeholder_without_audio(self, tab):
        assert tab.audio_header_file.text() == "-"

    def test_audio_cell_shows_the_filename(self, tab):
        # Long names middle-elide to the 150px cell (keeping start and
        # extension); the tooltip carries the full name.
        tab.current_show.timeline_data.audio_file_path = "neon_ruinen.wav"
        tab._update_audio_readout()
        text = tab.audio_header_file.text()
        assert text.startswith("neon")
        assert text.endswith(".wav")
        assert tab.audio_header_file.toolTip() == "neon_ruinen.wav"

    def test_load_chip_opens_dialog_and_loads(self, tab, monkeypatch):
        from PyQt6.QtWidgets import QFileDialog
        monkeypatch.setattr(
            QFileDialog, "getOpenFileName",
            staticmethod(lambda *a, **k: ("C:/tmp/song.wav", "")))
        loaded = []
        monkeypatch.setattr(tab.audio_lane, "load_audio_file",
                            loaded.append)
        tab.load_audio_btn.click()
        assert loaded == ["C:/tmp/song.wav"]

    def test_load_chip_cancel_is_a_noop(self, tab, monkeypatch):
        from PyQt6.QtWidgets import QFileDialog
        monkeypatch.setattr(
            QFileDialog, "getOpenFileName",
            staticmethod(lambda *a, **k: ("", "")))
        loaded = []
        monkeypatch.setattr(tab.audio_lane, "load_audio_file",
                            loaded.append)
        tab.load_audio_btn.click()
        assert loaded == []


# ---------------------------------------------------------------------------
# S2b: legacy chrome is gone, its functions moved
# ---------------------------------------------------------------------------
class TestLegacyChromeGone:
    def test_pause_show_group_is_gone(self, tab):
        from PyQt6.QtWidgets import QGroupBox
        assert not hasattr(tab, "pause_enable_cb")
        assert not hasattr(tab, "pause_color_btn")
        assert not hasattr(tab, "pause_trigger_device_combo")
        assert not hasattr(tab, "pause_trigger_channel_spin")
        assert tab.findChildren(QGroupBox) == []

    def test_per_show_trigger_row_is_gone(self, tab):
        # Triggers live on the setlist entries now, edited in the S2c
        # inspector; the old per-show device combo is gone. (The S2c
        # channel spin is a different, entry-bound widget.)
        assert not hasattr(tab, "trigger_device_combo")

    def test_new_show_button_is_gone(self, tab):
        # Song creation is the rail's + SONG tile.
        assert not hasattr(tab, "new_show_btn")

    def test_directory_button_is_gone(self, tab):
        """shows_directory lost its last UI: the hint self-maintains
        (import/export dialogs remember their folder) and merging
        pre-v1.0 CSV songs is the explicit File > Import Legacy CSV
        Songs action (see test_shell_nav.py for the menu action)."""
        assert not hasattr(tab, "set_directory_btn")
        assert not hasattr(tab, "_set_show_directory")
        # The whole dead CSV cluster went with it.
        for legacy in ("_save_to_csv", "_save_show_to_csv",
                       "_import_all_shows_from_csv", "_auto_load_shows",
                       "_load_all_shows", "_ensure_shows_directory"):
            assert not hasattr(tab, legacy), legacy


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
                     'QLabel[role="hint-box"]',
                     'QPushButton[role="segment"]',
                     'QPushButton[role="destructive"]',
                     'QPushButton[role="cta-outline"]'):
            assert rule in qss

    def test_ui_text_has_no_glyphs_barlow_lacks(self, tab):
        forbidden = "▾⚙＋½¼—–"
        texts = [tab.autogen_btn.text(), tab.add_part_tile.text(),
                 tab.parts_caption.text(), tab.grid_caption.text(),
                 tab.grid_hint.text(), tab.status_summary.text(),
                 tab.audio_readout.text(), tab.audio_status.text(),
                 tab.delete_part_btn.text(),
                 tab.song_title.text(), tab.song_meta.text(),
                 tab.rename_show_btn.text(), tab.delete_show_btn.text(),
                 tab.load_audio_btn.text(),
                 tab.audio_header_file.text()]
        texts += [chip.text() for chip in tab._chips]
        texts += [card.check_label.text() for card in tab._cards]
        # S2c inspector strings (the pause chip's ↓ is the established
        # dropdown indicator, deliberately not in the forbidden set).
        texts += [tab.song_caption.text(), tab.song_unlisted_hint.text(),
                  tab.learn_btn.text(), tab.trigger_micro_hint.text(),
                  tab.trigger_mode_hint.text(), tab.pause_mode_chip.text(),
                  tab.pause_micro_hint.text(),
                  tab.analysis_empty_hint.text()]
        texts += [b.text() for b in tab.trigger_buttons.values()]
        texts += [b.text() for b in tab.pause_until_buttons.values()]
        for text in texts:
            assert not any(ch in text for ch in forbidden), text

    def test_rail_text_has_no_glyphs_barlow_lacks(self, setlist_tab):
        forbidden = "▾▸⏸⚙＋½¼—–"
        texts = [setlist_tab.rail_title.text(),
                 setlist_tab.rail_summary.text(),
                 setlist_tab.chase_arm_btn.text(),
                 setlist_tab.sync_device_combo.currentText(),
                 setlist_tab.add_song_tile.text(),
                 setlist_tab.rail_footer_hint.text()]
        texts += [b.text() for b in setlist_tab.sync_buttons.values()]
        for card in setlist_tab._rail_cards:
            texts += [card.title_label.text(), card.duration_label.text(),
                      card.trigger_label.text(), card.open_tag.text(),
                      card.unlisted_tag.text()]
        texts += [row.text() for row in setlist_tab._rail_pause_rows]
        for text in texts:
            assert not any(ch in text for ch in forbidden), text


# ---------------------------------------------------------------------------
# Setlist rail: trigger / pause-look text helpers
# ---------------------------------------------------------------------------
class TestRailTextHelpers:
    def test_midi_note_names(self):
        from gui.tabs.structure_tab import midi_note_name

        assert midi_note_name(36) == "C2"     # the reference's NOTE C2
        assert midi_note_name(60) == "C4"     # middle C convention
        assert midi_note_name(61) == "C#4"
        assert midi_note_name(35) == "B1"

    def test_trigger_lines_per_mode(self):
        from gui.tabs.structure_tab import trigger_line

        assert trigger_line(SongTrigger(mode="manual")) == "Manual start"
        assert trigger_line(SongTrigger(mode="follow")) == \
            "Follows automatically"
        assert trigger_line(SongTrigger(mode="midi_pc", value=5,
                                        channel=1)) == "PC#5 · CH 1"
        assert trigger_line(SongTrigger(mode="midi_note", value=36,
                                        channel=2)) == "NOTE C2 · CH 2"
        assert trigger_line(SongTrigger(mode="mtc",
                                        timecode="00:14:32:00")) == \
            "00:14:32:00"
        assert trigger_line(SongTrigger(mode="smpte",
                                        timecode="01:00:00:00")) == \
            "01:00:00:00"
        # Timecode not set yet: fall back to the mode name.
        assert trigger_line(SongTrigger(mode="smpte")) == "SMPTE"

    def test_pause_look_lines_per_mode(self):
        from gui.tabs.structure_tab import pause_look_line

        assert pause_look_line(PauseLook(mode="blackout", until="duration",
                                         duration_s=30.0)) == \
            "PAUSE LOOK · Blackout · 30s"
        assert pause_look_line(PauseLook(mode="warm_white", level=20,
                                         until="trigger")) == \
            "PAUSE LOOK · Warm white 20% · until trigger"
        assert pause_look_line(PauseLook(mode="hold_last",
                                         until="trigger")) == \
            "PAUSE LOOK · Hold last look · until trigger"
        assert pause_look_line(PauseLook(mode="ambient_loop",
                                         until="trigger")) == \
            "PAUSE LOOK · Ambient loop · until trigger"

    def test_song_edge_color_prefers_first_part_color(self):
        from gui.tabs.structure_tab import song_edge_color

        song = one_part_song("X", color="#4ECBD4")
        assert song_edge_color("X", song).lower() == "#4ecbd4"

    def test_song_edge_color_falls_back_to_stable_palette_pick(self):
        from gui.tabs.structure_tab import song_edge_color, \
            SONG_COLOR_PALETTE

        empty = Song(name="X", parts=[], effects=[], timeline_data=None)
        color = song_edge_color("X", empty)
        assert color in SONG_COLOR_PALETTE
        assert color == song_edge_color("X", None)     # name-stable
        assert song_edge_color("X") == song_edge_color("X")


# ---------------------------------------------------------------------------
# Setlist rail: anatomy
# ---------------------------------------------------------------------------
class TestSetlistRailAnatomy:
    def entry_cards(self, tab):
        return [c for c in tab._rail_cards if c.entry_index >= 0]

    def test_rail_width_matches_mockup(self, setlist_tab):
        assert setlist_tab.setlist_rail.width() == 330

    def test_one_card_per_entry_in_setlist_order(self, setlist_tab):
        cards = self.entry_cards(setlist_tab)
        assert [c.song_name for c in cards] == \
            ["Neon Ruinen", "Monsters", "Schwarzes Gold"]

    def test_card_numbering_two_digits(self, setlist_tab):
        cards = self.entry_cards(setlist_tab)
        assert cards[0].title_label.text() == "01 · Neon Ruinen"
        assert cards[1].title_label.text() == "02 · Monsters"
        assert cards[2].title_label.text() == "03 · Schwarzes Gold"

    def test_card_durations_from_part_math(self, setlist_tab):
        # 8 bars of 4/4 at 120 BPM = 16 s; 4 bars = 8 s.
        cards = self.entry_cards(setlist_tab)
        assert cards[0].duration_label.text() == "00:16"
        assert cards[1].duration_label.text() == "00:08"
        assert cards[2].duration_label.text() == "00:16"

    def test_card_trigger_lines(self, setlist_tab):
        cards = self.entry_cards(setlist_tab)
        assert cards[0].trigger_label.text() == "PC#5 · CH 1"
        assert cards[1].trigger_label.text() == "NOTE C2 · CH 1"
        assert cards[2].trigger_label.text() == "Follows automatically"

    def test_card_colour_edge_uses_first_part_colour(self, setlist_tab):
        cards = self.entry_cards(setlist_tab)
        assert "border-left: 3px solid #4ecbd4" in cards[0].styleSheet()
        assert "border-left: 3px solid #c95fd0" in cards[2].styleSheet()

    def test_pause_rows_between_cards_show_preceding_pause(self,
                                                           setlist_tab):
        rows = setlist_tab._rail_pause_rows
        assert len(rows) == 2   # between 3 cards, never after the last
        assert rows[0].text() == \
            "PAUSE LOOK · Warm white 20% · until trigger"
        assert rows[1].text() == "PAUSE LOOK · Hold last look · until trigger"

    def test_pause_rows_are_display_only_dashed_hints(self, setlist_tab):
        for row in setlist_tab._rail_pause_rows:
            assert row.property("role") == "hint-box"

    def test_header_caption_and_totals(self, setlist_tab):
        # MicroLabels render caps; total = 16 + 8 + 16 s -> 1 min.
        assert setlist_tab.rail_title.text() == "SETLIST · DEMO TOUR"
        assert setlist_tab.rail_summary.text() == "3 SONGS · 1 MIN"

    def test_header_falls_back_to_config_name(self, setlist_tab):
        setlist_tab.config.setlist.name = ""
        setlist_tab.config._loaded_from = "/tmp/demo_tour.yaml"
        setlist_tab._refresh_setlist_rail()
        assert setlist_tab.rail_title.text() == "SETLIST · DEMO_TOUR"

    def test_chase_row_hidden_outside_smpte_mode(self, setlist_tab):
        # Default sync mode is manual: no device combo, no ARM chip.
        assert setlist_tab.config.setlist.sync_mode != "smpte"
        assert setlist_tab.sync_device_combo.isHidden()
        assert setlist_tab.chase_arm_btn.isHidden()

    def test_add_song_tile_is_dashed(self, setlist_tab):
        assert setlist_tab.add_song_tile.text() == "+ SONG"
        assert setlist_tab.add_song_tile.property("role") == "add-tile"

    def test_footer_hint_wraps_and_names_the_contract(self, setlist_tab):
        hint = setlist_tab.rail_footer_hint
        assert hint.wordWrap()
        assert hint.text() == (
            "Order = setlist. Triggers per song (MIDI PC/NOTE, MTC/SMPTE "
            "time) · 'Follows automatically' chains without a trigger.")

    def test_part_edit_refreshes_rail_durations(self, setlist_tab):
        # Open song is Monsters (4 bars): doubling its bars doubles the
        # card duration readout.
        assert setlist_tab.current_song_name == "Monsters"
        setlist_tab.bars_spin.setValue(8)
        cards = self.entry_cards(setlist_tab)
        assert cards[1].duration_label.text() == "00:16"


# ---------------------------------------------------------------------------
# Setlist rail: open state follows the existing song-switching path
# ---------------------------------------------------------------------------
class TestSetlistRailSelection:
    def test_open_card_is_the_combo_selection(self, setlist_tab):
        # The sorted combo opens "Monsters" first = setlist entry 2.
        assert setlist_tab.current_song_name == "Monsters"
        cards = setlist_tab._rail_cards
        assert cards[1].property("selected") == "true"
        assert cards[1].property("open") == "true"
        assert not cards[1].open_tag.isHidden()
        assert cards[0].property("selected") == "false"
        assert cards[0].open_tag.isHidden()

    def test_open_card_drops_the_colour_edge_for_the_accent_border(
            self, setlist_tab):
        # The mock's open card has the accent border + tint, no edge.
        assert "border-left" not in setlist_tab._rail_cards[1].styleSheet()

    def test_clicking_a_card_opens_that_song(self, setlist_tab):
        setlist_tab._rail_cards[2].clicked.emit("Schwarzes Gold")
        assert setlist_tab.current_song_name == "Schwarzes Gold"
        assert setlist_tab.show_combo.currentText() == "Schwarzes Gold"
        assert setlist_tab.current_show is \
            setlist_tab.config.songs["Schwarzes Gold"]
        assert setlist_tab._rail_cards[2].property("selected") == "true"
        assert setlist_tab._rail_cards[1].property("selected") == "false"

    def test_clicking_opens_in_the_centre_editor(self, setlist_tab):
        setlist_tab._rail_cards[0].clicked.emit("Neon Ruinen")
        # The centre parts strip now shows Neon Ruinen's parts.
        assert len(setlist_tab._cards) == 1
        assert setlist_tab._cards[0].name_label.text() == "INTRO"
        assert setlist_tab.stat_bars.value_label.text() == "8"

    def test_clicking_unknown_song_is_a_noop(self, setlist_tab):
        setlist_tab._rail_cards[0].clicked.emit("does not exist")
        assert setlist_tab.current_song_name == "Monsters"


# ---------------------------------------------------------------------------
# Setlist rail: SYNC segment
# ---------------------------------------------------------------------------
class TestSyncSegment:
    def test_initial_state_from_model(self, setlist_tab):
        assert setlist_tab.sync_buttons["midi"].isChecked()
        for mode in ("mtc", "smpte", "manual"):
            assert not setlist_tab.sync_buttons[mode].isChecked()

    def test_segment_click_writes_sync_mode(self, setlist_tab):
        setlist_tab.sync_buttons["mtc"].click()
        assert setlist_tab.config.setlist.sync_mode == "mtc"
        assert not setlist_tab.sync_buttons["midi"].isChecked()

    def test_segments_are_exclusive(self, setlist_tab):
        setlist_tab.sync_buttons["manual"].click()
        checked = [m for m, b in setlist_tab.sync_buttons.items()
                   if b.isChecked()]
        assert checked == ["manual"]

    def test_segments_use_the_theme_segment_role(self, setlist_tab):
        for btn in setlist_tab.sync_buttons.values():
            assert btn.property("role") == "segment"


# ---------------------------------------------------------------------------
# Setlist rail: + SONG, unlisted songs, reorder
# ---------------------------------------------------------------------------
class TestSetlistRailMutations:
    def test_add_song_tile_appends_song_and_entry(self, setlist_tab,
                                                  monkeypatch):
        from PyQt6.QtWidgets import QInputDialog
        monkeypatch.setattr(
            QInputDialog, "getText",
            staticmethod(lambda *a, **k: ("Encore", True)))
        setlist_tab.add_song_tile.click()

        assert "Encore" in setlist_tab.config.songs
        entries = setlist_tab.config.setlist.entries
        assert entries[-1].song == "Encore"
        assert entries[-1].trigger.mode == "manual"
        assert entries[-1].pause_after.mode == "hold_last"
        # The rail grew a numbered card (not an unlisted one).
        card = setlist_tab._rail_cards[-1]
        assert card.song_name == "Encore"
        assert card.entry_index == 3
        assert card.title_label.text() == "04 · Encore"
        # And it opened in the centre editor.
        assert setlist_tab.current_song_name == "Encore"

    def test_unlisted_songs_render_after_a_divider(self, setlist_tab):
        setlist_tab.config.songs["Ghost"] = one_part_song("Ghost")
        setlist_tab.update_from_config()

        unlisted = [c for c in setlist_tab._rail_cards
                    if c.entry_index < 0]
        assert [c.song_name for c in unlisted] == ["Ghost"]
        assert setlist_tab._unlisted_divider is not None
        card = unlisted[0]
        assert card.title_label.text() == "Ghost"   # no number
        assert not card.unlisted_tag.isHidden()
        assert card.unlisted_tag.text() == "UNLISTED"
        assert card.trigger_label.isHidden()        # no entry, no trigger

    def test_no_unlisted_divider_when_setlist_is_complete(self,
                                                          setlist_tab):
        assert setlist_tab._unlisted_divider is None

    def test_song_without_setlist_lands_unlisted_not_crashing(self, tab):
        # The legacy fixture has a song but an empty setlist.
        assert tab.config.setlist.entries == []
        unlisted = [c for c in tab._rail_cards if c.entry_index < 0]
        assert [c.song_name for c in unlisted] == ["Demo"]
        assert tab.rail_summary.text() == "0 SONGS · 0 MIN"

    def test_clicking_an_unlisted_card_opens_the_song(self, setlist_tab):
        setlist_tab.config.songs["Ghost"] = one_part_song("Ghost")
        setlist_tab.update_from_config()
        unlisted = [c for c in setlist_tab._rail_cards
                    if c.entry_index < 0][0]
        unlisted.clicked.emit("Ghost")
        assert setlist_tab.current_song_name == "Ghost"
        assert not unlisted.open_tag.isHidden()

    def test_reorder_entry_moves_and_renumbers(self, setlist_tab):
        setlist_tab._reorder_setlist_entry(0, 1)
        entries = setlist_tab.config.setlist.entries
        assert [e.song for e in entries] == \
            ["Monsters", "Neon Ruinen", "Schwarzes Gold"]
        cards = [c for c in setlist_tab._rail_cards if c.entry_index >= 0]
        assert cards[0].title_label.text() == "01 · Monsters"
        assert cards[1].title_label.text() == "02 · Neon Ruinen"
        # Pause rows follow their entries.
        assert setlist_tab._rail_pause_rows[0].text() == \
            "PAUSE LOOK · Hold last look · until trigger"

    def test_reorder_same_index_is_noop(self, setlist_tab):
        setlist_tab._reorder_setlist_entry(1, 1)
        assert [e.song for e in setlist_tab.config.setlist.entries] == \
            ["Neon Ruinen", "Monsters", "Schwarzes Gold"]

    def test_rail_card_drop_requests_reorder(self, setlist_tab):
        from gui.tabs.structure_tab import SETLIST_MIME_TYPE
        from PyQt6.QtCore import QMimeData

        cards = setlist_tab._rail_cards
        assert cards[0].acceptDrops()
        got = []
        cards[1].reorder_requested.connect(lambda s, t: got.append((s, t)))
        mime = QMimeData()
        mime.setData(SETLIST_MIME_TYPE, b"0")

        class _Drop:
            def mimeData(self):
                return mime

            def acceptProposedAction(self):
                pass

        cards[1].dropEvent(_Drop())
        assert got == [(0, 1)]

    def test_rail_card_ignores_part_strip_drags(self, setlist_tab):
        from gui.tabs.structure_tab import PART_MIME_TYPE
        from PyQt6.QtCore import QMimeData

        got = []
        cards = setlist_tab._rail_cards
        cards[1].reorder_requested.connect(lambda s, t: got.append((s, t)))
        mime = QMimeData()
        mime.setData(PART_MIME_TYPE, b"0")

        class _Drop:
            def mimeData(self):
                return mime

            def acceptProposedAction(self):
                pass

        cards[1].dropEvent(_Drop())
        assert got == []

    def test_unlisted_cards_are_not_drop_targets(self, setlist_tab):
        setlist_tab.config.songs["Ghost"] = one_part_song("Ghost")
        setlist_tab.update_from_config()
        unlisted = [c for c in setlist_tab._rail_cards
                    if c.entry_index < 0][0]
        assert not unlisted.acceptDrops()

    def test_rename_song_follows_into_the_setlist(self, setlist_tab,
                                                  monkeypatch):
        from PyQt6.QtWidgets import QInputDialog, QMessageBox
        setlist_tab._rail_cards[0].clicked.emit("Neon Ruinen")
        monkeypatch.setattr(
            QInputDialog, "getText",
            staticmethod(lambda *a, **k: ("Neon Ruins", True)))
        monkeypatch.setattr(
            QMessageBox, "information",
            staticmethod(lambda *a, **k: None))
        setlist_tab.rename_show_btn.click()
        assert setlist_tab.config.setlist.entries[0].song == "Neon Ruins"
        cards = [c for c in setlist_tab._rail_cards if c.entry_index >= 0]
        assert cards[0].title_label.text() == "01 · Neon Ruins"

    def test_delete_song_removes_its_entry(self, setlist_tab, monkeypatch):
        from PyQt6.QtWidgets import QMessageBox
        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
        monkeypatch.setattr(
            QMessageBox, "information",
            staticmethod(lambda *a, **k: None))
        setlist_tab._rail_cards[1].clicked.emit("Monsters")
        setlist_tab.delete_show_btn.click()
        assert "Monsters" not in setlist_tab.config.songs
        assert [e.song for e in setlist_tab.config.setlist.entries] == \
            ["Neon Ruinen", "Schwarzes Gold"]
        cards = [c for c in setlist_tab._rail_cards if c.entry_index >= 0]
        assert len(cards) == 2
        assert len(setlist_tab._rail_pause_rows) == 1


# ---------------------------------------------------------------------------
# S2c: SONG section (the open song's setlist-entry trigger)
# ---------------------------------------------------------------------------
class TestSongTriggerSection:
    """The setlist_tab opens "Monsters" (sorted combo): setlist entry
    2, trigger midi_note 36 (C2) on channel 1, pause hold_last."""

    def rail_card(self, tab, index):
        return [c for c in tab._rail_cards if c.entry_index >= 0][index]

    def test_caption_names_the_open_song(self, setlist_tab):
        assert setlist_tab.song_caption.text() == "SONG · MONSTERS"

    def test_all_six_model_modes_have_a_segment(self, setlist_tab):
        # The mock collapses to four; the model has six - all six stay
        # honest, two rows of three at 340px.
        assert set(setlist_tab.trigger_buttons) == \
            {"manual", "midi_pc", "midi_note", "mtc", "smpte", "follow"}
        labels = [setlist_tab.trigger_buttons[m].text() for m in
                  ("manual", "midi_pc", "midi_note",
                   "mtc", "smpte", "follow")]
        assert labels == ["MANUAL", "MIDI PC", "MIDI NOTE",
                          "MTC", "SMPTE", "FOLLOW"]

    def test_segments_reflect_the_model(self, setlist_tab):
        assert setlist_tab.trigger_buttons["midi_note"].isChecked()
        for mode in ("manual", "midi_pc", "mtc", "smpte", "follow"):
            assert not setlist_tab.trigger_buttons[mode].isChecked()

    def test_segments_follow_a_song_switch(self, setlist_tab):
        setlist_tab._rail_cards[0].clicked.emit("Neon Ruinen")
        assert setlist_tab.song_caption.text() == "SONG · NEON RUINEN"
        assert setlist_tab.trigger_buttons["midi_pc"].isChecked()
        assert setlist_tab.trigger_value_spin.value() == 5
        assert setlist_tab.trigger_value_spin.prefix() == "PC#"
        assert setlist_tab.trigger_channel_spin.value() == 1

    def test_segment_click_writes_mode_and_updates_the_rail(self,
                                                            setlist_tab):
        setlist_tab.trigger_buttons["mtc"].click()
        entry = setlist_tab.config.setlist.entries[1]
        assert entry.trigger.mode == "mtc"
        # Rail trigger line updates live (timecode unset: mode name).
        assert self.rail_card(setlist_tab, 1).trigger_label.text() == "MTC"
        # Exclusive: the old mode unchecked.
        assert not setlist_tab.trigger_buttons["midi_note"].isChecked()

    def test_editor_visibility_per_mode(self, setlist_tab):
        cases = {
            "manual": (False, False, False, False, True),
            "midi_pc": (True, False, True, False, False),
            "midi_note": (True, True, True, False, False),
            "mtc": (False, False, False, True, False),
            "smpte": (False, False, False, True, False),
            "follow": (False, False, False, False, True),
        }
        for mode, (value, note, channel, timecode, hint) in cases.items():
            setlist_tab.trigger_buttons[mode].click()
            assert setlist_tab.trigger_value_spin.isHidden() != value, mode
            assert setlist_tab.trigger_note_label.isHidden() != note, mode
            assert setlist_tab.trigger_channel_spin.isHidden() != channel, \
                mode
            assert setlist_tab.trigger_timecode_edit.isHidden() != timecode, \
                mode
            assert setlist_tab.trigger_mode_hint.isHidden() != hint, mode

    def test_mode_hints_copy(self, setlist_tab):
        setlist_tab.trigger_buttons["manual"].click()
        assert setlist_tab.trigger_mode_hint.text() == \
            "Started from the app"
        setlist_tab.trigger_buttons["follow"].click()
        assert setlist_tab.trigger_mode_hint.text() == \
            "Chains after the previous song's pause look"

    def test_note_value_write_through_with_note_name(self, setlist_tab):
        setlist_tab.trigger_value_spin.setValue(37)
        entry = setlist_tab.config.setlist.entries[1]
        assert entry.trigger.value == 37
        assert setlist_tab.trigger_note_label.text() == "C#2"
        assert self.rail_card(setlist_tab, 1).trigger_label.text() == \
            "NOTE C#2 · CH 1"

    def test_channel_write_through(self, setlist_tab):
        setlist_tab.trigger_channel_spin.setValue(5)
        entry = setlist_tab.config.setlist.entries[1]
        assert entry.trigger.channel == 5
        assert self.rail_card(setlist_tab, 1).trigger_label.text() == \
            "NOTE C2 · CH 5"

    def test_timecode_valid_write_through(self, setlist_tab):
        setlist_tab.trigger_buttons["mtc"].click()
        setlist_tab.trigger_timecode_edit.setText("00:14:32:00")
        setlist_tab.trigger_timecode_edit.editingFinished.emit()
        entry = setlist_tab.config.setlist.entries[1]
        assert entry.trigger.timecode == "00:14:32:00"
        assert setlist_tab.trigger_timecode_edit.property("state") == ""
        assert self.rail_card(setlist_tab, 1).trigger_label.text() == \
            "00:14:32:00"

    def test_timecode_invalid_keeps_old_value_and_tints(self, setlist_tab):
        setlist_tab.trigger_buttons["smpte"].click()
        setlist_tab.trigger_timecode_edit.setText("01:00:00:00")
        setlist_tab.trigger_timecode_edit.editingFinished.emit()
        setlist_tab.trigger_timecode_edit.setText("nonsense")
        setlist_tab.trigger_timecode_edit.editingFinished.emit()
        entry = setlist_tab.config.setlist.entries[1]
        # The model keeps the old value; the field reverts and carries
        # the quiet warning property (no popup).
        assert entry.trigger.timecode == "01:00:00:00"
        assert setlist_tab.trigger_timecode_edit.text() == "01:00:00:00"
        assert setlist_tab.trigger_timecode_edit.property("state") == \
            "invalid"
        # A valid edit clears the tint.
        setlist_tab.trigger_timecode_edit.setText("02:00:00:00")
        setlist_tab.trigger_timecode_edit.editingFinished.emit()
        assert entry.trigger.timecode == "02:00:00:00"
        assert setlist_tab.trigger_timecode_edit.property("state") == ""

    def test_invalid_state_rule_in_theme(self):
        """The tint rides the theme's property selector, not a
        widget-local stylesheet."""
        from gui.theme_tokens import render_theme
        qss = render_theme("dark")
        assert 'QLineEdit[state="invalid"]' in qss

    def test_timecode_may_be_cleared(self, setlist_tab):
        setlist_tab.trigger_buttons["mtc"].click()
        setlist_tab.trigger_timecode_edit.setText("00:14:32:00")
        setlist_tab.trigger_timecode_edit.editingFinished.emit()
        setlist_tab.trigger_timecode_edit.setText("")
        setlist_tab.trigger_timecode_edit.editingFinished.emit()
        entry = setlist_tab.config.setlist.entries[1]
        assert entry.trigger.timecode == ""
        assert self.rail_card(setlist_tab, 1).trigger_label.text() == "MTC"

    def test_learn_is_a_disabled_honest_placeholder(self, setlist_tab):
        assert setlist_tab.learn_btn.text() == "LEARN"
        assert not setlist_tab.learn_btn.isEnabled()
        assert setlist_tab.learn_btn.toolTip() == \
            "Arrives with the sync engine"

    def test_micro_hint_names_the_timecode_format(self, setlist_tab):
        assert setlist_tab.trigger_micro_hint.text() == \
            "MTC/SMPTE: start time e.g. 00:14:32:00 · devices in Settings"

    def test_unlisted_song_hides_editors_behind_a_hint(self, tab):
        # The legacy fixture's "Demo" song has no setlist entry.
        assert tab.song_caption.text() == "SONG · DEMO"
        assert tab.trigger_host.isHidden()
        assert not tab.song_unlisted_hint.isHidden()
        assert tab.song_unlisted_hint.text().startswith(
            "No setlist entry for this song")
        assert tab.pause_section.isHidden()

    def test_no_song_at_all_is_the_unlisted_state(self, empty_tab):
        assert empty_tab.song_caption.text() == "SONG · -"
        assert empty_tab.trigger_host.isHidden()
        assert not empty_tab.song_unlisted_hint.isHidden()

    def test_entry_sections_return_when_song_joins_the_setlist(self, tab):
        tab.config.setlist.entries.append(SetlistEntry(song="Demo"))
        tab.update_from_config()
        assert not tab.trigger_host.isHidden()
        assert tab.song_unlisted_hint.isHidden()
        assert not tab.pause_section.isHidden()
        assert tab.trigger_buttons["manual"].isChecked()   # entry default


# ---------------------------------------------------------------------------
# S2c: AFTER THE SONG section (the open entry's pause look)
# ---------------------------------------------------------------------------
class TestPauseLookSection:
    """Open song "Monsters" = entry index 1: its pause look renders in
    rail pause row 1 (the row above card 3)."""

    def test_chip_shows_current_mode(self, setlist_tab):
        assert setlist_tab.pause_mode_chip.text() == "HOLD LAST LOOK ↓"

    def test_menu_lists_the_four_modes_with_current_checked(self,
                                                            setlist_tab):
        menu = setlist_tab._build_pause_mode_menu()
        actions = menu.actions()
        assert [a.text() for a in actions] == \
            ["BLACKOUT", "WARM WHITE", "HOLD LAST LOOK", "AMBIENT LOOP"]
        assert [a.isChecked() for a in actions] == \
            [False, False, True, False]

    def test_menu_action_writes_mode_and_refreshes_the_rail(self,
                                                            setlist_tab):
        menu = setlist_tab._build_pause_mode_menu()
        menu.actions()[0].trigger()   # BLACKOUT
        entry = setlist_tab.config.setlist.entries[1]
        assert entry.pause_after.mode == "blackout"
        assert setlist_tab.pause_mode_chip.text() == "BLACKOUT ↓"
        assert setlist_tab._rail_pause_rows[1].text() == \
            "PAUSE LOOK · Blackout · until trigger"

    def test_level_spin_only_for_warm_white(self, setlist_tab):
        assert setlist_tab.pause_level_row.isHidden()   # hold_last
        setlist_tab._set_pause_mode("warm_white")
        assert not setlist_tab.pause_level_row.isHidden()
        assert setlist_tab.pause_level_spin.value() == 20   # model default

    def test_level_write_through_and_live_rail_refresh(self, setlist_tab):
        setlist_tab._set_pause_mode("warm_white")
        setlist_tab.pause_level_spin.setValue(55)
        entry = setlist_tab.config.setlist.entries[1]
        assert entry.pause_after.level == 55
        assert setlist_tab._rail_pause_rows[1].text() == \
            "PAUSE LOOK · Warm white 55% · until trigger"

    def test_until_duration_shows_the_spin_and_writes(self, setlist_tab):
        assert setlist_tab.pause_until_buttons["trigger"].isChecked()
        assert setlist_tab.pause_duration_spin.isHidden()
        setlist_tab.pause_until_buttons["duration"].click()
        entry = setlist_tab.config.setlist.entries[1]
        assert entry.pause_after.until == "duration"
        assert not setlist_tab.pause_duration_spin.isHidden()
        setlist_tab.pause_duration_spin.setValue(30)
        assert entry.pause_after.duration_s == 30.0
        assert setlist_tab._rail_pause_rows[1].text() == \
            "PAUSE LOOK · Hold last look · 30s"

    def test_until_trigger_hides_the_spin_again(self, setlist_tab):
        setlist_tab.pause_until_buttons["duration"].click()
        setlist_tab.pause_until_buttons["trigger"].click()
        entry = setlist_tab.config.setlist.entries[1]
        assert entry.pause_after.until == "trigger"
        assert setlist_tab.pause_duration_spin.isHidden()

    def test_last_entry_pause_edits_write_without_a_rail_row(self,
                                                             setlist_tab):
        # "Schwarzes Gold" is the last entry: no pause row below it, but
        # the model write path is identical.
        setlist_tab._rail_cards[2].clicked.emit("Schwarzes Gold")
        setlist_tab._set_pause_mode("ambient_loop")
        entry = setlist_tab.config.setlist.entries[2]
        assert entry.pause_after.mode == "ambient_loop"
        assert setlist_tab.pause_mode_chip.text() == "AMBIENT LOOP ↓"

    def test_micro_hint_is_honest_about_the_engine(self, setlist_tab):
        assert setlist_tab.pause_micro_hint.text() == (
            "Ambient loop = the screensaver rig behaviour · engine "
            "arrives in a later release")

    def test_pause_edits_mark_the_config_dirty_via_auto_save(self,
                                                             setlist_tab,
                                                             monkeypatch):
        calls = []
        monkeypatch.setattr(setlist_tab, "_auto_save",
                            lambda: calls.append(True))
        setlist_tab._set_pause_mode("blackout")
        setlist_tab.trigger_buttons["manual"].click()
        assert len(calls) == 2


class TestChaseRow:
    """ARM CHASE + sync device combo (docs/ltc-plan.md phase 3)."""

    @pytest.fixture(autouse=True)
    def _fake_devices(self, monkeypatch):
        from audio.device_manager import AudioDevice, DeviceManager
        devices = [AudioDevice(index=3, name="Line In (HD Audio)",
                               max_output_channels=0,
                               max_input_channels=2,
                               default_sample_rate=44100.0,
                               host_api="Windows WASAPI",
                               host_api_index=1,
                               display_name="Line In")]
        monkeypatch.setattr(DeviceManager, "enumerate_input_devices",
                            lambda self, **kw: devices)

    def _smpte(self, tab, with_trigger=True):
        tab.config.setlist.sync_mode = "smpte"
        if with_trigger and tab.config.setlist.entries:
            entry = tab.config.setlist.entries[0]
            entry.trigger.mode = "smpte"
            entry.trigger.timecode = "01:00:00:00"
        tab._refresh_sync_chase_row()

    def test_smpte_mode_reveals_and_populates_devices(self, setlist_tab):
        self._smpte(setlist_tab)
        combo = setlist_tab.sync_device_combo
        assert not combo.isHidden()
        assert not setlist_tab.chase_arm_btn.isHidden()
        assert [combo.itemText(i) for i in range(combo.count())] == \
            ["Default input", "Line In"]
        assert combo.itemData(1) == "Line In (HD Audio)"

    def test_arm_needs_an_smpte_trigger(self, setlist_tab):
        self._smpte(setlist_tab, with_trigger=False)
        assert not setlist_tab.chase_arm_btn.isEnabled()
        self._smpte(setlist_tab, with_trigger=True)
        assert setlist_tab.chase_arm_btn.isEnabled()

    def test_device_choice_persists_to_the_setlist(self, setlist_tab):
        self._smpte(setlist_tab)
        setlist_tab.sync_device_combo.setCurrentIndex(1)
        assert setlist_tab.config.setlist.sync_device == \
            "Line In (HD Audio)"

    def test_arm_toggle_requests_and_reflect_does_not_reemit(
            self, setlist_tab):
        self._smpte(setlist_tab)
        requests = []
        setlist_tab.chase_arm_requested.connect(requests.append)
        setlist_tab.chase_arm_btn.setChecked(True)
        assert requests == [True]
        # The shell refused (input would not open) and reflects back.
        setlist_tab.set_chase_armed(False)
        assert not setlist_tab.chase_arm_btn.isChecked()
        assert requests == [True]

    def test_set_chase_armed_renames_the_chip(self, setlist_tab):
        self._smpte(setlist_tab)
        setlist_tab.set_chase_armed(True)
        assert setlist_tab.chase_arm_btn.text() == "CHASING"
        assert setlist_tab.chase_arm_btn.isChecked()
        setlist_tab.set_chase_armed(False)
        assert setlist_tab.chase_arm_btn.text() == "ARM CHASE"
