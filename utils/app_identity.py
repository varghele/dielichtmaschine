"""Single source of truth for the product identity.

The product is Die Lichtmaschine (dielichtmaschine.de). Every user-visible
name, the QSettings organisation/application pair, and the brand asset
paths come from here so a future rename is one file again.

The legacy constants keep the pre-rebrand identity (QLC+ Show Creator)
around for the one-shot settings migration; nothing else may use them.
"""

import os

from _version import __version__
from utils.paths import get_project_root

# Display identity
APP_NAME = "Die Lichtmaschine"
APP_WORDMARK = "DIE LICHTMASCHINE"
APP_DOMAIN = "dielichtmaschine.de"
SLOGAN_DE = "ES WERDE LICHT"
SLOGAN_EN = "LET THERE BE LIGHT"

# Machine identity: QSettings keys, per-OS app-data directories.
# Deliberately space-free.
SETTINGS_ORG = "dielichtmaschine"
SETTINGS_APP = "Lichtmaschine"

# Pre-rebrand identity, used only by the settings migration.
LEGACY_SETTINGS_ORG = "QLCShowCreator"
LEGACY_SETTINGS_APP = "QLCShowCreator"

APP_VERSION = __version__


def version_string() -> str:
    """The one-line version string for --version and the About dialog."""
    return f"{APP_NAME} {APP_VERSION}"


def brand_dir() -> str:
    """Directory holding the brand assets (icons, banner, favicon)."""
    return os.path.join(get_project_root(), "resources", "brand")


def app_icon_path() -> str:
    """The window/taskbar icon (256px PNG; the .ico is for packaging)."""
    return os.path.join(brand_dir(), "icon-256.png")


def app_ico_path() -> str:
    """The multi-size Windows .ico used by PyInstaller."""
    return os.path.join(brand_dir(), "lichtmaschine.ico")


def brand_glyph_ring_path() -> str:
    """The hero rotor glyph WITH the thin outer registration ring
    (reference screen 01); the icon PNGs/favicon are the ring-less
    16px variant per the handoff."""
    return os.path.join(brand_dir(), "glyph-ring.svg")
