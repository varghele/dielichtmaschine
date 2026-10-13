"""Golden screenshot for the branded About dialog (2026-07-21).

Pins the card anatomy: rotor glyph + DIE LICHTMASCHINE wordmark with
the accent slogan under it, the body paragraph, the rating plate
(shipped facts in full text colour, outstanding dimmed - the same
facts as the README banner via app_identity.rating_plate), the accent
domain link and the CLOSE chip.

NOTE: the plate carries the version string, so the golden changes on a
version bump - regenerate as part of the release ritual's brand-asset
step. Regenerate after intended changes with

    QLC_REGEN_GOLDENS=1 pytest tests/visual/test_about_dialog_golden.py

Goldens live under goldens/<platform>/; the bundled brand fonts are
registered by tests/visual/conftest.py, so glyphs are real.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.visual.harness import compare_to_golden


def test_about_dialog_golden(qapp):
    from PyQt6.QtWidgets import QApplication
    from gui.theme_manager import ThemeManager
    from gui.dialogs.about_dialog import AboutDialog

    ThemeManager().apply(qapp, "dark")
    dialog = AboutDialog(None)
    try:
        dialog.show()
        for _ in range(10):
            QApplication.processEvents()
        compare_to_golden(dialog.grab().toImage(), "about_dialog_dark")
    finally:
        dialog.close()
        dialog.deleteLater()
