"""Golden screenshots for the Shows tab chrome (North Star card 4a,
reference design_handoff_lichtmaschine_app/screens/06-show-timeline.html).

Pins the tab-level chrome owned by gui/tabs/shows_tab.py:

- ``shows_toolbar_dark``: SHOW caption + combo, lane/generate actions,
  the GRID subdivision chip row + SNAP chip (output-select chips),
  ZOOM, Save and the 3D-pane chevron.
- ``shows_transport_dark``: icon-only play/stop transport buttons on
  their function-color fills, the mono #TimeReadout carrying the
  reference's "BAR n.m · mm:ss.s", position slider and the secondary
  total-time readout.
- ``shows_footer_dark``: the mono status line (lanes / blocks / grid /
  zoom).
- ``shows_block_inspector_dark``: the right-pane EFFECT BLOCK inspector
  with a block selected (title, group-colored lane + bar range + length,
  DIM/COL/MOV/SPC stat tiles).

Deliberately grabs only the toolbar, transport bar, footer and
inspector widgets, not the timeline grid area - lane/master rendering
belongs to timeline_ui and has its own goldens.

ShowsTab hangs headlessly on the embedded-GL visualizer, so the GL
pane and riff panel are stubbed with plain widgets before construction
(same trick as tests/unit/test_shows_tab_chrome.py). Regenerate after
intended changes with QLC_REGEN_GOLDENS=1 and review the PNGs.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.visual.harness import compare_to_golden


def _stub_heavy_widgets(monkeypatch):
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


@pytest.fixture
def chrome_tab(qapp, monkeypatch, sample_configuration):
    """A ShowsTab with a loaded two-part show, rendered at 1420px so the
    toolbar / transport widgets are exactly 1400px wide (10px margins)."""
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QApplication
    from config.models import Song, ShowPart, TimelineData
    from gui.theme_manager import ThemeManager

    _stub_heavy_widgets(monkeypatch)
    ThemeManager().apply(qapp, "dark")

    sample_configuration.songs["Golden Show"] = Song(
        name="Golden Show",
        parts=[
            ShowPart(name="Intro", color="#FF0000", signature="4/4",
                     bpm=120.0, num_bars=4, transition="instant"),
            ShowPart(name="Verse", color="#00FF00", signature="4/4",
                     bpm=140.0, num_bars=8, transition="instant"),
        ],
        effects=[],
        timeline_data=TimelineData(),
    )

    from gui.tabs.shows_tab import ShowsTab
    tab = ShowsTab(sample_configuration, parent=None)
    tab.artnet_enabled = False
    tab.tcp_enabled = False
    tab.update_from_config()
    tab.resize(1420, 800)
    tab.show()
    # Pin the splitter sizes: the restored QSettings state is real user
    # (or earlier-test) state and can arrive with the right pane collapsed,
    # which grabs a 0x0 inspector.
    tab._main_splitter.setSizes([900, 520])
    tab._right_splitter.setSizes([290, 170, 430])
    for _ in range(5):
        QApplication.processEvents()
    try:
        yield tab
    finally:
        tab.hide()
        tab.cleanup()
        tab.deleteLater()
        # processEvents() does NOT flush DeferredDelete at this nesting
        # level, so without the explicit sendPostedEvents the torn-down
        # tabs pile up and the next ThemeManager.apply() walks
        # app.allWidgets() over half-dead widgets -> access violation.
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        QApplication.processEvents()


def test_shows_toolbar_golden(chrome_tab):
    """Toolbar chrome: micro-caps captions, grid chip row with the
    whole-beat chip checked, primary Auto-Generate/Save, pane chevron."""
    toolbar = chrome_tab.toolbar_widget
    assert toolbar.width() == 1400, "grab width drifted - golden invalid"
    compare_to_golden(toolbar.grab().toImage(), "shows_toolbar_dark")


def test_shows_transport_golden(chrome_tab):
    """Transport bar: icon play/stop on success/destructive fills, the
    green mono BAR/time readout, position slider, total-time readout."""
    bar = chrome_tab.transport_bar
    assert bar.width() == 1400, "grab width drifted - golden invalid"
    compare_to_golden(bar.grab().toImage(), "shows_transport_dark")


def test_shows_footer_golden(chrome_tab):
    """Footer status line: mono micro-caps lanes/blocks/grid/zoom."""
    footer = chrome_tab.status_footer
    assert footer.width() == 1400, "grab width drifted - golden invalid"
    compare_to_golden(footer.grab().toImage(), "shows_footer_dark")


def test_shows_block_inspector_golden(qapp, chrome_tab):
    """Right-pane block inspector with a single block selected."""
    from config.models import ColourBlock, DimmerBlock, LightBlock
    from timeline.light_lane import LightLane

    lane = LightLane("Front Pars")
    lane.fixture_targets = ["TestGroup"]
    block = LightBlock(start_time=0.0, end_time=6.0,
                       effect_name="bars.static", name="Chorus Hit")
    block.dimmer_blocks = [DimmerBlock(start_time=0.0, end_time=3.0)]
    block.colour_blocks = [ColourBlock(start_time=0.0, end_time=6.0)]
    lane.light_blocks = [block]
    chrome_tab._add_lane_widget(lane)

    lane_widget = chrome_tab.lane_widgets[-1]
    chrome_tab.selection_manager.select(lane_widget.get_all_block_widgets()[0])

    inspector = chrome_tab.block_inspector
    qapp.processEvents()
    assert (inspector.width(), inspector.height()) == (520, 170), \
        "inspector grab size drifted - golden invalid"
    compare_to_golden(inspector.grab().toImage(), "shows_block_inspector_dark")
