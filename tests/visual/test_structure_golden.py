"""Golden screenshot for the Structure tab (North Star card 1e).

Pins the 1e anatomy: part cards with 3px top color bar + tint
(Intro red, Verse green - the mock_song_structure parts), the
transition chip between the cards, the dashed add tile, the micro
captions, the master grid with region bands below, and the part
inspector on the right. Regenerate after intended changes with

    QLC_REGEN_GOLDENS=1 pytest tests/visual/test_structure_golden.py
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import Configuration, Show, ShowPart, TimelineData
from tests.visual.harness import compare_to_golden


@pytest.fixture
def structure_config():
    """Deterministic show: the conftest mock_song_structure parts."""
    config = Configuration()
    config.shows["Demo"] = Show(
        name="Demo",
        parts=[
            ShowPart(name="Intro", color="#FF0000", signature="4/4",
                     bpm=120.0, num_bars=4, transition="instant"),
            ShowPart(name="Verse", color="#00FF00", signature="4/4",
                     bpm=140.0, num_bars=8, transition="instant"),
        ],
        effects=[],
        timeline_data=TimelineData(),
    )
    return config


def test_structure_tab_golden(qapp, structure_config):
    """Structure tab (North Star 1e): part cards + transition chip over
    the master grid, part inspector right, pause/playback rows below."""
    from gui.theme_manager import ThemeManager
    from gui.tabs.structure_tab import StructureTab

    ThemeManager().apply(qapp, "dark")
    with patch("utils.midi_utils.discover_midi_profiles", return_value=[]):
        tab = StructureTab(structure_config, parent=None)
    try:
        tab.update_from_config()
        tab.setFixedSize(1400, 700)
        compare_to_golden(tab.grab().toImage(), "structure_tab_dark")
    finally:
        tab.cleanup()
        tab.deleteLater()
