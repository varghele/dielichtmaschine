# gui/progress_manager.py
# Progress indicator management for long-running operations

import sys
from PyQt6.QtWidgets import (QProgressDialog, QApplication, QProgressBar,
                              QLabel, QWidget, QHBoxLayout, QVBoxLayout, QDialog, QTextEdit)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class StatusBarProgress(QWidget):
    """Progress indicator widget for status bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self.label = QLabel()
        self.label.setStyleSheet("color: #888;")
        layout.addWidget(self.label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(150)
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #555;
                border-radius: 3px;
                background-color: #2d2d2d;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self.progress_bar)

        self.hide()

    def start(self, message: str, maximum: int = 0):
        """Start showing progress.

        Args:
            message: Status message to display
            maximum: Maximum value (0 for indeterminate)
        """
        self.label.setText(message)
        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(0)
        self.show()
        QApplication.processEvents()

    def update(self, value: int = None, message: str = None):
        """Update progress.

        Args:
            value: Current progress value (None to increment by 1)
            message: Optional new message
        """
        if message:
            self.label.setText(message)
        if value is not None:
            self.progress_bar.setValue(value)
        elif self.progress_bar.maximum() > 0:
            self.progress_bar.setValue(self.progress_bar.value() + 1)
        QApplication.processEvents()

    def finish(self):
        """Hide the progress indicator."""
        self.hide()
        self.label.setText("")
        self.progress_bar.setValue(0)


class ProgressManager:
    """
    Manages progress indicators throughout the application.

    Provides both status bar progress (non-blocking) and modal dialogs (blocking).
    """

    def __init__(self, main_window=None):
        """Initialize progress manager.

        Args:
            main_window: Main application window (for status bar access)
        """
        self.main_window = main_window
        self.status_progress = None
        self.modal_dialog = None

        # Set up status bar progress widget
        if main_window and hasattr(main_window, 'statusBar'):
            self.status_progress = StatusBarProgress()
            main_window.statusBar().addPermanentWidget(self.status_progress)

    def start_status(self, message: str, maximum: int = 0):
        """Start status bar progress indicator.

        Args:
            message: Status message
            maximum: Maximum value (0 for indeterminate/busy indicator)
        """
        if self.status_progress:
            self.status_progress.start(message, maximum)

    def finish_status(self):
        """Finish status bar progress."""
        if self.status_progress:
            self.status_progress.finish()

    def start_modal(self, title: str, message: str, maximum: int = 0,
                    cancelable: bool = False, parent=None) -> QProgressDialog:
        """Start a modal progress dialog.

        Args:
            title: Dialog title
            message: Progress message
            maximum: Maximum value (0 for indeterminate)
            cancelable: Whether user can cancel
            parent: Parent widget (defaults to main window)

        Returns:
            QProgressDialog instance for further control
        """
        parent = parent or self.main_window

        self.modal_dialog = QProgressDialog(message, "Cancel" if cancelable else None, 0, maximum, parent)
        self.modal_dialog.setWindowTitle(title)
        self.modal_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.modal_dialog.setAutoClose(True)
        self.modal_dialog.setAutoReset(True)
        self.modal_dialog.setMinimumWidth(350)
        self.modal_dialog.setMinimumHeight(100)

        # Style the dialog
        self.modal_dialog.setStyleSheet("""
            QProgressDialog {
                background-color: #3d3d3d;
            }
            QLabel {
                color: white;
                font-size: 12px;
            }
            QProgressBar {
                border: 1px solid #555;
                border-radius: 3px;
                background-color: #2d2d2d;
                text-align: center;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 2px;
            }
        """)

        # Force the dialog to show immediately (bypass minimumDuration timer)
        self.modal_dialog.setMinimumDuration(0)
        self.modal_dialog.setValue(0)
        self.modal_dialog.show()
        self.modal_dialog.raise_()  # Bring to front
        self.modal_dialog.activateWindow()  # Ensure it's the active window

        # Multiple event processing to ensure dialog is fully rendered
        QApplication.processEvents()
        QApplication.processEvents()
        QApplication.processEvents()

        return self.modal_dialog

    def update_modal(self, value: int = None, message: str = None):
        """Update modal progress dialog.

        Args:
            value: Current value
            message: Optional new message
        """
        if self.modal_dialog:
            if message:
                self.modal_dialog.setLabelText(message)
            if value is not None:
                self.modal_dialog.setValue(value)
            QApplication.processEvents()

    def finish_modal(self):
        """Close modal progress dialog."""
        if self.modal_dialog:
            self.modal_dialog.close()
            self.modal_dialog = None

    def start_modal_with_log(self, title: str, message: str, maximum: int = 0,
                             parent=None) -> 'ProgressDialogWithLog':
        """Start a modal progress dialog with a scrolling log area.

        Use start_log_capture()/stop_log_capture() to redirect stdout into
        the log automatically.

        Returns:
            ProgressDialogWithLog instance
        """
        parent = parent or self.main_window

        self.modal_dialog = ProgressDialogWithLog(title, message, maximum, parent)
        self.modal_dialog.show()
        self.modal_dialog.raise_()
        self.modal_dialog.activateWindow()

        QApplication.processEvents()
        QApplication.processEvents()

        return self.modal_dialog

    def start_log_capture(self):
        """Redirect stdout to the modal log area. Call stop_log_capture() to restore."""
        if self.modal_dialog and hasattr(self.modal_dialog, 'append_log'):
            self._original_stdout = sys.stdout
            sys.stdout = _LogWriter(self.modal_dialog)

    def stop_log_capture(self):
        """Restore stdout after log capture."""
        if hasattr(self, '_original_stdout') and self._original_stdout is not None:
            sys.stdout = self._original_stdout
            self._original_stdout = None


# Global progress manager instance (set by MainWindow)
_progress_manager: ProgressManager = None


def get_progress_manager() -> ProgressManager:
    """Get the global progress manager instance."""
    return _progress_manager


def set_progress_manager(manager: ProgressManager):
    """Set the global progress manager instance."""
    global _progress_manager
    _progress_manager = manager


class ProgressDialogWithLog(QDialog):
    """Modal progress dialog with a scrolling log area beneath the progress bar."""

    def __init__(self, title: str, message: str, maximum: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(500)
        self.setMinimumHeight(300)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Status label
        self._label = QLabel(message)
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setMaximum(maximum)
        self._progress.setValue(0)
        self._progress.setFixedHeight(22)
        layout.addWidget(self._progress)

        # Log area
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 9))
        self._log.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self._log, stretch=1)

        # Styling
        self.setStyleSheet("""
            QDialog { background-color: #3d3d3d; }
            QLabel { color: white; font-size: 12px; }
            QProgressBar {
                border: 1px solid #555; border-radius: 3px;
                background-color: #2d2d2d; text-align: center; color: white;
            }
            QProgressBar::chunk { background-color: #4CAF50; border-radius: 2px; }
            QTextEdit {
                background-color: #1e1e1e; color: #cccccc;
                border: 1px solid #555; border-radius: 3px;
            }
        """)

        self._line_count = 0

    # --- API matching QProgressDialog so ProgressManager methods work ---
    def setLabelText(self, text: str):
        self._label.setText(text)

    def setValue(self, value: int):
        self._progress.setValue(value)

    def wasCanceled(self) -> bool:
        return False

    def append_log(self, text: str):
        """Append text to the log area and auto-scroll."""
        self._log.append(text.rstrip())
        # Auto-scroll to bottom
        scrollbar = self._log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self._line_count += 1
        # Process events periodically so the UI stays responsive
        if self._line_count % 5 == 0:
            QApplication.processEvents()


class _LogWriter:
    """File-like object that redirects writes to a ProgressDialogWithLog."""

    def __init__(self, dialog: ProgressDialogWithLog):
        self._dialog = dialog
        self._buffer = ""

    def write(self, text: str):
        self._buffer += text
        while '\n' in self._buffer:
            line, self._buffer = self._buffer.split('\n', 1)
            if line.strip():  # Skip blank lines
                self._dialog.append_log(line)

    def flush(self):
        if self._buffer.strip():
            self._dialog.append_log(self._buffer)
            self._buffer = ""
