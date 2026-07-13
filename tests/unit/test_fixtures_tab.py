"""
FixturesTab, rebuilt to the reference screen 02 (Setup Fixtures).

Contract under test:
- Action strip: DMX-conflict chip (hidden when clean) left, accent
  "+ ADD FIXTURE" CTA right. No tab title row.
- GROUPS panel: one row per group (name caps, "N FIX" mono, role line),
  "+" add-group button, clicking a row selects that group's fixtures.
- Table: read-only display items in reference column order
  (# / FIXTURE / TYPE / MODE / UNI / ADDRESS / GROUP), group-tinted row
  backgrounds at low alpha (diagonal candy stripes through every
  membership's tint on multi-group rows), group names in the group
  color, red UNI/ADDRESS cells + tooltip on DMX conflicts.
- Inspector: the single write path - Name/Universe/Address/Mode/Group/
  Role editors write directly to the config and refresh the table row;
  CAPABILITIES chips + CHANNEL MAP come from the definition cache;
  Duplicate/Remove live in the inspector footer.
- Status strip: counts + per-universe channel usage.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from gui.tabs.fixtures_tab import (
    COL_ADDRESS, COL_FIXTURE, COL_GROUP, COL_MODE, COL_NUM, COL_TYPE,
    COL_UNI, CONFLICT_BG, GROUP_TINT_ALPHA,
)


def _make_tab(qapp, config):
    from gui.theme_manager import ThemeManager
    from gui.tabs.fixtures_tab import FixturesTab

    ThemeManager().apply(qapp, "dark")
    return FixturesTab(config, parent=None)


# ---------------------------------------------------------------------------
# Action strip
# ---------------------------------------------------------------------------

def test_action_strip_cta_and_chip(qapp, sample_configuration):
    tab = _make_tab(qapp, sample_configuration)
    try:
        # Accent primary CTA on the right of the strip.
        assert tab.add_btn.text() == "+ ADD FIXTURE"
        assert tab.add_btn.property("role") == "cta-accent"

        # Conflict chip hidden while the patch is clean.
        assert not tab.conflict_label.isVisibleTo(tab)

        # No title label - the shell subnav names the screen.
        assert not hasattr(tab, "label")
    finally:
        tab.deleteLater()


def test_duplicate_remove_live_in_inspector_footer(qapp,
                                                   sample_configuration):
    tab = _make_tab(qapp, sample_configuration)
    try:
        from PyQt6.QtWidgets import QWidget

        panel = tab.findChild(QWidget, "FixtureInspector")
        assert panel is not None
        assert tab.duplicate_btn.text() == "Duplicate"
        assert tab.remove_btn.text() == "Remove"
        assert tab.remove_btn.property("role") == "destructive"
        assert panel.isAncestorOf(tab.duplicate_btn)
        assert panel.isAncestorOf(tab.remove_btn)
    finally:
        tab.deleteLater()


# ---------------------------------------------------------------------------
# Table: reference columns, read-only display items
# ---------------------------------------------------------------------------

def test_table_headers_reference_order_mono_caps(qapp, sample_configuration):
    """Headers are # FIXTURE TYPE MODE UNI ADDRESS GROUP; the mono
    family is pinned by the theme's QHeaderView::section rule, NOT
    asserted via header.font() (polish-order race)."""
    from gui.fonts import FONT_MONO
    from gui.theme_tokens import render_theme

    qss = render_theme("dark")
    header_rule = qss.split("QHeaderView::section {", 1)[1].split("}", 1)[0]
    assert FONT_MONO in header_rule

    tab = _make_tab(qapp, sample_configuration)
    try:
        headers = [tab.table.horizontalHeaderItem(c).text()
                   for c in range(tab.table.columnCount())]
        assert headers == ["#", "FIXTURE", "TYPE", "MODE", "UNI",
                           "ADDRESS", "GROUP"]
    finally:
        tab.deleteLater()


def test_table_is_read_only_display(qapp, sample_configuration):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QAbstractItemView

    tab = _make_tab(qapp, sample_configuration)
    try:
        assert (tab.table.editTriggers()
                == QAbstractItemView.EditTrigger.NoEditTriggers)
        for col in range(tab.table.columnCount()):
            item = tab.table.item(0, col)
            assert item is not None, f"column {col} must be a plain item"
            assert not (item.flags() & Qt.ItemFlag.ItemIsEditable)
            # No cell widgets anywhere - display items only.
            assert tab.table.cellWidget(0, col) is None
    finally:
        tab.deleteLater()


def test_table_cell_texts(qapp, sample_configuration):
    tab = _make_tab(qapp, sample_configuration)
    try:
        texts = {col: tab.table.item(0, col).text()
                 for col in range(tab.table.columnCount())}
        assert texts[COL_NUM] == "01"
        assert texts[COL_FIXTURE] == "Test Fixture 1"
        assert texts[COL_TYPE] == "MOVING HEAD"     # sample type "MH"
        assert texts[COL_MODE] == "10 CH"
        assert texts[COL_UNI] == "U0"
        assert texts[COL_ADDRESS] == "001-010"
        assert texts[COL_GROUP] == "TESTGROUP"
    finally:
        tab.deleteLater()


def test_group_tint_and_colored_group_name(qapp, sample_configuration):
    from PyQt6.QtGui import QColor
    from gui.theme_tokens import DARK
    from gui.tabs.fixtures_tab import group_tint_color

    tab = _make_tab(qapp, sample_configuration)
    try:
        group_color = QColor("#FF0000")  # saved on the sample group

        # Row background: the group color at the reference's low alpha,
        # pre-blended over the panel color (opaque - see
        # group_tint_color for the PE_PanelItemViewRow story).
        bg = tab.table.item(0, COL_FIXTURE).background().color()
        expected = group_tint_color(group_color, QColor(DARK["panel"]))
        assert bg.name() == expected.name()
        assert bg.alpha() == 255

        # Group name renders in the group color (foreground brush).
        fg = tab.table.item(0, COL_GROUP).foreground().color()
        assert fg.name() == group_color.name()
    finally:
        tab.deleteLater()


def test_ungrouped_rows_have_no_tint(qapp, sample_configuration):
    from PyQt6.QtGui import QColor
    from gui.theme_tokens import DARK

    tab = _make_tab(qapp, sample_configuration)
    try:
        tab.insp_group.setCurrentText("")
        item = tab.table.item(0, COL_FIXTURE)
        # Plain opaque panel background - no group tint.
        assert item.background().color().name() == QColor(DARK["panel"]).name()
        assert tab.table.item(0, COL_GROUP).text() == ""
    finally:
        tab.deleteLater()


# ---------------------------------------------------------------------------
# Inspector: loads the selection, writes directly to the config
# ---------------------------------------------------------------------------

def test_inspector_loads_selected_fixture(qapp, sample_configuration):
    tab = _make_tab(qapp, sample_configuration)
    try:
        # Row 0 is auto-selected after every rebuild.
        assert tab._selected_fixture_row() == 0

        assert tab.inspector_title.text() == "TEST FIXTURE 1"
        assert tab.inspector_source.text() == "TESTMFR · TESTMODEL · QXF"
        assert tab.insp_name.text() == "Test Fixture 1"
        assert tab.insp_address.value() == 1
        assert tab.insp_mode.currentText() == "Standard (10ch)"
        assert tab.insp_group.currentText() == "TestGroup"
        assert tab.insp_position.text() == "X 1.00   Y 2.00   Z 3.00 m"
    finally:
        tab.deleteLater()


def test_inspector_shows_gdtf_provenance(qapp, sample_configuration):
    sample_configuration.fixtures[0].definition_source = "gdtf"
    tab = _make_tab(qapp, sample_configuration)
    try:
        assert tab.inspector_source.text().endswith("GDTF")
    finally:
        tab.deleteLater()


def test_inspector_address_writes_config_and_row(qapp, sample_configuration):
    tab = _make_tab(qapp, sample_configuration)
    try:
        tab.insp_address.setValue(21)
        assert sample_configuration.fixtures[0].address == 21
        assert tab.table.item(0, COL_ADDRESS).text() == "021-030"
    finally:
        tab.deleteLater()


def test_inspector_name_writes_config_and_row(qapp, sample_configuration):
    tab = _make_tab(qapp, sample_configuration)
    try:
        tab.insp_name.setText("Renamed")
        tab.insp_name.textEdited.emit("Renamed")
        assert sample_configuration.fixtures[0].name == "Renamed"
        assert tab.table.item(0, COL_FIXTURE).text() == "Renamed"
        assert tab.inspector_title.text() == "RENAMED"
    finally:
        tab.deleteLater()


def test_inspector_mode_change_updates_channel_footprint(
        qapp, sample_configuration):
    from config.models import FixtureMode

    fixture = sample_configuration.fixtures[0]
    fixture.available_modes.append(FixtureMode(name="Extended", channels=16))
    tab = _make_tab(qapp, sample_configuration)
    try:
        tab.insp_mode.setCurrentIndex(1)
        assert fixture.current_mode == "Extended"
        assert tab.table.item(0, COL_MODE).text() == "16 CH"
        # The address range widens with the footprint.
        assert tab.table.item(0, COL_ADDRESS).text() == "001-016"
    finally:
        tab.deleteLater()


def test_inspector_group_change_writes_config(qapp, sample_configuration):
    tab = _make_tab(qapp, sample_configuration)
    try:
        tab.insp_group.setCurrentText("")
        assert sample_configuration.fixtures[0].group == ""
        # The empty group vanished from the rebuilt group table.
        assert "TestGroup" not in sample_configuration.groups
    finally:
        tab.deleteLater()


def test_inspector_role_edits_group_role(qapp, sample_configuration):
    tab = _make_tab(qapp, sample_configuration)
    try:
        tab.insp_role.setCurrentText("accent")
        assert (sample_configuration.groups["TestGroup"].lighting_role
                == "accent")
    finally:
        tab.deleteLater()


def test_selection_binds_inspector(qapp, sample_configuration):
    from config.models import Fixture, FixtureMode

    sample_configuration.fixtures.append(Fixture(
        universe=0, address=11, manufacturer="TestMfr", model="TestModel",
        name="Second", group="TestGroup", current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
    ))
    tab = _make_tab(qapp, sample_configuration)
    try:
        tab.table.selectRow(1)
        assert tab.inspector_title.text() == "SECOND"
        assert tab.insp_address.value() == 11
    finally:
        tab.deleteLater()


def test_inspector_disables_without_selection(qapp, sample_configuration):
    tab = _make_tab(qapp, sample_configuration)
    try:
        tab.table.clearSelection()
        assert tab.inspector_title.text() == "NO FIXTURE"
        for editor in tab._inspector_editors:
            assert not editor.isEnabled()
        assert not tab.duplicate_btn.isEnabled()
        assert not tab.remove_btn.isEnabled()

        tab.table.selectRow(0)
        assert tab.inspector_title.text() == "TEST FIXTURE 1"
        assert tab.duplicate_btn.isEnabled()
    finally:
        tab.deleteLater()


def test_inspector_panel_uses_inspector_role(qapp, sample_configuration):
    from PyQt6.QtWidgets import QWidget

    tab = _make_tab(qapp, sample_configuration)
    try:
        panel = tab.findChild(QWidget, "FixtureInspector")
        assert panel is not None
        assert panel.property("role") == "inspector"
    finally:
        tab.deleteLater()


# ---------------------------------------------------------------------------
# Capabilities + channel map (definition cache)
# ---------------------------------------------------------------------------

def _seeded_definition():
    """A legacy definition dict matching the sample fixture's identity
    and its 'Standard' 10-channel mode."""
    names = ["Dimmer", "Strobe", "Pan", "Pan Fine", "Tilt", "Tilt Fine",
             "Red", "Green", "Blue", "White"]
    presets = {
        "Dimmer": "IntensityMasterDimmer", "Strobe": "ShutterStrobeSlowFast",
        "Pan": "PositionPan", "Pan Fine": "PositionPanFine",
        "Tilt": "PositionTilt", "Tilt Fine": "PositionTiltFine",
        "Red": "IntensityRed", "Green": "IntensityGreen",
        "Blue": "IntensityBlue", "White": "IntensityWhite",
    }
    return {
        "manufacturer": "TestMfr",
        "model": "TestModel",
        "channels": [
            {"name": n, "preset": presets[n], "group": None,
             "capabilities": []}
            for n in names
        ],
        "modes": [{
            "name": "Standard",
            "channels": [{"number": i, "name": n}
                         for i, n in enumerate(names)],
        }],
    }


def test_capabilities_and_channel_map_from_definition(
        qapp, sample_configuration):
    from utils.fixture_utils import _fixture_definitions_cache
    from gui.widgets.chip import Chip

    _fixture_definitions_cache["TestMfr_TestModel"] = _seeded_definition()
    tab = None
    try:
        tab = _make_tab(qapp, sample_configuration)

        assert not tab.caps_placeholder.isVisibleTo(tab)
        chips = [tab._caps_flow.itemAt(i).widget()
                 for i in range(tab._caps_flow.count())]
        assert all(isinstance(c, Chip) for c in chips)
        assert [c.text() for c in chips] == [
            "PAN/TILT", "RGBW", "DIMMER", "STROBE"]

        assert tab.channel_map_header.text() == "CHANNEL MAP · MODE 10 CH"
        # 10 channel rows + the trailing stretch.
        rows = [tab._map_layout.itemAt(i).widget()
                for i in range(tab._map_layout.count())]
        assert sum(1 for r in rows if r is not None) == 10
    finally:
        _fixture_definitions_cache.pop("TestMfr_TestModel", None)
        if tab is not None:
            tab.deleteLater()


def test_unresolvable_definition_shows_placeholder(
        qapp, sample_configuration):
    tab = _make_tab(qapp, sample_configuration)
    try:
        # Synthetic TestMfr/TestModel resolves to nothing.
        assert tab.caps_placeholder.isVisibleTo(tab)
        assert tab.caps_placeholder.text() == "NO DEFINITION FOUND"
        assert tab._caps_flow.count() == 0
        assert tab.channel_map_header.text() == "CHANNEL MAP · MODE 10 CH"
    finally:
        tab.deleteLater()


# ---------------------------------------------------------------------------
# GROUPS panel
# ---------------------------------------------------------------------------

def _group_rows(tab):
    rows = []
    for i in range(tab._groups_layout.count()):
        widget = tab._groups_layout.itemAt(i).widget()
        if widget is not None:
            rows.append(widget)
    return rows


def test_groups_panel_rows(qapp, sample_configuration):
    from PyQt6.QtWidgets import QLabel

    sample_configuration.groups["TestGroup"].lighting_role = "wash"
    tab = _make_tab(qapp, sample_configuration)
    try:
        rows = _group_rows(tab)
        assert len(rows) == 1
        labels = [lbl.text() for lbl in rows[0].findChildren(QLabel)]
        assert "TESTGROUP" in labels
        assert "1 FIX" in labels
        assert "Role: wash · MH x1" in labels
        # The colored left border carries the group's data color.
        assert "border-left: 3px solid #ff0000" in rows[0].styleSheet()
    finally:
        tab.deleteLater()


def test_group_row_click_selects_group_fixtures(qapp, sample_configuration):
    from config.models import Fixture, FixtureMode

    sample_configuration.fixtures.append(Fixture(
        universe=0, address=11, manufacturer="TestMfr", model="TestModel",
        name="Loose", group="", current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
    ))
    sample_configuration.fixtures.append(Fixture(
        universe=0, address=21, manufacturer="TestMfr", model="TestModel",
        name="Second grouped", group="TestGroup", current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
    ))
    sample_configuration.groups["TestGroup"].fixtures.append(
        sample_configuration.fixtures[-1])
    tab = _make_tab(qapp, sample_configuration)
    try:
        tab.table.clearSelection()
        tab._on_group_row_clicked("TestGroup")
        selected = sorted({i.row() for i in tab.table.selectedItems()})
        assert selected == [0, 2]
        assert tab._selected_group == "TestGroup"
        # Selected row carries the raised background.
        assert "background-color: transparent" not in \
            _group_rows(tab)[0].styleSheet()
    finally:
        tab.deleteLater()


def test_create_group_persists_while_empty(qapp, sample_configuration):
    tab = _make_tab(qapp, sample_configuration)
    try:
        tab._create_group("Movers", role="accent")
        assert "Movers" in sample_configuration.groups
        assert sample_configuration.groups["Movers"].lighting_role == "accent"
        assert sample_configuration.groups["Movers"].fixtures == []
        # It got a data color and a panel row.
        assert sample_configuration.groups["Movers"].color != "#808080"
        assert len(_group_rows(tab)) == 2

        # A group rebuild (any config edit) must NOT drop it.
        tab._update_groups()
        assert "Movers" in sample_configuration.groups

        # It is offered in the inspector's group editor.
        items = [tab.insp_group.itemText(i)
                 for i in range(tab.insp_group.count())]
        assert "Movers" in items
    finally:
        tab.deleteLater()


def test_group_add_button_exists(qapp, sample_configuration):
    from gui.tabs.configuration_tab import TOOLBAR_BTN_WIDTH

    tab = _make_tab(qapp, sample_configuration)
    try:
        assert tab.group_add_btn.text() == "+"
        assert tab.group_add_btn.minimumWidth() == TOOLBAR_BTN_WIDTH
        assert tab.group_add_btn.maximumWidth() == TOOLBAR_BTN_WIDTH
    finally:
        tab.deleteLater()


# ---------------------------------------------------------------------------
# Status strip + footer
# ---------------------------------------------------------------------------

def test_status_strip_counts_and_universe_usage(qapp, sample_configuration):
    tab = _make_tab(qapp, sample_configuration)
    try:
        assert tab.summary_label.text() == "1 FIXTURE · 1 GROUP"
        assert tab.universe_usage_label.text() == "U0 10/512"
    finally:
        tab.deleteLater()


def test_universe_usage_tracks_moves(qapp, sample_configuration):
    tab = _make_tab(qapp, sample_configuration)
    try:
        tab.insp_universe.setValue(2)
        assert "U2 10/512" in tab.universe_usage_label.text()
    finally:
        tab.deleteLater()


# ---------------------------------------------------------------------------
# Duplicate / Remove semantics (unchanged from the toolbar era)
# ---------------------------------------------------------------------------

def test_duplicate_creates_conflict_free_copy(qapp, sample_configuration):
    from utils.dmx_conflicts import lint_dmx_addresses

    tab = _make_tab(qapp, sample_configuration)
    try:
        tab.duplicate_btn.click()
        fixtures = sample_configuration.fixtures
        assert len(fixtures) == 2
        assert fixtures[1].name == "Test Fixture 1 (Copy)"
        assert fixtures[1].group == "TestGroup"
        assert lint_dmx_addresses(fixtures).is_clean
        assert tab.table.rowCount() == 2
    finally:
        tab.deleteLater()


def test_remove_deletes_selected_fixture(qapp, sample_configuration):
    tab = _make_tab(qapp, sample_configuration)
    try:
        tab.remove_btn.click()
        assert sample_configuration.fixtures == []
        assert tab.table.rowCount() == 0
        # Group emptied out and was dropped.
        assert sample_configuration.groups == {}
    finally:
        tab.deleteLater()


# ---------------------------------------------------------------------------
# GroupRowDelegate: no dotted per-cell focus rectangle on selection
# ---------------------------------------------------------------------------

def test_group_row_delegate_strips_focus_and_selection(qapp):
    """The delegate clears State_HasFocus (kills Qt's dotted focus rect)
    and State_Selected (keeps the group tint) on the style option, so the
    only selection chrome is the RowOutlineTableWidget outline. Asserted
    on the option flags, not via a screenshot of the dotted line."""
    from PyQt6.QtCore import QModelIndex
    from PyQt6.QtWidgets import QStyle, QStyleOptionViewItem
    from gui.widgets.group_row_delegate import GroupRowDelegate

    delegate = GroupRowDelegate()
    option = QStyleOptionViewItem()
    option.state |= QStyle.StateFlag.State_HasFocus
    option.state |= QStyle.StateFlag.State_Selected
    delegate.initStyleOption(option, QModelIndex())
    assert not (option.state & QStyle.StateFlag.State_HasFocus)
    assert not (option.state & QStyle.StateFlag.State_Selected)


# ---------------------------------------------------------------------------
# Table right-click context menu: Duplicate / Remove
# ---------------------------------------------------------------------------

def test_table_context_menu_is_custom(qapp, sample_configuration):
    from PyQt6.QtCore import Qt

    tab = _make_tab(qapp, sample_configuration)
    try:
        assert (tab.table.contextMenuPolicy()
                == Qt.ContextMenuPolicy.CustomContextMenu)
    finally:
        tab.deleteLater()


def test_context_menu_actions_dispatch_to_crud(qapp, sample_configuration,
                                               monkeypatch):
    """The menu items reuse the existing CRUD methods. Triggering the
    actions calls _duplicate_fixture / _remove_fixture (patched so no real
    popup or config mutation runs)."""
    tab = _make_tab(qapp, sample_configuration)
    try:
        called = []
        monkeypatch.setattr(tab, "_duplicate_fixture",
                            lambda: called.append("duplicate"))
        monkeypatch.setattr(tab, "_remove_fixture",
                            lambda: called.append("remove"))

        menu = tab._build_table_context_menu()
        actions = {a.text(): a for a in menu.actions() if a.text()}
        # Duplicate and Remove are the top-level CRUD items (an "Assign to
        # group" submenu also lives here now).
        assert {"Duplicate", "Remove"} <= set(actions)

        actions["Duplicate"].trigger()
        actions["Remove"].trigger()
        assert called == ["duplicate", "remove"]
    finally:
        tab.deleteLater()


def test_context_menu_selects_row_under_cursor(qapp, sample_configuration,
                                               monkeypatch):
    """A right-click on an unselected row selects that row before the menu
    opens, so the CRUD methods act on the clicked fixture. The menu itself
    is stubbed so no blocking exec runs (qt-gotchas #7)."""
    from unittest.mock import MagicMock
    from PyQt6 import QtCore
    from config.models import Fixture, FixtureMode

    sample_configuration.fixtures.append(Fixture(
        universe=0, address=11, manufacturer="TestMfr", model="TestModel",
        name="Second", group="TestGroup", current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
    ))
    tab = _make_tab(qapp, sample_configuration)
    try:
        model = tab.table.model()
        monkeypatch.setattr(tab.table, "indexAt",
                            lambda pos: model.index(1, 0))
        monkeypatch.setattr(tab, "_build_table_context_menu",
                            lambda has_row=True: MagicMock())

        tab.table.clearSelection()
        tab._show_table_context_menu(QtCore.QPoint(0, 0))
        assert tab._selected_fixture_row() == 1
    finally:
        tab.deleteLater()


def test_empty_click_menu_offers_add_and_table_wide_actions(
        qapp, sample_configuration):
    """Right-clicking past the last row offers Add fixture plus the
    table-wide addressing actions (Untangle/Compact operate on the
    whole patch, so they need no row) - but none of the row CRUD."""
    tab = _make_tab(qapp, sample_configuration)
    try:
        menu = tab._build_table_context_menu(has_row=False)
        labels = [a.text() for a in menu.actions() if a.text()]
        assert labels == ["Add fixture...", "Untangle addresses",
                          "Compact addresses"]
    finally:
        tab.deleteLater()


def test_row_menu_offers_add_fixture(qapp, sample_configuration):
    """On a row the menu still leads with Add fixture, plus the CRUD items."""
    tab = _make_tab(qapp, sample_configuration)
    try:
        menu = tab._build_table_context_menu(has_row=True)
        labels = [a.text() for a in menu.actions() if a.text()]
        assert "Add fixture..." in labels
        assert {"Duplicate", "Remove"} <= set(labels)
    finally:
        tab.deleteLater()


def test_add_fixture_menu_action_calls_add(qapp, sample_configuration,
                                           monkeypatch):
    tab = _make_tab(qapp, sample_configuration)
    try:
        called = []
        monkeypatch.setattr(tab, "_add_fixture", lambda: called.append(1))
        menu = tab._build_table_context_menu(has_row=False)
        add = next(a for a in menu.actions() if a.text() == "Add fixture...")
        add.trigger()
        assert called == [1]
    finally:
        tab.deleteLater()


def test_groups_panel_menu_adds_a_group(qapp, sample_configuration,
                                        monkeypatch):
    from PyQt6 import QtCore
    tab = _make_tab(qapp, sample_configuration)
    try:
        # Intercept the exec so no real popup blocks; capture the menu.
        captured = {}
        real_exec = QtWidgets.QMenu.exec

        def fake_exec(self, *a):
            captured["labels"] = [x.text() for x in self.actions() if x.text()]
            return None
        monkeypatch.setattr(QtWidgets.QMenu, "exec", fake_exec)
        called = []
        monkeypatch.setattr(tab, "_add_group", lambda: called.append(1))

        panel = tab.findChild(QtWidgets.QWidget, "GroupsPanel")
        tab._show_groups_panel_menu(panel, QtCore.QPoint(0, 0))
        assert captured["labels"] == ["Add group..."]
    finally:
        monkeypatch.undo()
        tab.deleteLater()


def test_group_row_menu_offers_add_and_duplicate(qapp, sample_configuration,
                                                 monkeypatch):
    from PyQt6 import QtCore
    tab = _make_tab(qapp, sample_configuration)
    try:
        captured = {}

        def fake_exec(self, *a):
            captured["labels"] = [x.text() for x in self.actions() if x.text()]
            return None
        monkeypatch.setattr(QtWidgets.QMenu, "exec", fake_exec)
        tab._show_group_context_menu("TestGroup", QtCore.QPoint(0, 0))
        assert "Add group..." in captured["labels"]
        assert "Duplicate group" in captured["labels"]
    finally:
        monkeypatch.undo()
        tab.deleteLater()


# ---------------------------------------------------------------------------
# Group assignment (multi-select) and group duplication
# ---------------------------------------------------------------------------

def _multi_fixture_config():
    from config.models import (Configuration, Fixture, FixtureGroup,
                               FixtureMode, Universe)

    def mk(name, address, group=""):
        return Fixture(universe=0, address=address, manufacturer="M",
                       model="X", name=name, group=group, current_mode="Std",
                       available_modes=[FixtureMode(name="Std", channels=4)],
                       type="PAR")

    return Configuration(
        fixtures=[mk("P1", 1), mk("P2", 5), mk("P3", 9, "Wash")],
        groups={"Wash": FixtureGroup("Wash", [], lighting_role="wash")},
        universes={0: Universe(id=0, name="U0", output={})})


def _select_rows(tab, rows):
    from PyQt6.QtCore import QItemSelection, QItemSelectionModel
    model = tab.table.selectionModel()
    model.clear()
    for r in rows:
        idx = tab.table.model().index(r, 0)
        model.select(QItemSelection(idx, tab.table.model().index(
            r, tab.table.columnCount() - 1)),
            QItemSelectionModel.SelectionFlag.Select)


def test_assign_multiple_fixtures_to_a_group(qapp):
    tab = _make_tab(qapp, _multi_fixture_config())
    try:
        _select_rows(tab, [0, 1])
        assert tab._selected_fixture_rows() == [0, 1]
        tab._assign_selected_to_group("Wash")
        groups = {f.name: f.group for f in tab.config.fixtures}
        assert groups == {"P1": "Wash", "P2": "Wash", "P3": "Wash"}
        # The GROUP column text must update for the assigned rows, not just
        # the model (regression: multi-assign left the old name in the cell).
        assert tab.table.item(0, COL_GROUP).text() == "WASH"
        assert tab.table.item(1, COL_GROUP).text() == "WASH"
    finally:
        tab.deleteLater()


def test_assign_selection_to_a_new_group(qapp):
    from unittest.mock import patch
    tab = _make_tab(qapp, _multi_fixture_config())
    try:
        _select_rows(tab, [0, 1])
        with patch.object(QtWidgets.QInputDialog, "getText",
                          return_value=("Spots", True)):
            tab._assign_selected_to_new_group()
        assert "Spots" in tab.config.groups
        assert tab.config.fixtures[0].group == "Spots"
        assert tab.config.fixtures[1].group == "Spots"
    finally:
        tab.deleteLater()


def test_ungroup_selection(qapp):
    tab = _make_tab(qapp, _multi_fixture_config())
    try:
        _select_rows(tab, [2])  # P3 is in "Wash"
        tab._assign_selected_to_group("")
        assert tab.config.fixtures[2].group == ""
    finally:
        tab.deleteLater()


def test_context_menu_has_assign_submenu(qapp):
    tab = _make_tab(qapp, _multi_fixture_config())
    try:
        _select_rows(tab, [0])
        menu = tab._build_table_context_menu()
        submenus = [a.menu() for a in menu.actions() if a.menu() is not None]
        assign = next((m for m in submenus
                       if m.title().startswith("Assign")), None)
        assert assign is not None
        labels = [a.text() for a in assign.actions() if a.text()]
        assert "Wash" in labels          # existing group
        assert "New group..." in labels
        assert "Ungroup" in labels
    finally:
        tab.deleteLater()


def test_duplicate_group_copies_role_into_a_new_empty_group(qapp):
    tab = _make_tab(qapp, _multi_fixture_config())
    try:
        tab._duplicate_group("Wash")
        assert "Wash copy" in tab.config.groups
        assert tab.config.groups["Wash copy"].lighting_role == "wash"
        # Membership is deliberately not copied - the duplicate is an
        # empty group ready for its own members.
        assert tab.config.groups["Wash copy"].fixtures == []
        # A second duplicate gets a distinct name.
        tab._duplicate_group("Wash")
        assert "Wash copy 2" in tab.config.groups
    finally:
        tab.deleteLater()


def test_group_row_right_click_offers_duplicate(qapp):
    """The group row emits context_requested; the handler builds a menu."""
    from PyQt6.QtCore import QPoint
    from unittest.mock import patch
    tab = _make_tab(qapp, _multi_fixture_config())
    try:
        captured = {}

        class FakeMenu:
            def __init__(self, *a):
                self._actions = []

            def addAction(self, text):
                from PyQt6.QtGui import QAction
                act = QAction(text)
                self._actions.append(act)
                captured["actions"] = self._actions
                return act

            def exec(self, *a):
                return None

        with patch.object(QtWidgets, "QMenu", FakeMenu):
            tab._show_group_context_menu("Wash", QPoint(0, 0))
        assert any(a.text() == "Duplicate group"
                   for a in captured.get("actions", []))
    finally:
        tab.deleteLater()


# ---------------------------------------------------------------------------
# Multi-group membership (plan stage 2, docs/multi-group-fixtures-plan.md)
#
# The Assign submenu is MEMBERSHIP editing: checkable entries reflect
# the selection ("all selected have it"), clicking an unchecked group
# APPENDS the membership (never touching existing ones), clicking a
# checked group removes it. The GROUP column shows the full " · "-joined
# list (primary first) with the un-elided list in the tooltip; the
# inspector combo edits the PRIMARY slot only.
# ---------------------------------------------------------------------------

def _membership_config():
    """P1 in Wash, P2 ungrouped, P3 in Wash + Spots (Wash primary)."""
    from config.models import (Configuration, Fixture, FixtureGroup,
                               FixtureMode, Universe)

    def mk(name, address, groups=()):
        return Fixture(universe=0, address=address, manufacturer="M",
                       model="X", name=name, groups=list(groups),
                       current_mode="Std",
                       available_modes=[FixtureMode(name="Std", channels=4)],
                       type="PAR")

    fixtures = [mk("P1", 1, ["Wash"]), mk("P2", 5),
                mk("P3", 9, ["Wash", "Spots"])]
    groups = {
        "Wash": FixtureGroup("Wash", [fixtures[0], fixtures[2]],
                             lighting_role="wash"),
        "Spots": FixtureGroup("Spots", [fixtures[2]]),
    }
    return Configuration(
        fixtures=fixtures, groups=groups,
        universes={0: Universe(id=0, name="U0", output={})})


def _assign_submenu(tab):
    menu = tab._build_table_context_menu()
    submenus = [a.menu() for a in menu.actions() if a.menu() is not None]
    return next(m for m in submenus if m.title().startswith("Assign"))


def test_assign_adds_membership_keeps_existing(qapp):
    """The user's bug: assigning a grouped fixture to a second group must
    ADD the membership, not replace the first one. Primary stays first."""
    tab = _make_tab(qapp, _membership_config())
    try:
        _select_rows(tab, [0])  # P1, already in Wash
        tab._assign_selected_to_group("Spots")
        fixture = tab.config.fixtures[0]
        assert fixture.groups == ["Wash", "Spots"]
        assert fixture.group == "Wash"  # primary unchanged
        assert tab.table.item(0, COL_GROUP).text() == "WASH · SPOTS"
    finally:
        tab.deleteLater()


def test_assign_removes_membership_when_selection_has_it(qapp):
    tab = _make_tab(qapp, _membership_config())
    try:
        _select_rows(tab, [2])  # P3 in Wash + Spots
        tab._assign_selected_to_group("Spots")
        assert tab.config.fixtures[2].groups == ["Wash"]
        assert tab.table.item(2, COL_GROUP).text() == "WASH"
    finally:
        tab.deleteLater()


def test_multi_select_partial_membership_adds_to_missing(qapp):
    """P1 (Wash) + P3 (Wash, Spots) selected, click Spots: only P1 gains
    it; P3's memberships stay exactly as they were."""
    tab = _make_tab(qapp, _membership_config())
    try:
        _select_rows(tab, [0, 2])
        tab._assign_selected_to_group("Spots")
        assert tab.config.fixtures[0].groups == ["Wash", "Spots"]
        assert tab.config.fixtures[2].groups == ["Wash", "Spots"]
    finally:
        tab.deleteLater()


def test_assign_menu_checkstate_reflects_membership(qapp):
    tab = _make_tab(qapp, _membership_config())
    try:
        _select_rows(tab, [0, 2])
        assign = _assign_submenu(tab)
        actions = {a.text(): a for a in assign.actions() if a.text()}
        # Both selected fixtures are in Wash -> checked.
        assert actions["Wash"].isCheckable()
        assert actions["Wash"].isChecked()
        # Only P3 is in Spots -> partial membership shows unchecked
        # (clicking would add to the missing ones).
        assert actions["Spots"].isCheckable()
        assert not actions["Spots"].isChecked()
    finally:
        tab.deleteLater()


def test_make_primary_reorders_membership(qapp):
    tab = _make_tab(qapp, _membership_config())
    try:
        _select_rows(tab, [2])
        tab._make_selected_primary("Spots")
        fixture = tab.config.fixtures[2]
        assert fixture.groups == ["Spots", "Wash"]
        assert fixture.group == "Spots"
        assert tab.table.item(2, COL_GROUP).text() == "SPOTS · WASH"
        # The row visuals follow the new primary group's color.
        fg = tab.table.item(2, COL_GROUP).foreground().color()
        assert fg.name() == tab._ensure_group_color("Spots")
    finally:
        tab.deleteLater()


def test_make_primary_submenu_only_for_multi_group_single_selection(qapp):
    tab = _make_tab(qapp, _membership_config())
    try:
        _select_rows(tab, [2])  # P3 has two groups
        assign = _assign_submenu(tab)
        primary = next((a.menu() for a in assign.actions()
                        if a.menu() is not None
                        and a.menu().title() == "Make primary"), None)
        assert primary is not None
        entries = {a.text(): a for a in primary.actions()}
        assert list(entries) == ["Wash", "Spots"]
        assert entries["Wash"].isChecked()       # current primary
        assert not entries["Spots"].isChecked()

        _select_rows(tab, [0])  # single-group fixture: no reorder to offer
        assign = _assign_submenu(tab)
        assert all(a.menu() is None or a.menu().title() != "Make primary"
                   for a in assign.actions())
    finally:
        tab.deleteLater()


def test_group_column_joined_text_and_tooltip(qapp):
    tab = _make_tab(qapp, _membership_config())
    try:
        item = tab.table.item(2, COL_GROUP)
        assert item.text() == "WASH · SPOTS"
        assert item.toolTip() == "Wash (primary) · Spots"
        # Single-group rows keep the plain name; no primary flag needed.
        assert tab.table.item(0, COL_GROUP).text() == "WASH"
        assert tab.table.item(0, COL_GROUP).toolTip() == "Wash"
        assert tab.table.item(1, COL_GROUP).text() == ""
        assert tab.table.item(1, COL_GROUP).toolTip() == ""
    finally:
        tab.deleteLater()


def test_duplicate_copies_full_membership(qapp):
    tab = _make_tab(qapp, _membership_config())
    try:
        _select_rows(tab, [2])
        tab._duplicate_fixture()
        copy = tab.config.fixtures[-1]
        assert copy.name == "P3 (Copy)"
        assert copy.groups == ["Wash", "Spots"]
        # Independent list: editing the copy must not touch the original.
        assert copy.groups is not tab.config.fixtures[2].groups
        assert copy in tab.config.groups["Wash"].fixtures
        assert copy in tab.config.groups["Spots"].fixtures
    finally:
        tab.deleteLater()


# ---------------------------------------------------------------------------
# Multi-group candy stripes (row background texture)
#
# A fixture in 2+ groups gets a diagonal candy-stripe row background
# cycling through its memberships' tints (primary band first), slanted
# a little off vertical; single-group rows keep the solid tint. The
# tile is a cached, deterministic QPixmap (group_stripe_pixmap) set as
# a texture brush on every item of the row.
# ---------------------------------------------------------------------------

def test_stripe_tile_alternates_colors_along_scanline(qapp):
    from gui.tabs.fixtures_tab import STRIPE_WIDTH, group_stripe_pixmap

    c0, c1 = "#402515", "#153040"
    tile = group_stripe_pixmap((c0, c1))
    image = tile.toImage()
    assert tile.width() == 2 * STRIPE_WIDTH
    mid = STRIPE_WIDTH // 2
    # y=0: the first band is the PRIMARY colour, then the next member.
    assert image.pixelColor(mid, 0).name() == c0
    assert image.pixelColor(STRIPE_WIDTH + mid, 0).name() == c1
    # Band boundary exactly at STRIPE_WIDTH on the top scanline.
    assert image.pixelColor(STRIPE_WIDTH - 1, 0).name() == c0
    assert image.pixelColor(STRIPE_WIDTH, 0).name() == c1


def test_stripe_tile_three_colors_cycle_in_membership_order(qapp):
    from gui.tabs.fixtures_tab import STRIPE_WIDTH, group_stripe_pixmap

    colors = ("#402515", "#153040", "#154025")
    tile = group_stripe_pixmap(colors)
    image = tile.toImage()
    assert tile.width() == 3 * STRIPE_WIDTH
    mid = STRIPE_WIDTH // 2
    for i, expected in enumerate(colors):
        assert image.pixelColor(i * STRIPE_WIDTH + mid, 0).name() == expected


def test_stripe_tile_skew_direction_and_angle(qapp):
    """Boundaries slant a LITTLE off vertical (15-20 degrees, not 45),
    bands shifting RIGHT as y grows, consistently for every tile."""
    import math
    from gui.tabs.fixtures_tab import group_stripe_pixmap

    c0, c1 = "#402515", "#153040"
    tile = group_stripe_pixmap((c0, c1))
    image = tile.toImage()
    period = tile.width()
    # Tile geometry: the skew across the full height is one period.
    angle = math.degrees(math.atan(period / tile.height()))
    assert 15.0 <= angle <= 20.0

    def first_c0_to_c1_boundary(y):
        prev = image.pixelColor(0, y).name()
        for x in range(1, period):
            cur = image.pixelColor(x, y).name()
            if prev == c0 and cur == c1:
                return x
            prev = cur
        raise AssertionError(f"no c0->c1 boundary on scanline {y}")

    y = 30  # deep enough for a multi-pixel shift, above the wrap point
    top, lower = first_c0_to_c1_boundary(0), first_c0_to_c1_boundary(y)
    assert lower > top  # boundary moves RIGHT going down
    # ... by about tan(angle) px per scanline (integer steps allow 2px).
    assert abs((lower - top) - math.tan(math.radians(18.0)) * y) <= 2.0


def test_stripe_tile_cache_returns_same_object(qapp):
    from gui.tabs.fixtures_tab import group_stripe_pixmap

    a = group_stripe_pixmap(("#402515", "#153040"))
    b = group_stripe_pixmap(("#402515", "#153040"))
    assert a is b
    # Order is part of the identity (primary band first).
    c = group_stripe_pixmap(("#153040", "#402515"))
    assert c is not a


def test_multi_group_row_carries_striped_texture(qapp):
    """P3 (Wash + Spots) gets the texture brush on EVERY column; P1
    (Wash only) keeps the solid tint; the GROUP cell text colour stays
    the primary group's."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor
    from gui.theme_tokens import DARK
    from gui.tabs.fixtures_tab import group_stripe_pixmap, group_tint_color

    tab = _make_tab(qapp, _membership_config())
    try:
        base = QColor(DARK["panel"])
        expected = group_stripe_pixmap(tuple(
            group_tint_color(QColor(tab._ensure_group_color(g)), base).name()
            for g in ("Wash", "Spots")))
        for col in range(tab.table.columnCount()):
            brush = tab.table.item(2, col).background()
            assert brush.style() == Qt.BrushStyle.TexturePattern, \
                f"column {col} must carry the stripe texture"
            assert brush.texture().cacheKey() == expected.cacheKey()

        solid = tab.table.item(0, COL_FIXTURE).background()
        assert solid.style() == Qt.BrushStyle.SolidPattern
        wash = QColor(tab._ensure_group_color("Wash"))
        assert solid.color().name() == group_tint_color(wash, base).name()

        fg = tab.table.item(2, COL_GROUP).foreground().color()
        assert fg.name() == tab._ensure_group_color("Wash")
    finally:
        tab.deleteLater()


def test_membership_edit_flips_stripes_and_solid(qapp):
    """Crossing the 1<->2 membership boundary via the Assign menu path
    swaps the row between solid tint and stripes both ways."""
    from PyQt6.QtCore import Qt

    tab = _make_tab(qapp, _membership_config())
    try:
        assert (tab.table.item(0, COL_FIXTURE).background().style()
                == Qt.BrushStyle.SolidPattern)
        _select_rows(tab, [0])  # P1, Wash only
        tab._assign_selected_to_group("Spots")
        assert (tab.table.item(0, COL_FIXTURE).background().style()
                == Qt.BrushStyle.TexturePattern)
        # Selection has it now, so the same call removes the membership.
        _select_rows(tab, [0])
        tab._assign_selected_to_group("Spots")
        assert (tab.table.item(0, COL_FIXTURE).background().style()
                == Qt.BrushStyle.SolidPattern)
    finally:
        tab.deleteLater()


def test_primary_change_reorders_stripe_colors(qapp):
    """Make primary reorders the bands: the first band takes the new
    primary group's tint (deterministic stripe order)."""
    from PyQt6.QtGui import QColor
    from gui.theme_tokens import DARK
    from gui.tabs.fixtures_tab import STRIPE_WIDTH, group_tint_color

    tab = _make_tab(qapp, _membership_config())
    try:
        base = QColor(DARK["panel"])
        _select_rows(tab, [2])
        tab._make_selected_primary("Spots")
        tile = (tab.table.item(2, COL_FIXTURE).background()
                .texture().toImage())
        spots = group_tint_color(
            QColor(tab._ensure_group_color("Spots")), base)
        assert tile.pixelColor(STRIPE_WIDTH // 2, 0).name() == spots.name()
    finally:
        tab.deleteLater()


def test_delete_group_removes_membership_not_fixtures(qapp):
    tab = _make_tab(qapp, _membership_config())
    try:
        tab._delete_group("Wash")
        assert "Wash" not in tab.config.groups
        # Fixtures survive; only the membership is gone. P3's remaining
        # group is promoted to primary.
        names = [f.name for f in tab.config.fixtures]
        assert names == ["P1", "P2", "P3"]
        assert tab.config.fixtures[0].groups == []
        assert tab.config.fixtures[2].groups == ["Spots"]
        assert tab.config.fixtures[2].group == "Spots"
        assert tab.table.item(2, COL_GROUP).text() == "SPOTS"
    finally:
        tab.deleteLater()


def test_group_row_menu_offers_delete(qapp, sample_configuration,
                                      monkeypatch):
    from PyQt6 import QtCore
    tab = _make_tab(qapp, sample_configuration)
    try:
        captured = {}

        def fake_exec(self, *a):
            captured["labels"] = [x.text() for x in self.actions() if x.text()]
            return None
        monkeypatch.setattr(QtWidgets.QMenu, "exec", fake_exec)
        tab._show_group_context_menu("TestGroup", QtCore.QPoint(0, 0))
        assert "Delete group" in captured["labels"]
    finally:
        monkeypatch.undo()
        tab.deleteLater()


def test_after_group_assignment_refreshes_full_membership_text(qapp):
    """The multi-assign refresh path must rewrite the GROUP cells from the
    FULL membership list, not just the primary group."""
    tab = _make_tab(qapp, _membership_config())
    try:
        tab.config.fixtures[1].groups.append("Wash")
        tab.config.fixtures[1].groups.append("Spots")
        tab._after_group_assignment("Spots")
        item = tab.table.item(1, COL_GROUP)
        assert item.text() == "WASH · SPOTS"
        assert item.toolTip() == "Wash (primary) · Spots"
    finally:
        tab.deleteLater()


def test_new_group_flow_adds_membership(qapp):
    from unittest.mock import patch
    tab = _make_tab(qapp, _membership_config())
    try:
        _select_rows(tab, [0])  # P1 in Wash
        with patch.object(QtWidgets.QInputDialog, "getText",
                          return_value=("Fresh", True)):
            tab._assign_selected_to_new_group()
        assert tab.config.fixtures[0].groups == ["Wash", "Fresh"]
        assert "Fresh" in tab.config.groups
    finally:
        tab.deleteLater()


def test_ungroup_clears_all_memberships(qapp):
    tab = _make_tab(qapp, _membership_config())
    try:
        _select_rows(tab, [2])
        tab._assign_selected_to_group("")
        assert tab.config.fixtures[2].groups == []
        assert tab.table.item(2, COL_GROUP).text() == ""
    finally:
        tab.deleteLater()


def test_inspector_primary_combo_keeps_secondaries(qapp):
    """The inspector's group combo (labelled "Primary group") edits
    groups[0] only: switching P3's primary from Wash to a third group
    leaves the Spots membership alone."""
    tab = _make_tab(qapp, _membership_config())
    try:
        tab._create_group("Third")
        _select_rows(tab, [2])
        tab.insp_group.setCurrentText("Third")
        assert tab.config.fixtures[2].groups == ["Third", "Spots"]
    finally:
        tab.deleteLater()


def test_inspector_primary_combo_blank_promotes_next_group(qapp):
    tab = _make_tab(qapp, _membership_config())
    try:
        _select_rows(tab, [2])
        tab.insp_group.setCurrentText("")
        # Primary membership dropped; Spots is promoted.
        assert tab.config.fixtures[2].groups == ["Spots"]
    finally:
        tab.deleteLater()


def test_inspector_primary_combo_promotes_existing_secondary(qapp):
    """Picking a group the fixture is already a secondary member of makes
    it the sole primary (the old primary membership is what the primary-
    slot edit replaces; the pick is deduped, not doubled)."""
    tab = _make_tab(qapp, _membership_config())
    try:
        _select_rows(tab, [2])
        tab.insp_group.setCurrentText("Spots")
        assert tab.config.fixtures[2].groups == ["Spots"]
    finally:
        tab.deleteLater()


def test_auto_patch_footer_text_is_gone(qapp, sample_configuration):
    tab = _make_tab(qapp, sample_configuration)
    try:
        assert not hasattr(tab, "autopatch_label")
    finally:
        tab.deleteLater()


# ---------------------------------------------------------------------------
# DMX address conflict indicators
#
# Contract: fixtures whose (universe, address range) footprints overlap
# get the red background + white text + a tooltip naming the other
# fixture on their UNI/ADDRESS display items, and the action-strip chip
# shows the issue count. Resolving the conflict via the inspector's
# Address spin clears all of it (no full rebuild involved).
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
    config = _overlapping_config(sample_configuration)
    tab = _make_tab(qapp, config)
    try:
        assert tab.conflict_label.isVisibleTo(tab)
        assert "1 DMX ADDRESSING ISSUE" in tab.conflict_label.text()

        for row, other_name in ((0, "Test Fixture 2"), (1, "Test Fixture 1")):
            for col in (COL_UNI, COL_ADDRESS):
                item = tab.table.item(row, col)
                assert item.background().color().name() == CONFLICT_BG
                assert other_name in item.toolTip()
                assert "channels 5-10" in item.toolTip()
    finally:
        tab.deleteLater()


def test_resolving_conflict_clears_flags(qapp, sample_configuration):
    config = _overlapping_config(sample_configuration)
    tab = _make_tab(qapp, config)
    try:
        # Move the second fixture clear of the first (1-10 -> 11-20)
        # through the inspector, the only write path.
        tab.table.selectRow(1)
        tab.insp_address.setValue(11)

        assert not tab.conflict_label.isVisibleTo(tab)
        for row in (0, 1):
            for col in (COL_UNI, COL_ADDRESS):
                item = tab.table.item(row, col)
                assert item.background().color().name() != CONFLICT_BG
                assert item.toolTip() == ""
        assert tab.table.item(1, COL_ADDRESS).text() == "011-020"
    finally:
        tab.deleteLater()


def test_overflow_past_universe_end_is_flagged(qapp, sample_configuration):
    tab = _make_tab(qapp, sample_configuration)
    try:
        # 10-channel fixture at 510 runs to 519, past the 512 limit.
        tab.insp_address.setValue(510)

        assert tab.conflict_label.isVisibleTo(tab)
        item = tab.table.item(0, COL_ADDRESS)
        assert item.background().color().name() == CONFLICT_BG
        assert "ends at channel 519" in item.toolTip()
    finally:
        tab.deleteLater()


# ---------------------------------------------------------------------------
# Untangle / Compact addressing actions (v1.3)
# ---------------------------------------------------------------------------

def _addressed_config(addresses, channels=10):
    """A config with N fixtures on universe 1 at the given addresses."""
    from config.models import Configuration, Fixture, FixtureMode
    fixtures = [
        Fixture(universe=1, address=a, manufacturer="M", model="X",
                name=f"F{i}", group="G", current_mode="Std",
                available_modes=[FixtureMode(name="Std",
                                             channels=channels)])
        for i, a in enumerate(addresses)
    ]
    return Configuration(fixtures=fixtures, universes={})


def test_menu_offers_addressing_actions_even_without_row(qapp,
                                                         sample_configuration):
    tab = _make_tab(qapp, sample_configuration)
    try:
        for has_row in (True, False):
            menu = tab._build_table_context_menu(has_row=has_row)
            names = {a.text() for a in menu.actions() if a.text()}
            assert {"Untangle addresses", "Compact addresses"} <= names
    finally:
        tab.deleteLater()


def test_untangle_enabled_follows_the_lint(qapp):
    clean = _addressed_config([1, 11])
    tangled = _addressed_config([1, 5])
    for config, expected in ((clean, False), (tangled, True)):
        tab = _make_tab(qapp, config)
        try:
            menu = tab._build_table_context_menu()
            action = next(a for a in menu.actions()
                          if a.text() == "Untangle addresses")
            assert action.isEnabled() is expected
        finally:
            tab.deleteLater()


def test_untangle_resolves_the_config_and_clears_the_chip(qapp):
    tab = _make_tab(qapp, _addressed_config([1, 5]))
    try:
        assert not tab.conflict_label.isHidden()
        tab._untangle_addresses()
        from utils.dmx_conflicts import lint_dmx_addresses
        assert lint_dmx_addresses(tab.config.fixtures).is_clean
        assert tab.config.fixtures[0].address == 1   # incumbent stays
        assert tab.config.fixtures[1].address == 11  # nearest free
        assert tab.conflict_label.isHidden()
    finally:
        tab.deleteLater()


def test_compact_packs_the_universe(qapp):
    tab = _make_tab(qapp, _addressed_config([41, 101, 1]))
    try:
        tab._compact_addresses()
        assert [f.address for f in tab.config.fixtures] == [11, 21, 1]
    finally:
        tab.deleteLater()


def test_unresolved_fixtures_are_named_in_a_warning(qapp, monkeypatch):
    from PyQt6 import QtWidgets
    tab = _make_tab(qapp, _addressed_config([1, 5], channels=300))
    try:
        warnings = []
        monkeypatch.setattr(
            QtWidgets.QMessageBox, "warning",
            staticmethod(lambda parent, title, text: warnings.append(text)))
        tab._untangle_addresses()   # two 300-wide fixtures cannot both fit
        assert warnings and "F1" in warnings[0]
        assert tab.config.fixtures[1].address == 5   # left unchanged
    finally:
        tab.deleteLater()
