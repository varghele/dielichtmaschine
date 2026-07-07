"""Brand font registration.

Die Lichtmaschine ships its three brand families (all SIL OFL, licenses
next to the files in resources/fonts/):

- Barlow: UI and body text
- Barlow Condensed: display, headlines, tab labels (caps, tracked)
- IBM Plex Mono: numeric readouts, DMX/BPM values, micro-labels

``register_brand_fonts`` loads every ``.ttf`` in resources/fonts into the
application font database. Call it once after QApplication construction,
before any widget is created. Idempotent: Qt deduplicates re-added
application fonts by content, and the family constants below do not
depend on registration order.
"""

import os

from PyQt6.QtGui import QFontDatabase

from utils.paths import get_project_root

# Family names as they appear inside the shipped TTFs. Use these in QSS
# and QFont constructors; never hardcode the strings elsewhere.
FONT_UI = "Barlow"
FONT_DISPLAY = "Barlow Condensed"
FONT_MONO = "IBM Plex Mono"


def fonts_dir() -> str:
    return os.path.join(get_project_root(), "resources", "fonts")


def register_brand_fonts() -> list:
    """Load all shipped .ttf files. Returns the family names Qt reports.

    Missing directory or unloadable files degrade gracefully (Qt falls
    back to system fonts); the return value lets callers and tests see
    what actually registered.
    """
    families = []
    directory = fonts_dir()
    if not os.path.isdir(directory):
        print(f"fonts: directory not found: {directory}")
        return families
    for name in sorted(os.listdir(directory)):
        if not name.lower().endswith(".ttf"):
            continue
        path = os.path.join(directory, name)
        font_id = QFontDatabase.addApplicationFont(path)
        if font_id == -1:
            print(f"fonts: failed to load {path}")
            continue
        families.extend(QFontDatabase.applicationFontFamilies(font_id))
    return families
