"""The screensaver / pause screen (North Star card 11a, slice SS1).

A frameless fullscreen window shown between songs and sets: the animated
brand rotor, the wordmark, a large mono clock, and a status line. Any
key press, mouse click, or real mouse movement dismisses it (with a
small dead zone so the wake-up jiggle that opened it does not instantly
close it again).

The widget is deliberately self-contained: no imports from gui.gui, no
QSettings. Colors are hardcoded from the design handoff rather than
taken from theme tokens because the screensaver always renders on the
screensaver black, independent of the app theme.

Animation (design handoff "Brand" section): the inner 8-segment rotor
spins at INNER_PERIOD_S per revolution, the thin outer ring
counter-rotates slower at OUTER_PERIOD_S, and the Glutorange center dot
pulses its alpha over PULSE_PERIOD_S. A ~30 fps QTimer advances a phase
clock; ``set_phase(t_seconds)`` computes all angles deterministically
from a time value so tests and goldens can pin an exact frame, and
``set_animation_enabled(False)`` stops the timer entirely.
"""

import math
import time

from PyQt6.QtCore import QDateTime, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from gui.fonts import FONT_DISPLAY, FONT_MONO
from gui.typography import DisplayLabel, MicroLabel, mono_font
from utils.app_identity import APP_WORDMARK, SLOGAN_EN

# The screensaver black: deliberately darker than the dark theme's
# window token (#141416) - this is the "screen off" surface from the
# design handoff card 11a, hardcoded on purpose.
SCREENSAVER_BG = "#0E0E10"

# Handoff palette for the on-black elements (card 11a values).
INK = "#F4F1EA"            # wordmark + clock
DIM_INK = "#5C6068"        # slogan + status line
ROTOR_SEGMENT = "#C9CDD2"  # the 8 inner arc segments
OUTER_RING = "#3F4348"     # the thin outer registration ring
ACCENT = "#F0562E"         # Glutorange center dot

# Animation timing (handoff: inner 10-16 s/rev, outer counter-rotating
# 24-40 s/rev, center pulses).
INNER_PERIOD_S = 12.0
OUTER_PERIOD_S = 30.0
PULSE_PERIOD_S = 4.0
PULSE_MIN_ALPHA = 0.35
PULSE_MAX_ALPHA = 1.0
TICK_MS = 33  # ~30 fps

# Segments of the default bottom status line; real ArtNet / pause-light
# state gets injected by the caller once that wiring exists.
DEFAULT_STATUS_SEGMENTS = (
    "PAUSE LIGHT ACTIVE",
    "ARTNET RUNNING",
    "PRESS ANY KEY TO EXIT",
)
STATUS_SEPARATOR = " · "


class RotorGlyph(QWidget):
    """The brand rotor, drawn programmatically with QPainter.

    Geometry follows the 64-unit glyph viewBox from the handoff, scaled
    to the widget size: 8 arc segments of 22.5 degrees every 45 degrees
    at radius 21 (stroke 8), a thin outer ring at radius 30, and a
    radius-6 accent center dot. The outer ring is finely dashed (card
    11a: dash 7.85 / gap 3.93) - a solid ring's counter-rotation would
    be invisible.
    """

    GLYPH_UNITS = 64.0

    def __init__(self, size: int = 220, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        # All input is the window's business.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._inner_angle = 0.0
        self._outer_angle = 0.0
        self._pulse_alpha = PULSE_MIN_ALPHA

    def set_state(self, inner_angle_deg: float, outer_angle_deg: float,
                  pulse_alpha: float) -> None:
        self._inner_angle = inner_angle_deg
        self._outer_angle = outer_angle_deg
        self._pulse_alpha = max(0.0, min(1.0, pulse_alpha))
        self.update()

    def paintEvent(self, event):  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = min(self.width(), self.height()) / self.GLYPH_UNITS
        cx, cy = self.width() / 2.0, self.height() / 2.0

        # Thin outer ring, counter-rotating (dash pattern is in units
        # of the pen width in Qt, hence the division).
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self._outer_angle)
        pen = QPen(QColor(OUTER_RING))
        pen.setWidthF(1.2 * scale)
        pen.setDashPattern([7.85 / 1.2, 3.93 / 1.2])
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        radius = 30.0 * scale
        painter.drawEllipse(QRectF(-radius, -radius, 2 * radius, 2 * radius))
        painter.restore()

        # Inner rotor: 8 flat-capped arc segments.
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self._inner_angle)
        pen = QPen(QColor(ROTOR_SEGMENT))
        pen.setWidthF(8.0 * scale)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        radius = 21.0 * scale
        rect = QRectF(-radius, -radius, 2 * radius, 2 * radius)
        for i in range(8):
            painter.drawArc(rect, i * 45 * 16, int(22.5 * 16))
        painter.restore()

        # Pulsing Glutorange center dot.
        dot = QColor(ACCENT)
        dot.setAlphaF(self._pulse_alpha)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot)
        radius = 6.0 * scale
        painter.drawEllipse(QPointF(cx, cy), radius, radius)


