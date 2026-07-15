# timeline_ui/movement_block_dialog.py
# Dialog for editing movement sublane block parameters

import math
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QGroupBox, QSlider, QDoubleSpinBox, QSpinBox,
                             QLabel, QDialogButtonBox, QCheckBox, QFrame,
                             QPushButton, QComboBox, QWidget, QScrollArea,
                             QSizePolicy)
from PyQt6.QtCore import Qt, pyqtSignal, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath
from config.models import MovementBlock


def _active_tokens() -> dict:
    """Token dict of the theme currently applied to the app.

    Same stylesheet sniff as gui/tabs/stage_tab.py. Used only for the
    neutral chrome (backdrop/border) of the pan/tilt canvas; the shape,
    boundary and position overlays it paints are data colors.
    """
    from PyQt6.QtWidgets import QApplication
    from gui.theme_tokens import THEMES

    app = QApplication.instance()
    qss = app.styleSheet() if app is not None else ""
    light = THEMES.get("light")
    if light is not None and light["window"] in qss:
        return light
    return THEMES["dark"]


def generate_shape_points(effect_type: str, center_pan: float, center_tilt: float,
                          pan_amplitude: float, tilt_amplitude: float,
                          pan_min: float, pan_max: float, tilt_min: float, tilt_max: float,
                          lissajous_ratio: str = "1:2", num_points: int = 64) -> list:
    """Generate points for a movement shape with clipping.

    Args:
        effect_type: Type of shape to generate
        center_pan: Center pan position (0-255)
        center_tilt: Center tilt position (0-255)
        pan_amplitude: Pan amplitude from center
        tilt_amplitude: Tilt amplitude from center
        pan_min, pan_max: Pan boundary limits
        tilt_min, tilt_max: Tilt boundary limits
        lissajous_ratio: Frequency ratio for lissajous curves
        num_points: Number of points to generate

    Returns:
        List of (pan, tilt) tuples with clipping applied
    """
    points = []

    if effect_type == "static":
        # Single point at center
        pan = max(pan_min, min(pan_max, center_pan))
        tilt = max(tilt_min, min(tilt_max, center_tilt))
        return [(pan, tilt)]

    elif effect_type == "circle":
        for i in range(num_points):
            angle = 2 * math.pi * i / num_points
            pan = center_pan + pan_amplitude * math.cos(angle)
            tilt = center_tilt + tilt_amplitude * math.sin(angle)
            # Apply clipping
            pan = max(pan_min, min(pan_max, pan))
            tilt = max(tilt_min, min(tilt_max, tilt))
            points.append((pan, tilt))

    elif effect_type == "diamond":
        # Diamond is 4 points connected by lines
        corners = [
            (center_pan, center_tilt - tilt_amplitude),  # Top
            (center_pan + pan_amplitude, center_tilt),   # Right
            (center_pan, center_tilt + tilt_amplitude),  # Bottom
            (center_pan - pan_amplitude, center_tilt),   # Left
        ]
        points_per_side = num_points // 4
        for i in range(4):
            start = corners[i]
            end = corners[(i + 1) % 4]
            for j in range(points_per_side):
                t = j / points_per_side
                pan = start[0] + t * (end[0] - start[0])
                tilt = start[1] + t * (end[1] - start[1])
                pan = max(pan_min, min(pan_max, pan))
                tilt = max(tilt_min, min(tilt_max, tilt))
                points.append((pan, tilt))

    elif effect_type == "square":
        # Square shape
        corners = [
            (center_pan - pan_amplitude, center_tilt - tilt_amplitude),  # Top-left
            (center_pan + pan_amplitude, center_tilt - tilt_amplitude),  # Top-right
            (center_pan + pan_amplitude, center_tilt + tilt_amplitude),  # Bottom-right
            (center_pan - pan_amplitude, center_tilt + tilt_amplitude),  # Bottom-left
        ]
        points_per_side = num_points // 4
        for i in range(4):
            start = corners[i]
            end = corners[(i + 1) % 4]
            for j in range(points_per_side):
                t = j / points_per_side
                pan = start[0] + t * (end[0] - start[0])
                tilt = start[1] + t * (end[1] - start[1])
                pan = max(pan_min, min(pan_max, pan))
                tilt = max(tilt_min, min(tilt_max, tilt))
                points.append((pan, tilt))

    elif effect_type == "triangle":
        # Equilateral triangle
        corners = [
            (center_pan, center_tilt - tilt_amplitude),  # Top
            (center_pan + pan_amplitude * 0.866, center_tilt + tilt_amplitude * 0.5),  # Bottom-right
            (center_pan - pan_amplitude * 0.866, center_tilt + tilt_amplitude * 0.5),  # Bottom-left
        ]
        points_per_side = num_points // 3
        for i in range(3):
            start = corners[i]
            end = corners[(i + 1) % 3]
            for j in range(points_per_side):
                t = j / points_per_side
                pan = start[0] + t * (end[0] - start[0])
                tilt = start[1] + t * (end[1] - start[1])
                pan = max(pan_min, min(pan_max, pan))
                tilt = max(tilt_min, min(tilt_max, tilt))
                points.append((pan, tilt))

    elif effect_type == "figure_8":
        # Figure-8 is a lissajous with ratio 1:2
        for i in range(num_points):
            t = 2 * math.pi * i / num_points
            pan = center_pan + pan_amplitude * math.sin(t)
            tilt = center_tilt + tilt_amplitude * math.sin(2 * t)
            pan = max(pan_min, min(pan_max, pan))
            tilt = max(tilt_min, min(tilt_max, tilt))
            points.append((pan, tilt))

    elif effect_type == "lissajous":
        # Parse ratio
        try:
            parts = lissajous_ratio.split(":")
            freq_pan = int(parts[0])
            freq_tilt = int(parts[1])
        except (ValueError, IndexError):
            freq_pan, freq_tilt = 1, 2

        for i in range(num_points):
            t = 2 * math.pi * i / num_points
            pan = center_pan + pan_amplitude * math.sin(freq_pan * t)
            tilt = center_tilt + tilt_amplitude * math.sin(freq_tilt * t)
            pan = max(pan_min, min(pan_max, pan))
            tilt = max(tilt_min, min(tilt_max, tilt))
            points.append((pan, tilt))

    elif effect_type == "random":
        # Generate some random-looking but smooth points using sine waves with prime frequencies
        for i in range(num_points):
            t = 2 * math.pi * i / num_points
            # Use multiple prime frequencies for pseudo-random smooth motion
            pan = center_pan + pan_amplitude * (0.5 * math.sin(3 * t) + 0.3 * math.sin(7 * t) + 0.2 * math.sin(11 * t))
            tilt = center_tilt + tilt_amplitude * (0.5 * math.sin(5 * t) + 0.3 * math.sin(11 * t) + 0.2 * math.sin(13 * t))
            pan = max(pan_min, min(pan_max, pan))
            tilt = max(tilt_min, min(tilt_max, tilt))
            points.append((pan, tilt))

    elif effect_type == "bounce":
        # Bouncing pattern - diagonal bounces off walls
        # Simulate a bouncing motion within bounds
        for i in range(num_points):
            t = i / num_points * 4  # 4 full bounces
            # Sawtooth wave for bouncing effect
            pan_t = abs((t % 2) - 1)  # Triangle wave 0->1->0
            tilt_t = abs(((t + 0.5) % 2) - 1)  # Offset triangle wave
            pan = center_pan - pan_amplitude + 2 * pan_amplitude * pan_t
            tilt = center_tilt - tilt_amplitude + 2 * tilt_amplitude * tilt_t
            pan = max(pan_min, min(pan_max, pan))
            tilt = max(tilt_min, min(tilt_max, tilt))
            points.append((pan, tilt))

    return points


