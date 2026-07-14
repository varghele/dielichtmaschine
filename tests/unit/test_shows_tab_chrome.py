"""Shows tab chrome (timeline v3, reference screen
design_handoff_lichtmaschine_app/screens/06b-show-timeline-v3.html):
one compact toolbar row carrying song selector, actions, transport +
bar readout, GRID segment group, SNAP chip and SWING dropdown, plus
the right-pane header, block inspector and the footer status line.

Covers:
- The toolbar GRID segment group mirrors the master timeline's
  documented subdivision choices as one bordered role="card" group of
  role="segment" cells, and pushes clicks into TimelineGrid (master +
  audio lane + light lanes all follow). Same contract for the SNAP
  chip and the SWING percentage dropdown (0/25/50/75/100, fanned out
  as a 0.0-1.0 amount).
- The transport is merged INTO the toolbar row (no separate transport
  bar): play/stop are icon-only (line icons, no text), the play button
  swaps play/pause glyphs with playback state, and the position slider
  lives on the slim strip directly under the row.
- The inline readout is the reference's bar-based
  "BAR <bar>.<beat> · <mm:ss.s>", derived from the SongStructure parts.
- The pane-toggle chevron collapses and restores the right splitter
  pane, and follows manual splitter drags; the pane header carries the
  reference's POP-OUT + collapse chevron.
- The right-pane block inspector reflects the real SelectionManager
  state (empty / single / multi), carries the timeline v3 field rows
  (RANGE with bar span + snap, DIM effect chain, COL painted colour
  swatches with a transition arrow), and carries no overlap-function
  chip row or OVERLAP field, because per-block overlap functions do
  not exist in the data model (roadmap v1.7, plan "Deferred").
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
    from config.models import Song, ShowPart, TimelineData
    config.songs[name] = Song(
        name=name,
        parts=[ShowPart(name="Intro", color="#FF0000", signature="4/4",
                        bpm=120.0, num_bars=4, transition="instant")],
        effects=[],
        timeline_data=TimelineData(),
    )


def _add_setlist(config):
    """Three listed songs in a deliberately non-alphabetical setlist
    order, plus one song ("Zugabe") that stays off the setlist. The
    fixture's "Demo Show" is unlisted too."""
    from config.models import Setlist, SetlistEntry
    for name in ("Neon Ruinen", "Monsters", "Schwarzes Gold", "Zugabe"):
        _add_show(config, name)
    config.setlist = Setlist(name="Demo Tour", entries=[
        SetlistEntry(song="Schwarzes Gold"),
        SetlistEntry(song="Neon Ruinen"),
        SetlistEntry(song="Monsters"),
    ])


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
        # Timeline v3 (stage T1): one bordered group (role="card"), each
        # cell a borderless segment that accent-fills when checked (same
        # sanctioned pattern as the Stage tab layer bar).
        assert shows_tab.grid_group_frame.property("role") == "card"
        for chip in shows_tab.grid_chips.values():
            assert chip.property("role") == "segment"
            assert chip.parent() is shows_tab.grid_group_frame

    def test_chip_click_fans_out_to_master_and_lanes(self, shows_tab):
        from timeline.light_lane import LightLane
        shows_tab._add_lane_widget(LightLane("L1"))

        shows_tab.grid_chips[4].click()

        master = shows_tab.master_timeline
        # The master no longer has its own combobox; the chip drives its
        # grid drawing via the timeline widget.
        assert master.timeline_widget.grid_subdivision == 4
        assert not hasattr(master, "subdivision_combo")
        assert shows_tab.audio_lane.timeline_widget.grid_subdivision == 4
        assert shows_tab.lane_widgets[0].timeline_widget.grid_subdivision == 4

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

    def test_grid_signals_removed_with_master_controls(self, shows_tab):
        # The master combobox + its subdivision_changed/snap_changed fan-out
        # signals were removed; the toolbar chips are the single control.
        assert not hasattr(shows_tab.timeline_grid, "subdivision_changed")
        assert not hasattr(shows_tab.timeline_grid, "snap_changed")
        assert not hasattr(shows_tab.master_timeline, "subdivision_combo")
        assert not hasattr(shows_tab.master_timeline, "snap_checkbox")


