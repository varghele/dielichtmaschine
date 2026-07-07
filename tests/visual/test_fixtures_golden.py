"""Golden screenshot for the Fixtures tab (North Star card 1c).

Moved out of test_golden_screenshots.py when the tab became the 1c
"Setup · Fixtures" layout: brand title row with the accent
"+ ADD FIXTURE" CTA, group-tinted patch table with tracked-mono
headers, DMX-conflict red cells + warning chip, mono status footer,
and the right-hand inspector showing the selected fixture (name,
provenance, universe/address/mode/group editors, position readout).

Regenerate after intended changes:

    QLC_REGEN_GOLDENS=1 pytest tests/visual/test_fixtures_golden.py

Goldens live under goldens/<platform>/ because the offscreen QPA has
no font database on Windows (fallback boxes); layout, geometry, and
colors are what this pins, not glyph shapes.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import (
    Configuration, Fixture, FixtureGroup, FixtureMode, Universe,
)
from tests.visual.harness import compare_to_golden


def make_fixture(name, group, address, ftype="PAR", x=0.0, y=0.0):
    return Fixture(
        universe=1, address=address,
        manufacturer="TestMfr", model="TestModel",
        name=name, group=group,
        current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
        type=ftype, x=x, y=y,
    )


@pytest.fixture
def scene_config():
    """Deterministic config: 2 groups, a DMX conflict, a mover."""
    fixtures = [
        make_fixture("PAR 1", "Front", 1, x=-2.0, y=-1.5),
        make_fixture("PAR 2", "Front", 5, x=0.0, y=-1.5),   # conflicts with PAR 1
        make_fixture("MH 1", "Movers", 101, ftype="MH", x=2.0, y=1.0),
    ]
    groups = {
        "Front": FixtureGroup("Front", fixtures[:2], color="#cc6666"),
        "Movers": FixtureGroup("Movers", [fixtures[2]], color="#6688cc"),
    }
    return Configuration(
        fixtures=fixtures,
        groups=groups,
        universes={1: Universe(id=1, name="Universe 1", output={})},
        stage_width=8.0,
        stage_height=6.0,
    )


def test_fixtures_tab_golden(qapp, scene_config):
    """Fixtures tab (card 1c): group tinting + DMX-conflict red cells +
    accent CTA toolbar + selected-row inspector."""
    from gui.theme_manager import ThemeManager
    from gui.tabs.fixtures_tab import FixturesTab

    ThemeManager().apply(qapp, "dark")
    tab = FixturesTab(scene_config, parent=None)
    try:
        tab.setFixedSize(1280, 420)
        compare_to_golden(tab.grab().toImage(), "fixtures_tab_dark")
    finally:
        tab.deleteLater()