class PanTiltWidget(QFrame):
    """2D widget for pan/tilt position control with shape preview."""

    position_changed = pyqtSignal(float, float)  # pan, tilt (0-255)
    bounds_changed = pyqtSignal()  # Emitted when bounds are dragged

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(250, 250)
        self.setFrameShape(QFrame.Shape.Box)
        tokens = _active_tokens()
        self.setStyleSheet(
            f"background-color: {tokens['window']}; "
            f"border: 1px solid {tokens['border']};")

        self._pan = 127.5
        self._tilt = 127.5
        self._dragging = False

        # Effect parameters
        self._effect_type = "static"
        self._pan_amplitude = 50.0
        self._tilt_amplitude = 50.0
        self._pan_min = 0.0
        self._pan_max = 255.0
        self._tilt_min = 0.0
        self._tilt_max = 255.0
        self._lissajous_ratio = "1:2"

        # Cached shape points
        self._shape_points = []
        self._update_shape_points()

    def set_position(self, pan: float, tilt: float):
        """Set the pan/tilt position (0-255)."""
        self._pan = max(0, min(255, pan))
        self._tilt = max(0, min(255, tilt))
        self._update_shape_points()
        self.update()

    def set_effect_params(self, effect_type: str, pan_amplitude: float, tilt_amplitude: float,
                          pan_min: float, pan_max: float, tilt_min: float, tilt_max: float,
                          lissajous_ratio: str = "1:2"):
        """Set effect parameters for shape preview."""
        self._effect_type = effect_type
        self._pan_amplitude = pan_amplitude
        self._tilt_amplitude = tilt_amplitude
        self._pan_min = pan_min
        self._pan_max = pan_max
        self._tilt_min = tilt_min
        self._tilt_max = tilt_max
        self._lissajous_ratio = lissajous_ratio
        self._update_shape_points()
        self.update()

    def _update_shape_points(self):
        """Update cached shape points."""
        self._shape_points = generate_shape_points(
            self._effect_type, self._pan, self._tilt,
            self._pan_amplitude, self._tilt_amplitude,
            self._pan_min, self._pan_max, self._tilt_min, self._tilt_max,
            self._lissajous_ratio
        )

    def pan(self) -> float:
        return self._pan

    def tilt(self) -> float:
        return self._tilt

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        margin = 15

        def pan_to_x(pan):
            return margin + (pan / 255) * (w - 2 * margin)

        def tilt_to_y(tilt):
            return margin + (tilt / 255) * (h - 2 * margin)

        # Draw grid
        painter.setPen(QPen(QColor(50, 50, 70), 1))
        for i in range(5):
            x = margin + (w - 2 * margin) * i / 4
            painter.drawLine(int(x), margin, int(x), h - margin)
        for i in range(5):
            y = margin + (h - 2 * margin) * i / 4
            painter.drawLine(margin, int(y), w - margin, int(y))

        # Draw center crosshair
        painter.setPen(QPen(QColor(100, 100, 120), 1, Qt.PenStyle.DashLine))
        center_x = w / 2
        center_y = h / 2
        painter.drawLine(int(center_x), margin, int(center_x), h - margin)
        painter.drawLine(margin, int(center_y), w - margin, int(center_y))

        # Draw boundary box
        bound_left = pan_to_x(self._pan_min)
        bound_right = pan_to_x(self._pan_max)
        bound_top = tilt_to_y(self._tilt_min)
        bound_bottom = tilt_to_y(self._tilt_max)

        painter.setPen(QPen(QColor(255, 100, 100, 150), 2, Qt.PenStyle.DashLine))
        painter.setBrush(QBrush(QColor(255, 100, 100, 30)))
        painter.drawRect(int(bound_left), int(bound_top),
                         int(bound_right - bound_left), int(bound_bottom - bound_top))

        # Draw amplitude box (unclipped shape extent)
        if self._effect_type != "static":
            amp_left = pan_to_x(self._pan - self._pan_amplitude)
            amp_right = pan_to_x(self._pan + self._pan_amplitude)
            amp_top = tilt_to_y(self._tilt - self._tilt_amplitude)
            amp_bottom = tilt_to_y(self._tilt + self._tilt_amplitude)

            painter.setPen(QPen(QColor(100, 200, 100, 100), 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(int(amp_left), int(amp_top),
                             int(amp_right - amp_left), int(amp_bottom - amp_top))

        # Draw shape path
        if len(self._shape_points) > 1:
            path = QPainterPath()
            first_point = self._shape_points[0]
            path.moveTo(pan_to_x(first_point[0]), tilt_to_y(first_point[1]))

            for pan, tilt in self._shape_points[1:]:
                path.lineTo(pan_to_x(pan), tilt_to_y(tilt))

            # Close the path for shapes
            if self._effect_type != "static":
                path.lineTo(pan_to_x(first_point[0]), tilt_to_y(first_point[1]))

            # Draw the path with gradient effect
            painter.setPen(QPen(QColor(0, 200, 255), 2))
            painter.setBrush(QBrush(QColor(0, 200, 255, 40)))
            painter.drawPath(path)

        # Draw center position indicator
        pos_x = pan_to_x(self._pan)
        pos_y = tilt_to_y(self._tilt)

        # Outer circle
        painter.setPen(QPen(QColor(255, 165, 0), 2))
        painter.setBrush(QBrush(QColor(255, 165, 0, 100)))
        painter.drawEllipse(int(pos_x - 8), int(pos_y - 8), 16, 16)

        # Center dot
        painter.setBrush(QBrush(QColor(255, 200, 50)))
        painter.drawEllipse(int(pos_x - 3), int(pos_y - 3), 6, 6)

        # Labels
        painter.setPen(QColor(150, 150, 150))
        painter.drawText(margin, h - 2, "0")
        painter.drawText(w - margin - 20, h - 2, "255")
        painter.drawText(2, margin + 10, "0")
        painter.drawText(2, h - margin, "255")
        painter.drawText(int(center_x - 10), h - 2, "Pan")
        painter.drawText(2, int(center_y), "Tilt")

        # Draw effect type label
        painter.setPen(QColor(0, 200, 255))
        effect_label = self._effect_type.replace("_", " ").title()
        if self._effect_type == "lissajous":
            effect_label += f" ({self._lissajous_ratio})"
        painter.drawText(margin + 5, margin + 15, effect_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._update_position(event.position())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._update_position(event.position())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def _update_position(self, pos):
        """Update position from mouse coordinates."""
        w = self.width()
        h = self.height()
        margin = 15

        # Convert to 0-255 range
        pan = (pos.x() - margin) / (w - 2 * margin) * 255
        tilt = (pos.y() - margin) / (h - 2 * margin) * 255

        # Clamp to valid range
        pan = max(0, min(255, pan))
        tilt = max(0, min(255, tilt))

        self._pan = pan
        self._tilt = tilt
        self._update_shape_points()
        self.update()
        self.position_changed.emit(pan, tilt)


class MovementBlockDialog(QDialog):
    """Dialog for editing movement sublane block parameters."""

    def __init__(self, block: MovementBlock, parent=None, config=None):
        """Create the movement block dialog.

        Args:
            block: MovementBlock to edit
            parent: Parent widget
            config: Configuration object (needed for spot list)
        """
        super().__init__(parent)
        self.block = block
        self.config = config

        self.setWindowTitle("Edit Movement Block")
        self.setMinimumWidth(650)
        self.setMinimumHeight(700)

        self.setup_ui()
        self.load_current_values()
        self._connect_signals()
        self._update_ui_visibility()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)

        # Create scroll area for the content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)

        # Timing info (read-only display)
        timing_group = QGroupBox("Timing")
        timing_layout = QFormLayout()

        self.start_label = QLabel()
        self.end_label = QLabel()
        self.duration_label = QLabel()
        timing_layout.addRow("Start:", self.start_label)
        timing_layout.addRow("End:", self.end_label)
        timing_layout.addRow("Duration:", self.duration_label)

        timing_group.setLayout(timing_layout)
        layout.addWidget(timing_group)

        # Effect Type group
        effect_group = QGroupBox("Effect")
        effect_layout = QFormLayout()

        # Effect type selector
        self.effect_type_combo = QComboBox()
        self.effect_type_combo.addItems([
            "static", "circle", "diamond", "lissajous", "figure_8",
            "square", "triangle", "random", "bounce", "linear_sweep", "fan"
        ])
        effect_layout.addRow("Effect Type:", self.effect_type_combo)

        # Effect speed selector
        self.effect_speed_combo = QComboBox()
        self.effect_speed_combo.addItems(["1/16", "1/8", "1/4", "1/2", "1", "2", "4", "8", "16"])
        self.effect_speed_combo.setCurrentText("1")
        effect_layout.addRow("Speed:", self.effect_speed_combo)

        # Lissajous ratio selector (only visible when lissajous selected)
        self.lissajous_ratio_combo = QComboBox()
        self.lissajous_ratio_combo.addItems(["1:2", "2:3", "3:4", "3:2", "4:3", "1:3", "2:1", "3:1"])
        self.lissajous_ratio_label = QLabel("Lissajous Ratio:")
        effect_layout.addRow(self.lissajous_ratio_label, self.lissajous_ratio_combo)

        effect_group.setLayout(effect_layout)
        layout.addWidget(effect_group)

        # Target Spot group
        target_group = QGroupBox("Target Spot (Auto-Point)")
        target_layout = QFormLayout()

        self.target_spot_combo = QComboBox()
        self.target_spot_combo.addItem("(None - use manual position)", None)

        # Populate with spots from config
        if self.config and hasattr(self.config, 'spots'):
            for spot_name in sorted(self.config.spots.keys()):
                spot = self.config.spots[spot_name]
                # Show spot name with coordinates for clarity
                label = f"{spot_name} (x={spot.x:.1f}, y={spot.y:.1f}, z={spot.z:.1f})"
                self.target_spot_combo.addItem(label, spot_name)

        self.target_spot_combo.setToolTip(
            "Select a stage spot to automatically point at.\n"
            "Pan/tilt will be calculated based on fixture position and orientation.\n"
            "Leave as '(None)' to use manual pan/tilt values."
        )
        target_layout.addRow("Target Spot:", self.target_spot_combo)

        # Info label
        self.target_info_label = QLabel(
            "When a target spot is selected, pan/tilt values are calculated\n"
            "automatically for each fixture based on its position and orientation."
        )
        self.target_info_label.setProperty("role", "stat-caption")
        target_layout.addRow(self.target_info_label)

        target_group.setLayout(target_layout)
        layout.addWidget(target_group)

        # Position/Preview group with 2D widget
        position_group = QGroupBox("Position & Preview")
        position_layout = QHBoxLayout()

        # 2D control widget
        self.pan_tilt_widget = PanTiltWidget()
        position_layout.addWidget(self.pan_tilt_widget)

        # Numeric controls
        numeric_layout = QVBoxLayout()

        # Center position controls
        center_group = QGroupBox("Center Position")
        center_layout = QFormLayout()

        # Pan center
        pan_row = QHBoxLayout()
        self.pan_slider = QSlider(Qt.Orientation.Horizontal)
        self.pan_slider.setRange(0, 255)
        self.pan_spinbox = QDoubleSpinBox()
        self.pan_spinbox.setRange(0, 255)
        self.pan_spinbox.setDecimals(1)
        pan_row.addWidget(self.pan_slider, 1)
        pan_row.addWidget(self.pan_spinbox)
        center_layout.addRow("Pan:", pan_row)

        # Tilt center
        tilt_row = QHBoxLayout()
        self.tilt_slider = QSlider(Qt.Orientation.Horizontal)
        self.tilt_slider.setRange(0, 255)
        self.tilt_spinbox = QDoubleSpinBox()
        self.tilt_spinbox.setRange(0, 255)
        self.tilt_spinbox.setDecimals(1)
        tilt_row.addWidget(self.tilt_slider, 1)
        tilt_row.addWidget(self.tilt_spinbox)
        center_layout.addRow("Tilt:", tilt_row)

        # Center button
        center_btn = QPushButton("Center Position")
        center_btn.clicked.connect(self._center_position)
        center_layout.addRow(center_btn)

        center_group.setLayout(center_layout)
        numeric_layout.addWidget(center_group)

        # Fine adjustment controls
        fine_group = QGroupBox("Fine Adjustment")
        fine_layout = QFormLayout()

        self.pan_fine_spinbox = QDoubleSpinBox()
        self.pan_fine_spinbox.setRange(0, 255)
        self.pan_fine_spinbox.setDecimals(1)
        fine_layout.addRow("Pan Fine:", self.pan_fine_spinbox)

        self.tilt_fine_spinbox = QDoubleSpinBox()
        self.tilt_fine_spinbox.setRange(0, 255)
        self.tilt_fine_spinbox.setDecimals(1)
        fine_layout.addRow("Tilt Fine:", self.tilt_fine_spinbox)

        fine_group.setLayout(fine_layout)
        numeric_layout.addWidget(fine_group)

        position_layout.addLayout(numeric_layout)
        position_group.setLayout(position_layout)
        layout.addWidget(position_group)

        # Boundaries group (only for non-static effects)
        self.bounds_group = QGroupBox("Boundaries (Hard Limits)")
        bounds_layout = QFormLayout()

        # Pan bounds
        pan_bounds_row = QHBoxLayout()
        pan_bounds_row.addWidget(QLabel("Min:"))
        self.pan_min_spinbox = QDoubleSpinBox()
        self.pan_min_spinbox.setRange(0, 255)
        self.pan_min_spinbox.setDecimals(1)
        pan_bounds_row.addWidget(self.pan_min_spinbox)
        pan_bounds_row.addWidget(QLabel("Max:"))
        self.pan_max_spinbox = QDoubleSpinBox()
        self.pan_max_spinbox.setRange(0, 255)
        self.pan_max_spinbox.setDecimals(1)
        pan_bounds_row.addWidget(self.pan_max_spinbox)
        bounds_layout.addRow("Pan Bounds:", pan_bounds_row)

        # Tilt bounds
        tilt_bounds_row = QHBoxLayout()
        tilt_bounds_row.addWidget(QLabel("Min:"))
        self.tilt_min_spinbox = QDoubleSpinBox()
        self.tilt_min_spinbox.setRange(0, 255)
        self.tilt_min_spinbox.setDecimals(1)
        tilt_bounds_row.addWidget(self.tilt_min_spinbox)
        tilt_bounds_row.addWidget(QLabel("Max:"))
        self.tilt_max_spinbox = QDoubleSpinBox()
        self.tilt_max_spinbox.setRange(0, 255)
        self.tilt_max_spinbox.setDecimals(1)
        tilt_bounds_row.addWidget(self.tilt_max_spinbox)
        bounds_layout.addRow("Tilt Bounds:", tilt_bounds_row)

        # Reset bounds button
        reset_bounds_btn = QPushButton("Reset to Full Range")
        reset_bounds_btn.clicked.connect(self._reset_bounds)
        bounds_layout.addRow(reset_bounds_btn)

        self.bounds_group.setLayout(bounds_layout)
        layout.addWidget(self.bounds_group)

        # Amplitude group (only for non-static effects)
        self.amplitude_group = QGroupBox("Amplitude (Effect Size)")
        amplitude_layout = QFormLayout()

        # Pan amplitude
        pan_amp_row = QHBoxLayout()
        self.pan_amplitude_slider = QSlider(Qt.Orientation.Horizontal)
        self.pan_amplitude_slider.setRange(0, 1275)  # 0-127.5 * 10
        self.pan_amplitude_spinbox = QDoubleSpinBox()
        self.pan_amplitude_spinbox.setRange(0, 127.5)
        self.pan_amplitude_spinbox.setDecimals(1)
        pan_amp_row.addWidget(self.pan_amplitude_slider, 1)
        pan_amp_row.addWidget(self.pan_amplitude_spinbox)
        amplitude_layout.addRow("Pan Amplitude:", pan_amp_row)

        # Tilt amplitude
        tilt_amp_row = QHBoxLayout()
        self.tilt_amplitude_slider = QSlider(Qt.Orientation.Horizontal)
        self.tilt_amplitude_slider.setRange(0, 1275)  # 0-127.5 * 10
        self.tilt_amplitude_spinbox = QDoubleSpinBox()
        self.tilt_amplitude_spinbox.setRange(0, 127.5)
        self.tilt_amplitude_spinbox.setDecimals(1)
        tilt_amp_row.addWidget(self.tilt_amplitude_slider, 1)
        tilt_amp_row.addWidget(self.tilt_amplitude_spinbox)
        amplitude_layout.addRow("Tilt Amplitude:", tilt_amp_row)

        self.amplitude_group.setLayout(amplitude_layout)
        layout.addWidget(self.amplitude_group)

        # Phase offset group (only for non-static effects)
        self.phase_group = QGroupBox("Phase Offset")
        phase_layout = QFormLayout()

        self.phase_enabled_checkbox = QCheckBox("Enable phase offset between fixtures")
        phase_layout.addRow(self.phase_enabled_checkbox)

        phase_row = QHBoxLayout()
        self.phase_slider = QSlider(Qt.Orientation.Horizontal)
        self.phase_slider.setRange(0, 360)
        self.phase_spinbox = QDoubleSpinBox()
        self.phase_spinbox.setRange(0, 360)
        self.phase_spinbox.setDecimals(1)
        self.phase_spinbox.setSuffix("°")
        phase_row.addWidget(self.phase_slider, 1)
        phase_row.addWidget(self.phase_spinbox)
        self.phase_label = QLabel("Offset:")
        phase_layout.addRow(self.phase_label, phase_row)

        self.phase_group.setLayout(phase_layout)
        layout.addWidget(self.phase_group)

        # Speed and interpolation group
        options_group = QGroupBox("Movement Options")
        options_layout = QFormLayout()

        # Speed
        speed_row = QHBoxLayout()
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(0, 255)
        self.speed_spinbox = QSpinBox()
        self.speed_spinbox.setRange(0, 255)
        speed_row.addWidget(self.speed_slider, 1)
        speed_row.addWidget(self.speed_spinbox)
        options_layout.addRow("Speed (DMX):", speed_row)

        # Interpolation checkbox
        self.interpolate_checkbox = QCheckBox("Interpolate from previous position")
        self.interpolate_checkbox.setToolTip(
            "When enabled, the fixture will gradually move from its previous\n"
            "position to this block's position during any gap before this block."
        )
        options_layout.addRow(self.interpolate_checkbox)

        options_group.setLayout(options_layout)
        layout.addWidget(options_group)

        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)

        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setProperty("role", "primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

    def _connect_signals(self):
        """Connect all widget signals."""
        # Pan/tilt slider/spinbox sync
        self.pan_slider.valueChanged.connect(lambda v: self.pan_spinbox.setValue(v))
        self.pan_spinbox.valueChanged.connect(lambda v: self.pan_slider.setValue(int(v)))
        self.pan_slider.valueChanged.connect(self._on_position_changed)

        self.tilt_slider.valueChanged.connect(lambda v: self.tilt_spinbox.setValue(v))
        self.tilt_spinbox.valueChanged.connect(lambda v: self.tilt_slider.setValue(int(v)))
        self.tilt_slider.valueChanged.connect(self._on_position_changed)

        # Amplitude slider/spinbox sync
        self.pan_amplitude_slider.valueChanged.connect(lambda v: self.pan_amplitude_spinbox.setValue(v / 10.0))
        self.pan_amplitude_spinbox.valueChanged.connect(lambda v: self.pan_amplitude_slider.setValue(int(v * 10)))
        self.pan_amplitude_slider.valueChanged.connect(self._on_effect_params_changed)

        self.tilt_amplitude_slider.valueChanged.connect(lambda v: self.tilt_amplitude_spinbox.setValue(v / 10.0))
        self.tilt_amplitude_spinbox.valueChanged.connect(lambda v: self.tilt_amplitude_slider.setValue(int(v * 10)))
        self.tilt_amplitude_slider.valueChanged.connect(self._on_effect_params_changed)

        # Bounds spinbox changes
        self.pan_min_spinbox.valueChanged.connect(self._on_effect_params_changed)
        self.pan_max_spinbox.valueChanged.connect(self._on_effect_params_changed)
        self.tilt_min_spinbox.valueChanged.connect(self._on_effect_params_changed)
        self.tilt_max_spinbox.valueChanged.connect(self._on_effect_params_changed)

        # Phase slider/spinbox sync
        self.phase_slider.valueChanged.connect(lambda v: self.phase_spinbox.setValue(v))
        self.phase_spinbox.valueChanged.connect(lambda v: self.phase_slider.setValue(int(v)))
        self.phase_enabled_checkbox.toggled.connect(self._on_phase_enabled_changed)

        # Speed slider/spinbox sync
        self.speed_slider.valueChanged.connect(self.speed_spinbox.setValue)
        self.speed_spinbox.valueChanged.connect(self.speed_slider.setValue)

        # Effect type change
        self.effect_type_combo.currentTextChanged.connect(self._on_effect_type_changed)

        # Lissajous ratio change
        self.lissajous_ratio_combo.currentTextChanged.connect(self._on_effect_params_changed)

        # 2D widget position change
        self.pan_tilt_widget.position_changed.connect(self._on_position_widget_changed)

        # Target spot change
        self.target_spot_combo.currentIndexChanged.connect(self._on_target_spot_changed)

    def _on_target_spot_changed(self, index):
        """Handle target spot selection change."""
        spot_name = self.target_spot_combo.currentData()
        has_target = spot_name is not None

        # When a target spot is selected, manual pan/tilt becomes less relevant
        # but we still allow it as an offset or fallback
        # Update the info label
        if has_target:
            self.target_info_label.setText(
                f"Fixtures will automatically point at '{spot_name}'.\n"
                "Manual pan/tilt values serve as offsets for effects."
            )
        else:
            self.target_info_label.setText(
                "When a target spot is selected, pan/tilt values are calculated\n"
                "automatically for each fixture based on its position and orientation."
            )

    def _on_effect_type_changed(self, effect_type):
        """Handle effect type change."""
        self._update_ui_visibility()
        self._on_effect_params_changed()

    def _update_ui_visibility(self):
        """Show/hide UI elements based on effect type."""
        is_static = self.effect_type_combo.currentText() == "static"
        is_lissajous = self.effect_type_combo.currentText() == "lissajous"

        # Hide/show groups based on effect type
        self.bounds_group.setVisible(not is_static)
        self.amplitude_group.setVisible(not is_static)
        self.phase_group.setVisible(not is_static)

        # Show lissajous ratio only for lissajous
        self.lissajous_ratio_label.setVisible(is_lissajous)
        self.lissajous_ratio_combo.setVisible(is_lissajous)

    def _on_phase_enabled_changed(self, enabled):
        """Handle phase offset enable/disable."""
        self.phase_slider.setEnabled(enabled)
        self.phase_spinbox.setEnabled(enabled)

    def _on_position_widget_changed(self, pan, tilt):
        """Handle position change from 2D widget."""
        self.pan_slider.blockSignals(True)
        self.pan_spinbox.blockSignals(True)
        self.tilt_slider.blockSignals(True)
        self.tilt_spinbox.blockSignals(True)

        self.pan_slider.setValue(int(pan))
        self.pan_spinbox.setValue(pan)
        self.tilt_slider.setValue(int(tilt))
        self.tilt_spinbox.setValue(tilt)

        self.pan_slider.blockSignals(False)
        self.pan_spinbox.blockSignals(False)
        self.tilt_slider.blockSignals(False)
        self.tilt_spinbox.blockSignals(False)

    def _on_position_changed(self):
        """Handle position slider changes and update 2D widget."""
        self.pan_tilt_widget.set_position(
            self.pan_spinbox.value(),
            self.tilt_spinbox.value()
        )
        self._on_effect_params_changed()

    def _on_effect_params_changed(self):
        """Update shape preview when effect parameters change."""
        self.pan_tilt_widget.set_effect_params(
            effect_type=self.effect_type_combo.currentText(),
            pan_amplitude=self.pan_amplitude_spinbox.value(),
            tilt_amplitude=self.tilt_amplitude_spinbox.value(),
            pan_min=self.pan_min_spinbox.value(),
            pan_max=self.pan_max_spinbox.value(),
            tilt_min=self.tilt_min_spinbox.value(),
            tilt_max=self.tilt_max_spinbox.value(),
            lissajous_ratio=self.lissajous_ratio_combo.currentText()
        )

    def _center_position(self):
        """Reset to center position."""
        self.pan_slider.setValue(127)
        self.pan_spinbox.setValue(127.5)
        self.tilt_slider.setValue(127)
        self.tilt_spinbox.setValue(127.5)
        self.pan_tilt_widget.set_position(127.5, 127.5)

    def _reset_bounds(self):
        """Reset bounds to full range."""
        self.pan_min_spinbox.setValue(0)
        self.pan_max_spinbox.setValue(255)
        self.tilt_min_spinbox.setValue(0)
        self.tilt_max_spinbox.setValue(255)

    def load_current_values(self):
        """Load current block values into the dialog."""
        # Timing
        self.start_label.setText(f"{self.block.start_time:.2f}s")
        self.end_label.setText(f"{self.block.end_time:.2f}s")
        duration = self.block.end_time - self.block.start_time
        self.duration_label.setText(f"{duration:.2f}s")

        # Effect type and speed
        self.effect_type_combo.setCurrentText(self.block.effect_type)
        self.effect_speed_combo.setCurrentText(self.block.effect_speed)
        self.lissajous_ratio_combo.setCurrentText(self.block.lissajous_ratio)

        # Position
        self.pan_slider.setValue(int(self.block.pan))
        self.pan_spinbox.setValue(self.block.pan)
        self.pan_fine_spinbox.setValue(self.block.pan_fine)
        self.tilt_slider.setValue(int(self.block.tilt))
        self.tilt_spinbox.setValue(self.block.tilt)
        self.tilt_fine_spinbox.setValue(self.block.tilt_fine)
        self.pan_tilt_widget.set_position(self.block.pan, self.block.tilt)

        # Bounds
        self.pan_min_spinbox.setValue(self.block.pan_min)
        self.pan_max_spinbox.setValue(self.block.pan_max)
        self.tilt_min_spinbox.setValue(self.block.tilt_min)
        self.tilt_max_spinbox.setValue(self.block.tilt_max)

        # Amplitude
        self.pan_amplitude_slider.setValue(int(self.block.pan_amplitude * 10))
        self.pan_amplitude_spinbox.setValue(self.block.pan_amplitude)
        self.tilt_amplitude_slider.setValue(int(self.block.tilt_amplitude * 10))
        self.tilt_amplitude_spinbox.setValue(self.block.tilt_amplitude)

        # Phase offset
        self.phase_enabled_checkbox.setChecked(self.block.phase_offset_enabled)
        self.phase_slider.setValue(int(self.block.phase_offset_degrees))
        self.phase_spinbox.setValue(self.block.phase_offset_degrees)
        self._on_phase_enabled_changed(self.block.phase_offset_enabled)

        # Speed
        self.speed_slider.setValue(int(self.block.speed))

        # Interpolation
        self.interpolate_checkbox.setChecked(self.block.interpolate_from_previous)

        # Target spot selection
        target_spot = self.block.target_spot_name
        if target_spot:
            # Find the index for this spot
            for i in range(self.target_spot_combo.count()):
                if self.target_spot_combo.itemData(i) == target_spot:
                    self.target_spot_combo.setCurrentIndex(i)
                    break
        else:
            self.target_spot_combo.setCurrentIndex(0)  # "(None)"

        # Update preview
        self._on_effect_params_changed()
        self._on_target_spot_changed(self.target_spot_combo.currentIndex())

    def accept(self):
        """Save parameters to block and close."""
        # Effect parameters
        self.block.effect_type = self.effect_type_combo.currentText()
        self.block.effect_speed = self.effect_speed_combo.currentText()
        self.block.lissajous_ratio = self.lissajous_ratio_combo.currentText()

        # Position
        self.block.pan = self.pan_spinbox.value()
        self.block.tilt = self.tilt_spinbox.value()
        self.block.pan_fine = self.pan_fine_spinbox.value()
        self.block.tilt_fine = self.tilt_fine_spinbox.value()

        # Bounds
        self.block.pan_min = self.pan_min_spinbox.value()
        self.block.pan_max = self.pan_max_spinbox.value()
        self.block.tilt_min = self.tilt_min_spinbox.value()
        self.block.tilt_max = self.tilt_max_spinbox.value()

        # Amplitude
        self.block.pan_amplitude = self.pan_amplitude_spinbox.value()
        self.block.tilt_amplitude = self.tilt_amplitude_spinbox.value()

        # Phase offset
        self.block.phase_offset_enabled = self.phase_enabled_checkbox.isChecked()
        self.block.phase_offset_degrees = self.phase_spinbox.value()

        # Speed
        self.block.speed = float(self.speed_spinbox.value())

        # Interpolation
        self.block.interpolate_from_previous = self.interpolate_checkbox.isChecked()

        # Target spot
        self.block.target_spot_name = self.target_spot_combo.currentData()

        super().accept()
