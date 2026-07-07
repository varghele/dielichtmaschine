"""Truss docking (5a second step): a truss is its own layer.

Placing a truss auto-creates a StageLayer; fixtures dock by dropping
onto the truss (join its layer, Z snaps to the hang height, position
projects onto a straight truss's axis), follow the truss when it
moves, and undock by dragging off. Removing the truss undocks its
fixtures but keeps the layer.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import Configuration, Fixture, FixtureMode


def _fixture(name, x=0.0, y=0.0):
    return Fixture(universe=1, address=1, manufacturer="M", model="X",
                   name=name, group="G", current_mode="Std",
                   available_modes=[FixtureMode(name="Std", channels=8)],
                   type="MH", x=x, y=y)


@pytest.fixture
def view(qapp):
    from gui.StageView import StageView
    config = Configuration(fixtures=[_fixture("Mover 1"),
                                     _fixture("Mover 2", x=3.0, y=2.0)])
    stage_view = StageView()
    stage_view.set_config(config)
    yield stage_view, config
    stage_view.deleteLater()


def _drop_at(view, fixture_item, x_m, y_m):
    x_px, y_px = view.meters_to_pixels(x_m, y_m)
    fixture_item.setPos(x_px, y_px)
    view.handle_fixture_drop(fixture_item)


class TestTrussIsALayer:
    def test_placing_a_truss_creates_its_layer(self, view):
        stage_view, config = view
        truss = stage_view.add_stage_element("truss-straight")
        assert truss.element_id
        layer = config.get_stage_layer("Truss 1")
        assert layer is not None and layer.z_height == 4.0
        assert truss.layer == "Truss 1"
        assert truss.label == "Truss 1"

    def test_layer_names_are_unique_per_truss(self, view):
        stage_view, config = view
        stage_view.add_stage_element("truss-straight")
        second = stage_view.add_stage_element("truss-tower")
        assert second.layer == "Truss 2"

    def test_non_truss_elements_create_no_layer(self, view):
        stage_view, config = view
        stage_view.add_stage_element("wedge")
        assert config.stage_layers == []


class TestDocking:
    def test_drop_on_truss_docks(self, view):
        stage_view, config = view
        truss = stage_view.add_stage_element("truss-straight")  # 3m at 0,0
        item = stage_view.fixtures["Mover 1"]
        _drop_at(stage_view, item, 0.5, 0.05)

        fixture = config.fixtures[0]
        assert fixture.docked_to == truss.element_id
        assert fixture.layer == "Truss 1"
        assert fixture.z == 4.0
        assert fixture.z_uses_group_default is False
        # Projected onto the truss axis (y snaps to the truss line).
        assert fixture.y == pytest.approx(0.0, abs=0.02)
        assert fixture.x == pytest.approx(0.5, abs=0.02)

    def test_projection_clamps_to_span(self, view):
        stage_view, config = view
        stage_view.add_stage_element("truss-straight")  # width 3 -> ±1.5
        item = stage_view.fixtures["Mover 1"]
        _drop_at(stage_view, item, 1.6, 0.1)  # just past the end, inside pad
        assert config.fixtures[0].x == pytest.approx(1.5, abs=0.02)

    def test_drop_far_away_does_not_dock(self, view):
        stage_view, config = view
        stage_view.add_stage_element("truss-straight")
        item = stage_view.fixtures["Mover 1"]
        _drop_at(stage_view, item, 3.0, 2.5)
        assert config.fixtures[0].docked_to == ""
        assert config.fixtures[0].layer == ""

    def test_drag_off_undocks_and_clears_truss_layer(self, view):
        stage_view, config = view
        stage_view.add_stage_element("truss-straight")
        item = stage_view.fixtures["Mover 1"]
        _drop_at(stage_view, item, 0.0, 0.0)
        assert config.fixtures[0].docked_to
        _drop_at(stage_view, item, 3.0, 2.5)
        fixture = config.fixtures[0]
        assert fixture.docked_to == ""
        assert fixture.layer == ""
        assert fixture.x == pytest.approx(3.0, abs=0.02)

    def test_manual_layer_survives_non_truss_drops(self, view):
        stage_view, config = view
        item = stage_view.fixtures["Mover 1"]
        item.layer = "Balcony"  # manual, no docking involved
        _drop_at(stage_view, item, 1.0, 1.0)
        assert config.fixtures[0].layer == "Balcony"

    def test_rotated_truss_docking(self, view):
        stage_view, config = view
        truss = stage_view.add_stage_element("truss-straight")
        truss.rotation = 90.0  # runs along Y now
        item = stage_view.fixtures["Mover 1"]
        _drop_at(stage_view, item, 0.05, 1.0)
        fixture = config.fixtures[0]
        assert fixture.docked_to == truss.element_id
        assert fixture.x == pytest.approx(0.0, abs=0.02)
        assert fixture.y == pytest.approx(1.0, abs=0.02)


class TestTrussMoves:
    def test_moving_truss_carries_docked_fixture(self, view):
        stage_view, config = view
        truss = stage_view.add_stage_element("truss-straight")
        item = stage_view.fixtures["Mover 1"]
        _drop_at(stage_view, item, 0.5, 0.0)

        truss_item = stage_view.stage_element_items[0]
        from PyQt6.QtCore import QPointF
        delta_px = QPointF(1.0 * stage_view.pixels_per_meter,
                           -0.5 * stage_view.pixels_per_meter)
        truss_item.setPos(truss_item.pos() + delta_px)
        stage_view.move_docked_fixtures(truss, delta_px)
        stage_view.save_positions_to_config()

        fixture = config.fixtures[0]
        assert fixture.x == pytest.approx(1.5, abs=0.02)
        assert fixture.y == pytest.approx(-0.5, abs=0.02)
        # Undocked fixture untouched
        assert config.fixtures[1].x == pytest.approx(3.0, abs=0.02)

    def test_set_truss_height_moves_layer_and_fixtures(self, view):
        stage_view, config = view
        truss = stage_view.add_stage_element("truss-straight")
        item = stage_view.fixtures["Mover 1"]
        _drop_at(stage_view, item, 0.0, 0.0)

        stage_view.set_truss_height(truss, 5.5)
        assert config.get_stage_layer("Truss 1").z_height == 5.5
        assert config.fixtures[0].z == 5.5

    def test_remove_truss_undocks_but_keeps_layer(self, view):
        stage_view, config = view
        stage_view.add_stage_element("truss-straight")
        item = stage_view.fixtures["Mover 1"]
        _drop_at(stage_view, item, 0.0, 0.0)

        stage_view.remove_stage_element(stage_view.stage_element_items[0])
        fixture = config.fixtures[0]
        assert fixture.docked_to == ""
        assert fixture.layer == "Truss 1"  # keeps position/Z/layer
        assert config.get_stage_layer("Truss 1") is not None


class TestPersistence:
    def test_docking_round_trips_through_yaml(self, view, tmp_path):
        stage_view, config = view
        truss = stage_view.add_stage_element("truss-straight")
        item = stage_view.fixtures["Mover 1"]
        _drop_at(stage_view, item, 0.5, 0.0)

        path = str(tmp_path / "docked.yaml")
        config.save(path)
        loaded = Configuration.load(path)
        assert loaded.stage_elements[0].element_id == truss.element_id
        assert loaded.fixtures[0].docked_to == truss.element_id
        assert loaded.fixtures[0].layer == "Truss 1"
        assert loaded.get_stage_layer("Truss 1").z_height == 4.0
