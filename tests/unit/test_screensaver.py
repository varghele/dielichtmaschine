"""Tests for the screensaver / pause screen (design reference 12).

Rendering determinism, the close-on-any-input contract (with the
initial mouse-move dead zone), the deterministic hooks the golden test
relies on (set_phase / set_time_text / set_animation_enabled), the
reference backdrop (48px grid, four corner marks), and the honest
defaults of the status bar: state we cannot know is injectable, never
faked.
"""

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QFontMetrics, QKeyEvent, QMouseEvent

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


# ----------------------------------------------------------------- content


def test_builds_with_brand_content(window):
    assert window.wordmark_label.text() == APP_WORDMARK
    assert window.slogan_label.text() == SLOGAN_EN
    assert window.state_label.text() == "PAUSE"


def test_state_text_is_injectable(qapp):
    w = make_window(state_text="Interval")
    try:
        # MicroLabel uppercases what it renders.
        assert w.state_label.text() == "INTERVAL"
        w.set_state_text("back at 22:00")
        assert w.state_label.text() == "BACK AT 22:00"
    finally:
        w.deleteLater()


# ------------------------------------------------------------- status bar


def test_default_status_is_honest(window):
    """No rig look and no ArtNet state are known inside the widget, so
    the default bar claims neither. The reference's "RIG: PAUSENLICHT /
    WARMWEISS 20%" and "ARTNET AKTIV / 44 Hz" are live values with no
    data source here; the activation hint names the only trigger that
    exists (View > Screensaver in gui/gui.py::_start_screensaver), not
    the reference's LIVE pause key / 5 min idle, which do not."""
    from gui.screens.screensaver import ACTIVATION_HINT, KEY_HINT

    assert window.status_segments() == [KEY_HINT, ACTIVATION_HINT]
    assert window.status_text() == (
        "PRESS ANY KEY TO EXIT · ACTIVATE: VIEW MENU > SCREENSAVER")
    text = window.status_text()
    for lie in ("ARTNET", "RIG:", "IDLE", "%"):
        assert lie not in text


def test_rig_and_artnet_segments_injectable(qapp):
    w = make_window(rig_text="Rig: pause light warm white 20%",
                    artnet_text="ArtNet active 44 Hz")
    try:
        assert w.status_segments() == [
            "Rig: pause light warm white 20%",
            "ArtNet active 44 Hz",
            "PRESS ANY KEY TO EXIT",
            "ACTIVATE: VIEW MENU > SCREENSAVER",
        ]
        # Setters add and remove them again.
        w.set_artnet_text(None)
        assert "ArtNet active 44 Hz" not in w.status_segments()
        w.set_rig_text(None)
        assert len(w.status_segments()) == 2
        w.set_artnet_text("ArtNet stopped")
        assert w.status_segments()[0] == "ArtNet stopped"
    finally:
        w.deleteLater()


def test_status_segments_fully_replaceable(qapp):
    w = make_window(status_segments=["BREAK", "BACK AT 22:00"])
    try:
        assert w.status_text() == "BREAK · BACK AT 22:00"
        w.set_status_segments(None)  # back to the honest default
        assert w.status_segments()[0] == "PRESS ANY KEY TO EXIT"
    finally:
        w.deleteLater()


def test_status_bar_labels_have_separators_between_segments(window):
    from gui.screens.screensaver import STATUS_SEPARATOR

    texts = [w.text() for w in window.status_bar.findChildren(type(
        window.state_label))]
    assert texts.count(STATUS_SEPARATOR) == len(window.status_segments()) - 1


def test_status_bar_pinned_to_the_bottom(window):
    from gui.screens.screensaver import STATUS_BAR_H

    # A hidden widget gets no resizeEvent; the layout activates on the
    # first render (which is exactly what the golden captures).
    window.grab()
    bar = window.status_bar.geometry()
    assert bar.height() == STATUS_BAR_H
    assert bar.width() == window.width()
    assert bar.bottom() == window.height() - 1
    # The status bar overlays the bottom of the centered column without
    # colliding with the clock (reference: absolutely positioned bar).
    clock_bottom = window.clock_label.mapTo(
        window, window.clock_label.rect().bottomLeft()).y()
    assert clock_bottom < bar.top()