class TestToolbarStructure:
    """Stage T1: the transport merged into the single toolbar row; the
    separate transport bar row is gone. The position slider sits on the
    slim strip directly under the row, inside the same toolbar widget
    (a single row cannot hold both sliders at 1280px)."""

    def test_transport_bar_row_is_gone(self, shows_tab):
        from PyQt6.QtWidgets import QWidget
        assert not hasattr(shows_tab, "transport_bar")
        assert shows_tab.findChild(QWidget, "ShowsTransportBar") is None

    def test_transport_and_readout_live_in_the_toolbar(self, shows_tab):
        toolbar = shows_tab.toolbar_widget
        for widget in (shows_tab.play_btn, shows_tab.stop_btn,
                       shows_tab.time_label, shows_tab.position_slider,
                       shows_tab.total_time_label, shows_tab.zoom_slider,
                       shows_tab.swing_btn, shows_tab.snap_chip,
                       shows_tab.grid_group_frame, shows_tab.save_btn):
            assert toolbar.isAncestorOf(widget), widget

    def test_compact_action_texts_match_the_mock(self, shows_tab):
        assert shows_tab.add_lane_btn.text() == "+ LANE"
        assert shows_tab.autogen_btn.text() == "AUTOGEN"


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
        # The master has no snap checkbox now; the chip drives its ruler
        # snap via the timeline widget, and each lane follows.
        assert master.timeline_widget.snap_to_grid is False
        assert shows_tab.lane_widgets[0].timeline_widget.snap_to_grid is False
        # The per-lane checkbox mirrors the global state.
        assert not shows_tab.lane_widgets[0].snap_checkbox.isChecked()


class TestSwingDropdown:
    def test_swing_is_a_lane_chip_dropdown_defaulting_to_zero(self, shows_tab):
        # Timeline v3 (stage T1): SWING is a percentage dropdown chip, not
        # an on/off toggle. Default 0% (straight grid), 0% action checked.
        assert shows_tab.swing_btn.property("role") == "lane-chip"
        assert not shows_tab.swing_btn.isCheckable()
        # The mock's ▾ is tofu in the brand mono font; ↓ is the pinned
        # drop indicator (same as the lane header TARGETS chip).
        assert shows_tab.swing_btn.text() == "SWING 0% ↓"
        assert shows_tab.swing_percent == 0
        assert sorted(shows_tab.swing_actions) == [0, 25, 50, 75, 100]
        assert shows_tab.swing_actions[0].isChecked()
        assert [a.text() for a in shows_tab.swing_menu.actions()] == \
            ["0%", "25%", "50%", "75%", "100%"]

    def test_selecting_a_step_calls_grid_set_swing_with_amount(
            self, shows_tab, monkeypatch):
        calls = []
        monkeypatch.setattr(shows_tab.timeline_grid, "set_swing",
                            lambda amount: calls.append(amount))
        shows_tab.swing_actions[50].trigger()
        assert calls == [0.5]
        assert shows_tab.swing_btn.text() == "SWING 50% ↓"
        assert shows_tab.swing_percent == 50
        assert shows_tab.swing_actions[50].isChecked()
        shows_tab.swing_actions[0].trigger()
        assert calls == [0.5, 0.0]
        assert shows_tab.swing_btn.text() == "SWING 0% ↓"

    def test_swing_amount_fans_out_to_master_and_lanes(self, shows_tab):
        from timeline.light_lane import LightLane
        shows_tab._add_lane_widget(LightLane("L1"))
        shows_tab.swing_actions[100].trigger()  # full triplet feel
        master = shows_tab.master_timeline
        assert master.timeline_widget.swing_amount == 1.0
        assert shows_tab.audio_lane.timeline_widget.swing_amount == 1.0
        assert shows_tab.lane_widgets[0].timeline_widget.swing_amount == 1.0

        shows_tab.swing_actions[25].trigger()
        assert master.timeline_widget.swing_amount == 0.25
        assert shows_tab.lane_widgets[0].timeline_widget.swing_amount == 0.25


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


