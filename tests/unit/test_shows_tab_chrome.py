"""Shows tab chrome (North Star card 4a / reference screen
design_handoff_lichtmaschine_app/screens/06-show-timeline.html): toolbar
grid + snap chips, icon transport, bar readout, right-pane header,
block inspector and the footer status line.

Covers:
- The toolbar GRID chip row mirrors the master timeline's documented
  subdivision choices, pushes clicks into TimelineGrid (master combo +
  audio lane + light lanes all follow), and syncs back when the master
  combobox changes - with no signal feedback loop. Same contract for
  the SNAP chip.
- Transport buttons are icon-only (line icons, no text) and the play
  button swaps play/pause glyphs with playback state.
- The transport readout is the reference's bar-based
  "BAR <bar>.<beat> · <mm:ss.s>", derived from the SongStructure parts.
- The pane-toggle chevron collapses and restores the right splitter
  pane, and follows manual splitter drags; the pane header carries the
  reference's POP-OUT + collapse chevron.
- The right-pane block inspector reflects the real SelectionManager
  state (empty / single / multi) and carries no overlap-function chip
  row, because per-block overlap functions do not exist in the data
  model (roadmap v1.6).
- The footer status line reports lanes / blocks / grid / zoom.

Constructing ShowsTab headlessly normally hangs on the embedded-GL
visualizer, so these tests stub EmbeddedVisualizer and RiffBrowserPanel
with plain widgets before construction (same trick as
tests/visual/test_timeline_chrome_golden.py).
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _stub_heavy_widgets(monkeypatch):
    """Replace the GL visualizer + riff panel with inert widgets."""
    from PyQt6.QtWidgets import QWidget

    class StubVisualizer(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)

        def set_pop_out_callback(self, callback):
            pass

        def set_inner_pop_out_visible(self, visible):
            pass

        def set_config(self, config):
            pass

        def set_preview_mode(self, mode):
            pass

        def feed_dmx(self, universe, dmx_bytes):
            pass

        def cleanup(self):
            pass

    class StubRiffPanel(QWidget):
        def __init__(self, library=None, parent=None):
            super().__init__(parent)

    monkeypatch.setattr("gui.tabs.shows_tab.EmbeddedVisualizer", StubVisualizer)
    monkeypatch.setattr("gui.tabs.shows_tab.RiffBrowserPanel", StubRiffPanel)
    monkeypatch.setattr(
        "gui.tabs.shows_tab.ShowsTab._get_shared_riff_library",
        lambda self: None,
    )


def _add_show(config, name="Demo Show"):
    from config.models import Show, ShowPart, TimelineData
    config.shows[name] = Show(
        name=name,
        parts=[ShowPart(name="Intro", color="#FF0000", signature="4/4",
                        bpm=120.0, num_bars=4, transition="instant")],
        effects=[],
        timeline_data=TimelineData(),
    )


@pytest.fixture
def shows_tab(qapp, monkeypatch, sample_configuration):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QApplication
    from gui.theme_manager import ThemeManager

    _stub_heavy_widgets(monkeypatch)
    ThemeManager().apply(qapp, "dark")
    _add_show(sample_configuration)

    from gui.tabs.shows_tab import ShowsTab
    tab = ShowsTab(sample_configuration, parent=None)
    tab.artnet_enabled = False  # never open sockets in tests
    tab.tcp_enabled = False
    try:
        yield tab
    finally:
        tab.cleanup()
        tab.deleteLater()
        # DeferredDelete is not flushed by processEvents() at this nesting
        # level; without this the torn-down tabs accumulate and the next
        # ThemeManager.apply() repolishes half-dead widgets (native crash).
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        QApplication.processEvents()


def _icon_pixels(icon, size=16):
    from tests.visual.harness import qimage_to_array
    return qimage_to_array(icon.pixmap(size, size).toImage())


class TestGridChips:
    def test_chips_match_documented_subdivisions(self, shows_tab):
        from timeline_ui.master_timeline_widget import SUBDIVISION_CHOICES
        assert sorted(shows_tab.grid_chips) == sorted(
            v for _label, v in SUBDIVISION_CHOICES)
        # Default: whole-beat grid checked, chips exclusive.
        assert shows_tab.grid_chips[1].isChecked()
        assert shows_tab.grid_chip_group.exclusive()
        for chip in shows_tab.grid_chips.values():
            assert chip.property("role") == "output-select"

    def test_chip_click_fans_out_to_master_and_lanes(self, shows_tab):
        from timeline.light_lane import LightLane
        shows_tab._add_lane_widget(LightLane("L1"))

        shows_tab.grid_chips[4].click()

        master = shows_tab.master_timeline
        assert master.timeline_widget.grid_subdivision == 4
        assert master.subdivision_combo.currentData() == 4
        assert shows_tab.audio_lane.timeline_widget.grid_subdivision == 4
        assert shows_tab.lane_widgets[0].timeline_widget.grid_subdivision == 4

    def test_master_combo_change_syncs_chips(self, shows_tab):
        from timeline_ui.master_timeline_widget import SUBDIVISION_CHOICES
        master = shows_tab.master_timeline
        # Drive the combo to the 1/2-beat entry (value 2.0) by index.
        idx = next(i for i, (_l, v) in enumerate(SUBDIVISION_CHOICES)
                   if v == 2.0)
        master.subdivision_combo.setCurrentIndex(idx)
        assert shows_tab.grid_chips[2].isChecked()
        assert not shows_tab.grid_chips[1].isChecked()

    def test_seven_chips_labelled_by_grid_interval(self, shows_tab):
        # Chip text is the grid interval in beats, coarse to fine.
        labels = [shows_tab.grid_chips[v].text()
                  for v in (0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0)]
        assert labels == ["4", "2", "1", "1/2", "1/4", "1/8", "1/16"]
        assert len(shows_tab.grid_chips) == 7

    def test_coarse_chip_click_fans_out_float(self, shows_tab):
        shows_tab.grid_chips[0.25].click()
        master = shows_tab.master_timeline
        assert master.timeline_widget.grid_subdivision == 0.25
        assert master.subdivision_combo.currentData() == 0.25

    def test_no_feedback_loop_between_chip_and_combo(self, shows_tab):
        received = []
        shows_tab.timeline_grid.subdivision_changed.connect(received.append)
        shows_tab.grid_chips[2].click()
        # set_grid_subdivision syncs the master combo silently - the
        # grid-level signal must not re-fire from the chip path.
        assert received == []
        assert shows_tab.master_timeline.subdivision_combo.currentData() == 2


class TestTransportButtons:
    def test_buttons_are_icon_only(self, shows_tab):
        for btn in (shows_tab.play_btn, shows_tab.stop_btn,
                    shows_tab.pane_toggle_btn):
            assert btn.text() == ""
            assert not btn.icon().isNull()
            assert (_icon_pixels(btn.icon())[:, :, 3] > 0).any()

    def test_play_button_swaps_to_pause_glyph_while_playing(self, shows_tab):
        import numpy as np
        from gui.icons import line_icon

        shows_tab.update_from_config()  # loads the show -> song_structure
        assert shows_tab.song_structure is not None

        play_glyph = _icon_pixels(line_icon("play", "#ffffff"))
        pause_glyph = _icon_pixels(line_icon("pause", "#ffffff"))
        assert np.array_equal(_icon_pixels(shows_tab.play_btn.icon()),
                              play_glyph)

        shows_tab._start_playback()
        try:
            assert shows_tab.is_playing
            assert np.array_equal(_icon_pixels(shows_tab.play_btn.icon()),
                                  pause_glyph)
        finally:
            shows_tab._stop_playback()
        assert not shows_tab.is_playing
        assert np.array_equal(_icon_pixels(shows_tab.play_btn.icon()),
                              play_glyph)


class TestPaneToggle:
    def test_toggle_collapses_and_restores_right_pane(self, qapp, shows_tab):
        shows_tab.resize(1400, 800)
        shows_tab.show()
        for _ in range(3):
            qapp.processEvents()
        try:
            sizes = shows_tab._main_splitter.sizes()
            assert sizes[1] > 0, "right pane should start visible"

            shows_tab.pane_toggle_btn.setChecked(False)
            assert shows_tab._main_splitter.sizes()[1] == 0

            shows_tab.pane_toggle_btn.setChecked(True)
            assert shows_tab._main_splitter.sizes()[1] > 0
        finally:
            shows_tab.hide()

    def test_manual_splitter_drag_syncs_chevron_state(self, qapp, shows_tab):
        shows_tab.resize(1400, 800)
        shows_tab.show()
        for _ in range(3):
            qapp.processEvents()
        try:
            total = sum(shows_tab._main_splitter.sizes())
            # Simulate the user dragging the pane shut: the splitter's
            # splitterMoved handler is _save_main_splitter_state.
            shows_tab._main_splitter.setSizes([total, 0])
            shows_tab._save_main_splitter_state()
            assert not shows_tab.pane_toggle_btn.isChecked()

            shows_tab._main_splitter.setSizes([total - 400, 400])
            shows_tab._save_main_splitter_state()
            assert shows_tab.pane_toggle_btn.isChecked()
        finally:
            shows_tab.hide()


class TestSnapChip:
    def test_snap_chip_is_a_checked_output_select_chip(self, shows_tab):
        assert shows_tab.snap_chip.isCheckable()
        assert shows_tab.snap_chip.isChecked()
        assert shows_tab.snap_chip.property("role") == "output-select"

    def test_snap_chip_click_fans_out_to_master_and_lanes(self, shows_tab):
        from timeline.light_lane import LightLane
        shows_tab._add_lane_widget(LightLane("L1"))

        shows_tab.snap_chip.click()  # checked -> unchecked, emits clicked(False)
        assert not shows_tab.snap_chip.isChecked()

        master = shows_tab.master_timeline
        assert master.timeline_widget.snap_to_grid is False
        assert not master.snap_checkbox.isChecked()
        assert shows_tab.lane_widgets[0].timeline_widget.snap_to_grid is False

    def test_master_snap_checkbox_syncs_chip_without_loop(self, shows_tab):
        received = []
        shows_tab.timeline_grid.snap_changed.connect(received.append)

        shows_tab.master_timeline.snap_checkbox.setChecked(False)
        assert not shows_tab.snap_chip.isChecked()
        assert received == [False]

        # Chip path must not re-emit the grid-level signal.
        received.clear()
        shows_tab._on_snap_chip_clicked(True)
        assert received == []
        assert shows_tab.master_timeline.snap_checkbox.isChecked()


class TestSwingChip:
    def test_swing_chip_is_a_checkable_output_select_chip(self, shows_tab):
        assert shows_tab.swing_chip.isCheckable()
        assert not shows_tab.swing_chip.isChecked()  # default off
        assert shows_tab.swing_chip.property("role") == "output-select"

    def test_swing_chip_click_calls_grid_set_swing(self, shows_tab, monkeypatch):
        calls = []
        monkeypatch.setattr(shows_tab.timeline_grid, "set_swing",
                            lambda enabled: calls.append(enabled))
        shows_tab.swing_chip.click()  # off -> on
        assert calls == [True]
        assert shows_tab.swing_chip.isChecked()
        shows_tab.swing_chip.click()  # on -> off
        assert calls == [True, False]

    def test_swing_chip_fans_out_to_master_and_lanes(self, shows_tab):
        from timeline.light_lane import LightLane
        shows_tab._add_lane_widget(LightLane("L1"))
        shows_tab.swing_chip.click()  # turn swing on
        master = shows_tab.master_timeline
        assert master.timeline_widget.swing_enabled is True
        assert shows_tab.audio_lane.timeline_widget.swing_enabled is True
        assert shows_tab.lane_widgets[0].timeline_widget.swing_enabled is True


class TestBarReadout:
    def test_readout_is_bar_dot_beat_plus_time(self, shows_tab):
        shows_tab.update_from_config()  # 4 bars of 4/4 at 120 BPM
        assert shows_tab.song_structure is not None

        # 120 BPM -> 0.5 s/beat, 2 s/bar.
        assert shows_tab._bar_beat_at(0.0) == (1, 1)
        assert shows_tab._bar_beat_at(0.5) == (1, 2)
        assert shows_tab._bar_beat_at(2.0) == (2, 1)
        assert shows_tab._bar_beat_at(5.25) == (3, 3)

        assert shows_tab._format_readout(0.0) == "BAR 1.1 · 00:00.0"
        assert shows_tab._format_readout(112.6) == "BAR 4.4 · 01:52.6"

    def test_readout_without_structure_shows_dashes(self, shows_tab):
        shows_tab.song_structure = None
        assert shows_tab._bar_beat_at(3.0) is None
        assert shows_tab._format_readout(3.0) == "BAR --.- · 00:03.0"

    def test_playhead_move_updates_the_transport_readout(self, shows_tab):
        shows_tab.update_from_config()
        shows_tab._on_playhead_moved(2.5)
        assert shows_tab.time_label.text() == "BAR 2.2 · 00:02.5"
        assert shows_tab.time_label.objectName() == "TimeReadout"


class TestPaneHeader:
    def test_header_has_popout_and_collapse_chevron(self, shows_tab):
        assert shows_tab.pane_popout_btn.property("role") == "cta-outline"
        assert shows_tab.pane_collapse_btn.text() == ""
        assert not shows_tab.pane_collapse_btn.icon().isNull()

    def test_header_chevron_collapses_the_pane(self, qapp, shows_tab):
        shows_tab.resize(1400, 800)
        shows_tab.show()
        for _ in range(3):
            qapp.processEvents()
        try:
            assert shows_tab._main_splitter.sizes()[1] > 0
            shows_tab.pane_collapse_btn.click()
            assert shows_tab._main_splitter.sizes()[1] == 0
            assert not shows_tab.pane_toggle_btn.isChecked()
        finally:
            shows_tab.hide()

    def test_right_pane_holds_render_inspector_and_riffs(self, shows_tab):
        assert shows_tab._right_splitter.count() == 3
        assert shows_tab._right_splitter.widget(1) is shows_tab.block_inspector
        assert shows_tab.block_inspector.property("role") == "inspector"


def _lane_with_block(shows_tab, lane_name="Front Pars"):
    from config.models import ColourBlock, DimmerBlock, LightBlock
    from timeline.light_lane import LightLane

    lane = LightLane(lane_name)
    lane.fixture_targets = ["TestGroup"]
    block = LightBlock(start_time=0.0, end_time=4.0, effect_name="bars.static",
                       name="Chorus Hit")
    block.dimmer_blocks = [DimmerBlock(start_time=0.0, end_time=2.0),
                           DimmerBlock(start_time=2.0, end_time=4.0)]
    block.colour_blocks = [ColourBlock(start_time=0.0, end_time=4.0)]
    lane.light_blocks = [block]
    shows_tab._add_lane_widget(lane)
    return shows_tab.lane_widgets[-1]


class TestBlockInspector:
    def test_empty_state_when_nothing_selected(self, shows_tab):
        shows_tab.update_from_config()
        assert shows_tab.inspector_empty.text() == "NO BLOCK SELECTED"
        assert shows_tab.inspector_empty.property("role") == "hint-box"
        assert shows_tab.inspector_stats_row.isHidden()

    def test_single_selection_shows_real_block_facts(self, shows_tab):
        shows_tab.update_from_config()
        lane_widget = _lane_with_block(shows_tab)
        block_widget = lane_widget.get_all_block_widgets()[0]

        shows_tab.selection_manager.select(block_widget)

        assert shows_tab.inspector_title.text() == "EFFECT BLOCK · CHORUS HIT"
        meta = shows_tab.inspector_meta.text()
        assert "FRONT PARS" in meta
        assert "BARS 1-3" in meta  # 0-4 s at 120 BPM = bars 1..3
        assert "4.0S" in meta
        assert shows_tab.inspector_stat_values["DIM"].text() == "2"
        assert shows_tab.inspector_stat_values["COL"].text() == "1"
        assert shows_tab.inspector_stat_values["MOV"].text() == "0"
        assert shows_tab.inspector_stat_values["SPC"].text() == "0"

    def test_lane_name_carries_the_group_color(self, shows_tab,
                                               sample_configuration):
        shows_tab.update_from_config()
        color = sample_configuration.groups["TestGroup"].color
        assert color, "fixture group fixture must carry a color"
        lane_widget = _lane_with_block(shows_tab)
        shows_tab.selection_manager.select(lane_widget.get_all_block_widgets()[0])
        assert color.lower() in shows_tab.inspector_meta.text().lower()

    def test_multi_selection_reports_the_count(self, shows_tab):
        shows_tab.update_from_config()
        a = _lane_with_block(shows_tab, "Lane A")
        b = _lane_with_block(shows_tab, "Lane B")
        shows_tab.selection_manager.select_multiple(
            [a.get_all_block_widgets()[0], b.get_all_block_widgets()[0]])
        assert shows_tab.inspector_empty.text() == "2 BLOCKS SELECTED"
        assert shows_tab.inspector_stats_row.isHidden()

    def test_clearing_selection_returns_to_empty_state(self, shows_tab):
        shows_tab.update_from_config()
        lane_widget = _lane_with_block(shows_tab)
        shows_tab.selection_manager.select(lane_widget.get_all_block_widgets()[0])
        shows_tab.selection_manager.clear_selection()
        assert shows_tab.inspector_empty.text() == "NO BLOCK SELECTED"

    def test_no_overlap_function_chip_row(self, shows_tab):
        """Per-block overlap functions (XFADE/HTP/LTP/ADD in the design
        reference) do not exist in the data model - v1.6 roadmap work.
        The inspector must not fake them."""
        from PyQt6.QtWidgets import QPushButton
        labels = {b.text().upper()
                  for b in shows_tab.block_inspector.findChildren(QPushButton)}
        assert not ({"XFADE", "HTP", "LTP", "ADD"} & labels)


class TestStatusFooter:
    def test_footer_line_reports_real_state(self, shows_tab):
        shows_tab.update_from_config()
        assert shows_tab.status_line.text() == \
            "0 LANES · 0 BLOCKS · GRID 1 · ZOOM 1.0X"

        _lane_with_block(shows_tab)
        assert shows_tab.status_line.text() == \
            "1 LANES · 1 BLOCKS · GRID 1 · ZOOM 1.0X"

        shows_tab.grid_chips[4].click()
        shows_tab.zoom_slider.setValue(250)
        assert shows_tab.status_line.text() == \
            "1 LANES · 1 BLOCKS · GRID 1/4 · ZOOM 2.5X"

    def test_footer_is_mono_micro_caps(self, shows_tab):
        assert shows_tab.status_line.property("role") == "micro"


class TestThemeRolesExist:
    """The chrome leans on shared QSS roles - assert the rules exist in
    the rendered theme rather than the resolved widget font (polish-order
    race, see tests/README.md)."""

    def test_roles_used_by_this_tab_are_in_the_theme(self):
        from gui.theme_tokens import render_theme
        qss = render_theme("dark")
        for rule in ('QWidget[role="inspector"]',
                     'QWidget[role="stat-tile"]',
                     'QLabel[role="stat-caption"]',
                     'QLabel[role="stat-value"]',
                     'QLabel[role="hint-box"]',
                     'QLabel[role="micro"]',
                     'QPushButton[role="cta-outline"]',
                     'QPushButton[role="output-select"]',
                     'QWidget[role="section-caption"]'):
            assert rule in qss, rule


class TestPreservedChrome:
    def test_existing_toolbar_widgets_survive(self, shows_tab):
        """gui.py drives these by attribute - pin their existence."""
        for name in ("show_combo", "add_lane_btn", "autogen_btn",
                     "inspector_btn", "zoom_slider", "zoom_label",
                     "save_btn", "play_btn", "stop_btn", "time_label",
                     "position_slider", "total_time_label",
                     "embedded_riff_panel", "embedded_visualizer",
                     "snap_chip", "status_line", "block_inspector"):
            assert getattr(shows_tab, name, None) is not None, name
        assert shows_tab.autogen_btn.property("role") == "primary"

    def test_show_loads_and_zoom_still_works(self, shows_tab):
        shows_tab.update_from_config()
        assert shows_tab.show_combo.currentText() == "Demo Show"
        shows_tab.zoom_slider.setValue(200)
        assert shows_tab.zoom_label.text() == "2.0x"
        assert shows_tab.master_timeline.timeline_widget.zoom_factor == 2.0
