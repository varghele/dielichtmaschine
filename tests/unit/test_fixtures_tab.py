"""
FixturesTab (North Star card 1c): toolbar, table headers, inspector.

Toolbar contract: the -/duplicate icon buttons keep the shared fixed
``TOOLBAR_BTN_WIDTH`` (no compact density - the glyph-clipping saga,
see tests/visual/test_widget_clipping.py); add-fixture is the accent
primary CTA ("+ ADD FIXTURE", role="primary") like ConfigurationTab's
"+ ADD UNIVERSE".

Inspector contract: the right-hand panel (role="inspector") edits the
selected fixture. Its editors write through the table's cell widgets
(the single write path into the config), and table edits mirror back
into the inspector, so both always agree with config.fixtures.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_toolbar_buttons_match_default_button_styling(qapp, sample_configuration):
    from gui.theme_manager import ThemeManager
    from gui.tabs.configuration_tab import TOOLBAR_BTN_WIDTH
    from gui.tabs.fixtures_tab import FixturesTab

    ThemeManager().apply(qapp, "dark")
    tab = FixturesTab(sample_configuration, parent=None)
    try:
        # No compact-density: rely on the default
        # ``QPushButton { padding: 6px 14px; }`` rule so the icon
        # buttons render with the same proportions as text buttons.
        assert tab.remove_btn.property("density") in (None, "")
        assert tab.duplicate_btn.property("density") in (None, "")

        # Sanity: button glyphs are what we think they are.
        assert tab.remove_btn.text() == "-"
        assert tab.duplicate_btn.text() == "⎘"

        # The icon buttons match the shared icon-button width.
        for btn in (tab.remove_btn, tab.duplicate_btn):
            assert btn.minimumWidth() == TOOLBAR_BTN_WIDTH
            assert btn.maximumWidth() == TOOLBAR_BTN_WIDTH

        # Add-fixture is the accent primary CTA (auto-sized, no fixed
        # width - it carries text, not a glyph).
        assert tab.add_btn.text() == "+ ADD FIXTURE"
        assert tab.add_btn.property("role") == "primary"
        assert tab.add_btn.maximumWidth() > TOOLBAR_BTN_WIDTH
    finally:
        tab.deleteLater()


def test_table_headers_are_mono_caps(qapp, sample_configuration):
    """Column headers read as tracked mono micro-labels (card 1c)."""
    from gui.fonts import FONT_MONO
    from gui.tabs.fixtures_tab import FixturesTab

    tab = FixturesTab(sample_configuration, parent=None)
    try:
        header = tab.table.horizontalHeader()
        assert header.font().family() == FONT_MONO
        for col in range(tab.table.columnCount()):
            text = tab.table.horizontalHeaderItem(col).text()
            assert text == text.upper()
    finally:
        tab.deleteLater()


def test_status_footer_counts(qapp, sample_configuration):
    from gui.tabs.fixtures_tab import FixturesTab

    tab = FixturesTab(sample_configuration, parent=None)
    try:
        # MicroLabel renders caps; one fixture, one group in the sample.
        assert tab.summary_label.text() == "1 FIXTURE · 1 GROUP"
        assert "AUTO-PATCH" in tab.autopatch_label.text()
    finally:
        tab.deleteLater()


# ---------------------------------------------------------------------------
# Inspector panel (card 1c right column)
# ---------------------------------------------------------------------------

def test_inspector_loads_selected_fixture(qapp, sample_configuration):
    from gui.tabs.fixtures_tab import FixturesTab

    tab = FixturesTab(sample_configuration, parent=None)
    try:
        # Row 0 is auto-selected after every rebuild.
        assert tab._selected_fixture_row() == 0

        assert tab.inspector_title.text() == "TEST FIXTURE 1"
        # Provenance line: manufacturer, model, definition source.
        assert tab.inspector_source.text() == "TESTMFR · TESTMODEL · QXF"
        assert tab.insp_name.text() == "Test Fixture 1"
        assert tab.insp_address.value() == 1
        assert tab.insp_mode.currentText() == "Standard (10ch)"
        assert tab.insp_group.currentText() == "TestGroup"
        # Position readout: raw x/y, effective z (group default 3.0).
        assert tab.insp_position.text() == "X 1.00   Y 2.00   Z 3.00 m"
    finally:
        tab.deleteLater()


def test_inspector_shows_gdtf_provenance(qapp, sample_configuration):
    from gui.tabs.fixtures_tab import FixturesTab

    sample_configuration.fixtures[0].definition_source = "gdtf"
    tab = FixturesTab(sample_configuration, parent=None)
    try:
        assert tab.inspector_source.text().endswith("GDTF")
    finally:
        tab.deleteLater()


def test_inspector_edits_write_through_table_to_config(
        qapp, sample_configuration):
    from gui.tabs.fixtures_tab import FixturesTab

    tab = FixturesTab(sample_configuration, parent=None)
    try:
        # Address via inspector spin -> table spin -> config.
        tab.insp_address.setValue(21)
        assert tab.table.cellWidget(0, 1).value() == 21
        assert sample_configuration.fixtures[0].address == 21

        # Name via inspector line edit (textEdited = user typing).
        tab.insp_name.setText("Renamed")
        tab.insp_name.textEdited.emit("Renamed")
        assert tab.table.item(0, 6).text() == "Renamed"
        assert sample_configuration.fixtures[0].name == "Renamed"
        assert tab.inspector_title.text() == "RENAMED"
    finally:
        tab.deleteLater()


def test_inspector_mode_change_updates_table_and_channels(
        qapp, sample_configuration):
    from config.models import FixtureMode
    from gui.tabs.fixtures_tab import FixturesTab

    fixture = sample_configuration.fixtures[0]
    fixture.available_modes.append(FixtureMode(name="Extended", channels=16))
    tab = FixturesTab(sample_configuration, parent=None)
    try:
        tab.insp_mode.setCurrentIndex(1)
        assert fixture.current_mode == "Extended"
        assert tab.table.cellWidget(0, 5).currentIndex() == 1
        assert tab.table.item(0, 4).text() == "16"
    finally:
        tab.deleteLater()


def test_inspector_group_change_writes_config(qapp, sample_configuration):
    from gui.tabs.fixtures_tab import FixturesTab

    tab = FixturesTab(sample_configuration, parent=None)
    try:
        tab.insp_group.setCurrentText("")
        assert sample_configuration.fixtures[0].group == ""
        assert tab.table.cellWidget(0, 7).currentText() == ""
    finally:
        tab.deleteLater()


def test_table_edits_mirror_into_inspector(qapp, sample_configuration):
    from gui.tabs.fixtures_tab import FixturesTab

    tab = FixturesTab(sample_configuration, parent=None)
    try:
        tab.table.cellWidget(0, 1).setValue(33)
        assert tab.insp_address.value() == 33

        tab.table.item(0, 6).setText("From Table")
        assert tab.insp_name.text() == "From Table"
        assert tab.inspector_title.text() == "FROM TABLE"
    finally:
        tab.deleteLater()


def test_inspector_disables_without_selection(qapp, sample_configuration):
    from gui.tabs.fixtures_tab import FixturesTab

    tab = FixturesTab(sample_configuration, parent=None)
    try:
        tab.table.clearSelection()
        assert tab.inspector_title.text() == "NO FIXTURE"
        for editor in tab._inspector_editors:
            assert not editor.isEnabled()

        # Re-selecting brings it back.
        tab.table.selectRow(0)
        assert tab.inspector_title.text() == "TEST FIXTURE 1"
        for editor in tab._inspector_editors:
            assert editor.isEnabled()
    finally:
        tab.deleteLater()


def test_inspector_panel_uses_inspector_role(qapp, sample_configuration):
    from gui.tabs.fixtures_tab import FixturesTab

    from PyQt6.QtWidgets import QWidget

    tab = FixturesTab(sample_configuration, parent=None)
    try:
        panel = tab.findChild(QWidget, "FixtureInspector")
        assert panel is not None
        assert panel.property("role") == "inspector"
    finally:
        tab.deleteLater()


# ---------------------------------------------------------------------------
# DMX address conflict indicators
#
# Contract: fixtures whose (universe, address range) footprints overlap get
# the warning stylesheet + a tooltip naming the other fixture on their
# Universe/Address cell widgets, and the summary label shows the issue
# count. Resolving the conflict via the Address spinbox clears all of it
# (save_to_config re-lints; no full table rebuild involved).
# ---------------------------------------------------------------------------

def _overlapping_config(sample_configuration):
    """Add a second fixture overlapping the first (both 1-10 on universe 0)."""
    from config.models import Fixture, FixtureMode

    clash = Fixture(
        universe=0,
        address=5,
        manufacturer="TestMfr",
        model="TestModel",
        name="Test Fixture 2",
        group="TestGroup",
        current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
    )
    sample_configuration.fixtures.append(clash)
    sample_configuration.groups["TestGroup"].fixtures.append(clash)
    return sample_configuration


def test_conflicting_fixtures_are_flagged(qapp, sample_configuration):
    from gui.tabs.fixtures_tab import CONFLICT_CELL_QSS, FixturesTab

    config = _overlapping_config(sample_configuration)
    tab = FixturesTab(config, parent=None)
    try:
        assert tab.conflict_label.isVisibleTo(tab)
        # The label is a warning Chip and renders in caps.
        assert "1 DMX ADDRESSING ISSUE" in tab.conflict_label.text()

        for row, other_name in ((0, "Test Fixture 2"), (1, "Test Fixture 1")):
            for col in (0, 1):
                widget = tab.table.cellWidget(row, col)
                assert widget.styleSheet() == CONFLICT_CELL_QSS
                assert other_name in widget.toolTip()
                assert "channels 5-10" in widget.toolTip()
    finally:
        tab.deleteLater()


def test_resolving_conflict_clears_flags(qapp, sample_configuration):
    from gui.tabs.fixtures_tab import CONFLICT_CELL_QSS, FixturesTab

    config = _overlapping_config(sample_configuration)
    tab = FixturesTab(config, parent=None)
    try:
        # Move the second fixture clear of the first (1-10 -> 11-20).
        tab.table.cellWidget(1, 1).setValue(11)

        assert not tab.conflict_label.isVisibleTo(tab)
        for row in (0, 1):
            for col in (0, 1):
                widget = tab.table.cellWidget(row, col)
                assert widget.styleSheet() != CONFLICT_CELL_QSS
                assert widget.toolTip() == ""
    finally:
        tab.deleteLater()


def test_overflow_past_universe_end_is_flagged(qapp, sample_configuration):
    from gui.tabs.fixtures_tab import CONFLICT_CELL_QSS, FixturesTab

    tab = FixturesTab(sample_configuration, parent=None)
    try:
        # 10-channel fixture at 510 runs to 519, past the 512 limit.
        tab.table.cellWidget(0, 1).setValue(510)

        assert tab.conflict_label.isVisibleTo(tab)
        widget = tab.table.cellWidget(0, 1)
        assert widget.styleSheet() == CONFLICT_CELL_QSS
        assert "ends at channel 519" in widget.toolTip()
    finally:
        tab.deleteLater()
