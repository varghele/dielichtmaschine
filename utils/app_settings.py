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
