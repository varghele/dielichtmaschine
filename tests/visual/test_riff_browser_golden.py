"""Golden screenshot for the riff browser panel (North Star item 3,
docs/timeline-styling-review.md).

Pins the rebranded panel: brand panel/raised surfaces, the accent
Glutorange selection on a highlighted category, and the token-derived
riff-item cards - no Windows-blue selection or Material-gray surfaces.

Offscreen Windows has no font database, so glyphs render as fallback
boxes; the golden is still meaningful for surfaces, borders and the
accent selection color (which is what this pass changed). Regenerate
with QLC_REGEN_GOLDENS=1 and review the PNG.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.visual.harness import compare_to_golden


@pytest.fixture
def riff_panel(qapp):
    from PyQt6.QtWidgets import QApplication
    from gui.theme_manager import ThemeManager
    from timeline_ui.riff_browser_widget import RiffBrowserPanel

    ThemeManager().apply(qapp, "dark")
    panel = RiffBrowserPanel()
    panel.resize(280, 460)
    panel.show()
    # Select the first category so the golden captures the accent
    # selection band (the row without an embedded item widget shows the
    # QTreeView selection color directly).
    if panel.tree.topLevelItemCount():
        panel.tree.setCurrentItem(panel.tree.topLevelItem(0))
    for _ in range(5):
        QApplication.processEvents()
    try:
        yield panel
    finally:
        panel.hide()
        panel.deleteLater()
        QApplication.processEvents()


def test_riff_browser_golden(riff_panel):
    assert (riff_panel.width(), riff_panel.height()) == (280, 460), (
        "grab size drifted - golden invalid"
    )
    compare_to_golden(riff_panel.grab().toImage(), "riff_browser_dark")


def test_riff_browser_scenes_golden(qapp):
    """The SCENES section of the library rail (timeline v3 stage T5):
    the category header, a scene row with the painted colour swatch +
    "N GROUPS" mono tag, a chip-less row, and - in a second panel - the
    empty-library marker (same copy as the Live tab). Scrolled to the
    bottom so the section is inside the grab."""
    from PyQt6.QtWidgets import QApplication
    from config.models import Scene
    from gui.theme_manager import ThemeManager
    from scenes.scene_library import SceneLibrary
    from timeline_ui.riff_browser_widget import RiffBrowserPanel

    ThemeManager().apply(qapp, "dark")
    library = SceneLibrary(scenes_directory="__no_such_scenes_dir__")
    library.add_scene(Scene(name="Drop Total", color="#F0562E",
                            groups=["Front", "Back", "Movers", "Blinders"]),
                      "general")
    library.add_scene(Scene(name="Warm Pause", groups=["Front"]),
                      "general")
    panel = RiffBrowserPanel(scene_library=library)
    panel.resize(280, 460)
    panel.show()
    panel.tree.scrollToBottom()
    for _ in range(5):
        QApplication.processEvents()
    try:
        assert (panel.width(), panel.height()) == (280, 460), (
            "grab size drifted - golden invalid"
        )
        compare_to_golden(panel.grab().toImage(), "riff_browser_scenes_dark")
    finally:
        panel.hide()
        panel.deleteLater()
        QApplication.processEvents()
