# tests/unit/test_csv_table_import.py
"""CSV lighting-table import (ROADMAP v1.4): the pure column-mapping
pipeline (utils/csv_table_import.py - sniffing, auto-guess, mapping,
fixture building, library resolution) and the three-step wizard shell
(gui/dialogs/csv_import_wizard.py) plus its topbar/File-menu entry
points. Resolution runs against the bundled custom_fixtures/ library
(hermetic via the session conftest); the wizard tests drive the pages
directly - exec() stays blocked by the no-modals fixture.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import Configuration
from utils.csv_table_import import (
    FIELDS, REQUIRED_FIELDS, apply_mapping, build_fixtures, detect_delimiter,
    guess_mapping, resolve_fixtures, sniff_csv,
)

# Ships in custom_fixtures/, trailing space and all (CLAUDE.md: model
# names are matched verbatim).
BUNDLED_MFR = "Stairville"
BUNDLED_MODEL = "Retro Flat Par 18x12W RGBW "


def write_csv(path, text, encoding="utf-8"):
    path.write_bytes(text.encode(encoding))
    return str(path)


# ---------------------------------------------------------------------------
# Sniffing
# ---------------------------------------------------------------------------

class TestSniff:
    def test_comma_utf8_with_header(self, tmp_path):
        path = write_csv(
            tmp_path / "rig.csv",
            "Manufacturer,Model,Universe,Address\n"
            "Stairville,LED Par,1,1\n"
            "Martin,MAC Aura,1,9\n")
        sniff = sniff_csv(path)
        assert sniff.delimiter == ","
        assert sniff.encoding == "utf-8-sig"
        assert sniff.has_header is True
        assert sniff.header == ["Manufacturer", "Model", "Universe", "Address"]
        assert len(sniff.rows) == 2
        assert sniff.rows[0][0] == "Stairville"
        assert len(sniff.raw_rows) == 3  # header + data, for the raw preview

    def test_semicolon_cp1252_umlauts(self, tmp_path):
        """A German venue sheet: Excel's Windows encoding, semicolons."""
        path = write_csv(
            tmp_path / "buehne.csv",
            "Hersteller;Model;Adresse;Group\n"
            "Stairville;LED Par;1;Bühne links\n"
            "Müller Licht;Würfel;9;Bühne rechts\n",
            encoding="cp1252")
        sniff = sniff_csv(path)
        assert sniff.delimiter == ";"
        assert sniff.encoding == "cp1252"
        assert sniff.has_header is True
        assert sniff.rows[0][3] == "Bühne links"
        assert sniff.rows[1][0] == "Müller Licht"

    def test_tab_delimited(self, tmp_path):
        path = write_csv(
            tmp_path / "rig.txt",
            "Manufacturer\tModel\tAddress\nStairville\tLED Par\t1\n")
        sniff = sniff_csv(path)
        assert sniff.delimiter == "\t"
        assert sniff.rows == [["Stairville", "LED Par", "1"]]

    def test_utf8_bom_is_eaten(self, tmp_path):
        path = write_csv(
            tmp_path / "rig.csv",
            "\ufeffManufacturer,Model\nStairville,LED Par\n")
        sniff = sniff_csv(path)
        assert sniff.header[0] == "Manufacturer"  # no BOM residue

    def test_headerless_file_detected_and_gets_column_names(self, tmp_path):
        path = write_csv(
            tmp_path / "rig.csv",
            "Stairville,LED Par,1,1\nMartin,MAC Aura,1,9\n")
        sniff = sniff_csv(path)
        assert sniff.has_header is False
        assert sniff.header == ["Column 1", "Column 2", "Column 3", "Column 4"]
        assert len(sniff.rows) == 2

    def test_manual_overrides_win(self, tmp_path):
        path = write_csv(
            tmp_path / "rig.csv",
            "Manufacturer,Model\nStairville,LED Par\n")
        sniff = sniff_csv(path, delimiter=";", has_header=False)
        assert sniff.delimiter == ";"
        assert sniff.has_header is False
        # One column per line under the wrong delimiter - still no crash.
        assert len(sniff.rows) == 2

    def test_single_column_file_falls_back_to_comma(self, tmp_path):
        path = write_csv(tmp_path / "one.csv", "Model\nLED Par\n")
        sniff = sniff_csv(path)
        assert sniff.delimiter == ","
        assert sniff.rows == [["LED Par"]]

    def test_ragged_rows_pad_the_header(self, tmp_path):
        path = write_csv(
            tmp_path / "ragged.csv",
            "Manufacturer,Model\nStairville,LED Par,1,extra\n")
        sniff = sniff_csv(path)
        assert sniff.header == ["Manufacturer", "Model", "Column 3",
                                "Column 4"]

    def test_blank_lines_are_dropped(self, tmp_path):
        path = write_csv(
            tmp_path / "rig.csv",
            "Manufacturer,Model\n\nStairville,LED Par\n\n")
        sniff = sniff_csv(path)
        assert len(sniff.rows) == 1

    def test_detect_delimiter_fallback_counts(self):
        # csv.Sniffer chokes on this; the counting fallback picks ';'.
        assert detect_delimiter("a;b;c\n") == ";"
        assert detect_delimiter("plain text no delimiters") == ","

    def test_binary_junk_raises_csv_error(self, tmp_path):
        """Not silently misread: a non-CSV file is a csv.Error the
        wizard turns into a warning box."""
        import csv as csv_mod
        path = tmp_path / "garbage.csv"
        path.write_bytes(bytes(range(256)) * 8)
        with pytest.raises(csv_mod.Error):
            sniff_csv(str(path))