class ScreensaverWindow(QWidget):
    """Fullscreen pause screen: rotor, wordmark, clock, status line.

    Contract: ``activate()`` shows it fullscreen; any key press, mouse
    press, or mouse move beyond a small dead zone emits ``dismissed``
    and closes the window.
    """

    dismissed = pyqtSignal()

    MOUSE_DEAD_ZONE_PX = 24  # manhattan px the pointer may jiggle

    def __init__(self, status_segments=None, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("screensaver")
        # Local stylesheet so the screensaver black wins over any
        # app-wide theme QSS; WA_StyledBackground makes a plain QWidget
        # honor it.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QWidget#screensaver {{ background-color: {SCREENSAVER_BG}; }}")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.BlankCursor)

        self._time_override = None
        self._first_move_pos = None
        self._phase = 0.0
        self._last_tick = None

        self._build_ui(status_segments)

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._on_tick)
        self._animation_enabled = True
        self._timer.start()

        self.set_phase(0.0)
        self._refresh_clock()

    # ------------------------------------------------------------------ UI

    def _build_ui(self, status_segments) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(0)

        layout.addStretch(3)

        self.rotor = RotorGlyph(220, self)
        layout.addWidget(self.rotor, 0,
                         Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(36)

        self.wordmark_label = DisplayLabel(
            APP_WORDMARK, weight=QFont.Weight.ExtraBold, tracking_em=0.06,
            parent=self)
        self._pin_label_style(self.wordmark_label, FONT_DISPLAY, 44, 800, INK)
        layout.addWidget(self.wordmark_label)

        layout.addSpacing(8)

        self.slogan_label = MicroLabel(SLOGAN_EN, tracking_em=0.2,
                                       parent=self)
        self._pin_label_style(self.slogan_label, FONT_MONO, 12, 500, DIM_INK)
        layout.addWidget(self.slogan_label)

        layout.addSpacing(36)

        self.clock_label = QLabel("--:--", self)
        self.clock_label.setFont(mono_font(48, QFont.Weight.Medium))
        self._pin_label_style(self.clock_label, FONT_MONO, 72, 500, INK)
        layout.addWidget(self.clock_label)

        layout.addStretch(4)

        segments = (list(status_segments) if status_segments is not None
                    else list(DEFAULT_STATUS_SEGMENTS))
        self.status_label = MicroLabel(STATUS_SEPARATOR.join(segments),
                                       tracking_em=0.12, parent=self)
        self._pin_label_style(self.status_label, FONT_MONO, 10, 500, DIM_INK)
        layout.addWidget(self.status_label)

        for child in self.findChildren(QWidget):
            child.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            child.setMouseTracking(True)

    @staticmethod
    def _pin_label_style(label: QLabel, family: str, pixels: int,
                         weight_css: int, color: str) -> None:
        """Pin family / pixel size / weight in the label's own stylesheet.

        An app-wide theme stylesheet's ``QWidget { font-family }`` rule
        overrides fonts set via setFont, so relying on QFont alone would
        make the screensaver render differently themed vs unthemed. The
        label's own QSS wins in both contexts; letter spacing is not a
        QSS property and survives from the QFont set by the typography
        helpers. Design sizes are px at 1080p, pinned regardless of DPI.
        """
        font = label.font()
        font.setPixelSize(pixels)
        label.setFont(font)
        label.setStyleSheet(
            f'color: {color}; background: transparent; '
            f'font-family: "{family}"; font-size: {pixels}px; '
            f'font-weight: {weight_css};')
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter)

    # ----------------------------------------------------------- animation

    def set_animation_enabled(self, enabled: bool) -> None:
        self._animation_enabled = bool(enabled)
        if self._animation_enabled:
            self._last_tick = None
            self._timer.start()
        else:
            self._timer.stop()

    def set_phase(self, t_seconds: float) -> None:
        """Compute all animation state from an absolute time value.

        Deterministic: the same phase always paints the same frame,
        which is what the golden test pins.
        """
        self._phase = t_seconds
        inner = (t_seconds / INNER_PERIOD_S * 360.0) % 360.0
        outer = -((t_seconds / OUTER_PERIOD_S * 360.0) % 360.0)
        # Cosine ease between min and max alpha, min at t=0 (card 11a:
        # opacity 0.35 at 0%/100%, 1.0 at 50%).
        wave = 0.5 - 0.5 * math.cos(
            2.0 * math.pi * t_seconds / PULSE_PERIOD_S)
        pulse = PULSE_MIN_ALPHA + (PULSE_MAX_ALPHA - PULSE_MIN_ALPHA) * wave
        self.rotor.set_state(inner, outer, pulse)

    def _on_tick(self) -> None:
        now = time.monotonic()
        if self._last_tick is None:
            self._last_tick = now
        self.set_phase(self._phase + (now - self._last_tick))
        self._last_tick = now
        self._refresh_clock()

    # --------------------------------------------------------------- clock

    def set_time_text(self, text: str) -> None:
        """Pin the clock to a fixed string (tests / goldens)."""
        self._time_override = text
        self.clock_label.setText(text)

    def _refresh_clock(self) -> None:
        if self._time_override is not None:
            return
        text = QDateTime.currentDateTime().toString("HH:mm")
        if text != self.clock_label.text():
            self.clock_label.setText(text)

    # ------------------------------------------------------ show / dismiss

    def activate(self) -> None:
        """Show fullscreen and arm the close-on-any-input contract."""
        self._first_move_pos = None
        self._refresh_clock()
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def _dismiss(self) -> None:
        self.dismissed.emit()
        self.close()

    def keyPressEvent(self, event):  # noqa: N802 (Qt API)
        self._dismiss()

    def mousePressEvent(self, event):  # noqa: N802 (Qt API)
        self._dismiss()

    def mouseMoveEvent(self, event):  # noqa: N802 (Qt API)
        # Dead zone: the first move only records where the pointer woke
        # up, so the jiggle that OPENED the screensaver cannot close it.
        pos = event.position().toPoint()
        if self._first_move_pos is None:
            self._first_move_pos = pos
            return
        if ((pos - self._first_move_pos).manhattanLength()
                > self.MOUSE_DEAD_ZONE_PX):
            self._dismiss()

    def closeEvent(self, event):  # noqa: N802 (Qt API)
        self._timer.stop()
        super().closeEvent(event)
