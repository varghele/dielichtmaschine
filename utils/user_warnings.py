"""Structured user-visible warnings (the v1.4 silent-fallback audit).

For years the failure modes a user actually cares about - a fixture
definition that would not parse, a lane skipped on export, a colour
channel that could not be found - went to ``print`` and scrolled away
in a terminal nobody has open in the packaged app. This module is the
one sink those paths report into instead:

- :func:`warn` records a :class:`WarningEntry` (message, category,
  the operation it happened under, a repeat count) and forwards it to
  the structured file log (utils/app_logging.py) so every report also
  lands on disk.
- :func:`operation` groups the warnings of one user action ("Export
  QLC+ workspace", "Load project") so the UI can answer "what went
  wrong during the last export?" - the Warnings panel
  (gui/dialogs/warnings_dialog.py) renders exactly that.
- ``once_key`` deduplicates hot paths (a failing ArtNet socket at
  44 Hz must not record 44 entries a second - it records one and
  counts repeats).

Qt-free on purpose: the export pipeline and the DMX stack run headless
(CLI export, tests). UI code subscribes via :func:`add_listener`.
"""

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

logger = logging.getLogger("user.warnings")

#: hard cap on retained entries; oldest fall off
MAX_ENTRIES = 500


@dataclass
class WarningEntry:
    message: str
    category: str = "general"
    operation: str = ""
    timestamp: float = 0.0
    count: int = 1  # repeats folded in via once_key
    run_id: int = 0  # which operation() invocation recorded it (0 = none)


class UserWarningsLog:
    """Thread-safe warning collector with operation grouping."""

    def __init__(self, clock=time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: list = []
        self._op_stack: list = []  # (name, run_id)
        self._last_op: tuple = ("", 0)  # (name, run_id)
        self._run_counter: int = 0
        self._once: dict = {}  # (run_id, once_key) -> WarningEntry
        self._listeners: list = []

    # -- recording --------------------------------------------------------

    def warn(self, message: str, category: str = "general",
             once_key: str = None) -> None:
        """Record one user-visible warning; also writes the file log."""
        with self._lock:
            operation, run_id = (self._op_stack[-1] if self._op_stack
                                 else ("", 0))
            if once_key is not None:
                folded = self._once.get((run_id, once_key))
                if folded is not None:
                    folded.count += 1
                    return
            entry = WarningEntry(message=message, category=category,
                                 operation=operation,
                                 timestamp=self._clock(),
                                 run_id=run_id)
            if once_key is not None:
                self._once[(run_id, once_key)] = entry
            self._entries.append(entry)
            del self._entries[:-MAX_ENTRIES]
            listeners = list(self._listeners)
        logger.warning("[%s] %s", category, message)
        for listener in listeners:
            try:
                listener(entry)
            except Exception:
                logger.exception("warning listener failed")

    @contextmanager
    def operation(self, name: str):
        """Group warnings under one user action. Every entry to this
        context is a fresh RUN: last_operation() reports only the
        newest run's entries, and once-keys start over."""
        with self._lock:
            self._run_counter += 1
            run = (name, self._run_counter)
            self._op_stack.append(run)
            self._last_op = run
        try:
            yield self
        finally:
            with self._lock:
                if run in self._op_stack:
                    self._op_stack.remove(run)

    # -- reading ----------------------------------------------------------

    def entries(self) -> list:
        with self._lock:
            return list(self._entries)

    def last_operation(self) -> tuple:
        """(operation name, [entries of its LATEST run]).

        ("", []) when no operation ever ran. Entries from earlier runs
        of the same operation name are excluded: a clean re-export
        reports clean.
        """
        with self._lock:
            name, run_id = self._last_op
            if not name:
                return "", []
            return name, [entry for entry in self._entries
                          if entry.run_id == run_id]

    def add_listener(self, callback) -> None:
        with self._lock:
            self._listeners.append(callback)

    def remove_listener(self, callback) -> None:
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._once.clear()
            self._last_op = ("", 0)


# -- module-level API (the one shared log) ------------------------------------

_log = UserWarningsLog()


def get_log() -> UserWarningsLog:
    return _log


def warn(message: str, category: str = "general",
         once_key: str = None) -> None:
    _log.warn(message, category=category, once_key=once_key)


def operation(name: str):
    return _log.operation(name)