# ---------------------------------------------------------------------------
# Auto-guess
# ---------------------------------------------------------------------------

class TestGuessMapping:
    def test_typical_venue_headers(self):
        header = ["Position", "Make", "Fixture Type", "Mode", "Univ",
                  "DMX Address", "Group", "Label"]
        mapping = guess_mapping(header)
        assert mapping["position"] == 0
        assert mapping["manufacturer"] == 1
        assert mapping["model"] == 2
        assert mapping["mode"] == 3
        assert mapping["universe"] == 4
        assert mapping["address"] == 5
        assert mapping["group"] == 6
        assert mapping["name"] == 7

    def test_model_column_not_claimed_by_mode(self):
        """'mode' is a substring of 'model'; exact match + claim order
        must keep both fields on their own columns."""
        mapping = guess_mapping(["Model", "Mode", "Manufacturer"])
        assert mapping["model"] == 0
        assert mapping["mode"] == 1
        assert mapping["manufacturer"] == 2

    def test_model_without_mode_leaves_mode_unmapped(self):
        mapping = guess_mapping(["Manufacturer", "Model", "Address"])
        assert mapping["model"] == 1
        assert mapping["mode"] is None

    def test_unknown_headers_map_nothing(self):
        mapping = guess_mapping(["Foo", "Bar"])
        assert all(v is None for v in mapping.values())
        assert set(mapping) == {key for key, _ in FIELDS}

    def test_case_insensitive_substring(self):
        mapping = guess_mapping(["LIGHT MANUFACTURER", "fixture model"])
        assert mapping["manufacturer"] == 0
        assert mapping["model"] == 1


# ---------------------------------------------------------------------------
# Mapping application + fixture building
# ---------------------------------------------------------------------------

class TestApplyMapping:
    def test_projection_and_none_fields(self):
        rows = [["Stairville", " LED Par ", "3"]]
        mapping = {"manufacturer": 0, "model": 1, "address": 2,
                   "mode": None, "universe": None, "group": None,
                   "position": None, "name": None}
        records = apply_mapping(rows, mapping)
        assert records == [{
            "manufacturer": "Stairville", "model": " LED Par ",
            "address": "3", "mode": "", "universe": "", "group": "",
            "position": "", "name": "",
        }]

    def test_manufacturer_model_kept_verbatim(self):
        """Trailing spaces matter: library lookup matches exactly."""
        records = apply_mapping(
            [[BUNDLED_MFR, BUNDLED_MODEL]],
            {"manufacturer": 0, "model": 1})
        assert records[0]["model"] == BUNDLED_MODEL

    def test_short_rows_read_as_empty(self):
        records = apply_mapping([["OnlyMfr"]], {"manufacturer": 0, "model": 1})
        assert records[0]["model"] == ""


