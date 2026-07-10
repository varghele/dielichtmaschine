"""Golden screenshot for the Structure tab (reference screens 05 + 05b).

Pins the rebuilt anatomy: the 330px setlist rail on the left (header
with "SETLIST . DEMO TOUR" + "3 SONGS . 1 MIN", the SYNC segment row
with MIDI active, three numbered song cards with colour edges and mono
trigger lines - PC#5, NOTE C2, Follows automatically - dashed
pause-look rows between them, the open card's accent border + OPEN
tag, the dashed "+ SONG" tile and the wrapping mono footer hint), the
38px action strip, the parts strip of 190px cards with 3px top color
bars, transition chips and the dashed add tile, the master grid with
its snap-hint row, the 400px inspector and the mono status strip.

The open song is "Monsters" (first in the sorted combo, setlist entry
02) carrying the reference's five parts: grey INTRO, cyan VERSE 1,
accent-selected CHORUS 1, magenta DROP, grey OUTRO.

Regenerate after intended changes with

    QLC_REGEN_GOLDENS=1 pytest tests/visual/test_structure_golden.py

Goldens live under goldens/<platform>/; tests/visual/conftest.py
registers the brand fonts so the goldens pin real glyphs.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import (Configuration, Song, ShowPart, TimelineData,
                           Setlist, SetlistEntry, SongTrigger, PauseLook)
from tests.visual.harness import compare_to_golden

# Reference data colors: neutral grey, cyan, Glutorange accent, magenta.
GREY = "#8D9299"
CYAN = "#4ECBD4"
ACCENT = "#F0562E"
MAGENTA = "#C95FD0"


def part(name, color, bpm, bars, transition):
    return ShowPart(name=name, color=color, signature="4/4", bpm=bpm,
                    num_bars=bars, transition=transition)


def song(name, parts):
    return Song(name=name, parts=parts, effects=[],
                timeline_data=TimelineData())


@pytest.fixture
def structure_config():
    """Three songs in a setlist with mixed triggers and distinct pause
    looks; the open song (Monsters) is the reference's five parts."""
    config = Configuration()
    config.songs["Neon Ruinen"] = song("Neon Ruinen", [
        part("Intro", CYAN, 120.0, 8, "instant"),
        part("Verse", GREY, 120.0, 16, "instant"),
    ])
    config.songs["Monsters"] = song("Monsters", [
        part("Intro", GREY, 120.0, 8, "gradual"),
        part("Verse 1", CYAN, 126.0, 16, "gradual"),
        part("Chorus 1", ACCENT, 128.0, 8, "instant"),
        part("Drop", MAGENTA, 128.0, 8, "gradual"),
        part("Outro", GREY, 120.0, 8, "instant"),
    ])
    config.songs["Schwarzes Gold"] = song("Schwarzes Gold", [
        part("Intro", MAGENTA, 96.0, 8, "instant"),
    ])
    config.setlist = Setlist(
        name="Demo Tour",
        sync_mode="midi",
        entries=[
            SetlistEntry(
                song="Neon Ruinen",
                trigger=SongTrigger(mode="midi_pc", value=5, channel=1),
                pause_after=PauseLook(mode="warm_white", level=20,
                                      until="trigger")),
            SetlistEntry(
                song="Monsters",
                trigger=SongTrigger(mode="midi_note", value=36, channel=1),
                pause_after=PauseLook(mode="hold_last", until="trigger")),
            SetlistEntry(
                song="Schwarzes Gold",
                trigger=SongTrigger(mode="follow"),
                pause_after=PauseLook(mode="blackout", until="duration",
                                      duration_s=30.0)),
        ],
    )
    return config


def test_structure_tab_golden(qapp, structure_config):
    """Structure tab (reference screens 05/05b): setlist rail, action
    strip, part cards with transition chips over the master grid, 400px
    inspector, status strip."""
    from gui.theme_manager import ThemeManager
    from gui.tabs.structure_tab import StructureTab

    ThemeManager().apply(qapp, "dark")
    with patch("utils.midi_utils.discover_midi_profiles", return_value=[]):
        tab = StructureTab(structure_config, parent=None)
    try:
        tab.update_from_config()
        # The sorted combo opens Monsters (setlist entry 02): its rail
        # card carries the accent border + OPEN tag. Chorus 1 is the
        # selected part (accent border + accent title), matching the
        # reference screen.
        tab._select_part(2)
        # The reference board's width: five 190px cards, four transition
        # chips and the add tile fit the strip without scrolling.
        tab.setFixedSize(1920, 900)
        compare_to_golden(tab.grab().toImage(), "structure_tab_dark")
    finally:
        tab.cleanup()
        tab.deleteLater()
