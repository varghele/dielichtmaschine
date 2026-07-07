"""Central QSettings access for Die Lichtmaschine.

Every persisted UI setting goes through :func:`app_settings` so the
organisation/application identity lives in exactly one place
(utils/app_identity.py). Direct ``QSettings("QLCShowCreator", ...)``
constructions are forbidden; the pre-rebrand store is reachable only via
the one-shot :func:`migrate_legacy_settings`.
"""

from PyQt6.QtCore import QSettings

from utils.app_identity import (
    LEGACY_SETTINGS_APP,
    LEGACY_SETTINGS_ORG,
    SETTINGS_APP,
    SETTINGS_ORG,
)

# NativeFormat in production; tests switch to IniFormat + QSettings.setPath
# so nothing touches the real registry / config dir.
_settings_format = QSettings.Format.NativeFormat

_MIGRATION_FLAG = "internal/migrated_from_qlcshowcreator"


def _make(org: str, app: str) -> QSettings:
    return QSettings(_settings_format, QSettings.Scope.UserScope, org, app)


def app_settings() -> QSettings:
    """The application's settings store (new brand identity)."""
    return _make(SETTINGS_ORG, SETTINGS_APP)


_RECENT_KEY = "recent/configs"
_RECENT_MAX = 8


def record_recent_config(path: str) -> None:
    """Remember a config file for the Home screen's recent list.

    Most-recent-first, deduplicated by absolute path, capped."""
    import os
    if not path:
        return
    path = os.path.abspath(path)
    settings = app_settings()
    current = settings.value(_RECENT_KEY, [], type=list) or []
    current = [p for p in current if p and os.path.abspath(p) != path]
    current.insert(0, path)
    settings.setValue(_RECENT_KEY, current[:_RECENT_MAX])


def recent_configs() -> list:
    """Recent config paths, most recent first, existing files only."""
    import os
    settings = app_settings()
    stored = settings.value(_RECENT_KEY, [], type=list) or []
    return [p for p in stored if p and os.path.isfile(p)]


def migrate_legacy_settings() -> int:
    """Copy settings from the QLCShowCreator store, once.

    Runs at startup. Copies every key the new store does not already
    have, then stamps a flag so subsequent launches skip the legacy
    store entirely (existing keys are never clobbered). Returns the
    number of keys copied.
    """
    new = app_settings()
    if new.value(_MIGRATION_FLAG, False, type=bool):
        return 0
    old = _make(LEGACY_SETTINGS_ORG, LEGACY_SETTINGS_APP)
    copied = 0
    for key in old.allKeys():
        if not new.contains(key):
            new.setValue(key, old.value(key))
            copied += 1
    new.setValue(_MIGRATION_FLAG, True)
    new.sync()
    return copied
