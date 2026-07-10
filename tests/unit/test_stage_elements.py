"""Static stage elements (North Star 5a, first step - no truss docking).

Covers the model round-trip, the symbol catalog, the StageView
integration (place / move / remove / layer rules), and the printable
plot pass.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import Configuration, StageElement, StageLayer
from utils.stage_element_catalog import (
    CATALOG, CATEGORIES, make_element, specs_for_category, symbol_path,
)


class TestModelRoundTrip:
    def test_yaml_round_trip(self, tmp_path):
        config = Configuration()
        config.stage_elements = [
            StageElement(kind="drum-riser", x=1.5, y=-2.0, rotation=45.0,
                         width=2.0, depth=2.0, label="Drums", layer="Deck"),
            StageElement(kind="truss-straight", x=0.0, y=2.5),
        ]
        path = str(tmp_path / "cfg.yaml")
        config.save(path)
        loaded = Configuration.load(path)
        assert len(loaded.stage_elements) == 2
        first = loaded.stage_elements[0]
        assert first.kind == "drum-riser"
        assert first.x == 1.5 and first.y == -2.0
        assert first.rotation == 45.0
        assert first.label == "Drums"
        assert first.layer == "Deck"
        assert loaded.stage_elements[1].kind == "truss-straight"

    def test_old_configs_load_without_elements(self, tmp_path):
        config = Configuration()
        path = str(tmp_path / "old.yaml")
        config.save(path)
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        data.pop("stage_elements", None)
        with open(path, "w") as f:
            yaml.dump(data, f)
        loaded = Configuration.load(path)
        assert loaded.stage_elements == []


class TestCatalog:
    def test_every_kind_has_a_symbol_file(self):
        for kind in CATALOG:
            assert os.path.isfile(symbol_path(kind)), kind

    def test_categories_cover_all_specs(self):
        assert sum(len(specs_for_category(c)) for c in CATEGORIES) == len(CATALOG)

    def test_make_element_applies_default_footprint(self):
        element = make_element("foh", x=3.0, y=2.0)
        assert element.kind == "foh"
        assert (element.width, element.depth) == (2.0, 1.0)
        assert (element.x, element.y) == (3.0, 2.0)


@pytest.fixture
def stage_view(qapp):
    from gui.StageView import StageView
    config = Configuration(
        stage_layers=[StageLayer(name="Deck", z_height=0.4),
                      StageLayer(name="Hidden", z_height=4.0, visible=False)])
    view = StageView()
    view.set_config(config)
    yield view, config
    view.deleteLater()


class TestStageViewIntegration:
    def test_add_creates_model_and_item(self, stage_view):
        view, config = stage_view
        element = view.add_stage_element("wedge")
        assert config.stage_elements == [element]
        assert len(view.stage_element_items) == 1
        assert view.stage_element_items[0].element is element

    def test_positions_save_back_in_meters(self, stage_view):
        view, config = stage_view
        view.add_stage_element("amp")
        item = view.stage_element_items[0]
        x_px, y_px = view.meters_to_pixels(2.0, -1.5)
        item.setPos(x_px, y_px)
        view.save_positions_to_config()
        element = config.stage_elements[0]
        assert element.x == pytest.approx(2.0, abs=0.01)
        assert element.y == pytest.approx(-1.5, abs=0.01)

    def test_remove_deletes_model_and_item(self, stage_view):
        view, config = stage_view
        view.add_stage_element("riser")
        item = view.stage_element_items[0]
        view.remove_stage_element(item)
        assert config.stage_elements == []
        assert view.stage_element_items == []

    def test_update_from_config_rebuilds(self, stage_view):
        view, config = stage_view
        config.stage_elements.append(
            StageElement(kind="foh", x=0.0, y=2.0, width=2.0, depth=1.0))
        view.update_from_config()
        assert len(view.stage_element_items) == 1

    def test_active_layer_ghosts_non_members(self, stage_view):
        view, config = stage_view
        member = view.add_stage_element("wedge")
        member.layer = "Deck"
        outsider = view.add_stage_element("amp")
        assert outsider.layer == ""
        view.set_active_layer("Deck")
        ghost_by_kind = {i.element.kind: i.ghosted
                         for i in view.stage_element_items}
        assert ghost_by_kind == {"wedge": False, "amp": True}
        view.set_active_layer(None)
        assert all(not i.ghosted for i in view.stage_element_items)

    def test_hidden_layer_hides_element(self, stage_view):
        view, config = stage_view
        element = view.add_stage_element("hazer")
        element.layer = "Hidden"
        view.apply_layer_visibility()
        assert not view.stage_element_items[0].isVisible()


class TestStagePlot:
    def test_plot_renders_elements(self, qapp, tmp_path):
        from PyQt6.QtGui import QImage
        from gui.stage_plot import StagePlotRenderer

        config = Configuration(stage_width=8.0, stage_height=6.0)
        config.stage_elements = [
            StageElement(kind="drum-riser", x=0.0, y=1.0, width=2.0,
                         depth=2.0, label="Drums")]
        with_path = str(tmp_path / "with.png")
        StagePlotRenderer(config, title="elements").render(
            with_path, paper="A4", dpi=100)
        without_path = str(tmp_path / "without.png")
        config.stage_elements = []
        StagePlotRenderer(config, title="elements").render(
            without_path, paper="A4", dpi=100)

        from tests.visual.harness import qimage_to_array
        import numpy as np
        a = qimage_to_array(QImage(with_path)).astype(int)
        b = qimage_to_array(QImage(without_path)).astype(int)
        assert (np.abs(a - b) > 20).any(), "element left no ink on the plot"

    def test_hidden_layer_elements_skipped_on_plot(self, qapp, tmp_path):
        from PyQt6.QtGui import QImage
        from gui.stage_plot import StagePlotRenderer

        config = Configuration(
            stage_width=8.0, stage_height=6.0,
            stage_layers=[StageLayer(name="Hidden", z_height=2.0,
                                     visible=False)])
        config.stage_elements = [
            StageElement(kind="foh", x=0.0, y=0.0, width=2.0, depth=1.0,
                         layer="Hidden")]
        hidden_path = str(tmp_path / "hidden.png")
        StagePlotRenderer(config, title="elements").render(
            hidden_path, paper="A4", dpi=100)
        config.stage_elements = []
        empty_path = str(tmp_path / "empty.png")
        StagePlotRenderer(config, title="elements").render(
            empty_path, paper="A4", dpi=100)

        from tests.visual.harness import qimage_to_array
        import numpy as np
        a = qimage_to_array(QImage(hidden_path)).astype(int)
        b = qimage_to_array(QImage(empty_path)).astype(int)
        assert not (np.abs(a - b) > 20).any(), (
            "hidden-layer element painted on the plot")


class TestSpikeMark:
    """The stage spot renders the spike-mark symbol (screen 04 asset)
    with brand-mono labels, replacing the Arial-labelled primitive X."""

    def test_spike_mark_asset_renders(self, qapp):
        from PyQt6.QtGui import QColor
        from gui.widgets.fixture_icons import (
            _symbol_pixmap, stageplot_symbol_path)
        assert os.path.exists(stageplot_symbol_path("spike-mark"))
        pixmap = _symbol_pixmap("spike-mark", QColor("#8d9299"), 48)
        assert pixmap is not None and not pixmap.isNull()

    def test_bounding_rect_fits_label_metrics(self, qapp):
        from PyQt6.QtGui import QFontMetrics
        from gui.stage_items import SpotItem
        item = SpotItem(name="A Rather Long Spike Name")
        name_font, _z = item._label_fonts()
        needed = QFontMetrics(name_font).horizontalAdvance(item.name)
        assert item.boundingRect().width() >= needed

    def test_paint_smoke_both_selection_states(self, qapp):
        """Painting must not crash and must leave ink (offscreen)."""
        from PyQt6.QtGui import QImage, QPainter
        from PyQt6.QtCore import Qt as QtCore_Qt
        from PyQt6.QtWidgets import QGraphicsScene
        from gui.stage_items import SpotItem
        import numpy as np
        from tests.visual.harness import qimage_to_array

        scene = QGraphicsScene()
        item = SpotItem(name="Spot1")
        scene.addItem(item)
        for selected in (False, True):
            item.setSelected(selected)
            image = QImage(120, 120,
                           QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QtCore_Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.translate(60, 40)
            item.paint(painter, None, None)
            painter.end()
            alpha = qimage_to_array(image)[..., 3]
            assert (alpha > 0).any(), f"no ink (selected={selected})"
