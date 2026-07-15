"""Stage tab chrome goldens (reference screen 04-setup-stage.html).

Pins the rebuilt Stage tab anatomy without touching the GL visualizer:
the 38px action strip (right-aligned segmented layer chips, MORPH,
EXPORT RIDER PDF), the 260px library panel (group rows, element +
truss tiles, dashed hint, collapsed STAGE SETTINGS) and the 448px
inspector (SELECTION card, X/Y/Z stat tiles, accent LAYER field,
LAYERS rows).

Same rules as test_golden_screenshots.py: offscreen, fixed sizes,
per-platform goldens, regenerate with QLC_REGEN_GOLDENS=1.
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
    """Deterministic config with three layers for a busy chip row."""
    fixtures = [
        make_fixture("PAR 1", "Front", 1, x=-2.0, y=-1.5, layer="Buehne"),
        make_fixture("PAR 2", "Front", 11, x=0.0, y=-1.5, layer="Buehne"),
        make_fixture("MH 1", "Movers", 101, ftype="MH", x=2.0, y=1.0,
                     layer="Flown"),
    ]
    groups = {
        "Front": FixtureGroup("Front", fixtures[:2], color="#D9A441"),
        "Movers": FixtureGroup("Movers", [fixtures[2]], color="#C95FD0"),
    }
    return Configuration(
        fixtures=fixtures,
        groups=groups,
        universes={1: Universe(id=1, name="Universe 1", output={})},
        stage_layers=[
            StageLayer(name="Buehne", z_height=0.8),
            StageLayer(name="Riser", z_height=1.2),
            StageLayer(name="Flown", z_height=4.0),
        ],
        stage_width=12.0,
        stage_height=6.0,
    )


@pytest.fixture
def clean_sections():
    """The library's collapse states persist to (session-shared)
    QSettings; the goldens must render the defaults regardless of what
    ran before them."""
    from utils.app_settings import app_settings
    app_settings().remove("stage/section")
    yield
    app_settings().remove("stage/section")


@pytest.fixture
def stage_tab(qapp, clean_sections, scene_config):
    from gui.theme_manager import ThemeManager
    from gui.tabs.stage_tab import StageTab

    ThemeManager().apply(qapp, "dark")
    tab = StageTab(scene_config, parent=None)
    tab.update_from_config()
    yield tab
    tab.deleteLater()


def test_stage_action_strip_golden(qapp, stage_tab):
    """Action strip with an active layer: right-aligned ACTIVE LAYER
    caption, segmented chip group (ALL + three layers, BUEHNE accent-
    FILLED, + LAYER, DEFINE...), the 25%/locked hint, disabled MORPH
    and the EXPORT RIDER PDF CTA."""
    stage_tab._set_active_layer("Buehne")
    strip = stage_tab.action_strip
    strip.setFixedSize(1180, 38)
    compare_to_golden(strip.grab().toImage(), "stage_action_strip_dark")


def test_stage_library_panel_golden(qapp, stage_tab):
    """Left library in its default state: the expanded STAGE SETTINGS
    section first (STAGE open - dimensions + grid + view combined -
    MARKS / LAYERS collapsed, no PLANES), then RIG · FIXTURES rows in
    group colors, the stage element and truss tile grids, the dashed
    truss hint - with PLOT STAGE / LAUNCH VISUALIZER pinned at the
    foot."""
    panel = stage_tab.control_panel
    panel.setFixedSize(260, 900)
    compare_to_golden(panel.grab().toImage(), "stage_library_panel_dark")


def test_stage_library_panel_collapsed_golden(qapp, stage_tab):
    """Every section collapsed: four header rows with the right-pointing
    chevron marker, and the pinned action foot still reachable."""
    for section in stage_tab.sections.values():
        section.set_expanded(False)
    panel = stage_tab.control_panel
    panel.setFixedSize(260, 900)
    compare_to_golden(panel.grab().toImage(),
                      "stage_library_panel_collapsed_dark")


def test_stage_inspector_golden(qapp, stage_tab):
    """Right inspector with a fixture selected: display-caps name, the
    group name in the group color, the X/Y/Z stat tiles, the accent
    LAYER field, the accent-left-border hint and the LAYERS rows."""
    from gui.tabs.stage_tab import RIGHT_COLUMN_WIDTH
    stage_tab.stage_view.fixtures["MH 1"].setSelected(True)
    panel = stage_tab.inspector_panel
    # Match the real inspector column width (RIGHT_COLUMN_WIDTH) and make
    # it tall enough for SELECTION + ORIENTATION + LAYERS without the
    # orientation scroll area squeezing the rows below it.
    panel.setFixedSize(RIGHT_COLUMN_WIDTH, 900)
    compare_to_golden(panel.grab().toImage(), "stage_inspector_dark")


def test_stage_plan_overlays_golden(qapp, stage_tab):
    """Plan overlay chrome: caption, active-layer badge, legend and the
    title block, pinned to the StageView's corners."""
    stage_tab._set_active_layer("Flown")
    view = stage_tab.stage_view
    view.setFixedSize(760, 460)
    view.show()
    qapp.processEvents()
    stage_tab._position_plan_overlays()
    qapp.processEvents()
    try:
        compare_to_golden(view.grab().toImage(), "stage_plan_overlays_dark")
    finally:
        view.hide()
