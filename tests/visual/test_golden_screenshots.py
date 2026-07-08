"""Golden screenshot comparisons for deterministic renders.

Each scene renders offscreen at a fixed size and is compared against
``goldens/<platform>/<name>.png`` with a per-pixel tolerance (see
harness.compare_to_golden). Intended changes: regenerate with

    QLC_REGEN_GOLDENS=1 pytest tests/visual/test_golden_screenshots.py

review the image diff, and commit the new goldens.

Scenes deliberately avoid the GL visualizer (driver-dependent output)
and use fixed widget sizes. Goldens are per-platform because the
offscreen QPA's font rendering differs per OS — on Windows it draws
fallback boxes instead of glyphs, which is stable on one platform but
never comparable across platforms. Text *content* is therefore not what
these tests pin; layout, geometry, colors, and symbols are.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import (
    Configuration, Fixture, FixtureGroup, FixtureMode, StageLayer, Universe,
)
from tests.visual.harness import compare_to_golden


def make_fixture(name, group, address, ftype="PAR", x=0.0, y=0.0, layer=""):
    return Fixture(
        universe=1, address=address,
        manufacturer="TestMfr", model="TestModel",
        name=name, group=group,
        current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
        type=ftype, x=x, y=y, layer=layer,
    )


@pytest.fixture
def scene_config():
    """Deterministic config: 2 groups, a DMX conflict, layers, a mover."""
    fixtures = [
        make_fixture("PAR 1", "Front", 1, x=-2.0, y=-1.5),
        make_fixture("PAR 2", "Front", 5, x=0.0, y=-1.5),   # conflicts with PAR 1
        make_fixture("MH 1", "Movers", 101, ftype="MH", x=2.0, y=1.0,
                     layer="Top truss"),
    ]
    groups = {
        "Front": FixtureGroup("Front", fixtures[:2], color="#cc6666"),
        "Movers": FixtureGroup("Movers", [fixtures[2]], color="#6688cc"),
    }
    return Configuration(
        fixtures=fixtures,
        groups=groups,
        universes={1: Universe(id=1, name="Universe 1", output={})},
        stage_layers=[
            StageLayer(name="Ground", z_height=0.0),
            StageLayer(name="Top truss", z_height=5.0, visible=False),
        ],
        stage_width=8.0,
        stage_height=6.0,
    )


def test_stage_plot_golden(qapp, scene_config, tmp_path):
    """The whole printable plot: symbols, tint, labels, legend, scale."""
    from PyQt6.QtGui import QImage
    from gui.stage_plot import StagePlotRenderer

    path = str(tmp_path / "plot.png")
    StagePlotRenderer(scene_config, title="golden").render(path, paper="A4", dpi=100)
    compare_to_golden(QImage(path), "stage_plot_a4_100dpi")


def test_universes_tab_golden(qapp, scene_config):
    """Universes tab (reference screen 03): no title row, row cards with
    output chip, destination, channels-used bar and status dot; 420px
    inspector with display-caps heading, output-type chips, target/net/
    universe/rate fields, broadcast toggle and the info explainer; mono
    status strip."""
    from unittest.mock import patch
    from gui.theme_manager import ThemeManager
    from gui.tabs.configuration_tab import ConfigurationTab

    ThemeManager().apply(qapp, "dark")
    scene_config.universes[1].name = "Main rig"
    scene_config.universes[1].output = {
        "plugin": "ArtNet", "line": "0",
        "parameters": {"ip": "192.168.1.50", "subnet": "0", "universe": "0"},
    }
    with patch("gui.tabs.configuration_tab.get_device_display_names",
               return_value=["No Device"]):
        tab = ConfigurationTab(scene_config, parent=None)
    try:
        # Tall enough for the whole inspector stack; a squeezed grab
        # overlaps the output-type chips with the parameter form.
        tab.setFixedSize(1400, 620)
        compare_to_golden(tab.grab().toImage(), "universes_tab_dark")
    finally:
        tab.deleteLater()


# The Fixtures tab golden moved to tests/visual/test_fixtures_golden.py
# when the tab became the North Star 1c layout (table + inspector).


def _build_shell(qapp, theme):
    """Ui shell on a bare QMainWindow, themed, on SHOW > TIMELINE."""
    from PyQt6.QtWidgets import QMainWindow
    from gui.theme_manager import ThemeManager
    from gui.Ui_MainWindow import Ui_MainWindow

    ThemeManager().apply(qapp, theme)
    window = QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(window)
    ui.topbar.set_filename("demo_show.yaml")
    ui.tabWidget.setCurrentIndex(4)
    window.resize(1280, 200)
    ui.centralwidget.setFixedWidth(1280)
    return window, ui


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_topbar_golden(qapp, theme):
    """The shell topbar: wordmark, section nav with accent underline,
    icon buttons, filename, status chips (shell pass S2)."""
    window, ui = _build_shell(qapp, theme)
    try:
        compare_to_golden(ui.topbar.grab().toImage(), f"topbar_{theme}")
    finally:
        window.deleteLater()


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_subnav_golden(qapp, theme):
    """The subnav row for the SHOW section (STRUCTURE · TIMELINE)."""
    window, ui = _build_shell(qapp, theme)
    try:
        compare_to_golden(ui.subnav.grab().toImage(), f"subnav_{theme}")
    finally:
        window.deleteLater()


def test_home_screen_golden(qapp, tmp_path):
    """The Home landing page (reference screen 01): brand lockup with
    accent rule + slogan, NEW PROJECT / OPEN CTAs, recent rows with
    relative age, and the FROM ZERO TO SHOW checklist card."""
    from gui.theme_manager import ThemeManager
    from gui.widgets.home_screen import HomeScreen

    ThemeManager().apply(qapp, "dark")
    home = HomeScreen()
    try:
        paths = []
        for name in ("festival_mainstage.yaml", "club_band.yaml"):
            p = tmp_path / name
            p.write_text("x")  # real files so the age column renders
            paths.append(str(p))
        home.refresh(paths)
        home.refresh_checklist(scene_config_for_home())
        # Reference is a 1920 layout: 460 + 80 + 560 columns need width.
        home.setFixedSize(1440, 810)
        compare_to_golden(home.grab().toImage(), "home_dark")
    finally:
        home.deleteLater()


def scene_config_for_home():
    """A config two steps in: universes + fixtures done, placement not
    (all fixtures at origin), so the checklist shows 2/5 with step 03
    current, like the reference."""
    fixtures = [make_fixture("PAR 1", "Front", 1),
                make_fixture("PAR 2", "Front", 11)]
    return Configuration(
        fixtures=fixtures,
        groups={"Front": FixtureGroup("Front", fixtures, color="#cc6666")},
        universes={1: Universe(id=1, name="U1", output={})},
    )


def test_timeline_block_golden(qapp, scene_config):
    """Effect-block anatomy: group-color envelope frame + ~0.18 tint,
    hard corners, sublane blocks (slice N2)."""
    from config.models import ColourBlock, DimmerBlock, LightBlock
    from gui.theme_manager import ThemeManager
    from timeline.light_lane import LightLane
    from timeline_ui.light_lane_widget import LightLaneWidget

    ThemeManager().apply(qapp, "dark")
    lane = LightLane(name="Front lane", fixture_targets=["Front"])
    lane.light_blocks.append(LightBlock(
        start_time=0.0, end_time=4.0, effect_name="bars.static",
        dimmer_blocks=[DimmerBlock(start_time=0.0, end_time=2.0,
                                   intensity=200.0)],
        colour_blocks=[ColourBlock(start_time=0.0, end_time=1.5, red=204,
                                   green=40, blue=40),
                       ColourBlock(start_time=2.0, end_time=4.0, red=40,
                                   green=80, blue=204)],
    ))
    widget = LightLaneWidget(
        lane=lane, fixture_groups=list(scene_config.groups),
        config=scene_config)
    try:
        # The synthetic TestMfr/TestModel fixtures resolve no definition,
        # so capability detection yields all-False and no sublane would
        # paint. Pin the sublane layout explicitly instead.
        from config.models import FixtureGroupCapabilities
        widget.capabilities = FixtureGroupCapabilities(
            has_dimmer=True, has_colour=True,
            has_movement=False, has_special=False)
        widget.num_sublanes = 2
        widget.sublane_height = 64
        widget.timeline_widget.setFixedSize(480, 128)
        # Block widgets size themselves from the timeline at creation;
        # re-run after the fixed size so the envelope spans all sublanes.
        for block_widget in widget.light_block_widgets:
            block_widget.update_position()
        compare_to_golden(widget.timeline_widget.grab().toImage(),
                          "timeline_block_dark")
    finally:
        widget.deleteLater()


def test_master_timeline_golden(qapp, mock_song_structure):
    """Master timeline region bands (slice T2): 3px part-color top bar
    over a ~0.18-alpha tint, part name in condensed caps, grid lines
    and the red playhead on the themed background."""
    from gui.theme_manager import ThemeManager
    from timeline_ui.master_timeline_widget import MasterTimelineWidget

    ThemeManager().apply(qapp, "dark")
    widget = MasterTimelineWidget()
    try:
        # set_song_structure recomputes the minimum width, so pin the
        # size afterwards (setFixedSize overrides min and max).
        widget.set_song_structure(mock_song_structure)
        widget.setFixedSize(640, 60)
        widget.set_playhead_position(2.0)
        compare_to_golden(widget.grab().toImage(), "master_timeline_dark")
    finally:
        widget.deleteLater()


def test_stage_layer_panel_golden(qapp, scene_config):
    """The Stage Layers card: micro caption, checkboxes, buttons,
    active-layer label."""
    from gui.theme_manager import ThemeManager
    from gui.tabs.stage_tab import StageTab

    ThemeManager().apply(qapp, "dark")
    tab = StageTab(scene_config, parent=None)
    try:
        tab.update_from_config()
        panel = tab.layer_list.parentWidget()  # the role="card" layers panel
        panel.setFixedSize(240, 200)
        compare_to_golden(panel.grab().toImage(), "stage_layer_panel_dark")
    finally:
        tab.deleteLater()
