"""Golden screenshot for the Live tab (reference screen 09, layout 3b).

Pins the three-region busking surface: the 320px LEFT panel (one SELECT
tile per group with a data-color accent bar + a PROGRAMMER readout), the
CENTER palette grid (STATIC / STROBE / SPARKLE / WATERFALL / CIRCLE /
WHITE WASH with the active cell in the accent) over the engineering grid,
and the 340px RIGHT panel (MASTER fader, STROBE, FADE TIME, BLACKOUT,
SONG PALETTE strip).

The render is deterministic: two groups selected and one palette staged,
no output engine (this is a UI shell only).

Regenerate after intended changes:

    QLC_REGEN_GOLDENS=1 pytest tests/visual/test_live_tab_golden.py

Goldens live under goldens/<platform>/ because the offscreen QPA has no
font database on Windows; this pins layout, geometry and colors, not
glyph shapes.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import (
    Configuration, Fixture, FixtureGroup, FixtureMode, Universe,
)
from tests.visual.harness import compare_to_golden


def _fixture(name, group, address, ftype="PAR"):
    return Fixture(
        universe=1, address=address, manufacturer="TestMfr",
        model="TestModel", name=name, group=group, current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=8)],
        type=ftype)


@pytest.fixture
def scene_config():
    """Reference-flavoured rig: five colored groups."""
    rows = (
        ("Front Pars", "#D9A441", "PAR", 4),
        ("Rear Wash", "#4ECBD4", "WASH", 2),
        ("Movers", "#C95FD0", "MH", 6),
        ("Pixel Bar", "#6F9E4C", "PIXELBAR", 1),
        ("Sunstrip", "#8D9299", "SUNSTRIP", 1),
    )
    fixtures = []
    groups = {}
    address = 1
    for name, color, ftype, count in rows:
        members = []
        for i in range(count):
            members.append(_fixture(f"{name} {i + 1}", name, address, ftype))
            address += 10
        fixtures.extend(members)
        groups[name] = FixtureGroup(name, members, color=color)
    return Configuration(
        fixtures=fixtures, groups=groups,
        universes={1: Universe(id=1, name="Universe 1", output={})},
        stage_width=8.0, stage_height=6.0,
    )


def test_live_tab_golden(qapp, scene_config):
    """Live tab (reference screen 09), two groups selected, CIRCLE staged."""
    from gui.theme_manager import ThemeManager
    from gui.tabs.live_tab import LiveTab

    ThemeManager().apply(qapp, "dark")

    tab = None
    try:
        tab = LiveTab(scene_config, parent=None)
        # Deterministic programmer state: select two groups and stage a
        # palette so the active cell + PROGRAMMER readout render.
        tab.state.toggle_group("Front Pars")
        tab.state.toggle_group("Movers")
        tab.state.stage_palette("circle")
        tab.state.set_master(85)
        tab.state.set_strobe_rate(40)
        tab.setFixedSize(1600, 860)
        compare_to_golden(tab.grab().toImage(), "live_tab_dark")
    finally:
        if tab is not None:
            tab.deleteLater()