def _col_row_contents(shows_tab):
    """The COL row's live layout contents, in order: "chip:#RRGGBB" for
    a painted swatch, or the label text for arrows / placeholders.
    Reads the layout (not findChildren) so swatches replaced by an
    earlier refresh (deleteLater pending) can't leak in."""
    from PyQt6.QtWidgets import QLabel
    box = shows_tab._inspector_col_box
    out = []
    for i in range(box.count()):
        widget = box.itemAt(i).widget()
        if not isinstance(widget, QLabel):
            continue
        pixmap = widget.pixmap()
        if pixmap is not None and not pixmap.isNull():
            color = pixmap.toImage().pixelColor(
                pixmap.width() // 2, pixmap.height() // 2)
            out.append(f"chip:{color.name().upper()}")
        else:
            out.append(widget.text())
    return out


class TestBlockInspector:
    def test_empty_state_when_nothing_selected(self, shows_tab):
        shows_tab.update_from_config()
        assert shows_tab.inspector_empty.text() == "NO BLOCK SELECTED"
        assert shows_tab.inspector_empty.property("role") == "hint-box"
        assert shows_tab.inspector_stats_row.isHidden()
        assert shows_tab.inspector_rows.isHidden()

    def test_single_selection_shows_real_block_facts(self, shows_tab):
        shows_tab.update_from_config()
        lane_widget = _lane_with_block(shows_tab)
        block_widget = lane_widget.get_all_block_widgets()[0]

        shows_tab.selection_manager.select(block_widget)

        assert shows_tab.inspector_title.text() == "EFFECT BLOCK · CHORUS HIT"
        meta = shows_tab.inspector_meta.text()
        assert "FRONT PARS" in meta
        assert "4.0S" in meta
        # The bar span moved into the RANGE field row (T5), counted the
        # same way as the T3 block header strip: 0-4 s at 120 BPM 4/4 is
        # bars 1..2 (a block ending on a bar line doesn't claim the next
        # bar); the default grid is the whole-beat "1" with snap on.
        assert shows_tab.inspector_range_value.text() == "BARS 1-2 · SNAP 1"
        assert shows_tab.inspector_stat_values["DIM"].text() == "2"
        assert shows_tab.inspector_stat_values["COL"].text() == "1"
        assert shows_tab.inspector_stat_values["MOV"].text() == "0"
        assert shows_tab.inspector_stat_values["SPC"].text() == "0"

    def test_range_row_follows_snap_and_grid_state(self, shows_tab):
        shows_tab.update_from_config()
        lane_widget = _lane_with_block(shows_tab)
        shows_tab.selection_manager.select(
            lane_widget.get_all_block_widgets()[0])

        shows_tab.grid_chips[4].click()  # 1/4 grid
        assert shows_tab.inspector_range_value.text() == \
            "BARS 1-2 · SNAP 1/4"

        shows_tab.snap_chip.click()  # snap off
        assert shows_tab.inspector_range_value.text() == \
            "BARS 1-2 · SNAP OFF"

    def test_dim_row_lists_the_effect_chain(self, shows_tab):
        from config.models import DimmerBlock
        shows_tab.update_from_config()
        lane_widget = _lane_with_block(shows_tab)
        block_widget = lane_widget.get_all_block_widgets()[0]
        block_widget.block.dimmer_blocks = [
            DimmerBlock(start_time=0.0, end_time=2.0,
                        effect_type="fade", intensity=208.0),
            DimmerBlock(start_time=2.0, end_time=4.0,
                        effect_type="pulse", effect_speed="1/2"),
        ]

        shows_tab.selection_manager.select(block_widget)
        assert shows_tab.inspector_dim_value.text() == "FADE 208 → PULSE 1/2"

    def test_dim_row_placeholder_without_dimmer_blocks(self, shows_tab):
        shows_tab.update_from_config()
        lane_widget = _lane_with_block(shows_tab)
        block_widget = lane_widget.get_all_block_widgets()[0]
        block_widget.block.dimmer_blocks = []
        shows_tab.selection_manager.select(block_widget)
        assert shows_tab.inspector_dim_value.text() == "-"

    def test_col_row_paints_swatches_with_transition_arrow(self, shows_tab):
        """Two colours in the block -> two ACTUAL QColor swatches joined
        by an arrow (the mock's chip → chip treatment)."""
        from config.models import ColourBlock
        shows_tab.update_from_config()
        lane_widget = _lane_with_block(shows_tab)
        block_widget = lane_widget.get_all_block_widgets()[0]
        block_widget.block.colour_blocks = [
            ColourBlock(start_time=0.0, end_time=2.0, red=225, green=113,
                        blue=38),
            ColourBlock(start_time=2.0, end_time=4.0, red=255, green=0,
                        blue=255),
        ]

        shows_tab.selection_manager.select(block_widget)
        assert _col_row_contents(shows_tab) == \
            ["chip:#E17126", "→", "chip:#FF00FF"]
        assert len(shows_tab.inspector_col_chips) == 2

    def test_col_row_single_colour_has_no_arrow(self, shows_tab):
        from config.models import ColourBlock
        shows_tab.update_from_config()
        lane_widget = _lane_with_block(shows_tab)
        block_widget = lane_widget.get_all_block_widgets()[0]
        block_widget.block.colour_blocks = [
            ColourBlock(start_time=0.0, end_time=4.0, red=255)]

        shows_tab.selection_manager.select(block_widget)
        assert _col_row_contents(shows_tab) == ["chip:#FF0000"]

    def test_col_row_placeholder_without_colour_blocks(self, shows_tab):
        shows_tab.update_from_config()
        lane_widget = _lane_with_block(shows_tab)
        block_widget = lane_widget.get_all_block_widgets()[0]
        block_widget.block.colour_blocks = []
        shows_tab.selection_manager.select(block_widget)
        assert _col_row_contents(shows_tab) == ["-"]

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
        assert shows_tab.inspector_rows.isHidden()

    def test_clearing_selection_returns_to_empty_state(self, shows_tab):
        shows_tab.update_from_config()
        lane_widget = _lane_with_block(shows_tab)
        shows_tab.selection_manager.select(lane_widget.get_all_block_widgets()[0])
        shows_tab.selection_manager.clear_selection()
        assert shows_tab.inspector_empty.text() == "NO BLOCK SELECTED"
        assert shows_tab.inspector_rows.isHidden()

    def test_no_overlap_function_chip_row(self, shows_tab):
        """Per-block overlap functions (XFADE/HTP/LTP/ADD and the
        mock's OVERLAP field row) do not exist in the data model -
        v1.7 roadmap work (plan "Deferred"). The inspector must not
        fake them, even with a block selected."""
        from PyQt6.QtWidgets import QLabel, QPushButton

        shows_tab.update_from_config()
        lane_widget = _lane_with_block(shows_tab)
        shows_tab.selection_manager.select(
            lane_widget.get_all_block_widgets()[0])

        buttons = {b.text().upper()
                   for b in shows_tab.block_inspector.findChildren(QPushButton)}
        assert not ({"XFADE", "HTP", "LTP", "ADD"} & buttons)
        labels = {l.text().upper()
                  for l in shows_tab.block_inspector.findChildren(QLabel)}
        assert "OVERLAP" not in labels
        assert not any("XFADE" in text for text in labels)


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
                     'QPushButton[role="segment"]',
                     'QPushButton[role="lane-chip"]',
                     'QWidget[role="card"]',
                     'QWidget[role="section-caption"]'):
            assert rule in qss, rule


