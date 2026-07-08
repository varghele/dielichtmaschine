"""Golden screenshot for the screensaver / pause screen (reference 12).

Regenerate after intended changes with

    QLC_REGEN_GOLDENS=1 pytest tests/visual/test_screensaver_golden.py

and review the image. See tests/visual/harness.py for the tolerance and
the per-platform golden layout.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.visual.harness import compare_to_golden


def test_screensaver_golden(qapp):
    """The screensaver frame at the reference's own 1920x1080: 48px grid
    and corner registration marks on screensaver black, rotor glyph
    pinned at the pulse peak, wordmark + slogan, the PAUSE kicker over a
    pinned clock, and the honest default status bar.

    Rendered at the design size on purpose - the type sizes are design
    px, so only a 1080p frame shows the reference's proportions."""
    from gui.screens.screensaver import ScreensaverWindow
    from gui.theme_manager import ThemeManager

    # Pin the active theme like every other golden here: earlier tests
    # leave a stylesheet on the app, so without this the render depends
    # on test order (passes alone, fails after a themed test).
    ThemeManager().apply(qapp, "dark")
    window = ScreensaverWindow()
    try:
        window.set_animation_enabled(False)
        # Phase 2.0 = the center-dot pulse peak of the 4 s cosine, so
        # the pinned frame shows the brand dot at full Glutorange.
        window.set_phase(2.0)
        window.set_time_text("21:17")  # the reference's clock
        window.setFixedSize(1920, 1080)
        compare_to_golden(window.grab().toImage(), "screensaver_dark")
    finally:
        window.deleteLater()
