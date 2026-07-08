"""The screensaver / pause screen (design reference screen 12).

A frameless fullscreen window shown between songs and sets: the faint
48px registration grid, four corner marks, the animated brand rotor, the
wordmark with its slogan, a state kicker over a large mono clock, and a
bottom status bar. Any key press, mouse click, or real mouse movement
dismisses it (with a small dead zone so the wake-up jiggle that opened
it does not instantly close it again).

The widget is deliberately self-contained: no imports from gui.gui, no
QSettings, no reach into the ArtNet controllers. Colors are hardcoded
from ``design_handoff_lichtmaschine_app/screens/12-screensaver.html``
rather than taken from theme tokens because the screensaver always
renders on the screensaver black, independent of the app theme.

Live state the widget cannot know (which rig look the pause light is
holding, whether ArtNet output is running) is *injectable*: the
constructor and the ``set_rig_text`` / ``set_artnet_text`` setters take
it from the caller. The honest default omits those segments entirely -
the reference's "RIG: PAUSENLICHT / WARMWEISS 20%" and "ARTNET AKTIV /
44 Hz" would be fiction here, and the reference's activation hint
("LIVE pause key or auto after 5 min idle") describes triggers that do
not exist yet, so the default hint names the one that does: the View
menu (gui/gui.py::_start_screensaver).

Animation (reference screen 12): the inner 8-segment rotor spins
clockwise at INNER_PERIOD_S per revolution, the thin dashed outer ring
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
from PyQt6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QStyle, QStyleOption, QVBoxLayout,
    QWidget,
)

from gui.fonts import FONT_DISPLAY, FONT_MONO
from gui.typography import DisplayLabel, MicroLabel
from utils.app_identity import APP_WORDMARK, SLOGAN_EN

# The screensaver black: deliberately darker than the dark theme's
# window token (#141416) - this is the "screen off" surface from the
# design reference, hardcoded on purpose.
SCREENSAVER_BG = "#0E0E10"

# Reference palette for the on-black elements.
INK = "#F4F1EA"            # wordmark + clock
MUTED_INK = "#8D9299"      # the state kicker above the clock
DIM_INK = "#5C6068"        # slogan + status bar
ROTOR_SEGMENT = "#C9CDD2"  # the 8 inner arc segments
OUTER_RING = "#3F4348"     # the thin outer registration ring
ACCENT = "#F0562E"         # Glutorange center dot
MARK_INK = "#3A3A3A"       # the four corner registration crosses

# Backdrop: 1px lines every 48px in rgba(141,146,153,0.04).
GRID_PITCH_PX = 48
GRID_INK = QColor(141, 146, 153, 10)

# Corner registration crosses: 15x15 px, 24px in from each corner.
MARK_SIZE_PX = 15
MARK_INSET_PX = 24

# Bottom status bar: 34px tall, spans the full width, 28px between the
# segments and the interpunct separators that sit between them.
STATUS_BAR_H = 34
STATUS_GAP_PX = 28
STATUS_SEPARATOR = "·"  # MIDDLE DOT; IBM Plex Mono has it

# Animation timing (reference: inner ring 16 s/rev, outer ring
# counter-rotating 40 s/rev, center pulses over 4 s).
INNER_PERIOD_S = 16.0
OUTER_PERIOD_S = 40.0
PULSE_PERIOD_S = 4.0
PULSE_MIN_ALPHA = 0.35
PULSE_MAX_ALPHA = 1.0
TICK_MS = 33  # ~30 fps

# Design pixel sizes at 1080p, pinned regardless of DPI.
ROTOR_SIZE_PX = 220
BLOCK_GAP_PX = 36
WORDMARK_PX = 44
SLOGAN_PX = 12
STATE_PX = 13
CLOCK_PX = 72
STATUS_PX = 10
SLOGAN_GAP_PX = 8

# The state kicker above the clock. "PAUSE" is what the screensaver
# itself means; anything richer is the caller's to inject.
DEFAULT_STATE_TEXT = "PAUSE"

# The two status segments the widget can state truthfully on its own.
KEY_HINT = "PRESS ANY KEY TO EXIT"
ACTIVATION_HINT = "ACTIVATE: VIEW MENU > SCREENSAVER"


class RotorGlyph(QWidget):
    """The brand rotor, drawn programmatically with QPainter.

    Geometry follows the 64-unit glyph viewBox from the reference,
    scaled to the widget size: an inner ring at radius 21 with stroke 8
    dashed 8.24/8.24 (that is exactly 8 arc segments of 22.5 degrees
    every 45 degrees, since 2*pi*21 / 16 = 8.246), a thin outer ring at
    radius 30 stroke 1.2 dashed 7.85/3.93, and a radius-6 accent center
    dot. Both rings are dashed on purpose: a solid ring's rotation would
    be invisible.
    """

    GLYPH_UNITS = 64.0

    def __init__(self, size: int = ROTOR_SIZE_PX, parent=None):
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
    """Fullscreen pause screen: grid, corner marks, rotor, wordmark,
    slogan, state kicker, clock, status bar.

    Contract: ``activate()`` shows it fullscreen; any key press, mouse
    press, or mouse move beyond a small dead zone emits ``dismissed``
    and closes the window.
    """

    dismissed = pyqtSignal()

    MOUSE_DEAD_ZONE_PX = 24  # manhattan px the pointer may jiggle

    def __init__(self, status_segments=None, rig_text=None, artnet_text=None,
                 state_text=DEFAULT_STATE_TEXT, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("screensaver")
        # Local stylesheet so the screensaver black wins over any
        # app-wide theme QSS; WA_StyledBackground makes a plain QWidget
        # honor it (paintEvent draws PE_Widget for it explicitly).
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

        self._explicit_segments = (list(status_segments)
                                   if status_segments is not None else None)
        self._rig_text = rig_text or None
        self._artnet_text = artnet_text or None

        self._build_ui(state_text)

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._on_tick)
        self._animation_enabled = True
        self._timer.start()

        self.set_phase(0.0)
        self._refresh_clock()

    # ------------------------------------------------------------------ UI

    def _build_ui(self, state_text: str) -> None:
        # One grid cell holds both children, so the centered column
        # spans the full window and the status bar overlays its bottom
        # 34px - exactly the reference's absolutely positioned flex
        # column (inset:0) plus a separate bottom bar. A stacking layout
        # rather than manual geometry, because resizeEvent is not
        # delivered to a hidden widget (grab() would render a stale
        # layout).
        root = QGridLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.content = QWidget(self)
        column = QVBoxLayout(self.content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        column.addStretch(1)

        self.rotor = RotorGlyph(ROTOR_SIZE_PX, self.content)
        column.addWidget(self.rotor, 0, Qt.AlignmentFlag.AlignHCenter)

        column.addSpacing(BLOCK_GAP_PX)

        brand = QWidget(self.content)
        brand_box = QVBoxLayout(brand)
        brand_box.setContentsMargins(0, 0, 0, 0)
        brand_box.setSpacing(0)
        self.wordmark_label = DisplayLabel(
            APP_WORDMARK, weight=QFont.Weight.ExtraBold, tracking_em=0.06,
            parent=brand)
        self._pin_label_style(self.wordmark_label, FONT_DISPLAY,
                              WORDMARK_PX, 800, INK)
        brand_box.addWidget(self.wordmark_label)
        brand_box.addSpacing(SLOGAN_GAP_PX)
        self.slogan_label = MicroLabel(
            SLOGAN_EN, weight=QFont.Weight.Normal, tracking_em=0.2,
            parent=brand)
        self._pin_label_style(self.slogan_label, FONT_MONO,
                              SLOGAN_PX, 400, DIM_INK)
        brand_box.addWidget(self.slogan_label)
        column.addWidget(brand)

        column.addSpacing(BLOCK_GAP_PX)

        clock_block = QWidget(self.content)
        clock_box = QVBoxLayout(clock_block)
        clock_box.setContentsMargins(0, 0, 0, 0)
        clock_box.setSpacing(0)
        self.state_label = MicroLabel(state_text, tracking_em=0.2,
                                      parent=clock_block)
        self._pin_label_style(self.state_label, FONT_MONO,
                              STATE_PX, 500, MUTED_INK)
        clock_box.addWidget(self.state_label)
        self.clock_label = QLabel("--:--", clock_block)
        self._pin_label_style(self.clock_label, FONT_MONO,
                              CLOCK_PX, 400, INK)
        # line-height 1.2 in the reference.
        self.clock_label.setFixedHeight(int(CLOCK_PX * 1.2))
        clock_box.addWidget(self.clock_label)
        column.addWidget(clock_block)

        column.addStretch(1)
        root.addWidget(self.content, 0, 0)

        self.status_bar = QWidget(self)
        self.status_bar.setFixedHeight(STATUS_BAR_H)
        root.addWidget(self.status_bar, 0, 0,
                       Qt.AlignmentFlag.AlignBottom)
        self._status_box = QHBoxLayout(self.status_bar)
        self._status_box.setContentsMargins(0, 0, 0, 0)
        self._status_box.setSpacing(STATUS_GAP_PX)
        self._status_labels = []
        self._rebuild_status()

        self._make_children_click_through()

    def _make_children_click_through(self) -> None:
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

    # -------------------------------------------------------------- status

    def status_segments(self) -> list:
        """The segments currently shown, left to right.

        Explicitly injected segments win; otherwise the optional rig and
        ArtNet segments (only when the caller supplied them) precede the
        two hints the widget can state truthfully by itself.
        """
        if self._explicit_segments is not None:
            return list(self._explicit_segments)
        return [s for s in (self._rig_text, self._artnet_text,
                            KEY_HINT, ACTIVATION_HINT) if s]

    def status_text(self) -> str:
        """The status bar read as one line (tests, logs)."""
        return f" {STATUS_SEPARATOR} ".join(self.status_segments())

    def set_status_segments(self, segments) -> None:
        """Replace the whole status bar (None restores the default)."""
        self._explicit_segments = (list(segments) if segments is not None
                                   else None)
        self._rebuild_status()

    def set_rig_text(self, text) -> None:
        """Inject the rig / pause-light segment, e.g. "RIG: PAUSE LIGHT
        WARM WHITE 20%". None removes it. Never guessed here."""
        self._rig_text = text or None
        self._rebuild_status()

    def set_artnet_text(self, text) -> None:
        """Inject the ArtNet segment, e.g. "ARTNET ACTIVE 44 HZ". None
        removes it. The widget never inspects the output controller."""
        self._artnet_text = text or None
        self._rebuild_status()

    def set_state_text(self, text: str) -> None:
        """The kicker above the clock (default "PAUSE")."""
        self.state_label.setText(text)

    def _rebuild_status(self) -> None:
        while self._status_box.count():
            item = self._status_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._status_labels = []

        self._status_box.addStretch(1)
        segments = self.status_segments()
        for index, segment in enumerate(segments):
            if index:
                self._status_box.addWidget(self._status_micro(
                    STATUS_SEPARATOR))
            label = self._status_micro(segment)
            self._status_labels.append(label)
            self._status_box.addWidget(label)
        self._status_box.addStretch(1)
        self._make_children_click_through()

    def _status_micro(self, text: str) -> MicroLabel:
        # Tracking 0: the reference sets no letter-spacing on the bar.
        label = MicroLabel(text, weight=QFont.Weight.Normal, tracking_em=0.0,
                           parent=self.status_bar)
        self._pin_label_style(label, FONT_MONO, STATUS_PX, 400, DIM_INK)
        return label

    # ------------------------------------------------------------ backdrop

    def paintEvent(self, event):  # noqa: N802 (Qt API)
        # WA_StyledBackground normally paints the object-name rule for
        # us, but overriding paintEvent takes that over: draw PE_Widget
        # first, then the backdrop.
        option = QStyleOption()
        option.initFrom(self)
        painter = QPainter(self)
        style = self.style()
        if style is not None:
            style.drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option,
                                painter, self)
        self._paint_grid(painter)
        self._paint_corner_marks(painter)

    def _paint_grid(self, painter: QPainter) -> None:
        width, height = self.width(), self.height()
        for x in range(0, width, GRID_PITCH_PX):
            painter.fillRect(x, 0, 1, height, GRID_INK)
        for y in range(0, height, GRID_PITCH_PX):
            painter.fillRect(0, y, width, 1, GRID_INK)

    def _paint_corner_marks(self, painter: QPainter) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen = QPen(QColor(MARK_INK))
        pen.setWidth(1)
        painter.setPen(pen)
        half = MARK_SIZE_PX / 2.0
        inset = MARK_INSET_PX
        centers = (
            (inset + half, inset + half),
            (self.width() - inset - half, inset + half),
            (inset + half, self.height() - inset - half),
            (self.width() - inset - half, self.height() - inset - half),
        )
        for cx, cy in centers:
            painter.drawLine(QPointF(cx, cy - half), QPointF(cx, cy + half))
            painter.drawLine(QPointF(cx - half, cy), QPointF(cx + half, cy))
        painter.restore()

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
        # Cosine ease between min and max alpha, min at t=0 (reference:
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