class TestBuildFixtures:
    def _records(self, **overrides):
        record = {"name": "", "manufacturer": "Stairville",
                  "model": "LED Par", "mode": "", "universe": "",
                  "address": "", "group": "", "position": ""}
        record.update(overrides)
        return [record]

    def test_defaults_mirror_the_fixture_list_import(self):
        fixtures, errors = build_fixtures(self._records())
        assert errors == []
        f = fixtures[0]
        assert f.name == "LED Par"          # name defaults to the model
        assert f.current_mode == "Default"  # synthesized single mode
        assert [(m.name, m.channels) for m in f.available_modes] == [
            ("Default", 1)]
        assert f.type == "PAR"
        assert (f.universe, f.address) == (1, 1)
        assert f.group == ""
        # No orientation in a venue sheet: group defaults stay in charge.
        assert f.orientation_uses_group_default is True

    def test_group_and_position_land_on_the_model(self):
        fixtures, _ = build_fixtures(self._records(
            group="Front Wash", position="FOH Truss"))
        assert fixtures[0].group == "Front Wash"
        assert fixtures[0].layer == "FOH Truss"

    def test_numbers_parse_including_spreadsheet_floats(self):
        fixtures, errors = build_fixtures(self._records(
            universe="2", address="10.0"))
        assert errors == []
        assert (fixtures[0].universe, fixtures[0].address) == (2, 10)

    def test_missing_required_is_an_error_not_a_drop(self):
        fixtures, errors = build_fixtures(
            self._records(manufacturer="  ") + self._records())
        assert len(fixtures) == 1
        assert errors == ["Row 1: manufacturer and model are required"]

    def test_bad_number_is_an_error(self):
        fixtures, errors = build_fixtures(self._records(address="patch-9"))
        assert fixtures == []
        assert errors == ["Row 1: address 'patch-9' is not a number"]

    def test_all_empty_rows_skip_silently(self):
        blank = {key: "" for key, _ in FIELDS}
        fixtures, errors = build_fixtures([blank] + self._records())
        assert len(fixtures) == 1
        assert errors == []


# ---------------------------------------------------------------------------
# Resolution against the bundled library
# ---------------------------------------------------------------------------

class TestResolve:
    def _fixture_records(self):
        return [
            {"name": "", "manufacturer": BUNDLED_MFR,
             "model": BUNDLED_MODEL, "mode": "8 Channel", "universe": "1",
             "address": "1", "group": "", "position": ""},
            {"name": "", "manufacturer": "NoSuchMfr",
             "model": "NoSuchModel", "mode": "", "universe": "1",
             "address": "9", "group": "", "position": ""},
        ]

    def test_bundled_model_resolves_and_upgrades_modes(self):
        fixtures, _ = build_fixtures(self._fixture_records()[:1])
        report = resolve_fixtures(fixtures)
        assert report.resolved == [(BUNDLED_MFR, BUNDLED_MODEL)]
        assert report.missing == []
        assert report.is_resolved(fixtures[0])
        assert [(m.name, m.channels) for m in fixtures[0].available_modes] == [
            ("4 Channel", 4), ("6 Channel", 6), ("8 Channel", 8)]
        assert fixtures[0].current_mode == "8 Channel"

    def test_unknown_model_is_reported_and_keeps_its_mode(self):
        fixtures, _ = build_fixtures(self._fixture_records())
        report = resolve_fixtures(fixtures)
        assert ("NoSuchMfr", "NoSuchModel") in report.missing
        assert not report.is_resolved(fixtures[1])
        assert any("NoSuchMfr NoSuchModel" in w for w in report.warnings)
        assert fixtures[1].available_modes[0].name == "Default"

    def test_end_to_end_from_a_german_semicolon_sheet(self, tmp_path):
        """The whole pure pipeline on one cp1252 venue file."""
        path = write_csv(
            tmp_path / "venue.csv",
            "Position;Hersteller-Make;Model;DMX;Group\n"
            f"Traverse Bühne;{BUNDLED_MFR};{BUNDLED_MODEL};17;Wäsche\n",
            encoding="cp1252")
        sniff = sniff_csv(path)
        mapping = guess_mapping(sniff.header)
        assert mapping["manufacturer"] == 1
        assert mapping["model"] == 2
        assert mapping["address"] == 3
        fixtures, errors = build_fixtures(apply_mapping(sniff.rows, mapping))
        assert errors == []
        report = resolve_fixtures(fixtures)
        f = fixtures[0]
        assert report.is_resolved(f)
        assert f.address == 17
        assert f.group == "Wäsche"
        assert f.layer == "Traverse Bühne"
        assert len(f.available_modes) == 3  # real .qxf modes, not synthesized


# ---------------------------------------------------------------------------
# The wizard dialog
# ---------------------------------------------------------------------------

