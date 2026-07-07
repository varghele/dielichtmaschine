# tests/unit/test_app_logging.py
# Structured local logging: log_dir override, setup_logging idempotence,
# file output, and the exception hooks (logging + chaining + callback).

import logging
import os
import sys
import threading

import pytest

from utils import app_logging


def _read_log(log_directory):
    """Flush all root handlers and return the log file's content."""
    for handler in logging.getLogger().handlers:
        handler.flush()
    path = os.path.join(str(log_directory), app_logging.LOG_FILE_NAME)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _raise_and_capture():
    try:
        raise ValueError("app-logging-test boom")
    except ValueError:
        return sys.exc_info()


@pytest.fixture
def log_env(tmp_path, monkeypatch):
    """QLC_LOG_DIR pointed at tmp_path; hooks and handlers restored after.

    shutdown_logging() closes the file handler on teardown, otherwise
    Windows cannot delete the tmp directory while the file is open.
    """
    log_directory = tmp_path / "logs"
    monkeypatch.setenv(app_logging.LOG_DIR_ENV, str(log_directory))
    previous_excepthook = sys.excepthook
    previous_thread_hook = threading.excepthook
    yield log_directory
    app_logging.shutdown_logging()
    sys.excepthook = previous_excepthook
    threading.excepthook = previous_thread_hook


def test_log_dir_env_override(log_env):
    assert app_logging.log_dir() == str(log_env)


def test_setup_logging_creates_dir_and_file(log_env):
    path = app_logging.setup_logging()
    assert os.path.isdir(str(log_env))
    assert os.path.isfile(path)
    assert os.path.basename(path) == app_logging.LOG_FILE_NAME
    # The startup banner is written immediately.
    content = _read_log(log_env)
    from utils import app_identity
    assert app_identity.version_string() in content


def test_setup_logging_is_idempotent(log_env):
    first_path = app_logging.setup_logging()
    handlers_after_first = list(logging.getLogger().handlers)
    second_path = app_logging.setup_logging()
    handlers_after_second = list(logging.getLogger().handlers)
    assert second_path == first_path
    assert handlers_after_second == handlers_after_first


def test_logged_message_lands_in_file(log_env):
    app_logging.setup_logging()
    logging.getLogger("test.app_logging").info("hello from the test")
    assert "hello from the test" in _read_log(log_env)


def test_excepthook_logs_chains_and_calls_back(log_env):
    app_logging.setup_logging()

    previous_calls = []
    sys.excepthook = lambda *args: previous_calls.append(args)

    callback_calls = []
    app_logging.install_exception_hooks(
        on_exception=lambda *args: callback_calls.append(args))

    exc_type, exc, tb = _raise_and_capture()
    sys.excepthook(exc_type, exc, tb)

    content = _read_log(log_env)
    assert "app-logging-test boom" in content
    assert "Traceback (most recent call last)" in content
    assert "ValueError" in content

    # The previous hook was chained.
    assert previous_calls == [(exc_type, exc, tb)]
    # The on_exception callback received the exc info.
    assert callback_calls == [(exc_type, exc, tb)]


def test_excepthook_survives_failing_callback(log_env):
    app_logging.setup_logging()

    previous_calls = []
    sys.excepthook = lambda *args: previous_calls.append(args)

    def bad_callback(*args):
        raise RuntimeError("callback blew up")

    app_logging.install_exception_hooks(on_exception=bad_callback)
    exc_type, exc, tb = _raise_and_capture()
    # Must not raise even though the callback does.
    sys.excepthook(exc_type, exc, tb)
    assert previous_calls == [(exc_type, exc, tb)]
    assert "app-logging-test boom" in _read_log(log_env)


def test_thread_excepthook_logs(log_env):
    app_logging.setup_logging()
    app_logging.install_exception_hooks()

    def worker():
        raise ValueError("thread-test boom")

    thread = threading.Thread(target=worker, name="log-test-thread")
    thread.start()
    thread.join()

    content = _read_log(log_env)
    assert "thread-test boom" in content
    assert "log-test-thread" in content


def test_fallback_dir_when_log_dir_unwritable(log_env, tmp_path, monkeypatch):
    # Point QLC_LOG_DIR at a path that cannot be created (a file in the
    # way), and check setup_logging falls back to the tmp location.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    monkeypatch.setenv(app_logging.LOG_DIR_ENV,
                       str(blocker / "logs"))
    fallback = tmp_path / "fallback-logs"
    monkeypatch.setattr(app_logging, "_fallback_dir", lambda: str(fallback))
    path = app_logging.setup_logging()
    assert os.path.dirname(path) == str(fallback)
    assert os.path.isfile(path)
