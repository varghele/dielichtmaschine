"""Crash-recovery autosave.

Reaper-style: while the user works, the current configuration is written
to a sidecar backup file every few seconds whenever it has unsaved
changes. A real save (Ctrl+S) writes the project file and clears the
backup. If the app crashed before a save, the next launch finds a backup
newer than the project file and offers to recover it.

The core (path resolution, recovery detection, the write/clear cycle) is
plain and testable; the periodic trigger is a QTimer wired in gui.py.
"""

import os
import sys
from typing import Callable, Optional

from utils import app_identity

AUTOSAVE_DIR_ENV = "QLC_AUTOSAVE_DIR"
BACKUP_SUFFIX = ".autosave"
UNTITLED_BACKUP = "untitled.autosave.yaml"


def autosave_dir() -> str:
    """Where backups for unsaved (never-saved) projects live, per OS.

    Saved projects back up to a sidecar next to the project file instead;
    this directory only holds the "untitled" backup. ``QLC_AUTOSAVE_DIR``
    overrides everything (tests).
    """
    override = os.environ.get(AUTOSAVE_DIR_ENV)
    if override:
        return override

    home = os.path.expanduser("~")
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            home, "AppData", "Local")
    elif sys.platform == "darwin":
        base = os.path.join(home, "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(
            home, ".local", "share")
    return os.path.join(base, app_identity.SETTINGS_ORG,
                        app_identity.SETTINGS_APP, "autosave")


def backup_path_for(config_path: Optional[str], fallback_dir: str) -> str:
    """The backup path for a project.

    A saved project ``/rigs/show.yaml`` backs up to
    ``/rigs/show.yaml.autosave`` (a sidecar, easy to find next to the
    project). An unsaved project has no path, so it backs up to
    ``<fallback_dir>/untitled.autosave.yaml``.
    """
    if config_path:
        return config_path + BACKUP_SUFFIX
    return os.path.join(fallback_dir, UNTITLED_BACKUP)


def find_recoverable(config_path: Optional[str],
                     fallback_dir: str) -> Optional[str]:
    """Return the backup path if it holds unsaved work worth recovering.

    That means the backup exists and, for a saved project, is newer than
    the project file (a save clears the backup, so a surviving newer
    backup means the app stopped before the last edits were saved).
    """
    backup = backup_path_for(config_path, fallback_dir)
    if not os.path.exists(backup):
        return None
    if config_path and os.path.exists(config_path):
        if os.path.getmtime(backup) <= os.path.getmtime(config_path):
            return None  # saved after the last autosave: nothing pending
    return backup


def write_snapshot(snapshot_bytes: bytes, path: str) -> None:
    """Serialize a pickled Configuration snapshot to ``path``.

    The performance half of the autosave (2026-07-16): the UI thread
    only pickles the config (~10 ms on a real project); THIS function -
    deserialize, YAML-dump, write - runs on a worker thread, so it must
    stay Qt-free. The write is atomic (temp file + replace) so a crash
    mid-write can never leave a torn recovery backup.
    """
    import pickle
    config = pickle.loads(snapshot_bytes)
    tmp = path + ".tmp"
    config.save(tmp)
    os.replace(tmp, path)


class AutosaveManager:
    """Owns the write/clear cycle. Change detection is a content
    fingerprint (not the undo stack, so it catches edits that never push
    an undo command). Kept free of QTimer so a test can drive it with an
    explicit ``maybe_backup()`` tick.

    ``fingerprint_fn`` returns any equality-comparable value that changes
    when the config content changes (e.g. a hash of ``config.to_dict()``).
    """

    def __init__(self, save_fn: Callable[[str], None],
                 fingerprint_fn: Callable[[], object],
                 current_path: Callable[[], Optional[str]],
                 fallback_dir: Optional[str] = None):
        self._save_fn = save_fn                # (path) -> write config to path
        self._fingerprint_fn = fingerprint_fn  # () -> content fingerprint
        self._current_path = current_path      # () -> project path or None
        self._fallback_dir = fallback_dir or autosave_dir()
        self._last_backup: Optional[str] = None
        # The content fingerprint that is already persisted (saved to the
        # project file, or freshly loaded). Backups are only written when
        # the live content differs from this.
        self._clean_fp: object = object()

    def backup_path(self) -> str:
        return backup_path_for(self._current_path(), self._fallback_dir)

    def prime(self) -> None:
        """Mark the current content as clean. Call after a load or new so a
        just-opened, unchanged project is not backed up on the next tick."""
        self._clean_fp = self._fingerprint_fn()

    def maybe_backup(self) -> Optional[str]:
        """Write a backup if the content changed since it was last
        persisted; return the path written, or None when unchanged or the
        write failed."""
        fingerprint = self._fingerprint_fn()
        if fingerprint == self._clean_fp:
            return None
        path = self.backup_path()
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            self._save_fn(path)
        except OSError:
            return None
        self._clean_fp = fingerprint
        self._last_backup = path
        return path

    def clear(self) -> None:
        """Delete the backup(s) and mark the current content clean. Call
        after a real save, so a later crash does not offer stale recovery
        and the next tick does not immediately re-backup unchanged work."""
        for path in {self.backup_path(), self._last_backup}:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        self._last_backup = None
        self._clean_fp = self._fingerprint_fn()