VENUE_CSV = (
    "Make,Fixture,Mode,Univ,DMX,Group,Position\n"
    f"{BUNDLED_MFR},{BUNDLED_MODEL},8 Channel,1,1,Wash,FOH\n"
    f"{BUNDLED_MFR},{BUNDLED_MODEL},8 Channel,1,9,Wash,FOH\n"
    "NoSuchMfr,NoSuchModel,,1,17,Spots,LX1\n"
)


@pytest.fixture
def venue_csv(tmp_path):
    return write_csv(tmp_path / "venue.csv", VENUE_CSV)


@pytest.fixture
def wizard(qapp, venue_csv):
    from gui.dialogs.csv_import_wizard import CsvImportWizard
    w = CsvImportWizard(existing_fixture_count=2)
    yield w, venue_csv
    w.deleteLater()


class TestWizard:
    def test_starts_gated_until_a_file_loads(self, wizard):
        w, path = wizard
        assert w._stack.currentIndex() == 0
        assert not w.next_btn.isEnabled()
        w.set_source_file(path)
        assert w.next_btn.isEnabled()
        assert w.header_check.isChecked()
        assert w.raw_table.rowCount() == 4  # header + 3 rows, raw preview
        assert "comma" in w.detected_label.text()

    def test_delimiter_override_reparses(self, wizard):
        w, path = wizard
        w.set_source_file(path)
        w.delimiter_combo.setCurrentIndex(2)  # semicolon: wrong on purpose
        assert w.raw_table.columnCount() == 1
        w.delimiter_combo.setCurrentIndex(0)  # auto again
        assert w.raw_table.columnCount() == 7

    def test_mapping_page_autoguesses_and_gates_next(self, wizard):
        w, path = wizard
        w.set_source_file(path)
        w._go_next()
        assert w._stack.currentIndex() == 1
        mapping = w.mapping()
        assert mapping["manufacturer"] == 0
        assert mapping["model"] == 1
        assert mapping["mode"] == 2
        assert mapping["universe"] == 3
        assert mapping["address"] == 4
        assert mapping["group"] == 5
        assert mapping["position"] == 6
        assert w.next_btn.isEnabled()
        # Unmap a required field: NEXT locks.
        w.field_combos["manufacturer"].setCurrentIndex(0)  # (none)
        assert not w.next_btn.isEnabled()
        w.field_combos["manufacturer"].setCurrentIndex(1)
        assert w.next_btn.isEnabled()
        # The live preview shows mapped values.
        assert w.mapped_table.rowCount() == 3
        model_col = [key for key, _ in FIELDS].index("model")
        assert w.mapped_table.item(0, model_col).text() == BUNDLED_MODEL

    def test_preview_page_resolves_and_marks_missing(self, wizard):
        w, path = wizard
        w.set_source_file(path)
        w._go_next()
        w._go_next()
        assert w._stack.currentIndex() == 2
        assert w.next_btn.text() == "Import"
        assert w.resolved_table.rowCount() == 3
        status_col = w.resolved_table.columnCount() - 1
        assert w.resolved_table.item(0, status_col).text() == "OK"
        assert w.resolved_table.item(2, status_col).text() == "NO DEFINITION"
        assert "1 model(s) not in the fixture library" in \
            w.summary_label.text()

    def test_cancel_changes_nothing(self, wizard, qapp):
        """The gui.py contract: only Accepted applies anything."""
        from PyQt6.QtWidgets import QDialog
        w, path = wizard
        config = Configuration()
        w.set_source_file(path)
        w._go_next()
        w._go_next()
        w.reject()
        assert w.result() == QDialog.DialogCode.Rejected
        assert config.fixtures == []
        assert config.groups == {}

    def test_confirm_returns_the_resolved_list(self, wizard):
        from PyQt6.QtWidgets import QDialog
        w, path = wizard
        w.set_source_file(path)
        w._go_next()
        w._go_next()
        w._go_next()  # Import
        assert w.result() == QDialog.DialogCode.Accepted
        fixtures = w.result_fixtures()
        assert len(fixtures) == 3
        # Resolution ran: the bundled model carries the real mode list.
        assert len(fixtures[0].available_modes) == 3
        assert fixtures[0].current_mode == "8 Channel"
        assert fixtures[2].layer == "LX1"
        assert w.replace_rig() is False  # Add is the default
        assert any("NoSuchMfr" in note for note in w.resolution_warnings())

    def test_replace_choice_reaches_the_result(self, wizard):
        w, path = wizard
        w.set_source_file(path)
        w._go_next()
        w._go_next()
        assert w._mode_box.isVisibleTo(w)  # rig has 2 fixtures
        w.replace_radio.setChecked(True)
        w._go_next()
        assert w.replace_rig() is True

    def test_empty_rig_hides_replace_choice(self, qapp, venue_csv):
        from gui.dialogs.csv_import_wizard import CsvImportWizard
        w = CsvImportWizard(existing_fixture_count=0)
        try:
            w.set_source_file(venue_csv)
            w._go_next()
            w._go_next()
            assert not w._mode_box.isVisibleTo(w)
            assert w.replace_rig() is False
        finally:
            w.deleteLater()

    def test_header_only_file_cannot_import(self, qapp, tmp_path):
        from gui.dialogs.csv_import_wizard import CsvImportWizard
        path = write_csv(tmp_path / "empty.csv", "Make,Fixture\n")
        w = CsvImportWizard()
        try:
            w.set_source_file(path)
            assert not w.next_btn.isEnabled()  # no data rows, no import
        finally:
            w.deleteLater()

    def test_garbage_file_warns_and_gates_instead_of_crashing(
            self, qapp, tmp_path, monkeypatch):
        from PyQt6 import QtWidgets
        from gui.dialogs.csv_import_wizard import CsvImportWizard
        warnings = []
        monkeypatch.setattr(
            QtWidgets.QMessageBox, "warning",
            staticmethod(lambda *a, **k: warnings.append(a)))
        path = tmp_path / "garbage.csv"
        path.write_bytes(bytes(range(256)) * 8)
        w = CsvImportWizard()
        try:
            w.set_source_file(str(path))
            assert len(warnings) == 1
            assert not w.next_btn.isEnabled()
            assert w.raw_table.rowCount() == 0
        finally:
            w.deleteLater()

    def test_bad_rows_are_listed_not_dropped_silently(self, qapp, tmp_path):
        from gui.dialogs.csv_import_wizard import CsvImportWizard
        path = write_csv(
            tmp_path / "bad.csv",
            "Make,Fixture,DMX\nStairville,LED Par,nine\nMartin,MAC Aura,9\n")
        w = CsvImportWizard()
        try:
            w.set_source_file(path)
            w._go_next()
            w._go_next()
            assert w.resolved_table.rowCount() == 1
            assert w.row_errors() == ["Row 1: address 'nine' is not a number"]
            assert "1 row(s) skipped" in w.summary_label.text()
            assert w.errors_label.isVisibleTo(w)
        finally:
            w.deleteLater()


