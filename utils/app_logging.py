# utils/app_logging.py
"""Structured local logging for Die Lichtmaschine.

Provides three things:

- log_dir(): the per-OS application log directory (overridable via the
  QLC_LOG_DIR environment variable, which tests use).
- setup_logging(): idempotent root-logger configuration with a daily
  rotating file handler plus a WARNING-level console handler, a startup
  banner, and warnings-module capture.
- install_exception_hooks(): sys.excepthook / threading.excepthook /
  Qt message handler wiring so uncaught errors always land in the log
  file, with an optional on_exception callback (the crash dialog).
"""

import logging
import logging.handlers
import os
import platform
import sys
import tempfile
import threading
import traceback

from utils import app_identity

LOG_FILE_NAME = "lichtmaschine.log"
LOG_DIR_ENV = "QLC_LOG_DIR"
LOG_BACKUP_DAYS = 14

# Handlers installed by setup_logging(), kept so repeated calls are
# no-ops and so shutdown_logging() can cleanly close them (Windows
# cannot delete an open log file, which matters for tests).
_state = {"file_handler": None, "console_handler": None}


def log_dir() -> str:
    """The directory where log files live, per OS.

    - Windows: %LOCALAPPDATA%/dielichtmaschine/Lichtmaschine/logs
    - macOS: ~/Library/Application Support/dielichtmaschine/Lichtmaschine/logs
    - Linux: $XDG_DATA_HOME or ~/.local/share/dielichtmaschine/Lichtmaschine/logs

    The QLC_LOG_DIR environment variable overrides everything (tests).
    """
    override = os.environ.get(LOG_DIR_ENV)
    if override:
        return override
    return os.path.join(app_identity.user_data_dir(), "logs")


def _fallback_dir() -> str:
    """Last-resort log location when the app-data dir is not writable."""
    return os.path.join(tempfile.gettempdir(), "lichtmaschine-logs")


def _make_file_handler():
    """Create the rotating file handler, falling back to the tmp dir.

    Returns (handler, path). Raises only if even the tmp fallback fails.
    """
    for directory in (log_dir(), _fallback_dir()):
        try:
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, LOG_FILE_NAME)
            handler = logging.handlers.TimedRotatingFileHandler(
                path, when="midnight", backupCount=LOG_BACKUP_DAYS,
                encoding="utf-8")
            return handler, path
        except OSError:
            continue
    raise OSError("no writable log directory found")


def setup_logging() -> str:
    """Configure root logging. Idempotent. Returns the log file path.

    - TimedRotatingFileHandler at INFO, rotating daily, keeping
      LOG_BACKUP_DAYS days, UTF-8.
    - StreamHandler at WARNING so the console stays quiet-ish while
      existing print() output is untouched.
    - warnings-module output routed into logging.
    - A startup banner with version, Python/Qt versions and platform.
    """
    root = logging.getLogger()

    existing = _state["file_handler"]
    if existing is not None and existing in root.handlers:
        return existing.baseFilename

    file_handler, path = _make_file_handler()
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
    root.addHandler(file_handler)
    _state["file_handler"] = file_handler

    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(console)
    _state["console_handler"] = console

    # Root must pass INFO records for the file handler to see them.
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)

    logging.captureWarnings(True)

    _log_banner(path)
    return path


def _log_banner(path: str) -> None:
    log = logging.getLogger("app")
    log.info("%s starting", app_identity.version_string())
    log.info("Python %s on %s", sys.version.split()[0], platform.platform())
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
        log.info("Qt %s / PyQt %s", QT_VERSION_STR, PYQT_VERSION_STR)
    except Exception:
        log.info("Qt: not available")
    log.info("Log file: %s", path)


def shutdown_logging() -> None:
    """Remove and close the handlers setup_logging() installed.

    Mainly for tests: on Windows the tmp directory cannot be deleted
    while the log file handle is open.
    """
    root = logging.getLogger()
    for key in ("file_handler", "console_handler"):
        handler = _state[key]
        if handler is None:
            continue
        if handler in root.handlers:
            root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
        _state[key] = None
    logging.captureWarnings(False)


def install_exception_hooks(on_exception=None) -> None:
    """Route uncaught exceptions and Qt messages into logging.

    - Wraps sys.excepthook: logs the full traceback on logger "crash",
      calls on_exception(exc_type, exc, tb) if given (guarded), then
      chains to the previous hook.
    - Installs a threading.excepthook that logs uncaught thread
      exceptions (and chains to the previous one).
    - Installs a Qt message handler forwarding qDebug/qWarning/
      qCritical output into logging (logger "qt").
    """
    crash_logger = logging.getLogger("crash")

    previous_hook = sys.excepthook

    def _excepthook(exc_type, exc, tb):
        try:
            crash_logger.critical(
                "Uncaught exception:\n%s",
                "".join(traceback.format_exception(exc_type, exc, tb)))
        except Exception:
            pass
        if on_exception is not None:
            try:
                on_exception(exc_type, exc, tb)
            except Exception:
                try:
                    crash_logger.exception("Crash handler itself failed")
                except Exception:
                    pass
        if callable(previous_hook):
            try:
                previous_hook(exc_type, exc, tb)
            except Exception:
                pass

    sys.excepthook = _excepthook

    previous_thread_hook = threading.excepthook

    def _thread_excepthook(args):
        try:
            name = args.thread.name if args.thread is not None else "<unknown>"
            crash_logger.critical(
                "Uncaught exception in thread %r:\n%s", name,
                "".join(traceback.format_exception(
                    args.exc_type, args.exc_value, args.exc_traceback)))
        except Exception:
            pass
        if callable(previous_thread_hook):
            try:
                previous_thread_hook(args)
            except Exception:
                pass

    threading.excepthook = _thread_excepthook

    _install_qt_message_handler()


def _install_qt_message_handler() -> None:
    try:
        from PyQt6.QtCore import QtMsgType, qInstallMessageHandler
    except Exception:
        return

    qt_logger = logging.getLogger("qt")
    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def _qt_handler(msg_type, context, message):
        try:
            qt_logger.log(levels.get(msg_type, logging.WARNING), "%s", message)
        except Exception:
            pass

    qInstallMessageHandler(_qt_handler)