def test_no_glyph_outside_the_brand_fonts():
    """Every non-ASCII character we render must exist in IBM Plex Mono.

    Only the interpunct qualifies today; the reference's "▸" is not
    used. The offscreen Windows QPA has no font database, so skip there
    rather than assert on fallback boxes."""
    from gui.fonts import register_brand_fonts
    from gui.screens.screensaver import (
        ACTIVATION_HINT, DEFAULT_STATE_TEXT, KEY_HINT, STATUS_SEPARATOR,
    )
    from gui.typography import mono_font

    for text in (KEY_HINT, ACTIVATION_HINT, DEFAULT_STATE_TEXT):
        assert text.isascii(), f"{text!r} needs a glyph check"

    register_brand_fonts()
    metrics = QFontMetrics(mono_font(10))
    if not metrics.inFont("A"):
        pytest.skip("no font database on this platform (offscreen QPA)")
    assert metrics.inFont(STATUS_SEPARATOR)


# --------------------------------------------------------------- backdrop


def test_grid_and_corner_marks_are_painted(window):
    from gui.screens.screensaver import (
        GRID_PITCH_PX, MARK_INSET_PX, MARK_SIZE_PX, SCREENSAVER_BG,
    )
    from PyQt6.QtGui import QColor

    arr = grab_array(window)
    bg = np.array(QColor(SCREENSAVER_BG).getRgb()[:3], dtype=np.int16)

    # A grid line sits on every 48px column; the pixels between two
    # lines, away from the centered content and away from the grid rows
    # at y=384 / y=432, are pure background.
    def column(x):
        return arr[400:430, x, :3].astype(np.int16)

    assert not np.array_equal(column(GRID_PITCH_PX * 2), np.tile(bg, (30, 1)))
    assert np.array_equal(column(GRID_PITCH_PX * 2 + 20), np.tile(bg, (30, 1)))

    # Corner cross: the center of the top-left mark is mark ink.
    cx = cy = MARK_INSET_PX + MARK_SIZE_PX // 2
    patch = arr[cy - 1:cy + 2, cx - 1:cx + 2, :3].astype(np.int16)
    assert np.abs(patch - bg).sum() > 0
    # ...and the mark is a cross, not a box: its corner is empty.
    assert np.array_equal(
        arr[MARK_INSET_PX, MARK_INSET_PX, :3].astype(np.int16), bg)


def test_corner_marks_track_the_window_size(qapp):
    from gui.screens.screensaver import (
        MARK_INSET_PX, MARK_SIZE_PX, SCREENSAVER_BG,
    )
    from PyQt6.QtGui import QColor

    w = make_window()
    try:
        w.setFixedSize(700, 400)
        arr = grab_array(w)
        bg = np.array(QColor(SCREENSAVER_BG).getRgb()[:3], dtype=np.int16)
        cx = 700 - MARK_INSET_PX - MARK_SIZE_PX // 2 - 1
        cy = 400 - MARK_INSET_PX - MARK_SIZE_PX // 2 - 1
        patch = arr[cy - 1:cy + 2, cx - 1:cx + 2, :3].astype(np.int16)
        assert np.abs(patch - bg).sum() > 0
    finally:
        w.deleteLater()


# ---------------------------------------------------------------- animation


def test_rotor_periods_match_the_reference():
    from gui.screens import screensaver

    assert screensaver.INNER_PERIOD_S == 16.0   # lm-spin 16s
    assert screensaver.OUTER_PERIOD_S == 40.0   # lm-spin 40s reverse
    assert screensaver.PULSE_PERIOD_S == 4.0    # lm-pulse 4s


def test_outer_ring_counter_rotates(window):
    window.set_phase(4.0)
    assert window.rotor._inner_angle > 0
    assert window.rotor._outer_angle < 0


def test_pulse_peaks_at_half_period(window):
    from gui.screens.screensaver import PULSE_MAX_ALPHA, PULSE_MIN_ALPHA

    window.set_phase(0.0)
    assert window.rotor._pulse_alpha == pytest.approx(PULSE_MIN_ALPHA)
    window.set_phase(2.0)  # the golden's pinned frame
    assert window.rotor._pulse_alpha == pytest.approx(PULSE_MAX_ALPHA)


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


# ------------------------------------------------------------------ input


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
