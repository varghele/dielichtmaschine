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
    from utils.fixture_library import invalidate_fixture_caches
    invalidate_fixture_caches()


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


# -- audio output ------------------------------------------------------------
# Song playback (Shows and Structure tabs) goes through ONE pygame mixer
# (audio/simple_audio_player.shared_player). These are its persisted
# parameters, set in Settings > Audio Settings. output_device is an SDL
# playback device name; "" means the system default device.

_AUDIO_DEVICE_KEY = "audio/output_device"
_AUDIO_RATE_KEY = "audio/sample_rate"
_AUDIO_BUFFER_KEY = "audio/buffer_size"

AUDIO_SAMPLE_RATES = (44100, 48000, 96000)
AUDIO_DEFAULT_SAMPLE_RATE = 44100
AUDIO_DEFAULT_BUFFER_SIZE = 2048


def audio_output_settings() -> dict:
    """The stored audio output parameters, with defaults filled in.

    Returns a dict with ``output_device`` (str, "" = system default),
    ``sample_rate`` and ``buffer_size`` (ints). A stored sample rate the
    dialog does not offer falls back to the default."""
    settings = app_settings()
    device = settings.value(_AUDIO_DEVICE_KEY, "", type=str) or ""
    rate = settings.value(_AUDIO_RATE_KEY, AUDIO_DEFAULT_SAMPLE_RATE, type=int)
    if rate not in AUDIO_SAMPLE_RATES:
        rate = AUDIO_DEFAULT_SAMPLE_RATE
    buffer_size = settings.value(_AUDIO_BUFFER_KEY, AUDIO_DEFAULT_BUFFER_SIZE,
                                 type=int)
    if buffer_size <= 0:
        buffer_size = AUDIO_DEFAULT_BUFFER_SIZE
    return {"output_device": device, "sample_rate": rate,
            "buffer_size": buffer_size}


def set_audio_output_settings(output_device: str, sample_rate: int,
                              buffer_size: int) -> None:
    """Persist the audio output parameters ("" device = system default)."""
    settings = app_settings()
    if output_device:
        settings.setValue(_AUDIO_DEVICE_KEY, output_device)
    else:
        settings.remove(_AUDIO_DEVICE_KEY)
    settings.setValue(_AUDIO_RATE_KEY, int(sample_rate))
    settings.setValue(_AUDIO_BUFFER_KEY, int(buffer_size))
    settings.sync()
