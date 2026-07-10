"""Golden screenshot for the Fixtures tab (reference screen 02).

Pins the rebuilt "Setup Fixtures" anatomy: slim action strip (conflict
chip + accent "+ ADD FIXTURE" CTA), the 280px GROUPS panel (color-coded
rows + dashed hint box), the display-styled read-only patch table
(# / FIXTURE / TYPE / MODE / UNI / ADDRESS / GROUP with low-alpha group
tints, colored group names, the " · "-joined multi-group membership
list elided to the GROUP column, red conflict cells), the AUTO-PATCH footer,
the inspector (capabilities + channel map + editors + Duplicate/Remove
footer) and the mono status strip.

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


def make_fixture(name, group, address, ftype="PAR", channels=8,
                 universe=1, x=0.0, y=0.0, groups=None):
    return Fixture(
        universe=universe, address=address,
        manufacturer="TestMfr", model="TestModel",
        name=name, group=group,
        groups=list(groups) if groups else [],
        current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=channels)],
        type=ftype, x=x, y=y,
    )


@pytest.fixture
def scene_config():
    """Deterministic reference-flavoured rig: amber pars, magenta
    movers, cyan wash, one DMX conflict, and one multi-group fixture
    (MHX-50 · R in Movers + Rear Wash + Front Pars) so the GROUP column
    pins the " · "-joined membership display AND its right-elision at
    the column width (the three names overflow the 150px column)."""
    fixtures = [
        make_fixture("LED PAR 64 · A", "Front Pars", 1, x=-2.0, y=-1.5),
        make_fixture("LED PAR 64 · B", "Front Pars", 5, x=-1.0, y=-1.5),  # conflict
        make_fixture("LED PAR 64 · C", "Front Pars", 17, x=1.0, y=-1.5),
        make_fixture("MHX-50 · L", "Movers", 33, ftype="MH", channels=16,
                     x=-2.5, y=1.0),
        make_fixture("MHX-50 · R", "Movers", 49, ftype="MH", channels=16,
                     x=2.5, y=1.0,
                     groups=["Movers", "Rear Wash", "Front Pars"]),
        make_fixture("TMH-X4 · 1", "Rear Wash", 1, ftype="WASH",
                     channels=14, universe=2, x=0.0, y=2.0),
    ]
    groups = {
        "Front Pars": FixtureGroup("Front Pars",
                                   fixtures[:3] + [fixtures[4]],
                                   color="#D9A441", lighting_role="wash"),
        "Movers": FixtureGroup("Movers", fixtures[3:5],
                               color="#C95FD0", lighting_role="accent"),
        "Rear Wash": FixtureGroup("Rear Wash", [fixtures[4], fixtures[5]],
                                  color="#4ECBD4", lighting_role="texture"),
    }
    return Configuration(
        fixtures=fixtures,
        groups=groups,
        universes={1: Universe(id=1, name="Universe 1", output={}),
                   2: Universe(id=2, name="Universe 2", output={})},
        stage_width=8.0,
        stage_height=6.0,
    )


def _seeded_definition():
    """Legacy definition dict for TestMfr/TestModel so the inspector's
    CAPABILITIES chips + CHANNEL MAP render in the golden (the selected
    LED PAR runs the 8-channel 'Standard' mode)."""
    names = ["Dimmer", "Strobe", "Red", "Green", "Blue", "White",
             "Amber", "UV"]
    presets = {
        "Dimmer": "IntensityMasterDimmer",
        "Strobe": "ShutterStrobeSlowFast",
        "Red": "IntensityRed", "Green": "IntensityGreen",
        "Blue": "IntensityBlue", "White": "IntensityWhite",
        "Amber": "IntensityAmber", "UV": "IntensityUV",
    }
    return {
        "manufacturer": "TestMfr",
        "model": "TestModel",
        "channels": [
            {"name": n, "preset": presets[n], "group": None,
             "capabilities": []}
            for n in names
        ],
        "modes": [{
            "name": "Standard",
            "channels": [{"number": i, "name": n}
                         for i, n in enumerate(names)],
        }],
    }


def test_fixtures_tab_golden(qapp, scene_config):
    """Fixtures tab (reference screen 02): groups panel + tinted table +
    conflict cells + inspector sections + status strip."""
    from gui.theme_manager import ThemeManager
    from gui.tabs.fixtures_tab import FixturesTab
    from utils.fixture_utils import _fixture_definitions_cache

    ThemeManager().apply(qapp, "dark")
    _fixture_definitions_cache["TestMfr_TestModel"] = _seeded_definition()
    tab = None
    try:
        tab = FixturesTab(scene_config, parent=None)
        tab.setFixedSize(1500, 560)
        compare_to_golden(tab.grab().toImage(), "fixtures_tab_dark")
    finally:
        _fixture_definitions_cache.pop("TestMfr_TestModel", None)
        if tab is not None:
            tab.deleteLater()
