# gui/dialogs/csv_import_wizard.py
"""File > Import Lighting Table (CSV): the column-mapping import wizard.

Three steps, all logic in utils/csv_table_import.py (pure, tested
headlessly) - this dialog is a thin shell:

1. Pick the file. Delimiter and header row are auto-detected (encoding
   tolerant: UTF-8, then cp1252/latin-1) with manual overrides; a raw
   preview shows the first rows as parsed.
2. Map columns. Each rig field picks the CSV column that feeds it,
   auto-guessed from the header names; NEXT stays disabled until
   manufacturer and model are mapped. A live preview shows the mapped
   result.
3. Preview the resolved rig. The mapped rows run through the same
   resolution pipeline as File > Import Fixture List (library lookup;
   synthesized modes upgraded to the real definition's mode list).
   Models the library misses are marked NO DEFINITION, never silently
   dropped; bad rows are listed. Replace/Add mirrors the fixture-list
   import.

The dialog never touches a Configuration: the caller (gui.py) applies
``result_fixtures()`` via utils/fixture_io.apply_fixture_list only
after the user confirms with IMPORT. Cancel anywhere = zero changes.
"""

import csv
import os

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt

from utils.csv_table_import import (
    FIELDS, REQUIRED_FIELDS, apply_mapping, build_fixtures, guess_mapping,
    resolve_fixtures, sniff_csv,
)

_DELIMITER_CHOICES = [
    ("Auto-detect", None),
    ("Comma (,)", ","),
    ("Semicolon (;)", ";"),
    ("Tab", "\t"),
]
_DELIMITER_NAMES = {",": "comma", ";": "semicolon", "\t": "tab"}

PREVIEW_ROWS = 20


