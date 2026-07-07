# gui/dialogs/crash_dialog.py
"""Crash reporter dialog shown for uncaught exceptions.

CrashDialog presents the traceback with copy/save actions and a
pointer to the log folder. install_crash_dialog() returns a callable
suitable as the on_exception argument of
utils.app_logging.install_exception_hooks(); it shows the dialog only
when a QApplication exists and never raises itself.
"""

import datetime
import traceback

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices, QFont, QFontDatabase
from PyQt6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout,
                             QLabel, QPlainTextEdit, QPushButton, QVBoxLayout)

from utils import app_identity
from utils.app_logging import log_dir


class CrashDialog(QDialog):
    """Modal error report for an uncaught exception."""

    def __init__(self, exc_type, exc, tb, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Unexpected error")
        self.setMinimumSize(640, 420)

        self._traceback_text = "".join(
            traceback.format_exception(exc_type, exc, tb))

        layout = QVBoxLayout(self)

        self.header_label = QLabel(
            f"{app_identity.version_string()} ran into an unexpected "
            "error. The application may be in an inconsistent state; "
            "please save your work and restart.")
        self.header_label.setWordWrap(True)
        layout.addWidget(self.header_label)

        self.traceback_view = QPlainTextEdit()
        self.traceback_view.setReadOnly(True)
        self.traceback_view.setPlainText(self._traceback_text)
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.traceback_view.setFont(QFont(mono))
        layout.addWidget(self.traceback_view, stretch=1)

        note = QLabel(
            "If this keeps happening, please attach this to a GitHub "
            "issue. The log folder contains details about what led up "
            "to the error.")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QHBoxLayout()
        self.copy_button = QPushButton("Copy to clipboard")
        self.copy_button.clicked.connect(self.copy_to_clipboard)
        buttons.addWidget(self.copy_button)

        self.save_button = QPushButton("Save as file...")
        self.save_button.clicked.connect(self.save_as_file)
        buttons.addWidget(self.save_button)

        self.open_logs_button = QPushButton("Open log folder")
        self.open_logs_button.clicked.connect(self.open_log_folder)
        buttons.addWidget(self.open_logs_button)

        buttons.addStretch(1)

        self.close_button = QPushButton("Close")
        self.close_button.setDefault(True)
        self.close_button.clicked.connect(self.accept)
        buttons.addWidget(self.close_button)

        layout.addLayout(buttons)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def report_text(self) -> str:
        """The full report: version line plus traceback."""
        return f"{app_identity.version_string()}\n\n{self._traceback_text}"

    def copy_to_clipboard(self):
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.report_text())

    def save_as_file(self):
        date = datetime.date.today().isoformat()
        default_name = f"lichtmaschine-crash-{date}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save crash report", default_name,
            "Text files (*.txt);;All files (*)")
        if path:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self.report_text())

    def open_log_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(log_dir()))


def _show_crash_dialog(exc_type, exc, tb) -> None:
    """Thin exec() wrapper, separate so tests can build without blocking."""
    dialog = CrashDialog(exc_type, exc, tb)
    dialog.exec()


def install_crash_dialog():
    """Return an on_exception callable for install_exception_hooks().

    The callable shows CrashDialog only when a QApplication instance
    exists, skips KeyboardInterrupt/SystemExit, and never raises: the
    excepthook must always survive so the traceback still reaches the
    log and the chained hook.
    """

    def _on_exception(exc_type, exc, tb):
        try:
            if isinstance(exc_type, type) and issubclass(
                    exc_type, (KeyboardInterrupt, SystemExit)):
                return
            if QApplication.instance() is None:
                return
            _show_crash_dialog(exc_type, exc, tb)
        except Exception:
            pass

    return _on_exception
