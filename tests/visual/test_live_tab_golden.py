"""Golden screenshot for the Live tab (reference screen 09, layout 3b).

Pins the North Star 3b busking surface: the TOP SELECT row (one tile per
group with a data-color accent bar + ALL / ODD-EVEN / CLEAR SEL) and FADE
row (whose right end carries the OUT / SYNC engine-status chips - OUT
dormant grey here since no arbiter is wired, SYNC INT in the readout
treatment - then the tempo cluster), the CENTRE five-pool grid (COLOUR PALETTES painted in their actual
colours as square swatches in a 3-wide grid with the active one outlined,
then POSITION PALETTES - a PRESETS subsection with the five computed
geometry presets (CENTRE / AUDIENCE / CROSS / FAN OUT / CEILING) plus a
DRUMS preset for the placed drum-riser element, over a MARKS subsection
with one selectable cell per config.spots spike mark with a mono
coordinate tag; movers-only gated as a whole and enabled here because
the selected Movers group is type MH, the staged CROSS preset
accent-outlined - then the marked MOVEMENT placeholders, then INTENSITY
placeholders, then
the library-backed EFFECTS pool - riffs, selection-scoped, greyed with no
selection - and SCENES pool - whole-rig looks, always on - each with the
active item outlined in the accent), the PROGRAMMER state bar naming the
staged FX/SCENE/POS, the 330px RIGHT column
(the dual queue: an ACTIVE PLAYBACKS stack with one row per running
effect/scene, each with PAUSE + KILL; the NEXT UP list with the QUEUE
latch beside its caption, one row per queued item with a remove X, and
the GO cta underneath; then STROBE, STROBE KILL / HOLD LOOK / RELEASE
ALL) and the BOTTOM submaster bank: a GRAND master column (accent fader +
DBO) first, a divider, then a bounded fader per group in the group
colours, left-aligned.

The render is deterministic: two groups selected (one of them movers),
one colour active, the CROSS position preset staged, one effect and one
scene staged (so the running stack shows two rows), two items enqueued
in NEXT UP (one effect, one scene, GO enabled), a couple of submasters
at different levels, no output engine (UI shell only).

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
    Configuration, Fixture, FixtureGroup, FixtureMode, Spot, StageElement,
    Universe,
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
    """Reference-flavoured rig: five colored groups + three spike marks
    (the POSITION PALETTES pool renders one selectable cell per mark)."""
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
    spots = {
        "DS Centre": Spot(name="DS Centre", x=0.0, y=-2.5, z=0.0),
        "Drum Riser": Spot(name="Drum Riser", x=0.0, y=1.5, z=0.6),
        "SL Solo": Spot(name="SL Solo", x=-3.0, y=-1.0, z=0.0),
    }
    # A placed drum riser earns a computed DRUMS preset in the PRESETS
    # subsection (sixth cell after the five geometry presets).
    elements = [StageElement(kind="drum-riser", x=0.0, y=1.5,
                             width=2.0, depth=2.0, element_id="drums1")]
    return Configuration(
        fixtures=fixtures, groups=groups,
        universes={1: Universe(id=1, name="Universe 1", output={})},
        spots=spots, stage_elements=elements,
        stage_width=8.0, stage_height=6.0,
    )


def test_live_tab_golden(qapp, scene_config, tmp_path):
    """Live tab (reference screen 09), two groups selected, RED active."""
    from gui.theme_manager import ThemeManager
    from gui.tabs.live_tab import LiveTab

    ThemeManager().apply(qapp, "dark")

    tab = None
    try:
        tab = LiveTab(scene_config, parent=None)
        # Small library-backed pools so EFFECTS and SCENES render populated
        # + active. Built in-test (no disk scan) so the golden is stable.
        from riffs.riff_library import RiffLibrary
        from scenes.scene_library import SceneLibrary
        from config.models import Riff, Scene

        riff_lib = RiffLibrary(riffs_directory=str(tmp_path / "riffs"))
        riff_lib.riffs = {}
        riff_lib.by_category = {}
        for cat, name in (("drops", "Build Drop"), ("loops", "Four Floor"),
                          ("fills", "Snare Roll")):
            riff_lib.riffs[f"{cat}/{name}"] = Riff(name=name, category=cat)
        tab.set_effect_library(riff_lib)

        scene_lib = SceneLibrary(scenes_directory=str(tmp_path / "scenes"))
        for name, cat, color in (("Warm Wash", "looks", "#F0562E"),
                                  ("Cold Snap", "looks", "#4ECBD4"),
                                  ("Blackout Hit", "looks", "")):
            scene_lib.add_scene(Scene(name=name, category=cat, color=color),
                                category=cat)
        tab.set_scene_library(scene_lib)

        # Deterministic programmer state: two groups selected with a colour
        # applied, a couple of submasters at different levels, and the
        # grandmaster pulled down so the masters read distinctly.
        tab.state.toggle_group("Front Pars")
        tab.state.toggle_group("Movers")
        tab.state.stage_colour("red")
        tab.state.set_grandmaster(85)
        tab.state.set_submaster("Front Pars", 80)
        tab.state.set_submaster("Movers", 55)
        tab.state.set_strobe_rate(40)
        # Round-2 additions: a tapped tempo and the default LIVE mode, plus
        # one staged effect and one staged scene so both pools show active.
        tab.state.set_bpm(128)
        tab.state.set_mode("live")
        tab.state.set_effect("loops/Four Floor")
        tab.state.set_scene("looks/Warm Wash")
        # Round-3: stage the computed CROSS preset. The Movers group
        # (type MH) is selected, so the movers-only POSITION pool is
        # enabled and the staged preset cell renders accent-outlined
        # (the programmer bar reads "POS: CROSS").
        tab.state.set_position("preset:cross", "Cross")
        # Dual queue: the staged effect+scene render as running rows;
        # preload two NEXT UP items (one effect, one scene) so the queue
        # rows, the remove X and the enabled GO all pin.
        tab.state.enqueue("effect", "drops/Build Drop", "Build Drop")
        tab.state.enqueue("scene", "looks/Cold Snap", "Cold Snap")
        tab.setFixedSize(1600, 900)
        compare_to_golden(tab.grab().toImage(), "live_tab_dark")
    finally:
        if tab is not None:
            tab.deleteLater()
