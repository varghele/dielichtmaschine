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