class TestButtonCoherence:
    """Every toolbar/transport/pane button maps onto one coherent role
    system so there is no font/weight/color drift within a zone."""

    def test_toolbar_action_roles(self, shows_tab):
        # Add semantic -> success; the sole loud CTA -> cta-accent; every
        # other text action -> cta-outline (bordered display caps).
        assert shows_tab.add_lane_btn.property("role") == "success"
        assert shows_tab.autogen_btn.property("role") == "cta-accent"
        assert shows_tab.save_btn.property("role") == "cta-outline"
        assert shows_tab.inspector_btn.property("role") == "cta-outline"
        assert shows_tab.pane_popout_btn.property("role") == "cta-outline"

    def test_display_caps_actions_are_uppercase(self, shows_tab):
        # cta-accent / cta-outline text buttons carry display caps.
        assert shows_tab.autogen_btn.text() == "AUTOGEN"
        assert shows_tab.save_btn.text() == "SAVE"
        assert shows_tab.inspector_btn.text() == "INSPECTOR"

    def test_grid_snap_swing_chips_carry_their_theme_roles(self, shows_tab):
        # Grid cells are borderless segments inside the card group; SNAP
        # keeps the output-select chip role; SWING is a lane-chip dropdown.
        for chip in shows_tab.grid_chips.values():
            assert chip.property("role") == "segment"
        assert shows_tab.snap_chip.property("role") == "output-select"
        assert shows_tab.swing_btn.property("role") == "lane-chip"

    def test_transport_uses_function_colors(self, shows_tab):
        assert shows_tab.play_btn.property("role") == "success"
        assert shows_tab.stop_btn.property("role") == "destructive"

    def test_icon_only_chevrons_share_the_pane_icon_role(self, shows_tab):
        for btn in (shows_tab.pane_toggle_btn, shows_tab.pane_collapse_btn):
            assert btn.property("role") == "pane-icon"
            assert btn.text() == ""

    def test_lane_and_audio_chips_carry_chip_roles(self, shows_tab):
        from timeline.light_lane import LightLane
        shows_tab._add_lane_widget(LightLane("L1"))
        lane = shows_tab.lane_widgets[0]
        # Timeline v3 (stage T2): the header chips share the lane-chip
        # role (mono family + compact padding pinned in the theme).
        assert lane.mute_button.property("role") == "lane-chip"
        assert lane.solo_button.property("role") == "lane-chip"
        # + BLOCK is the lane's primary action: accent chip variant.
        assert lane.add_block_button.property("role") == "lane-chip-accent"
        assert lane.remove_button.property("role") == "destructive"
        assert shows_tab.audio_lane.mute_button.property("role") == \
            "output-select"
        assert shows_tab.audio_lane.load_button.property("role") == \
            "cta-outline"


