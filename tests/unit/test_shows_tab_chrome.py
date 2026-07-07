"""Shows tab chrome (North Star card 4a): toolbar grid chips, icon
transport buttons and the 3D-pane toggle.

Covers:
- The toolbar GRID chip row mirrors the master timeline's documented
  subdivision choices, pushes clicks into TimelineGrid (master combo +
  audio lane + light lanes all follow), and syncs back when the master
  combobox changes - with no signal feedback loop.
- Transport buttons are icon-only (line icons, no text) and the play
  button swaps play/pause glyphs with playback state.
- The pane-toggle chevron collapses and restores the right splitter
  pane, and follows manual splitter drags.

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
        master = shows_tab.master_timeline
        # Index 1 == subdivision 2 (see SUBDIVISION_CHOICES).
        master.subdivision_combo.setCurrentIndex(1)
        assert shows_tab.grid_chips[2].isChecked()
        assert not shows_tab.grid_chips[1].isChecked()

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


class TestPreservedChrome:
    def test_existing_toolbar_widgets_survive(self, shows_tab):
        """gui.py drives these by attribute - pin their existence."""
        for name in ("show_combo", "add_lane_btn", "autogen_btn",
                     "inspector_btn", "zoom_slider", "zoom_label",
                     "save_btn", "play_btn", "stop_btn", "time_label",
                     "position_slider", "total_time_label"):
            assert getattr(shows_tab, name, None) is not None, name
        assert shows_tab.autogen_btn.property("role") == "primary"

    def test_show_loads_and_zoom_still_works(self, shows_tab):
        shows_tab.update_from_config()
        assert shows_tab.show_combo.currentText() == "Demo Show"
        shows_tab.zoom_slider.setValue(200)
        assert shows_tab.zoom_label.text() == "2.0x"
        assert shows_tab.master_timeline.timeline_widget.zoom_factor == 2.0
