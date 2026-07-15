# gui/dialogs/movement_migration_dialog.py
"""Confirmation dialog for Tools > Convert Movement to World Targets...

Shows the FULL per-block report from utils/movement_migration.py
(song, lane, time range, resolved point or skip reason) BEFORE anything
changes; the config is only written after CONVERT. The apply itself
runs on the in-memory config - the user saves manually, so a reload
discards an unwanted conversion.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QHeaderView,
                             QLabel, QTableWidget, QTableWidgetItem,
                             QVBoxLayout)

from gui.typography import mono_font


class MovementMigrationDialog(QDialog):
    """Read-only report table + CONVERT / Cancel."""

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.entries = entries
        self.setWindowTitle("Convert Movement to World Targets")
        self.setMinimumSize(720, 420)

        layout = QVBoxLayout(self)

        converted = sum(1 for e in entries if e.status == "converted")
        skipped = len(entries) - converted
        if entries:
            summary = (f"{converted} movement block(s) get a world target"
                       f" · {skipped} skipped")
        else:
            summary = ("No movement blocks to convert - every block "
                       "already has a world target (or no song carries "
                       "movement).")
        self.summary_label = QLabel(summary)
        layout.addWidget(self.summary_label)

        hint = QLabel(
            "The centre beam of each block is traced onto the stage; the "
            "landing point becomes the block's world target. Pan/tilt "
            "values stay as fallback. Nothing changes until CONVERT; "
            "save the config to persist.")
        hint.setWordWrap(True)
        hint.setProperty("role", "stat-caption")
        layout.addWidget(hint)

        self.report_table = QTableWidget(len(entries), 4)
        self.report_table.setHorizontalHeaderLabels(
            ["SONG", "LANE", "RANGE", "RESULT"])
        self.report_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers)
        self.report_table.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection)
        self.report_table.verticalHeader().setVisible(False)
        self.report_table.setFont(mono_font(8))
        header = self.report_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for row, entry in enumerate(entries):
            for col, text in enumerate((entry.song, entry.lane,
                                        entry.time_range,
                                        entry.result_text())):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.report_table.setItem(row, col, item)
        layout.addWidget(self.report_table, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText("CONVERT")
        self.ok_button.setProperty("role", "primary")
        self.ok_button.setEnabled(converted > 0)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def run_movement_migration(config, parent=None, execute=None):
    """Plan -> confirm -> apply, in that order.

    Returns the number of blocks converted, or None when the user
    cancelled (in which case the config is untouched). ``execute`` lets
    tests drive the dialog without a modal exec() (qt-gotchas #7).
    """
    from utils.movement_migration import apply_migration, plan_migration

    entries = plan_migration(config)
    dialog = MovementMigrationDialog(entries, parent=parent)
    result = execute(dialog) if execute is not None else dialog.exec()
    if result != QDialog.DialogCode.Accepted:
        return None
    return apply_migration(config, entries)
