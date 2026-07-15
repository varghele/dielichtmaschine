# gui/dialogs/warnings_dialog.py
"""Help > Warnings: the structured warnings panel (v1.4 fallback audit).

Shows what utils/user_warnings collected - the last operation ("Export
QLC+ workspace", "Load project") called out on top with its entries,
the full recent history underneath, both newest-first. Everything is
also in the file log; this panel is the in-app answer to "what did the
last export leave out?". COPY puts a plain-text block on the clipboard
for bug reports.
"""

import time

from PyQt6 import QtWidgets

from gui.fonts import FONT_MONO
from utils import user_warnings


def _format_entry(entry) -> str:
    stamp = time.strftime("%H:%M:%S", time.localtime(entry.timestamp))
    repeat = f" (x{entry.count})" if entry.count > 1 else ""
    return f"[{stamp}] [{entry.category}] {entry.message}{repeat}"


def render_report(log=None) -> str:
    """The panel text: last operation first, then the full history."""
    log = log or user_warnings.get_log()
    op_name, op_entries = log.last_operation()
    lines = []
    if op_name:
        lines.append(f"LAST OPERATION · {op_name}")
        if op_entries:
            lines += [_format_entry(e) for e in reversed(op_entries)]
        else:
            lines.append("(no warnings)")
        lines.append("")
    entries = log.entries()
    lines.append(f"ALL RECENT WARNINGS ({len(entries)})")
    if entries:
        lines += [_format_entry(e) for e in reversed(entries)]
    else:
        lines.append("(none this session)")
    return "\n".join(lines)


class WarningsDialog(QtWidgets.QDialog):
    """Modal viewer over the shared user-warnings log."""

    def __init__(self, parent=None, log=None):
        super().__init__(parent)
        self.setWindowTitle("Warnings")
        self.setModal(True)
        self.resize(720, 480)
        self._log = log or user_warnings.get_log()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)

        intro = QtWidgets.QLabel(
            "Problems the app worked around instead of stopping - "
            "skipped lanes, unreadable fixture definitions, missing "
            "audio. Everything here is also in the log file "
            "(Help > Open Log Folder).")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.text_view = QtWidgets.QPlainTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.setStyleSheet(
            f'font-family: "{FONT_MONO}"; font-size: 12px;')
        layout.addWidget(self.text_view, 1)

        bottom = QtWidgets.QHBoxLayout()
        self.copy_btn = QtWidgets.QPushButton("COPY TO CLIPBOARD")
        self.copy_btn.clicked.connect(self._copy)
        bottom.addWidget(self.copy_btn)
        self.clear_btn = QtWidgets.QPushButton("CLEAR")
        self.clear_btn.clicked.connect(self._clear)
        bottom.addWidget(self.clear_btn)
        self.copied_label = QtWidgets.QLabel("")
        bottom.addWidget(self.copied_label, 1)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

        self.refresh()

    def refresh(self):
        self.text_view.setPlainText(render_report(self._log))

    def _copy(self):
        QtWidgets.QApplication.clipboard().setText(
            self.text_view.toPlainText())
        self.copied_label.setText("Copied.")

    def _clear(self):
        self._log.clear()
        self.copied_label.setText("Cleared.")
        self.refresh()
