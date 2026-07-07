"""Tests for the screensaver / pause screen (North Star card 11a).

Rendering determinism, the close-on-any-input contract (with the
initial mouse-move dead zone), and the deterministic hooks the golden
test relies on (set_phase / set_time_text / set_animation_enabled).
"""

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent

from tests.visual.harness import qimage_to_array
from utils.app_identity import APP_WORDMARK, SLOGAN_EN


def make_window(**kwargs):
    from gui.screens.screensaver import ScreensaverWindow
    window = ScreensaverWindow(**kwargs)
    window.set_animation_enabled(False)
    window.setFixedSize(960, 540)
    return window


def grab_array(window) -> np.ndarray:
    return qimage_to_array(window.grab().toImage())


def move_event(x: int, y: int) -> QMouseEvent:
    return QMouseEvent(
        QEvent.Type.MouseMove, QPointF(x, y), QPointF(x, y),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier)


@pytest.fixture
def window(qapp):
    w = make_window()
    yield w
    w.close()
    w.deleteLater()


def test_builds_with_brand_content(window):
    assert window.wordmark_label.text() == APP_WORDMARK
    assert window.slogan_label.text() == SLOGAN_EN
    assert window.status_label.text() == (
        "PAUSE LIGHT ACTIVE · ARTNET RUNNING · PRESS ANY KEY TO EXIT")


def test_status_segments_injectable(qapp):
    w = make_window(status_segments=["BREAK", "BACK AT 22:00"])
    try:
        assert w.status_label.text() == "BREAK · BACK AT 22:00"
    finally:
        w.deleteLater()


def test_clock_starts_from_system_time(window):
    # No override set: the constructor fills in a real HH:MM.
    text = window.clock_label.text()
    assert len(text) == 5 and text[2] == ":"
    assert text != "--:--"


def test_set_time_text_reflected_and_pinned(window):
    window.set_time_text("21:36")
    assert window.clock_label.text() == "21:36"
    # The timer's clock refresh must not overwrite the override.
    window._refresh_clock()
    assert window.clock_label.text() == "21:36"


def test_set_phase_is_deterministic(window):
    window.set_time_text("21:36")
    window.set_phase(1.234)
    first = grab_array(window)
    window.set_phase(7.0)  # move away...
    window.set_phase(1.234)  # ...and back to the same phase
    second = grab_array(window)
    assert np.array_equal(first, second)


def test_different_phases_paint_differently(window):
    window.set_time_text("21:36")
    window.set_phase(0.0)
    first = grab_array(window)
    window.set_phase(3.0)
    second = grab_array(window)
    assert not np.array_equal(first, second)


def test_key_press_dismisses_and_closes(qapp, window):
    fired = []
    window.dismissed.connect(lambda: fired.append(True))
    window.show()
    assert window.isVisible()
    window.keyPressEvent(QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Space,
        Qt.KeyboardModifier.NoModifier))
    assert fired == [True]
    assert not window.isVisible()


def test_mouse_press_dismisses(qapp, window):
    fired = []
    window.dismissed.connect(lambda: fired.append(True))
    window.show()
    window.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(10, 10), QPointF(10, 10),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier))
    assert fired == [True]
    assert not window.isVisible()


def test_mouse_move_dead_zone(qapp, window):
    fired = []
    window.dismissed.connect(lambda: fired.append(True))
    window.show()
    # First move just records the wake-up position.
    window.mouseMoveEvent(move_event(100, 100))
    assert fired == []
    # A jiggle inside the dead zone must not dismiss.
    window.mouseMoveEvent(move_event(105, 103))
    assert fired == []
    assert window.isVisible()
    # A real move beyond the dead zone dismisses.
    window.mouseMoveEvent(move_event(200, 200))
    assert fired == [True]
    assert not window.isVisible()


def test_activate_rearms_dead_zone(qapp, window):
    window.mouseMoveEvent(move_event(100, 100))
    assert window._first_move_pos == QPoint(100, 100)
    window.activate()
    assert window._first_move_pos is None
    assert window.isFullScreen()
    window.close()


def test_set_animation_enabled_controls_timer(window):
    assert not window._timer.isActive()  # disabled by make_window
    window.set_animation_enabled(True)
    assert window._timer.isActive()
    window.set_animation_enabled(False)
    assert not window._timer.isActive()
