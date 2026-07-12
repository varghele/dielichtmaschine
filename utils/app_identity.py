"""Single source of truth for the product identity.

The product is Die Lichtmaschine (dielichtmaschine.de). Every user-visible
name, the QSettings organisation/application pair, and the brand asset
paths come from here so a future rename is one file again.

The legacy constants keep the pre-rebrand identity (QLC+ Show Creator)
around for the one-shot settings migration; nothing else may use them.
"""

import os
import sys

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


def user_data_dir() -> str:
    """The per-user, always-writable app-data directory, per OS.

    - Windows: %LOCALAPPDATA%/dielichtmaschine/Lichtmaschine
    - macOS: ~/Library/Application Support/dielichtmaschine/Lichtmaschine
    - Linux: $XDG_DATA_HOME or ~/.local/share/dielichtmaschine/Lichtmaschine

    Logs, user fixture libraries and future per-user state live under
    here - the packaged app must never depend on writing into its
    install directory. Not created here; each consumer creates its own
    subdirectory when it first writes.
    """
    home = os.path.expanduser("~")
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            home, "AppData", "Local")
    elif sys.platform == "darwin":
        base = os.path.join(home, "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(
            home, ".local", "share")
    return os.path.join(base, SETTINGS_ORG, SETTINGS_APP)


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
