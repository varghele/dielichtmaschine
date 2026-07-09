"""Stage layers (named Z-planes with per-layer visibility).

Contract under test:
- StageLayer + Fixture.layer round-trip through config YAML.
- Configuration.is_fixture_visible: hidden only when the fixture sits on
  a layer that exists and is unchecked; no layer / dangling name = visible.
- build_fixtures_payload omits fixtures on hidden layers (this is the one
  filter point shared by the embedded previews and the TCP visualizer).
- StageView hides/shows items per layer and assignment snaps Z to the
  layer plane.
- StageTab's layer panel: list refresh, visibility toggle, edit (rename +
  move plane with its fixtures), remove (fixtures keep height, lose tag).
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from config.models import (
    Configuration, Fixture, FixtureGroup, FixtureMode, StageLayer, Universe,
)


def make_fixture(name, layer="", z=0.0, group=""):
    return Fixture(
        universe=1, address=1,
        manufacturer="TestMfr", model="TestModel",
        name=name, group=group,
        current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
        z=z, z_uses_group_default=False,
        layer=layer,
    )


@pytest.fixture
def layered_config():
    f_ground = make_fixture("Ground Par", layer="Ground", z=0.0)
    f_top = make_fixture("Top Wash", layer="Top truss", z=5.0)
    f_free = make_fixture("Floater", layer="", z=2.0)
    return Configuration(
        fixtures=[f_ground, f_top, f_free],
        universes={1: Universe(id=1, name="Universe 1", output={})},
        stage_layers=[
            StageLayer(name="Ground", z_height=0.0, visible=True),
            StageLayer(name="Top truss", z_height=5.0, visible=False),
        ],
    )


class TestModel:

    def test_yaml_round_trip(self, layered_config, tmp_path):
        path = str(tmp_path / "config.yaml")
        layered_config.save(path)
        loaded = Configuration.load(path)

        assert loaded.stage_layers == [
            StageLayer(name="Ground", z_height=0.0, visible=True),
            StageLayer(name="Top truss", z_height=5.0, visible=False),
        ]
        assert [f.layer for f in loaded.fixtures] == ["Ground", "Top truss", ""]

    def test_config_without_layers_loads_empty(self, tmp_path):
        config = Configuration(fixtures=[make_fixture("A")])
        path = str(tmp_path / "config.yaml")
        config.save(path)
        # Simulate a pre-layers config: strip the new keys from the YAML.
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        data.pop('stage_layers', None)
        for f_data in data['fixtures']:
            f_data.pop('layer', None)
        with open(path, 'w') as f:
            yaml.dump(data, f)

        loaded = Configuration.load(path)
        assert loaded.stage_layers == []
        assert loaded.fixtures[0].layer == ""

    def test_is_fixture_visible(self, layered_config):
        ground, top, free = layered_config.fixtures
        assert layered_config.is_fixture_visible(ground) is True
        assert layered_config.is_fixture_visible(top) is False   # hidden layer
        assert layered_config.is_fixture_visible(free) is True   # no layer

        # Dangling layer name (layer deleted): visible.
        free.layer = "NoSuchLayer"
        assert layered_config.is_fixture_visible(free) is True


class TestVisualizerPayload:

    def test_hidden_layer_omitted_from_payload(self, layered_config):
        from utils.tcp.protocol import VisualizerProtocol
        payload = VisualizerProtocol.build_fixtures_payload(layered_config)
        names = {f["name"] for f in payload}
        assert names == {"Ground Par", "Floater"}

        layered_config.get_stage_layer("Top truss").visible = True
        payload = VisualizerProtocol.build_fixtures_payload(layered_config)
        assert {f["name"] for f in payload} == {"Ground Par", "Top Wash", "Floater"}


class TestStageView:

    def test_visibility_applied_from_config(self, qapp, layered_config):
        from gui.StageView import StageView
        view = StageView(None)
        try:
            view.set_config(layered_config)
            assert view.fixtures["Ground Par"].isVisible()
            assert not view.fixtures["Top Wash"].isVisible()
            assert view.fixtures["Floater"].isVisible()

            layered_config.get_stage_layer("Top truss").visible = True
            view.apply_layer_visibility()
            assert view.fixtures["Top Wash"].isVisible()
        finally:
            view.deleteLater()

    def test_assignment_snaps_z_to_layer_plane(self, qapp, layered_config):
        from gui.StageView import StageView
        view = StageView(None)
        try:
            view.set_config(layered_config)
            item = view.fixtures["Floater"]
            item.setSelected(True)

            view.assign_selected_to_layer("Ground")
            fixture = layered_config.fixtures[2]
            assert fixture.layer == "Ground"
            assert fixture.z == 0.0
            assert fixture.z_uses_group_default is False

            # Clearing keeps the height, drops the tag.
            view.assign_selected_to_layer("")
            assert fixture.layer == ""
            assert fixture.z == 0.0
        finally:
            view.deleteLater()


class TestStageTab:

    @pytest.fixture
    def tab(self, qapp, layered_config):
        from gui.tabs.stage_tab import StageTab
        tab = StageTab(layered_config, parent=None)
        tab.update_from_config()
        yield tab
        tab.deleteLater()

    def test_layer_list_reflects_config(self, tab):
        from PyQt6.QtCore import Qt
        assert tab.layer_list.count() == 2
        first, second = tab.layer_list.item(0), tab.layer_list.item(1)
        assert first.text() == "Ground (0 m)"
        assert first.checkState() == Qt.CheckState.Checked
        assert second.text() == "Top truss (5 m)"
        assert second.checkState() == Qt.CheckState.Unchecked

    def test_toggle_visibility_via_checkbox(self, tab, layered_config):
        from PyQt6.QtCore import Qt
        item = tab.layer_list.item(1)  # Top truss, hidden
        item.setCheckState(Qt.CheckState.Checked)  # fires itemChanged

        assert layered_config.get_stage_layer("Top truss").visible is True
        assert tab.stage_view.fixtures["Top Wash"].isVisible()

    def test_edit_layer_moves_plane_with_fixtures(self, tab, layered_config, monkeypatch):
        monkeypatch.setattr(tab, "_layer_dialog", lambda *a, **k: ("Mid truss", 3.5))
        tab.layer_list.setCurrentRow(1)  # Top truss
        tab._edit_layer()

        layer = layered_config.get_stage_layer("Mid truss")
        assert layer is not None and layer.z_height == 3.5
        assert layered_config.get_stage_layer("Top truss") is None
        fixture = layered_config.fixtures[1]
        assert fixture.layer == "Mid truss"
        assert fixture.z == 3.5

    def test_remove_layer_keeps_fixture_height(self, tab, layered_config, monkeypatch):
        from PyQt6 import QtWidgets
        monkeypatch.setattr(
            QtWidgets.QMessageBox, "question",
            lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes,
        )
        tab.layer_list.setCurrentRow(1)  # Top truss
        tab._remove_layer()

        assert layered_config.get_stage_layer("Top truss") is None
        fixture = layered_config.fixtures[1]
        assert fixture.layer == ""
        assert fixture.z == 5.0
        # No longer on a hidden layer -> visible again.
        assert tab.stage_view.fixtures["Top Wash"].isVisible()

    def test_add_layer(self, tab, layered_config, monkeypatch):
        monkeypatch.setattr(tab, "_layer_dialog", lambda *a, **k: ("Booms", 1.5))
        tab._add_layer()
        layer = layered_config.get_stage_layer("Booms")
        assert layer is not None
        assert layer.z_height == 1.5
        assert tab.layer_list.count() == 3


class TestActiveLayerView:
    """StageView active-layer editing: only the active layer's fixtures
    stay interactive; everything else (other layers AND unassigned)
    ghosts — faint, unselectable, undraggable."""

    @pytest.fixture
    def view(self, qapp, layered_config):
        from gui.StageView import StageView
        layered_config.get_stage_layer("Top truss").visible = True
        view = StageView(None)
        view.set_config(layered_config)
        yield view
        view.deleteLater()

    def test_activating_ghosts_everything_off_layer(self, view):
        from PyQt6.QtWidgets import QGraphicsItem

        view.set_active_layer("Ground")

        member = view.fixtures["Ground Par"]
        assert member.ghosted is False
        assert member.opacity() == 1.0

        for name in ("Top Wash", "Floater"):  # other layer + unassigned
            ghost = view.fixtures[name]
            assert ghost.ghosted is True
            assert ghost.opacity() < 0.3
            assert not (ghost.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
            assert not (ghost.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)

    def test_ghosting_clears_selection(self, view):
        floater = view.fixtures["Floater"]
        floater.setSelected(True)
        view.set_active_layer("Ground")
        assert not floater.isSelected()

    def test_deactivating_restores_everything(self, view):
        from PyQt6.QtWidgets import QGraphicsItem
        view.set_active_layer("Ground")
        view.set_active_layer(None)
        for item in view.fixtures.values():
            assert item.ghosted is False
            assert item.opacity() == 1.0
            assert item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable

    def test_unknown_layer_treated_as_none(self, view):
        view.set_active_layer("NoSuchLayer")
        assert view.active_layer is None
        assert all(not i.ghosted for i in view.fixtures.values())

    def test_new_config_resets_active_layer(self, view):
        view.set_active_layer("Ground")
        view.set_config(Configuration())
        assert view.active_layer is None


class TestActiveLayerTab:

    @pytest.fixture
    def tab(self, qapp, layered_config):
        from gui.tabs.stage_tab import StageTab
        tab = StageTab(layered_config, parent=None)
        tab.update_from_config()
        yield tab
        tab.deleteLater()

    def test_cycle_goes_all_then_each_layer_then_all(self, tab):
        assert tab.stage_view.active_layer is None
        tab._cycle_active_layer()
        assert tab.stage_view.active_layer == "Ground"
        tab._cycle_active_layer()
        assert tab.stage_view.active_layer == "Top truss"
        tab._cycle_active_layer()
        assert tab.stage_view.active_layer is None

    def test_double_click_toggles(self, tab):
        item = tab.layer_list.item(0)  # Ground
        tab._on_layer_double_clicked(item)
        assert tab.stage_view.active_layer == "Ground"
        assert "Ground only" in tab.active_layer_label.text()
        tab._on_layer_double_clicked(item)
        assert tab.stage_view.active_layer is None
        assert "all layers" in tab.active_layer_label.text()

    def test_activating_hidden_layer_forces_it_visible(self, tab, layered_config):
        # Top truss starts hidden in layered_config.
        assert layered_config.get_stage_layer("Top truss").visible is False
        tab._set_active_layer("Top truss")
        assert layered_config.get_stage_layer("Top truss").visible is True
        assert tab.stage_view.fixtures["Top Wash"].isVisible()

    def test_hiding_active_layer_ends_editing(self, tab, layered_config):
        from PyQt6.QtCore import Qt
        tab._set_active_layer("Ground")
        tab.layer_list.item(0).setCheckState(Qt.CheckState.Unchecked)
        assert tab.stage_view.active_layer is None

    def test_removing_active_layer_ends_editing(self, tab, layered_config, monkeypatch):
        from PyQt6 import QtWidgets
        monkeypatch.setattr(
            QtWidgets.QMessageBox, "question",
            lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes,
        )
        tab._set_active_layer("Ground")
        tab.layer_list.setCurrentRow(0)
        tab._remove_layer()
        assert tab.stage_view.active_layer is None
        assert all(not i.ghosted for i in tab.stage_view.fixtures.values())

    def test_renaming_active_layer_follows(self, tab, layered_config, monkeypatch):
        tab._set_active_layer("Ground")
        monkeypatch.setattr(tab, "_layer_dialog", lambda *a, **k: ("Deck", 0.0))
        tab.layer_list.setCurrentRow(0)
        tab._edit_layer()
        assert tab.stage_view.active_layer == "Deck"
        # Still ghosting the non-members after the rebuild.
        assert tab.stage_view.fixtures["Top Wash"].ghosted is True


class TestLayerChipRow:
    """North Star 5a layer chip row above the canvas: one checkable chip
    per layer ('NAME · <z>M' mono caps), an ALL chip (= no active layer)
    and a + LAYER chip. Chips drive the same active-layer editing mode
    as the panel list."""

    @pytest.fixture
    def tab(self, qapp, layered_config):
        from gui.tabs.stage_tab import StageTab
        tab = StageTab(layered_config, parent=None)
        tab.update_from_config()
        yield tab
        tab.deleteLater()

    def test_chips_reflect_layers(self, tab):
        assert set(tab.layer_chips) == {"Ground", "Top truss"}
        assert tab.layer_chips["Ground"].text() == "GROUND · 0M"
        assert tab.layer_chips["Top truss"].text() == "TOP TRUSS · 5M"
        # No active layer -> ALL is the checked (accent) chip.
        assert tab.all_layers_chip.isChecked()
        assert tab.layer_lock_hint.isHidden()

    def test_chip_click_activates_layer(self, tab):
        tab.layer_chips["Ground"].click()
        assert tab.stage_view.active_layer == "Ground"
        assert tab.layer_chips["Ground"].isChecked()
        assert not tab.all_layers_chip.isChecked()
        assert not tab.layer_lock_hint.isHidden()
        # Ghosting applied exactly like the list double-click path.
        assert tab.stage_view.fixtures["Floater"].ghosted is True

    def test_chip_click_on_hidden_layer_forces_it_visible(self, tab, layered_config):
        assert layered_config.get_stage_layer("Top truss").visible is False
        tab.layer_chips["Top truss"].click()
        assert layered_config.get_stage_layer("Top truss").visible is True
        assert tab.stage_view.fixtures["Top Wash"].isVisible()

    def test_all_chip_returns_to_all_layers(self, tab):
        tab.layer_chips["Ground"].click()
        tab.all_layers_chip.click()
        assert tab.stage_view.active_layer is None
        assert tab.all_layers_chip.isChecked()
        assert tab.layer_lock_hint.isHidden()
        assert all(not i.ghosted for i in tab.stage_view.fixtures.values())

    def test_external_activation_syncs_chips(self, tab):
        # L-shortcut / list double-click path must reflect on the chips.
        tab._cycle_active_layer()  # all -> Ground
        assert tab.layer_chips["Ground"].isChecked()
        tab._set_active_layer(None)
        assert tab.all_layers_chip.isChecked()

    def test_add_layer_chip_uses_add_flow(self, tab, layered_config, monkeypatch):
        monkeypatch.setattr(tab, "_layer_dialog", lambda *a, **k: ("Booms", 1.5))
        tab.add_layer_chip.click()
        assert layered_config.get_stage_layer("Booms") is not None
        assert "Booms" in tab.layer_chips
        assert tab.layer_chips["Booms"].text() == "BOOMS · 1.5M"

    def test_chips_follow_rename_and_remove(self, tab, layered_config, monkeypatch):
        from PyQt6 import QtWidgets

        monkeypatch.setattr(tab, "_layer_dialog", lambda *a, **k: ("Deck", 0.8))
        tab.layer_list.setCurrentRow(0)  # Ground
        tab._edit_layer()
        assert "Ground" not in tab.layer_chips
        assert tab.layer_chips["Deck"].text() == "DECK · 0.8M"

        # Removing goes through a confirm when fixtures are assigned.
        monkeypatch.setattr(
            QtWidgets.QMessageBox, "question",
            lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes,
        )
        tab.layer_list.setCurrentRow(0)  # Deck
        tab._remove_layer()
        assert "Deck" not in tab.layer_chips

    def test_set_layer_visible_reuses_checkbox_path(self, tab, layered_config):
        tab._set_layer_visible("Top truss", True)
        assert layered_config.get_stage_layer("Top truss").visible is True
        assert tab.stage_view.fixtures["Top Wash"].isVisible()
        item = tab.layer_list.item(1)
        from PyQt6.QtCore import Qt
        assert item.checkState() == Qt.CheckState.Checked

        tab._set_layer_visible("Top truss", False)
        assert layered_config.get_stage_layer("Top truss").visible is False
        assert not tab.stage_view.fixtures["Top Wash"].isVisible()


class TestInspectorLayerCombo:
    """The inspector's LAYER field assigns the selection through the
    same StageView code path as right-click > Assign to Layer."""

    @pytest.fixture
    def tab(self, qapp, layered_config):
        from gui.tabs.stage_tab import StageTab
        tab = StageTab(layered_config, parent=None)
        tab.update_from_config()
        yield tab
        tab.deleteLater()

    def test_combo_lists_layers(self, tab):
        texts = [tab.layer_combo.itemText(i)
                 for i in range(tab.layer_combo.count())]
        assert texts == ["No layer", "Ground · 0 m", "Top truss · 5 m"]
        # Disabled until something is selected.
        assert not tab.layer_combo.isEnabled()

    def test_combo_follows_selection(self, tab):
        # The inspector header is a DisplayLabel: caps rendering.
        tab.stage_view.fixtures["Ground Par"].setSelected(True)
        assert tab.selection_label.text() == "GROUND PAR"
        assert tab.layer_combo.isEnabled()
        assert tab.layer_combo.currentData() == "Ground"

        tab.stage_view.fixtures["Floater"].setSelected(True)
        # Mixed layers -> no entry shown.
        assert tab.selection_label.text() == "2 FIXTURES"
        assert tab.layer_combo.currentIndex() == -1

    def test_combo_assignment_snaps_z_like_context_menu(self, tab, layered_config):
        tab.stage_view.fixtures["Floater"].setSelected(True)
        index = tab.layer_combo.findData("Ground")
        tab._on_layer_combo_activated(index)

        fixture = layered_config.fixtures[2]  # Floater
        assert fixture.layer == "Ground"
        assert fixture.z == 0.0
        assert fixture.z_uses_group_default is False
        assert tab.layer_combo.currentData() == "Ground"

    def test_combo_clears_assignment(self, tab, layered_config):
        tab.stage_view.fixtures["Ground Par"].setSelected(True)
        tab._on_layer_combo_activated(0)  # "No layer"
        fixture = layered_config.fixtures[0]
        assert fixture.layer == ""
        assert fixture.z == 0.0  # keeps its height

    def test_deselecting_resets_inspector(self, tab):
        item = tab.stage_view.fixtures["Ground Par"]
        item.setSelected(True)
        item.setSelected(False)
        assert tab.selection_label.text() == "NO FIXTURE SELECTED"
        assert not tab.layer_combo.isEnabled()


# ---------------------------------------------------------------------------
# Reference-screen anatomy (design_handoff .../screens/04-setup-stage.html)
# ---------------------------------------------------------------------------

class TestPureHelpers:
    """The library-row and palette helpers, unit-tested without Qt."""

    def test_dominant_layer_picks_the_majority(self):
        from gui.tabs.stage_tab import dominant_layer
        fixtures = [make_fixture("a", layer="Flown"),
                    make_fixture("b", layer="Flown"),
                    make_fixture("c", layer="Ground")]
        assert dominant_layer(fixtures) == "Flown"

    def test_dominant_layer_without_assignment(self):
        from gui.tabs.stage_tab import dominant_layer
        assert dominant_layer([make_fixture("a")]) == "-"
        assert dominant_layer([]) == "-"

    def test_group_row_readout(self):
        from gui.tabs.stage_tab import group_row_readout
        fixtures = [make_fixture("a", layer="Flown"),
                    make_fixture("b", layer="Flown")]
        assert group_row_readout(fixtures) == "2x · FLOWN"
        assert group_row_readout([make_fixture("c")]) == "1x · -"

    def test_reference_element_order_comes_first(self):
        from gui.tabs.stage_tab import (
            REFERENCE_ELEMENT_ORDER, ordered_element_specs,
        )
        from utils.stage_element_catalog import (
            CATEGORY_STAGE, specs_for_category,
        )
        specs = specs_for_category(CATEGORY_STAGE)
        ordered = ordered_element_specs(specs)
        assert [s.kind for s in ordered[:8]] == list(REFERENCE_ELEMENT_ORDER)
        # Nothing dropped: the palette keeps every catalog kind.
        assert {s.kind for s in ordered} == {s.kind for s in specs}


class TestThemeRoles:
    """The reference chrome comes from theme roles, not ad-hoc QSS.

    Never assert font().family() (polish-order race) - assert the rules.
    """

    def test_roles_used_by_the_stage_tab_exist(self):
        from gui.theme_tokens import render_theme
        qss = render_theme("dark")
        for rule in ('QLabel[role="hint-box"]', '#GroupRow',
                     'QWidget[role="card"]', 'QWidget[role="inspector"]',
                     'QPushButton[role="primary"]',
                     'QToolButton[role="topbar-icon"]',
                     'QPushButton[role="nav"]'):
            assert rule in qss, f"missing theme rule: {rule}"


@pytest.fixture
def rig_config():
    """Two groups on two layers, for the library panel."""
    fixtures = [
        make_fixture("Par 1", layer="Ground", group="Front pars"),
        make_fixture("Par 2", layer="Ground", group="Front pars"),
        make_fixture("MH 1", layer="Top truss", z=5.0, group="Movers"),
    ]
    return Configuration(
        fixtures=fixtures,
        groups={
            "Front pars": FixtureGroup("Front pars", fixtures[:2],
                                       color="#D9A441"),
            "Movers": FixtureGroup("Movers", fixtures[2:], color="#C95FD0"),
        },
        universes={1: Universe(id=1, name="Universe 1", output={})},
        stage_layers=[
            StageLayer(name="Ground", z_height=0.0),
            StageLayer(name="Top truss", z_height=5.0),
        ],
        stage_width=12.0,
        stage_height=6.0,
    )


def _row_texts(row):
    from PyQt6.QtWidgets import QLabel
    return [child.text() for child in row.findChildren(QLabel)]


class TestLibraryPanel:
    """Left 260px panel: the expanded STAGE SETTINGS section first, then
    RIG · FIXTURES rows, element/truss tiles and the dashed hint - all
    collapsible - with the export/visualizer actions pinned at the foot."""

    @pytest.fixture
    def clean_sections(self):
        """The library's collapse states persist to (session-shared)
        QSettings, so each test starts and ends from the defaults."""
        from utils.app_settings import app_settings
        app_settings().remove("stage/section")
        yield
        app_settings().remove("stage/section")

    @pytest.fixture
    def tab(self, qapp, clean_sections, rig_config):
        from gui.tabs.stage_tab import StageTab
        tab = StageTab(rig_config, parent=None)
        tab.update_from_config()
        yield tab
        tab.deleteLater()

    def _group_rows(self, tab):
        layout = tab._group_rows_layout
        return [layout.itemAt(i).widget() for i in range(layout.count())]

    def test_panel_width_matches_reference(self, tab):
        from gui.tabs.stage_tab import LIBRARY_WIDTH
        assert LIBRARY_WIDTH == 260
        assert tab.control_panel.width() == 260

    def test_group_rows_show_count_and_dominant_layer(self, tab):
        rows = self._group_rows(tab)
        assert len(rows) == 2
        assert _row_texts(rows[0]) == ["FRONT PARS", "2X · GROUND"]
        assert _row_texts(rows[1]) == ["MOVERS", "1X · TOP TRUSS"]

    def test_group_row_carries_the_group_color(self, tab):
        rows = self._group_rows(tab)
        assert "border-left: 3px solid #D9A441" in rows[0].styleSheet()

    def test_group_row_click_selects_the_groups_fixtures(self, tab):
        tab._on_group_row_clicked("Front pars")
        selected = {item.fixture_name
                    for item in tab.stage_view.get_selected_fixtures()}
        assert selected == {"Par 1", "Par 2"}

    def test_palette_keeps_every_catalog_kind(self, tab):
        from utils.stage_element_catalog import CATALOG
        assert set(tab.element_buttons) == set(CATALOG)

    def test_element_tile_places_an_element(self, tab, rig_config):
        tab.element_buttons["drum-riser"].click()
        assert [e.kind for e in rig_config.stage_elements] == ["drum-riser"]

    def test_truss_tile_creates_its_layer_and_chip(self, tab, rig_config):
        tab.element_buttons["truss-straight"].click()
        assert rig_config.get_stage_layer("Truss 1") is not None
        assert "Truss 1" in tab.layer_chips

    def test_truss_hint_uses_the_theme_hint_box(self, tab):
        assert tab.truss_hint.property("role") == "hint-box"

    def test_settings_section_is_expanded_and_keeps_the_old_controls(self, tab):
        """Stage dimensions are set first, so STAGE SETTINGS opens
        expanded - and every control that used to live in the blob is
        still somewhere inside it."""
        assert tab.settings_toggle.isChecked() is True
        assert tab.settings_container.isVisibleTo(tab.control_panel) is True
        for name in ("stage_width", "stage_height", "grid_size",
                     "grid_toggle", "snap_to_grid", "fit_view_btn",
                     "show_axes_checkbox", "add_spot_btn", "remove_item_btn",
                     "layer_list", "add_layer_btn",
                     "remove_layer_btn", "edit_layer_btn", "layer_panel"):
            widget = getattr(tab, name)
            assert tab.settings_container.isAncestorOf(widget), (
                f"{name} is not inside the STAGE SETTINGS section")

    def test_stage_section_combines_dimensions_grid_and_view(self, tab):
        """The reorganized STAGE section holds the dimensions, the grid
        controls AND the view controls in one collapsible (key
        stage_dims); the old separate grid/view sections are gone."""
        stage_section = tab.sections["stage_dims"]
        for name in ("stage_width", "stage_height", "grid_size",
                     "grid_toggle", "snap_to_grid", "fit_view_btn",
                     "show_axes_checkbox"):
            widget = getattr(tab, name)
            assert stage_section.isAncestorOf(widget), (
                f"{name} is not inside the combined STAGE section")

    def test_stage_subsections_are_indented_under_settings(self, tab):
        """The nested Stage / Marks / Layers sections must read as children
        of STAGE SETTINGS, not siblings: both the header (indent) and the
        content (left margin) sit further right than the umbrella."""
        outer = tab.sections["settings"]
        outer_left = outer.content.contentsMargins().left()
        for key in ("stage_dims", "marks", "layers"):
            sub = tab.sections[key]
            assert sub._indent > 0, f"{key} header is not indented"
            assert sub.content.contentsMargins().left() > outer_left, (
                f"{key} content is not indented past STAGE SETTINGS")

    def test_dropped_sections_and_planes_picker_are_gone(self, tab):
        """The Grid / View / Planes sections were folded away, and the
        stage-planes picker UI no longer exists on the tab."""
        for gone in ("grid", "view", "planes"):
            assert gone not in tab.sections
        assert not hasattr(tab, "plane_list")
        # Marks and Layers survive as their own siblings.
        assert "marks" in tab.sections
        assert "layers" in tab.sections

    def test_export_actions_are_pinned_outside_the_collapsibles(self, tab):
        """PLOT STAGE / LAUNCH VISUALIZER / TCP status must stay reachable
        with every section collapsed."""
        for name in ("plot_stage_btn", "launch_visualizer_btn",
                     "tcp_status_label"):
            widget = getattr(tab, name)
            assert tab.action_footer.isAncestorOf(widget)
            assert not tab.settings_container.isAncestorOf(widget)

    def test_settings_toggle_collapses(self, tab):
        tab.settings_toggle.setChecked(False)
        assert tab.settings_container.isVisibleTo(tab.control_panel) is False

    def test_section_order_puts_stage_settings_first(self, tab):
        """Panel order: STAGE SETTINGS, RIG · FIXTURES, elements, trusses."""
        from gui.tabs.stage_tab import _CollapsibleSection
        scroll = tab.control_panel.findChild(QtWidgets.QScrollArea)
        layout = scroll.widget().layout()
        top_level = []
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if isinstance(widget, _CollapsibleSection):
                top_level.append(widget.toggle.text())
        assert top_level == ["STAGE SETTINGS", "RIG · FIXTURES",
                             "STAGE ELEMENTS · DRAG", "TRUSSES · DRAG"]

    def test_every_library_section_is_collapsible(self, tab):
        """Elements and trusses collapse with the same affordance as the
        settings section (the user's report: they could not)."""
        for key in ("settings", "stage_dims", "marks",
                    "layers", "fixtures", "elements", "trusses"):
            section = tab.sections[key]
            assert section.toggle.isCheckable()
            section.set_expanded(False)
            # isVisibleTo(section), not the panel: STAGE / MARKS / LAYERS
            # are nested inside the STAGE SETTINGS section.
            assert section.container.isVisibleTo(section) is False
            section.set_expanded(True)
            assert section.container.isVisibleTo(section) is True

    def test_default_expansion_state(self, tab):
        expanded = {key: s.is_expanded() for key, s in tab.sections.items()}
        assert expanded == {
            "settings": True, "stage_dims": True,
            "marks": False, "layers": False,
            "fixtures": True, "elements": True, "trusses": True,
        }

    def test_section_state_persists_via_app_settings(self, qapp,
                                                     clean_sections,
                                                     rig_config):
        """QSettings is isolated by tests/conftest.py, so this is safe."""
        from gui.tabs.stage_tab import StageTab
        from utils.app_settings import app_settings

        tab = StageTab(rig_config, parent=None)
        tab.sections["elements"].set_expanded(False)
        assert app_settings().value(
            "stage/section/elements", True, type=bool) is False
        tab.deleteLater()

        reborn = StageTab(rig_config, parent=None)
        assert reborn.sections["elements"].is_expanded() is False
        # ... and the rest kept their defaults.
        assert reborn.sections["settings"].is_expanded() is True
        reborn.deleteLater()


class TestActionStrip:
    """38px strip: chips right-aligned, MORPH disabled, EXPORT wired."""

    @pytest.fixture
    def tab(self, qapp, rig_config):
        from gui.tabs.stage_tab import StageTab
        tab = StageTab(rig_config, parent=None)
        tab.update_from_config()
        yield tab
        tab.deleteLater()

    def test_strip_height(self, tab):
        from gui.tabs.stage_tab import STRIP_HEIGHT
        assert STRIP_HEIGHT == 38

    def test_active_chip_is_accent_filled_not_just_bordered(self, tab):
        """The chip wears role="segment"; the theme's rule fills the
        checked segment with the accent (widget-local CSS would race
        the app-wide font/colour rules, see docs/qt-gotchas.md)."""
        from gui.theme_tokens import THEMES, render_theme

        assert tab.layer_chips["Ground"].property("role") == "segment"
        rule = render_theme("dark").split(
            'QPushButton[role="segment"]:checked {', 1)[1].split("}", 1)[0]
        assert THEMES["dark"]["accent"] in rule
        assert THEMES["dark"]["on_accent"] in rule

    def test_morph_is_disabled_with_a_tooltip(self, tab):
        assert not tab.morph_btn.isEnabled()
        assert "morph milestone" in tab.morph_btn.toolTip()

    def test_export_rider_runs_the_stage_plot_export(self, tab, monkeypatch):
        calls = []
        monkeypatch.setattr(tab, "_export_stage_plot",
                            lambda: calls.append("export"))
        # Rebind: the signal holds the original bound method.
        tab.export_rider_btn.clicked.disconnect()
        tab.export_rider_btn.clicked.connect(tab._export_stage_plot)
        tab.export_rider_btn.click()
        assert calls == ["export"]

    def test_define_chip_edits_the_active_layer(self, tab, monkeypatch):
        seen = {}

        def fake_dialog(title, name="", z_height=3.0):
            seen["name"] = name
            return None

        monkeypatch.setattr(tab, "_layer_dialog", fake_dialog)
        tab._set_active_layer("Top truss")
        tab.define_layer_chip.click()
        assert seen["name"] == "Top truss"

    def test_define_chip_disabled_without_layers(self, qapp):
        from gui.tabs.stage_tab import StageTab
        tab = StageTab(Configuration(), parent=None)
        try:
            assert not tab.define_layer_chip.isEnabled()
        finally:
            tab.deleteLater()


class TestPlanOverlays:
    """Overlay chrome on the plan: caption, badge, legend, title block."""

    @pytest.fixture
    def tab(self, qapp, rig_config):
        from gui.tabs.stage_tab import StageTab
        tab = StageTab(rig_config, parent=None)
        tab.update_from_config()
        yield tab
        tab.deleteLater()

    def test_overlays_are_children_of_the_view_and_click_through(self, tab):
        from PyQt6.QtCore import Qt
        for widget in (tab.plan_caption, tab.active_layer_badge,
                       tab.plan_legend, tab.title_block):
            assert widget.parent() is tab.stage_view
            assert widget.testAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def test_caption_names_the_real_grid_size(self, tab, rig_config):
        assert tab.plan_caption.text() == \
            "STAGE PLAN · TOP VIEW · 1 SQUARE = 0.5 M"
        rig_config.grid_size = 1.0
        tab.update_from_config()
        assert "1 SQUARE = 1 M" in tab.plan_caption.text()

    def test_badge_only_shows_while_a_layer_is_active(self, tab):
        assert tab.active_layer_badge.isHidden()
        tab._set_active_layer("Top truss")
        assert not tab.active_layer_badge.isHidden()
        assert tab.active_layer_badge.text() == \
            "ACTIVE LAYER: TOP TRUSS 5 M · OTHERS DIMMED"
        tab._set_active_layer(None)
        assert tab.active_layer_badge.isHidden()

    def test_legend_first_entry_follows_the_active_layer(self, tab):
        assert tab.legend_active_label.text() == "ALL LAYERS"
        tab._set_active_layer("Ground")
        assert tab.legend_active_label.text() == "GROUND 0 m"

    def test_title_block_is_honest_about_the_project(self, tab, rig_config):
        import datetime
        assert tab.title_name.text() == "STAGE PLAN · UNTITLED"
        assert tab.title_sheet.text() == "SHEET 1/1"
        assert tab.title_dims.text() == "12x6 m"
        assert tab.title_date.text() == datetime.date.today().isoformat()

        rig_config._loaded_from = "/tmp/neon_ruinen.yaml"
        tab.update_from_config()
        assert tab.title_name.text() == "STAGE PLAN · NEON_RUINEN"

    def test_title_block_follows_stage_dimensions(self, tab):
        tab.stage_width.setValue(8)
        assert tab.title_dims.text() == "8x6 m"


class TestSelectionCard:
    """SELECTION card + LAYERS section + preview header."""

    @pytest.fixture
    def tab(self, qapp, rig_config):
        from gui.tabs.stage_tab import StageTab
        tab = StageTab(rig_config, parent=None)
        tab.update_from_config()
        yield tab
        tab.deleteLater()

    def test_stat_tiles_read_the_selected_fixture(self, tab, rig_config):
        rig_config.fixtures[2].x = 2.5
        rig_config.fixtures[2].y = -1.0
        tab.update_from_config()
        tab.stage_view.fixtures["MH 1"].setSelected(True)
        assert tab.stat_x.text() == "2.50"
        assert tab.stat_y.text() == "-1.00"
        assert tab.stat_z.text() == "5.00"

    def test_stat_tiles_survive_the_first_config_load(self, qapp, rig_config):
        """update_from_config maps fixtures with the CONFIG's stage size.

        StageView.meters_to_pixels reads stage_width_m / stage_depth_m,
        which set_config does not refresh - so the items placed by the
        first set_config used the view's default 10x6 m grid and every
        readout (and the next save) was off. Pin the re-place.
        """
        from gui.tabs.stage_tab import StageTab
        rig_config.fixtures[2].x = 4.0
        tab = StageTab(rig_config, parent=None)   # 12 x 6 m stage
        try:
            tab.update_from_config()              # exactly one load
            tab.stage_view.fixtures["MH 1"].setSelected(True)
            assert tab.stat_x.text() == "4.00"
        finally:
            tab.deleteLater()

    def test_group_name_uses_the_group_color(self, tab):
        tab.stage_view.fixtures["MH 1"].setSelected(True)
        assert tab.selection_group_label.text() == "MOVERS"
        assert "#C95FD0" in tab.selection_group_label.styleSheet()

    def test_multi_selection_blanks_the_stats(self, tab):
        tab.stage_view.fixtures["Par 1"].setSelected(True)
        tab.stage_view.fixtures["Par 2"].setSelected(True)
        assert tab.stat_x.text() == "-"
        assert tab.selection_group_label.text() == "FRONT PARS"

    def test_layer_combo_is_accent_bordered(self, tab):
        """Theme-owned via QComboBox[role="accent-field"]."""
        from gui.theme_tokens import THEMES, render_theme

        assert tab.layer_combo.property("role") == "accent-field"
        rule = render_theme("dark").split(
            'QComboBox[role="accent-field"] {', 1)[1].split("}", 1)[0]
        assert THEMES["dark"]["accent"] in rule

    def test_selection_hint_has_the_accent_left_border(self, tab):
        """Theme-owned via QLabel[role="hint-accent"]."""
        from gui.theme_tokens import THEMES, render_theme

        assert tab.selection_hint.property("role") == "hint-accent"
        rule = render_theme("dark").split(
            'QLabel[role="hint-accent"] {', 1)[1].split("}", 1)[0]
        assert "border-left: 3px solid" in rule
        assert THEMES["dark"]["accent"] in rule

    def test_selection_hint_is_hidden_until_the_layer_field_is_hovered(self, tab):
        """The active-layer rule hint stays out of the way and reveals only
        while the pointer is over the LAYER field.

        isHidden() (not isVisible()) is asserted: the tab is never shown, so
        isVisible() is always False regardless of the explicit hide state."""
        from PyQt6.QtCore import QEvent
        from PyQt6.QtWidgets import QApplication

        assert tab.selection_hint.isHidden()
        QApplication.sendEvent(tab.layer_combo, QEvent(QEvent.Type.Enter))
        assert not tab.selection_hint.isHidden()
        QApplication.sendEvent(tab.layer_combo, QEvent(QEvent.Type.Leave))
        assert tab.selection_hint.isHidden()

    def test_layers_section_lists_every_layer(self, tab):
        layout = tab._layer_rows_layout
        rows = [layout.itemAt(i).widget() for i in range(layout.count())]
        assert [_row_texts(row) for row in rows] == [
            ["Ground", "H 0 m"], ["Top truss", "H 5 m"]]

    def test_preview_collapse_hides_the_gl_pane(self, tab):
        tab.preview_collapse_btn.setChecked(True)
        assert tab.embedded_visualizer.isHidden()
        tab.preview_collapse_btn.setChecked(False)
        assert not tab.embedded_visualizer.isHidden()


class TestStageViewGroupSelection:

    def test_select_group_fixtures_skips_ghosted(self, qapp, rig_config):
        from gui.StageView import StageView
        view = StageView(None)
        try:
            view.set_config(rig_config)
            assert {i.fixture_name
                    for i in view.select_group_fixtures("Front pars")} == \
                {"Par 1", "Par 2"}

            # Ghosted (off active layer) fixtures are not selectable.
            view.set_active_layer("Top truss")
            assert view.select_group_fixtures("Front pars") == []
            assert {i.fixture_name
                    for i in view.select_group_fixtures("Movers")} == {"MH 1"}
        finally:
            view.deleteLater()