class TestPreservedChrome:
    def test_existing_toolbar_widgets_survive(self, shows_tab):
        """gui.py drives these by attribute - pin their existence."""
        for name in ("show_combo", "add_lane_btn", "autogen_btn",
                     "inspector_btn", "zoom_slider", "zoom_label",
                     "save_btn", "play_btn", "stop_btn", "time_label",
                     "position_slider", "total_time_label",
                     "embedded_riff_panel", "embedded_visualizer",
                     "snap_chip", "swing_btn", "status_line",
                     "block_inspector"):
            assert getattr(shows_tab, name, None) is not None, name
        assert shows_tab.autogen_btn.property("role") == "cta-accent"

    def test_show_loads_and_zoom_still_works(self, shows_tab):
        shows_tab.update_from_config()
        # The song key lives in itemData now (display text is the
        # numbered setlist label); an unlisted-only config shows the
        # bare name.
        assert shows_tab.show_combo.currentData() == "Demo Show"
        assert shows_tab.show_combo.currentText() == "Demo Show"
        shows_tab.zoom_slider.setValue(200)
        assert shows_tab.zoom_label.text() == "2.0x"
        assert shows_tab.master_timeline.timeline_widget.zoom_factor == 2.0


def _separator_indices(combo):
    """Indices of QComboBox separator rows (non-selectable model items)."""
    from PyQt6.QtCore import Qt
    model = combo.model()
    return [i for i in range(combo.count())
            if not (model.flags(model.index(i, 0))
                    & Qt.ItemFlag.ItemIsSelectable)]


