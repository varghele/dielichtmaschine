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

# Project file format. The native extension is .lms (a Lichtmaschine
# project, as named in the design handoff); the on-disk format is plain
# YAML, so legacy .yaml/.yml projects load unchanged and can be re-saved
# as either. The extension is cosmetic - Configuration.load/save key off
# the path only, never the suffix.
PROJECT_EXT = ".lms"
PROJECT_EXTENSIONS = (".lms", ".yaml", ".yml")


def version_string() -> str:
    """The one-line version string for --version and the About dialog."""
    return f"{APP_NAME} {APP_VERSION}"


def rating_plate(version: str = None):
    """The machine's RATING PLATE (2026-07-20 banner decision): only
    verifiable claims - protocols, standards, formats, version, license,
    platforms - never adjectives. Each line is a list of
    (text, emphasis) segments; emphasis is "shipped" (capability on the
    wire today), "outstanding" (declared but not delivered yet) or
    "label" (neutral). Presentation maps emphasis to colours.

    ONE copy of the facts: consumed by scripts/render_brand_assets.py
    (README banner + social preview) and gui/dialogs/about_dialog.py.
    """
    version = version or APP_VERSION
    return [
        [("ARTNET", "shipped"), (" / E1.31 / DMX", "outstanding")],
        [("SYNC: ", "label"), ("LTC / SMPTE", "shipped"),
         (" / MTC / MIDI", "outstanding")],
        [("COMPATIBLE WITH: ", "label"),
         ("GDTF · DIN SPEC 15800 · QLC+", "shipped")],
        [(f"v{version} · GPL-3.0 · WINDOWS / LINUX", "label")],
    ]


def project_open_filter() -> str:
    """QFileDialog name-filter for opening a project.

    The native .lms and the legacy .yaml/.yml all match the first entry,
    so old projects stay visible without switching filters.
    """
    return (f"{APP_NAME} Project (*.lms *.yaml *.yml);;"
            "YAML Files (*.yaml *.yml);;"
            "All Files (*)")


def project_save_filter() -> str:
    """QFileDialog name-filter for saving a project.

    The native .lms leads (it is the default suffix); .yaml stays offered
    for interop and for users who prefer the plain extension.
    """
    return f"{APP_NAME} Project (*.lms);;YAML Files (*.yaml)"


def ensure_project_ext(path: str) -> str:
    """Give a save path the native .lms suffix when the user typed a bare
    name with no extension. An explicit suffix (.yaml, .lms, anything) is
    left exactly as chosen."""
    if path and not os.path.splitext(path)[1]:
        return path + PROJECT_EXT
    return path


def project_path_from_argv(argv) -> str | None:
    """The first non-flag argument in ``argv``, treated as a project to
    open on launch - a command-line path or a file the OS handed us from
    a .lms double-click. ``None`` when there is no positional argument."""
    for arg in argv:
        if arg and not arg.startswith("-"):
            return arg
    return None


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
