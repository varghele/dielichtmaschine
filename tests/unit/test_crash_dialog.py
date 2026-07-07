# tests/unit/test_crash_dialog.py
# Crash reporter dialog: builds offscreen from a real exception, shows
# the traceback and version, copies to the clipboard, and the
# install_crash_dialog() hook callable never raises.

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.dialogs import crash_dialog
from utils import app_identity


def _exc_info():
    try:
        raise ValueError("crash-dialog-test boom")
    except ValueError:
        return sys.exc_info()


@pytest.fixture
def dialog(qapp):
    exc_type, exc, tb = _exc_info()
    dlg = crash_dialog.CrashDialog(exc_type, exc, tb)
    yield dlg
    dlg.close()
    dlg.deleteLater()


def test_dialog_builds_and_shows_traceback(dialog):
    assert dialog.windowTitle() == "Unexpected error"
    text = dialog.traceback_view.toPlainText()
    assert "crash-dialog-test boom" in text
    assert "ValueError" in text
    assert "Traceback (most recent call last)" in text
    assert dialog.traceback_view.isReadOnly()


def test_dialog_shows_version_string(dialog):
    assert app_identity.version_string() in dialog.header_label.text()
    assert app_identity.version_string() in dialog.report_text()


def test_dialog_mentions_github_issue_and_logs(dialog):
    # The hint text and the log-folder button both exist.
    labels = [w.text() for w in dialog.findChildren(type(dialog.header_label))]
    assert any("GitHub issue" in text for text in labels)
    assert dialog.open_logs_button.text() == "Open log folder"


def test_copy_button_puts_traceback_on_clipboard(qapp, dialog):
    qapp.clipboard().clear()
    dialog.copy_button.click()
    clip = qapp.clipboard().text()
    assert "crash-dialog-test boom" in clip
    assert app_identity.version_string() in clip


def test_install_crash_dialog_shows_via_wrapper(qapp, monkeypatch):
    shown = []
    monkeypatch.setattr(crash_dialog, "_show_crash_dialog",
                        lambda *args: shown.append(args))
    handler = crash_dialog.install_crash_dialog()
    exc_type, exc, tb = _exc_info()
    handler(exc_type, exc, tb)
    assert shown == [(exc_type, exc, tb)]


def test_install_crash_dialog_skips_keyboard_interrupt(qapp, monkeypatch):
    shown = []
    monkeypatch.setattr(crash_dialog, "_show_crash_dialog",
                        lambda *args: shown.append(args))
    handler = crash_dialog.install_crash_dialog()
    handler(KeyboardInterrupt, KeyboardInterrupt(), None)
    handler(SystemExit, SystemExit(0), None)
    assert shown == []


def test_install_crash_dialog_never_raises(qapp, monkeypatch):
    def blow_up(*args):
        raise RuntimeError("dialog construction failed")

    monkeypatch.setattr(crash_dialog, "_show_crash_dialog", blow_up)
    handler = crash_dialog.install_crash_dialog()
    exc_type, exc, tb = _exc_info()
    # Must swallow the internal failure.
    handler(exc_type, exc, tb)


def test_show_wrapper_calls_exec(qapp, monkeypatch):
    calls = []

    def fake_exec(self):
        calls.append(self.traceback_view.toPlainText())
        return 0

    monkeypatch.setattr(crash_dialog.CrashDialog, "exec", fake_exec)
    exc_type, exc, tb = _exc_info()
    crash_dialog._show_crash_dialog(exc_type, exc, tb)
    assert len(calls) == 1
    assert "crash-dialog-test boom" in calls[0]
