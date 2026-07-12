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


# -- user fixture library directories ---------------------------------------
# Where the user's OWN fixture definitions live (ROADMAP v1.2
# "Configurable fixture library paths"): a GDTF directory and a .qxf
# directory, folded into utils/fixture_library.fixture_search_dirs()
# with priority user GDTF > project gdtf_fixtures/ > bundled
# custom_fixtures/ > user QXF > platform QLC+ dirs. The defaults sit in
# the per-user app-data dir - always writable, never the install dir -
# which is also where GDTF Share downloads will land (Phase 4).

_USER_GDTF_KEY = "library/user_gdtf_dir"
_USER_QXF_KEY = "library/user_qxf_dir"


def default_user_gdtf_dir() -> str:
    import os
    from utils.app_identity import user_data_dir
    return os.path.join(user_data_dir(), "fixtures", "gdtf")


def default_user_qxf_dir() -> str:
    import os
    from utils.app_identity import user_data_dir
    return os.path.join(user_data_dir(), "fixtures", "qxf")


def user_gdtf_dir() -> str:
    """The user's GDTF directory: the configured path, or the writable
    app-data default. May not exist yet; scanners skip missing dirs."""
    stored = app_settings().value(_USER_GDTF_KEY, "", type=str)
    return stored or default_user_gdtf_dir()


def user_qxf_dir() -> str:
    """The user's .qxf directory: the configured path, or the writable
    app-data default. May not exist yet; scanners skip missing dirs."""
    stored = app_settings().value(_USER_QXF_KEY, "", type=str)
    return stored or default_user_qxf_dir()


def set_user_gdtf_dir(path: str) -> None:
    """Persist the user GDTF directory ('' resets to the default) and
    invalidate the fixture-definition cache so the next lookup rescans."""
    _set_library_dir(_USER_GDTF_KEY, path)


def set_user_qxf_dir(path: str) -> None:
    """Persist the user .qxf directory ('' resets to the default) and
    invalidate the fixture-definition cache so the next lookup rescans."""
    _set_library_dir(_USER_QXF_KEY, path)


def _set_library_dir(key: str, path: str) -> None:
    settings = app_settings()
    if path:
        settings.setValue(key, path)
    else:
        settings.remove(key)
    settings.sync()
    # Deferred import: fixture_library must stay importable without Qt,
    # so it may not be imported here at module level either way round.
    from utils.fixture_library import clear_library_cache
    clear_library_cache()


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