# ---------------------------------------------------------------------------
# Shell entry points (topbar import menu + File menu)
# ---------------------------------------------------------------------------

class TestShellEntryPoints:
    @pytest.fixture
    def shell(self, qapp):
        from PyQt6.QtWidgets import QMainWindow
        from gui.Ui_MainWindow import Ui_MainWindow
        window = QMainWindow()
        ui = Ui_MainWindow()
        ui.setupUi(window)
        yield window, ui
        window.deleteLater()

    def test_topbar_import_button_pops_a_choice_menu(self, shell):
        from PyQt6.QtWidgets import QToolButton
        _, ui = shell
        assert ui.import_btn.menu() is ui.import_menu
        assert (ui.import_btn.popupMode()
                == QToolButton.ToolButtonPopupMode.InstantPopup)
        actions = ui.import_menu.actions()
        assert actions == [ui.actionImportWorkspace, ui.actionImportCsvTable]
        assert ui.actionImportCsvTable.text() == \
            "Import Lighting Table (CSV)..."

    def test_file_menu_carries_the_new_action(self, shell):
        _, ui = shell
        actions = ui.menuFile.actions()
        assert ui.actionImportCsvTable in actions
        # Next to the other rig import, per the menu's grouping.
        assert (actions.index(ui.actionImportCsvTable)
                == actions.index(ui.actionImportFixtureList) + 1)

    def test_shortcut_registration_still_works(self, shell):
        """The popup menu must not break register_menu_shortcuts (the
        only reason overflow-menu shortcuts fire without a menubar)."""
        from gui.widgets.topbar import register_menu_shortcuts
        window, ui = shell
        count = register_menu_shortcuts(window, ui.overflow_menu)
        assert count >= 7
        shortcuts = [a.shortcut().toString() for a in window.actions()]
        assert "Ctrl+S" in shortcuts
