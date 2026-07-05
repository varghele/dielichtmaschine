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


def test_fixtures_tab_golden(qapp, scene_config):
    """Fixtures table: group tinting + DMX-conflict red cells + toolbar."""
    from gui.theme_manager import ThemeManager
    from gui.tabs.fixtures_tab import FixturesTab

    ThemeManager().apply(qapp, "dark")
    tab = FixturesTab(scene_config, parent=None)
    try:
        tab.setFixedSize(1100, 320)
        compare_to_golden(tab.grab().toImage(), "fixtures_tab_dark")
    finally:
        tab.deleteLater()


def test_stage_layer_panel_golden(qapp, scene_config):
    """The Stage Layers group box: checkboxes, buttons, active-layer label."""
    from gui.theme_manager import ThemeManager
    from gui.tabs.stage_tab import StageTab

    ThemeManager().apply(qapp, "dark")
    tab = StageTab(scene_config, parent=None)
    try:
        tab.update_from_config()
        panel = tab.layer_list.parentWidget()  # the QGroupBox
        panel.setFixedSize(240, 200)
        compare_to_golden(panel.grab().toImage(), "stage_layer_panel_dark")
    finally:
        tab.deleteLater()
