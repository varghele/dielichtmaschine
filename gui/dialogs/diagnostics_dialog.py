# gui/dialogs/diagnostics_dialog.py
"""Help > Diagnostics: the copyable bug-report block.

Renders utils/diagnostics.report() into a read-only mono text view with
one COPY button - the point is pasting the whole block into a GitHub
issue. Gathering runs on open (the GL probe spins up a context, ~100ms
worst case); every probe degrades to an error string, so the dialog
always opens. The mono family is pinned in a widget stylesheet because
the app-wide QSS font rule overrides plain setFont families (see
CLAUDE.md, screensaver gotcha).
"""

from PyQt6 import QtWidgets

from gui.fonts import FONT_MONO


class DiagnosticsDialog(QtWidgets.QDialog):
    """Modal diagnostics report viewer."""

    def __init__(self, main_window=None, parent=None, report_fn=None):
        super().__init__(parent)
        self.setWindowTitle("Diagnostics")
        self.setModal(True)
        self.resize(640, 520)

        if report_fn is None:
            from utils.diagnostics import report as report_fn_default
            report_fn = lambda: report_fn_default(main_window)
        try:
            text = report_fn()
        except Exception as exc:  # the report must never block the dialog
            text = f"diagnostics failed: {exc}"

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)

        intro = QtWidgets.QLabel(
            "Attach this block to a bug report (it contains no personal "
            "data beyond file paths).")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.text_view = QtWidgets.QPlainTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.setPlainText(text)
        self.text_view.setStyleSheet(
            f'font-family: "{FONT_MONO}"; font-size: 12px;')
        layout.addWidget(self.text_view, 1)

        bottom = QtWidgets.QHBoxLayout()
        self.copy_btn = QtWidgets.QPushButton("COPY TO CLIPBOARD")
        self.copy_btn.clicked.connect(self._copy)
        bottom.addWidget(self.copy_btn)
        self.copied_label = QtWidgets.QLabel("")
        bottom.addWidget(self.copied_label, 1)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

    def _copy(self):
        QtWidgets.QApplication.clipboard().setText(
            self.text_view.toPlainText())
        self.copied_label.setText("Copied.")
