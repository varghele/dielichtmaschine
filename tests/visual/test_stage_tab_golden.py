"""Stage tab North Star 5a chrome goldens.

Pins the new Stage tab anatomy (layer chip row above the canvas, quiet
left rail with micro captions, bottom action buttons) without touching
the GL visualizer. Same rules as test_golden_screenshots.py: offscreen,
fixed sizes, per-platform goldens, regenerate with QLC_REGEN_GOLDENS=1.
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
        "Front": FixtureGroup("Front", fixtures[:2], color="#cc6666"),
        "Movers": FixtureGroup("Movers", [fixtures[2]], color="#6688cc"),
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
def stage_tab(qapp, scene_config):
    from gui.theme_manager import ThemeManager
    from gui.tabs.stage_tab import StageTab

    ThemeManager().apply(qapp, "dark")
    tab = StageTab(scene_config, parent=None)
    tab.update_from_config()
    yield tab
    tab.deleteLater()


def test_stage_layer_bar_golden(qapp, stage_tab):
    """Chip row with an active layer: ALL, three layer chips (BUEHNE
    accented), + LAYER, and the 25%/locked hint on the right."""
    stage_tab._set_active_layer("Buehne")
    bar = stage_tab.layer_bar
    bar.setFixedSize(820, 44)
    compare_to_golden(bar.grab().toImage(), "stage_layer_bar_dark")


def test_stage_control_panel_golden(qapp, stage_tab):
    """Left rail: micro captions, mono dimension fields, layers card,
    planes list, PLOT STAGE / LAUNCH VISUALIZER at the bottom."""
    panel = stage_tab.control_panel
    panel.setFixedSize(250, 720)
    compare_to_golden(panel.grab().toImage(), "stage_control_panel_dark")