class CsvImportWizard(QtWidgets.QDialog):
    """Modal three-step import wizard for foreign CSV lighting tables."""

    def __init__(self, existing_fixture_count: int = 0, start_dir: str = "",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Lighting Table (CSV)")
        self.setModal(True)
        self.setMinimumSize(780, 540)

        self._existing_fixture_count = existing_fixture_count
        self._start_dir = start_dir
        self._path = ""
        self._sniff = None
        self._updating = False           # guards programmatic control writes
        self._guessed_for = None         # header the auto-guess last ran on
        self._fixtures = []
        self._report = None
        self._row_errors = []

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)

        self._stack = QtWidgets.QStackedWidget()
        self._stack.addWidget(self._build_file_page())
        self._stack.addWidget(self._build_mapping_page())
        self._stack.addWidget(self._build_preview_page())
        layout.addWidget(self._stack, 1)

        row = QtWidgets.QHBoxLayout()
        self.back_btn = QtWidgets.QPushButton("Back")
        self.back_btn.clicked.connect(self._go_back)
        row.addWidget(self.back_btn)
        row.addStretch(1)
        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        row.addWidget(cancel_btn)
        self.next_btn = QtWidgets.QPushButton("Next")
        self.next_btn.setDefault(True)
        self.next_btn.clicked.connect(self._go_next)
        row.addWidget(self.next_btn)
        layout.addLayout(row)

        self._sync_buttons()

    # -- page 1: pick the file --------------------------------------------

    def _build_file_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setSpacing(8)

        intro = QtWidgets.QLabel(
            "Import fixtures from any spreadsheet saved as CSV - the venue's "
            "lighting table, a hire list, a patch sheet. The next step maps "
            "its columns onto the rig fields. Nothing is changed until you "
            "confirm on the last page.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        file_row = QtWidgets.QHBoxLayout()
        file_row.setSpacing(6)
        self.path_edit = QtWidgets.QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("Choose a .csv file...")
        browse = QtWidgets.QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        file_row.addWidget(self.path_edit, 1)
        file_row.addWidget(browse)
        layout.addLayout(file_row)

        options_row = QtWidgets.QHBoxLayout()
        options_row.setSpacing(12)
        options_row.addWidget(QtWidgets.QLabel("Delimiter:"))
        self.delimiter_combo = QtWidgets.QComboBox()
        for label, value in _DELIMITER_CHOICES:
            self.delimiter_combo.addItem(label, value)
        self.delimiter_combo.currentIndexChanged.connect(self._reparse)
        options_row.addWidget(self.delimiter_combo)
        self.header_check = QtWidgets.QCheckBox("First row is column headers")
        self.header_check.toggled.connect(self._reparse)
        options_row.addWidget(self.header_check)
        options_row.addStretch(1)
        self.detected_label = QtWidgets.QLabel("")
        options_row.addWidget(self.detected_label)
        layout.addLayout(options_row)

        self.raw_table = QtWidgets.QTableWidget()
        self.raw_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.raw_table.verticalHeader().setVisible(False)
        layout.addWidget(self.raw_table, 1)
        return page

    def _browse(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Import Lighting Table", self._start_dir,
            "CSV files (*.csv *.txt);;All files (*)")
        if path:
            self.set_source_file(path)

    def set_source_file(self, path: str) -> None:
        """Load + sniff a file (Browse and tests both land here)."""
        self._path = path
        self.path_edit.setText(path)
        # Fresh file, fresh detection: overrides belong to the old file.
        self._sniff = None
        self._updating = True
        try:
            self.delimiter_combo.setCurrentIndex(0)  # back to auto-detect
        finally:
            self._updating = False
        self._reparse()

    def _reparse(self) -> None:
        """(Re)sniff with the current manual overrides applied."""
        if self._updating or not self._path:
            return
        delimiter = self.delimiter_combo.currentData()
        # Only trust the checkbox once a sniff populated it; the very
        # first parse detects the header row itself.
        has_header = self.header_check.isChecked() if self._sniff else None
        try:
            self._sniff = sniff_csv(self._path, delimiter=delimiter,
                                    has_header=has_header)
        except (OSError, csv.Error) as exc:
            # csv.Error: not a delimited text file at all (binary
            # content, stray NULs, unquoted newlines).
            self._sniff = None
            self.raw_table.clear()
            self.raw_table.setRowCount(0)
            self.raw_table.setColumnCount(0)
            self.detected_label.setText("")
            QtWidgets.QMessageBox.warning(
                self, "Import Lighting Table",
                f"{os.path.basename(self._path)} could not be read as a "
                f"CSV text file.\n\nDetails: {exc}")
            self._sync_buttons()
            return
        self._updating = True
        try:
            self.header_check.setChecked(self._sniff.has_header)
        finally:
            self._updating = False
        self.detected_label.setText(
            f"Detected: {_DELIMITER_NAMES.get(self._sniff.delimiter, '?')}"
            f" · {self._sniff.encoding}"
            f" · {len(self._sniff.rows)} data row(s)")
        self._fill_raw_preview()
        self._sync_buttons()

    def _fill_raw_preview(self) -> None:
        sniff = self._sniff
        rows = sniff.raw_rows[:PREVIEW_ROWS]
        width = len(sniff.header)
        self.raw_table.clear()
        self.raw_table.setColumnCount(width)
        self.raw_table.setHorizontalHeaderLabels(sniff.header)
        self.raw_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c in range(width):
                value = row[c] if c < len(row) else ""
                self.raw_table.setItem(r, c, QtWidgets.QTableWidgetItem(value))

    # -- page 2: map the columns ------------------------------------------

    def _build_mapping_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setSpacing(8)

        intro = QtWidgets.QLabel(
            "Pick which CSV column feeds each rig field. Manufacturer and "
            "model are required (the library looks fixtures up by them); "
            "everything else is optional. Position becomes a stage layer.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QtWidgets.QFormLayout()
        form.setSpacing(6)
        self.field_combos = {}
        for key, label in FIELDS:
            combo = QtWidgets.QComboBox()
            combo.currentIndexChanged.connect(self._on_mapping_changed)
            self.field_combos[key] = combo
            if key in REQUIRED_FIELDS:
                label += " (required)"
            form.addRow(label, combo)
        layout.addLayout(form)

        layout.addWidget(QtWidgets.QLabel("Mapped preview:"))
        self.mapped_table = QtWidgets.QTableWidget()
        self.mapped_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.mapped_table.verticalHeader().setVisible(False)
        layout.addWidget(self.mapped_table, 1)
        return page

    def _enter_mapping_page(self) -> None:
        """Populate the combos for the current sniff; auto-guess only
        when the header changed (manual picks survive Back/Next)."""
        header = self._sniff.header
        key = tuple(header)
        self._updating = True
        try:
            previous = self.mapping() if self._guessed_for == key else None
            for combo in self.field_combos.values():
                combo.clear()
                combo.addItem("(none)", None)
                for i, name in enumerate(header):
                    combo.addItem(name, i)
            chosen = previous or guess_mapping(header)
            for fld, combo in self.field_combos.items():
                index = chosen.get(fld)
                combo.setCurrentIndex(0 if index is None else index + 1)
            self._guessed_for = key
        finally:
            self._updating = False
        self._on_mapping_changed()

    def mapping(self) -> dict:
        """field -> column index (or None), straight from the combos."""
        return {fld: combo.currentData()
                for fld, combo in self.field_combos.items()}

    def _on_mapping_changed(self) -> None:
        if self._updating:
            return
        self._fill_mapped_preview()
        self._sync_buttons()

    def _fill_mapped_preview(self) -> None:
        records = apply_mapping(self._sniff.rows[:PREVIEW_ROWS],
                                self.mapping())
        self.mapped_table.clear()
        self.mapped_table.setColumnCount(len(FIELDS))
        self.mapped_table.setHorizontalHeaderLabels(
            [label for _key, label in FIELDS])
        self.mapped_table.setRowCount(len(records))
        for r, record in enumerate(records):
            for c, (key, _label) in enumerate(FIELDS):
                self.mapped_table.setItem(
                    r, c, QtWidgets.QTableWidgetItem(record[key]))

    def _required_mapped(self) -> bool:
        mapping = self.mapping()
        return all(mapping.get(fld) is not None for fld in REQUIRED_FIELDS)

    # -- page 3: resolved preview + commit --------------------------------

    def _build_preview_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setSpacing(8)

        self.summary_label = QtWidgets.QLabel("")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.resolved_table = QtWidgets.QTableWidget()
        self.resolved_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.resolved_table.verticalHeader().setVisible(False)
        layout.addWidget(self.resolved_table, 1)

        self.errors_label = QtWidgets.QLabel("")
        self.errors_label.setWordWrap(True)
        layout.addWidget(self.errors_label)

        mode_box = QtWidgets.QGroupBox("Apply as")
        mode_layout = QtWidgets.QVBoxLayout(mode_box)
        self.add_radio = QtWidgets.QRadioButton("Add to the current rig")
        self.replace_radio = QtWidgets.QRadioButton(
            "Replace the current rig")
        self.add_radio.setChecked(True)
        mode_layout.addWidget(self.add_radio)
        mode_layout.addWidget(self.replace_radio)
        self._mode_box = mode_box
        layout.addWidget(mode_box)
        return page

    def _enter_preview_page(self) -> None:
        records = apply_mapping(self._sniff.rows, self.mapping())
        self._fixtures, self._row_errors = build_fixtures(records)
        self._report = resolve_fixtures(self._fixtures)

        missing = len(self._report.missing)
        parts = [f"{len(self._fixtures)} fixture(s) ready to import"]
        if missing:
            parts.append(
                f"{missing} model(s) not in the fixture library (marked "
                f"below; they import with the mode from the sheet)")
        if self._row_errors:
            parts.append(f"{len(self._row_errors)} row(s) skipped")
        self.summary_label.setText(" · ".join(parts) + ".")
        self.errors_label.setText(
            "\n".join(self._row_errors[:10])
            + ("\n..." if len(self._row_errors) > 10 else ""))
        self.errors_label.setVisible(bool(self._row_errors))

        headers = ["Name", "Manufacturer", "Model", "Mode", "Universe",
                   "Address", "Group", "Position", "Library"]
        self.resolved_table.clear()
        self.resolved_table.setColumnCount(len(headers))
        self.resolved_table.setHorizontalHeaderLabels(headers)
        self.resolved_table.setRowCount(len(self._fixtures))
        for r, fixture in enumerate(self._fixtures):
            resolved = self._report.is_resolved(fixture)
            values = [fixture.name, fixture.manufacturer, fixture.model,
                      fixture.current_mode, str(fixture.universe),
                      str(fixture.address), fixture.group, fixture.layer,
                      "OK" if resolved else "NO DEFINITION"]
            for c, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                if not resolved:
                    item.setForeground(Qt.GlobalColor.red)
                self.resolved_table.setItem(r, c, item)

        # Nothing to replace on an empty rig: Add covers it.
        has_rig = self._existing_fixture_count > 0
        self._mode_box.setVisible(has_rig)
        if not has_rig:
            self.add_radio.setChecked(True)
        self.add_radio.setText(
            f"Add to the current rig ({self._existing_fixture_count} "
            f"fixture(s))" if has_rig else "Add to the current rig")

    # -- navigation ---------------------------------------------------------

    def _go_next(self) -> None:
        index = self._stack.currentIndex()
        if index == 0:
            self._enter_mapping_page()
            self._stack.setCurrentIndex(1)
        elif index == 1:
            self._enter_preview_page()
            self._stack.setCurrentIndex(2)
        else:
            self.accept()
        self._sync_buttons()

    def _go_back(self) -> None:
        index = self._stack.currentIndex()
        if index > 0:
            self._stack.setCurrentIndex(index - 1)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        index = self._stack.currentIndex()
        self.back_btn.setEnabled(index > 0)
        if index == 0:
            self.next_btn.setText("Next")
            self.next_btn.setEnabled(
                self._sniff is not None and bool(self._sniff.rows))
        elif index == 1:
            self.next_btn.setText("Next")
            self.next_btn.setEnabled(self._required_mapped())
        else:
            self.next_btn.setText("Import")
            self.next_btn.setEnabled(bool(self._fixtures))

    # -- results (valid after accept) ---------------------------------------

    def result_fixtures(self) -> list:
        """The resolved Fixture objects the user confirmed."""
        return list(self._fixtures)

    def replace_rig(self) -> bool:
        """True = swap the whole rig, False = append (import default)."""
        return self.replace_radio.isChecked()

    def resolution_warnings(self) -> list:
        """Library-resolution warnings for the caller's summary box."""
        return list(self._report.warnings) if self._report else []

    def row_errors(self) -> list:
        """Rows that could not become fixtures (also shown on page 3)."""
        return list(self._row_errors)
