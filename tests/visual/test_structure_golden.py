"""Golden screenshot for the Structure tab (reference screen 05).

Pins the rebuilt anatomy: the 38px action strip (mono audio readout +
bordered "AUTOGENERATE SHOW..." CTA), the parts strip of 190px cards
with 3px top color bars, low-alpha tints, transition chips between them
and the dashed 44x44 add tile, the "MASTER GRID . N BARS . mm:ss"
caption over the master grid with its snap-hint row, the 400px
inspector (part name in the part color, 2x2 stat tiles, editors,
TRANSITION OUT, AUDIO ANALYSIS placeholders) and the mono status strip.

The show is the reference's five parts: grey INTRO, cyan VERSE 1,
accent-selected CHORUS 1, magenta DROP, grey OUTRO.

Regenerate after intended changes with

    QLC_REGEN_GOLDENS=1 pytest tests/visual/test_structure_golden.py

Goldens live under goldens/<platform>/ because the offscreen QPA has no
font database on Windows (fallback boxes); layout, geometry and colors
are what this pins, not glyph shapes.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import Configuration, Song, ShowPart, TimelineData
from tests.visual.harness import compare_to_golden

# Reference data colors: neutral grey, cyan, Glutorange accent, magenta.
GREY = "#8D9299"
CYAN = "#4ECBD4"
ACCENT = "#F0562E"
MAGENTA = "#C95FD0"


def part(name, color, bpm, bars, transition):
    return ShowPart(name=name, color=color, signature="4/4", bpm=bpm,
                    num_bars=bars, transition=transition)


@pytest.fixture
def structure_config():
    """The reference song: five parts of four different colors."""
    config = Configuration()
    config.songs["Demo"] = Song(
        name="Demo",
        parts=[
            part("Intro", GREY, 120.0, 8, "gradual"),
            part("Verse 1", CYAN, 126.0, 16, "gradual"),
            part("Chorus 1", ACCENT, 128.0, 8, "instant"),
            part("Drop", MAGENTA, 128.0, 8, "gradual"),
            part("Outro", GREY, 120.0, 8, "instant"),
        ],
        effects=[],
        timeline_data=TimelineData(),
    )
    return config


def test_structure_tab_golden(qapp, structure_config):
    """Structure tab (reference screen 05): action strip, part cards with
    transition chips over the master grid, 400px inspector, status strip."""
    from gui.theme_manager import ThemeManager
    from gui.tabs.structure_tab import StructureTab

    ThemeManager().apply(qapp, "dark")
    with patch("utils.midi_utils.discover_midi_profiles", return_value=[]):
        tab = StructureTab(structure_config, parent=None)
    try:
        tab.update_from_config()
        # Chorus 1 is the selected card (accent border + accent title),
        # matching the reference screen.
        tab._select_part(2)
        # The reference board's width: five 190px cards, four transition
        # chips and the add tile fit the strip without scrolling.
        tab.setFixedSize(1920, 900)
        compare_to_golden(tab.grab().toImage(), "structure_tab_dark")
    finally:
        tab.cleanup()
        tab.deleteLater()
