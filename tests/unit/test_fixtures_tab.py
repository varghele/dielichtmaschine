"""
FixturesTab, rebuilt to the reference screen 02 (Setup Fixtures).

Contract under test:
- Action strip: DMX-conflict chip (hidden when clean) left, accent
  "+ ADD FIXTURE" CTA right. No tab title row.
- GROUPS panel: one row per group (name caps, "N FIX" mono, role line),
  "+" add-group button, clicking a row selects that group's fixtures.
- Table: read-only display items in reference column order
  (# / FIXTURE / TYPE / MODE / UNI / ADDRESS / GROUP), group-tinted row
  backgrounds at low alpha, group names in the group color, red
  UNI/ADDRESS cells + tooltip on DMX conflicts.
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


def test_empty_click_menu_only_offers_add(qapp, sample_configuration):
    """Right-clicking past the last row offers just Add fixture (no row to
    duplicate/remove/assign)."""
    tab = _make_tab(qapp, sample_configuration)
    try:
        menu = tab._build_table_context_menu(has_row=False)
        labels = [a.text() for a in menu.actions() if a.text()]
        assert labels == ["Add fixture..."]
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
        # Membership is not copied (a fixture belongs to one group).
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
