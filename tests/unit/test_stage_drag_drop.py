"""Drag a stage-element tile from the library, drop it on the plan.

The reference screen labels the palette "BUEHNENELEMENTE · ZIEHEN"
(stage elements, drag), so the tiles are drag sources carrying
``ELEMENT_MIME_TYPE`` and StageView is the drop target: the element is
created at the drop position, snapped to the grid when snapping is on,
joining the layer currently being edited. Click-to-place (at stage
centre) keeps working.

Drops are exercised by handing StageView a real QDropEvent with real
QMimeData - no QDrag event loop, so this stays hermetic and offscreen.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QDropEvent, QMouseEvent

from config.models import Configuration, StageLayer
from gui.StageView import (
    ELEMENT_MIME_TYPE, element_kind_from_mime, element_mime_data,
)


@pytest.fixture
def config():
    return Configuration(
        fixtures=[], groups={}, universes={},
        stage_layers=[StageLayer(name="Ground", z_height=0.0)],
        stage_width=12.0, stage_height=6.0,
    )


@pytest.fixture
def tab(qapp, config):
    from gui.tabs.stage_tab import StageTab
    tab = StageTab(config, parent=None)
    tab.update_from_config()
    yield tab
    tab.deleteLater()


@pytest.fixture
def view(qapp, tab):
    """The plan, sized and laid out so mapToScene has a real transform
    (without processEvents the viewport keeps its default size and the
    view/scene mapping is meaningless)."""
    view = tab.stage_view
    view.setFixedSize(700, 420)
    view.show()
    qapp.processEvents()
    view.fit_to_stage()
    yield view
    view.hide()


def make_drop_event(pos, mime):
    """A QDropEvent that keeps its QMimeData alive.

    QDropEvent stores a bare pointer and does NOT take ownership (QDrag
    normally owns the payload); without the back-reference below Python
    frees the QMimeData and reading it segfaults.
    """
    event = QDropEvent(
        QPointF(pos), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    event._mime_keepalive = mime
    return event


def drop_at_meters(view, kind, x_m, y_m):
    """Drop ``kind`` at the viewport point that maps to (x_m, y_m)."""
    x_px, y_px = view.meters_to_pixels(x_m, y_m)
    viewport_pos = view.mapFromScene(QPointF(x_px, y_px))
    event = make_drop_event(viewport_pos, element_mime_data(kind))
    view.dropEvent(event)
    return event


class TestMime:
    def test_mime_round_trip(self):
        mime = element_mime_data("drum-riser")
        assert mime.hasFormat(ELEMENT_MIME_TYPE)
        assert element_kind_from_mime(mime) == "drum-riser"

    def test_foreign_mime_carries_no_kind(self):
        from PyQt6.QtCore import QMimeData
        mime = QMimeData()
        mime.setText("drum-riser")
        assert element_kind_from_mime(mime) == ""


class TestPaletteTileIsADragSource:
    def test_tiles_are_drag_capable(self, tab):
        from gui.tabs.stage_tab import _ElementTile
        assert isinstance(tab.element_buttons["wedge"], _ElementTile)
        assert tab.element_buttons["wedge"].kind == "wedge"

    def _move(self, tile, dx):
        return QMouseEvent(
            QMouseEvent.Type.MouseMove, QPointF(5 + dx, 5),
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

    def _press(self, tile):
        return QMouseEvent(
            QMouseEvent.Type.MouseButtonPress, QPointF(5, 5),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

    def test_a_long_drag_starts_a_drag(self, tab, monkeypatch):
        tile = tab.element_buttons["amp"]
        started = []
        monkeypatch.setattr(tile, "start_drag", lambda: started.append(True))
        tile.mousePressEvent(self._press(tile))
        tile.mouseMoveEvent(self._move(tile, 60))
        assert started == [True]

    def test_a_twitch_does_not_start_a_drag(self, tab, monkeypatch):
        """Click-to-place must survive a 1px wobble under the finger."""
        tile = tab.element_buttons["amp"]
        started = []
        monkeypatch.setattr(tile, "start_drag", lambda: started.append(True))
        tile.mousePressEvent(self._press(tile))
        tile.mouseMoveEvent(self._move(tile, 1))
        assert started == []

    def test_click_still_places_at_stage_centre(self, tab, config):
        tab.element_buttons["amp"].click()
        assert [(e.kind, e.x, e.y) for e in config.stage_elements] == [
            ("amp", 0.0, 0.0)]


class TestDropCreatesElementAtTheDropPosition:
    def test_drop_lands_at_the_dropped_metres(self, view, config):
        view.snap_enabled = False
        drop_at_meters(view, "drum-riser", -3.2, 1.4)
        element = config.stage_elements[-1]
        assert element.kind == "drum-riser"
        assert element.x == pytest.approx(-3.2, abs=0.05)
        assert element.y == pytest.approx(1.4, abs=0.05)

    def test_drop_is_accepted(self, view):
        event = drop_at_meters(view, "amp", 1.0, 1.0)
        assert event.isAccepted()

    def test_drop_snaps_to_the_grid_when_snapping_is_on(self, view, config):
        view.set_snap_to_grid(True)
        view.grid_size_m = 1.0
        drop_at_meters(view, "wedge", 2.4, -1.4)
        element = config.stage_elements[-1]
        assert element.x == pytest.approx(2.0, abs=0.01)
        assert element.y == pytest.approx(-1.0, abs=0.01)

    def test_drop_does_not_snap_when_snapping_is_off(self, view, config):
        view.set_snap_to_grid(False)
        view.grid_size_m = 1.0
        drop_at_meters(view, "wedge", 2.4, -1.4)
        element = config.stage_elements[-1]
        assert element.x == pytest.approx(2.4, abs=0.05)
        assert element.y == pytest.approx(-1.4, abs=0.05)

    def test_dropped_element_gets_a_scene_item(self, view, config):
        drop_at_meters(view, "amp", 0.0, 0.0)
        assert len(view.stage_element_items) == len(config.stage_elements) == 1
        assert view.stage_element_items[0].element is config.stage_elements[0]

    def test_drop_emits_fixtures_changed(self, view):
        seen = []
        view.fixtures_changed.connect(lambda: seen.append(True))
        drop_at_meters(view, "amp", 0.0, 0.0)
        assert seen == [True]

    def test_dropped_element_joins_the_active_layer(self, view, config):
        view.set_active_layer("Ground")
        drop_at_meters(view, "amp", 1.0, 1.0)
        assert config.stage_elements[-1].layer == "Ground"
        # ... and is therefore not born ghosted.
        assert view.stage_element_items[-1].opacity() == 1.0

    def test_dropped_truss_creates_its_layer_and_chip(self, tab, view, config):
        view.set_snap_to_grid(False)
        drop_at_meters(view, "truss-straight", 0.0, -2.0)
        element = config.stage_elements[-1]
        assert element.layer == "Truss 1"
        assert config.get_stage_layer("Truss 1") is not None
        assert element.y == pytest.approx(-2.0, abs=0.05)
        # The tab's layer UI followed the drop (stage_element_added).
        assert "Truss 1" in tab.layer_chips

    def test_foreign_drop_is_ignored(self, view, config):
        from PyQt6.QtCore import QMimeData
        mime = QMimeData()
        mime.setText("drum-riser")
        view.dropEvent(make_drop_event(QPointF(10.0, 10.0), mime))
        assert config.stage_elements == []

    def test_unknown_kind_is_ignored(self, view, config):
        from PyQt6.QtCore import QMimeData, QByteArray
        mime = QMimeData()
        mime.setData(ELEMENT_MIME_TYPE, QByteArray(b"not-a-real-kind"))
        view.dropEvent(make_drop_event(QPointF(10.0, 10.0), mime))
        assert config.stage_elements == []


class TestDragEnterAndMove:
    def _drag_event(self, kind, event_type):
        from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent
        cls = (QDragEnterEvent if event_type == "enter" else QDragMoveEvent)
        mime = element_mime_data(kind)
        event = cls(QPoint(10, 10), Qt.DropAction.CopyAction, mime,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        event._mime_keepalive = mime  # see make_drop_event
        return event

    def test_drag_enter_accepts_element_drags(self, view):
        event = self._drag_event("amp", "enter")
        view.dragEnterEvent(event)
        assert event.isAccepted()

    def test_drag_move_accepts_element_drags(self, view):
        event = self._drag_event("amp", "move")
        view.dragMoveEvent(event)
        assert event.isAccepted()


class TestClickAndDropShareOnePath:
    def test_add_stage_element_delegates_to_add_stage_element_at(self, view):
        calls = []
        real = view.add_stage_element_at
        view.add_stage_element_at = lambda *a, **k: (calls.append(a), real(*a, **k))[1]
        view.add_stage_element("amp")
        assert calls == [("amp", 0.0, 0.0)]
