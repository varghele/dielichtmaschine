"""
HSV Color Wheel widget for Auto mode color override.
"""

import math
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from PyQt6.QtCore import QCoreApplication, Qt, pyqtSignal, QPointF
from PyQt6.QtGui import QPainter, QColor, QImage, QPen

from gui.theme_style import bind_style, token_color


class HSVColorWheel(QWidget):
    """Interactive HSV color wheel with override/auto toggle.

    Hue = angle around the wheel, Saturation = distance from center.
    Value is fixed at 1.0 (full brightness).
    """

    color_changed = pyqtSignal(int, int, int)  # R, G, B

    def __init__(self, parent=None):
        super().__init__(parent)

        self._hue = 0.0         # 0-360
        self._saturation = 1.0  # 0-1
        self._override_active = False
        self._dragging = False
        self._wheel_radius = 0
        self._wheel_center = QPointF(0, 0)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Wheel area
        self._wheel_widget = _WheelCanvas(self)
        self._wheel_widget.setMinimumSize(150, 150)
        self._wheel_widget.position_selected.connect(self._on_position_selected)
        layout.addWidget(self._wheel_widget)

        # Color swatch
        self._swatch = QLabel()
        self._swatch.setFixedHeight(24)
        # Starts on white LIGHT (data); only the border is chrome.
        self._swatch_fill = "white"
        bind_style(self._swatch, self._swatch_style)
        layout.addWidget(self._swatch)

        # Override / Auto buttons
        btn_layout = QHBoxLayout()
        self._override_btn = QPushButton(QCoreApplication.translate("HSVColorWheel", "Override"))
        self._override_btn.setCheckable(True)
        self._override_btn.toggled.connect(self._on_override_toggled)
        self._auto_btn = QPushButton(QCoreApplication.translate("HSVColorWheel", "Auto"))
        self._auto_btn.setCheckable(True)
        self._auto_btn.setChecked(True)
        self._auto_btn.toggled.connect(self._on_auto_toggled)
        btn_layout.addWidget(self._override_btn)
        btn_layout.addWidget(self._auto_btn)
        layout.addLayout(btn_layout)

        self._update_swatch()

    def is_override_active(self) -> bool:
        return self._override_active

    def get_color(self):
        """Get current RGB tuple."""
        c = QColor.fromHsvF(self._hue / 360.0, self._saturation, 1.0)
        return (c.red(), c.green(), c.blue())

    def get_hue_saturation(self) -> tuple:
        """Get current (hue 0-360, saturation 0-1)."""
        return (self._hue, self._saturation)

    def set_state(self, override_active: bool, hue: float, saturation: float) -> None:
        """Restore wheel state.

        Emits :pyattr:`color_changed` with the restored RGB (or ``-1,-1,-1``
        for auto) so a connected engine learns the persisted override
        immediately, rather than only after the user moves the wheel. The
        connected slot is responsible for ignoring no-op refreshes if it
        cares about minimising work.
        """
        self._hue = max(0.0, min(360.0, hue))
        self._saturation = max(0.0, min(1.0, saturation))
        self._wheel_widget._selector_hue = self._hue
        self._wheel_widget._selector_sat = self._saturation
        self._wheel_widget.update()
        self._update_swatch()

        # Toggle buttons silently to match override_active.
        self._override_btn.blockSignals(True)
        self._auto_btn.blockSignals(True)
        self._override_btn.setChecked(override_active)
        self._auto_btn.setChecked(not override_active)
        self._override_btn.blockSignals(False)
        self._auto_btn.blockSignals(False)
        self._override_active = override_active

        if override_active:
            r, g, b = self.get_color()
            self.color_changed.emit(r, g, b)
        else:
            self.color_changed.emit(-1, -1, -1)

    def _on_position_selected(self, hue: float, saturation: float):
        self._hue = hue
        self._saturation = saturation
        self._update_swatch()
        if self._override_active:
            r, g, b = self.get_color()
            self.color_changed.emit(r, g, b)

    def _on_override_toggled(self, checked):
        if checked:
            self._auto_btn.blockSignals(True)
            self._auto_btn.setChecked(False)
            self._auto_btn.blockSignals(False)
            self._override_active = True
            r, g, b = self.get_color()
            self.color_changed.emit(r, g, b)

    def _on_auto_toggled(self, checked):
        if checked:
            self._override_btn.blockSignals(True)
            self._override_btn.setChecked(False)
            self._override_btn.blockSignals(False)
            self._override_active = False
            # Signal with (-1, -1, -1) to indicate auto mode
            self.color_changed.emit(-1, -1, -1)

    def _update_swatch(self):
        c = QColor.fromHsvF(self._hue / 360.0, self._saturation, 1.0)
        self._swatch_fill = c.name()
        bind_style(self._swatch, self._swatch_style)

    def _swatch_style(self, t: dict) -> str:
        return (f"background-color: {self._swatch_fill};"
                f" border: 1px solid {t['swatch_border']};")


class _WheelCanvas(QWidget):
    """Renders the HSV wheel and handles mouse interaction."""

    position_selected = pyqtSignal(float, float)  # hue (0-360), saturation (0-1)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._wheel_image: QImage = None
        self._selector_hue = 0.0
        self._selector_sat = 1.0
        self._dragging = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        size = min(self.width(), self.height()) - 4
        if size < 10:
            return

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        radius = size / 2.0

        # Build wheel image if needed
        if self._wheel_image is None or self._wheel_image.width() != size:
            self._wheel_image = self._build_wheel_image(size)

        # Draw wheel
        x = int(cx - size / 2)
        y = int(cy - size / 2)
        painter.drawImage(x, y, self._wheel_image)

        # Draw selector circle
        angle_rad = math.radians(self._selector_hue)
        dist = self._selector_sat * radius
        sx = cx + dist * math.cos(angle_rad)
        sy = cy - dist * math.sin(angle_rad)

        painter.setPen(QPen(token_color("wheel_marker"), 2))
        painter.drawEllipse(QPointF(sx, sy), 6, 6)
        painter.setPen(QPen(token_color("wheel_marker_outline"), 1))
        painter.drawEllipse(QPointF(sx, sy), 7, 7)

    def _build_wheel_image(self, size: int) -> QImage:
        """Render HSV wheel to a QImage."""
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)

        cx = size / 2.0
        cy = size / 2.0
        radius = size / 2.0

        for y in range(size):
            for x in range(size):
                dx = x - cx
                dy = cy - y  # Flip Y so 0 degrees is right
                dist = math.sqrt(dx * dx + dy * dy)

                if dist > radius:
                    continue

                hue = (math.degrees(math.atan2(dy, dx)) % 360.0) / 360.0
                sat = dist / radius
                c = QColor.fromHsvF(hue, sat, 1.0)
                image.setPixelColor(x, y, c)

        return image

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._update_from_mouse(event.position())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._update_from_mouse(event.position())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def _update_from_mouse(self, pos):
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        size = min(self.width(), self.height()) - 4
        radius = size / 2.0

        dx = pos.x() - cx
        dy = cy - pos.y()
        dist = math.sqrt(dx * dx + dy * dy)

        hue = math.degrees(math.atan2(dy, dx)) % 360.0
        sat = min(1.0, dist / radius)

        self._selector_hue = hue
        self._selector_sat = sat
        self.update()
        self.position_selected.emit(hue, sat)