class TestSongSelector:
    """S3 (docs/setlist-plan.md): the toolbar SONG selector lists songs
    in SETLIST order with "NN · Name" display text (same format as the
    Structure rail cards); songs missing from the setlist follow after
    a separator, unnumbered. The display text is no longer the song
    key - the raw name travels as itemData (UserRole), so every read
    and write goes through data, never text."""

    def test_setlist_order_with_numbering_and_data(self, shows_tab):
        _add_setlist(shows_tab.config)
        shows_tab.update_from_config()
        combo = shows_tab.show_combo
        assert [combo.itemText(i) for i in range(3)] == [
            "01 · Schwarzes Gold", "02 · Neon Ruinen", "03 · Monsters"]
        assert [combo.itemData(i) for i in range(3)] == [
            "Schwarzes Gold", "Neon Ruinen", "Monsters"]

    def test_unlisted_songs_follow_after_a_separator(self, shows_tab):
        _add_setlist(shows_tab.config)
        shows_tab.update_from_config()
        combo = shows_tab.show_combo
        # 3 listed + separator + 2 unlisted (Demo Show, Zugabe; sorted).
        assert combo.count() == 6
        assert _separator_indices(combo) == [3]
        assert [combo.itemText(i) for i in (4, 5)] == ["Demo Show", "Zugabe"]
        assert [combo.itemData(i) for i in (4, 5)] == ["Demo Show", "Zugabe"]

    def test_no_separator_without_setlist_entries(self, shows_tab):
        # The fixture config carries only the unlisted "Demo Show".
        shows_tab.update_from_config()
        combo = shows_tab.show_combo
        assert combo.count() == 1
        assert combo.itemText(0) == "Demo Show"
        assert _separator_indices(combo) == []

    def test_no_separator_when_every_song_is_listed(self, shows_tab):
        from config.models import SetlistEntry
        _add_setlist(shows_tab.config)
        shows_tab.config.setlist.entries += [
            SetlistEntry(song="Zugabe"), SetlistEntry(song="Demo Show")]
        shows_tab.update_from_config()
        combo = shows_tab.show_combo
        assert combo.count() == 5
        assert _separator_indices(combo) == []
        assert combo.itemText(4) == "05 · Demo Show"

    def test_switching_via_the_combo_loads_by_data(self, shows_tab):
        _add_setlist(shows_tab.config)
        shows_tab.update_from_config()
        assert shows_tab.current_song_name == "Schwarzes Gold"  # entry 01
        shows_tab.show_combo.setCurrentIndex(2)  # "03 · Monsters"
        assert shows_tab.current_song_name == "Monsters"

    def test_repopulate_preserves_selection_by_data(self, shows_tab):
        _add_setlist(shows_tab.config)
        shows_tab.update_from_config()
        combo = shows_tab.show_combo
        combo.setCurrentIndex(combo.findData("Monsters"))
        assert shows_tab.current_song_name == "Monsters"

        # Structure-tab reorder: Monsters moves to the front. The usual
        # config rebind must renumber AND keep the selected song.
        entries = shows_tab.config.setlist.entries
        entries.insert(0, entries.pop(2))
        shows_tab.update_from_config()
        assert combo.currentData() == "Monsters"
        assert combo.currentText() == "01 · Monsters"
        assert shows_tab.current_song_name == "Monsters"

    def test_tab_activation_refreshes_numbering_without_reload(
            self, shows_tab):
        """A setlist reorder does not dirty the timeline config; plain
        tab activation still refreshes the selector's order/numbering,
        keeping the selection by data."""
        _add_setlist(shows_tab.config)
        shows_tab.update_from_config()
        combo = shows_tab.show_combo
        combo.setCurrentIndex(combo.findData("Neon Ruinen"))
        assert combo.currentText() == "02 · Neon Ruinen"

        entries = shows_tab.config.setlist.entries
        entries.insert(0, entries.pop(1))  # Neon Ruinen first
        assert not shows_tab._config_dirty
        shows_tab.on_tab_activated()
        assert combo.currentText() == "01 · Neon Ruinen"
        assert combo.currentData() == "Neon Ruinen"
        assert shows_tab.current_song_name == "Neon Ruinen"

    def test_stale_selection_falls_back_to_the_first_entry(self, shows_tab):
        _add_setlist(shows_tab.config)
        shows_tab.update_from_config()
        combo = shows_tab.show_combo
        combo.setCurrentIndex(combo.findData("Zugabe"))
        del shows_tab.config.songs["Zugabe"]
        shows_tab.update_from_config()
        assert combo.currentData() == "Schwarzes Gold"
        assert combo.currentText() == "01 · Schwarzes Gold"
