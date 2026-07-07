# tests/visual/conftest.py
"""Visual tests render in the state the shipped app runs in.

The app registers the brand fonts (gui/fonts.py) before any widget is
created, and a registered "Barlow" changes glyph metrics and therefore
pixels. Without this fixture the visual results depended on test
order: running tests/unit/test_branding.py first (which registers the
fonts into the session QApplication) made freshly regenerated goldens
fail in a full-suite run. Registration is idempotent, so forcing it
here makes every ordering equivalent - and pins the real brand look.
"""

import pytest


@pytest.fixture(scope="session", autouse=True)
def _brand_fonts(qapp):
    from gui.fonts import register_brand_fonts
    register_brand_fonts()
