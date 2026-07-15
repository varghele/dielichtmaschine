# timeline_ui/dimmer_block_dialog.py
# Dialog for editing dimmer sublane block parameters

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QGroupBox, QSlider, QDoubleSpinBox, QSpinBox,
                             QLabel, QDialogButtonBox, QCheckBox, QComboBox,
                             QScrollArea, QWidget, QFrame)
from PyQt6.QtCore import Qt
from config.models import DimmerBlock


class DimmerBlockDialog(QDialog):
    """Dialog for editing dimmer sublane block parameters."""

    def __init__(self, block: DimmerBlock, parent=None):
        """Create the dimmer block dialog.

        Args:
            block: DimmerBlock to edit
            parent: Parent widget
        """
        super().__init__(parent)
        self.block = block

        self.setWindowTitle("Edit Dimmer Block")
        self.setMinimumWidth(450)
        self.setMinimumHeight(550)

        self.setup_ui()
        self.load_current_values()

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

        # Effect group
        effect_group = QGroupBox("Effect")
        effect_layout = QFormLayout()

        # Effect type selector
        self.effect_type_combo = QComboBox()
        self.effect_type_combo.addItems(["static", "stroke", "throb", "ping_pong", "chase", "wave", "waterfall", "fill", "random_stroke", "sparkle", "pulse", "strobe", "fade", "cascade", "heartbeat"])
        effect_layout.addRow("Effect Type:", self.effect_type_combo)

        # Effect speed selector
        self.effect_speed_combo = QComboBox()
        self.effect_speed_combo.addItems(["1/16", "1/8", "1/4", "1/2", "1", "2", "4", "8", "16"])
        self.effect_speed_combo.setCurrentText("1")
        effect_layout.addRow("Speed:", self.effect_speed_combo)

        # Direction selector (waterfall, fade)
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["down", "up", "in", "out"])
        self.direction_label = QLabel("Direction:")
        effect_layout.addRow(self.direction_label, self.direction_combo)

        # Chase scope selector (chase)
        self.chase_scope_combo = QComboBox()
        self.chase_scope_combo.addItems(["fixture", "global"])
        self.chase_scope_label = QLabel("Scope:")
        self.chase_scope_combo.setToolTip(
            "fixture: each fixture animates independently\n"
            "global: all fixtures treated as one continuous chain"
        )
        effect_layout.addRow(self.chase_scope_label, self.chase_scope_combo)

        # Phase offset per fixture (pulse)
        self.phase_offset_check = QCheckBox("Spread phase across fixtures")
        self.phase_offset_check.setToolTip(
            "When enabled, each fixture gets a phase offset\n"
            "creating a wave-like breathing effect across the group"
        )
        self.phase_offset_label = QLabel("Phase Offset:")
        effect_layout.addRow(self.phase_offset_label, self.phase_offset_check)

        # Build fraction (cascade)
        self.build_fraction_spin = QDoubleSpinBox()
        self.build_fraction_spin.setRange(0.1, 0.95)
        self.build_fraction_spin.setSingleStep(0.05)
        self.build_fraction_spin.setValue(0.7)
        self.build_fraction_spin.setToolTip("Portion of block spent building (rest is release)")
        self.build_fraction_label = QLabel("Build Fraction:")
        effect_layout.addRow(self.build_fraction_label, self.build_fraction_spin)

        # Connect effect type change to show/hide rudiment-specific controls
        self.effect_type_combo.currentTextChanged.connect(self._on_effect_type_changed)

        effect_group.setLayout(effect_layout)
        layout.addWidget(effect_group)

        # Intensity group
        intensity_group = QGroupBox("Intensity")
        intensity_layout = QFormLayout()

        # Intensity slider
        intensity_widget = QHBoxLayout()
        self.intensity_slider = QSlider(Qt.Orientation.Horizontal)
        self.intensity_slider.setRange(0, 255)
        self.intensity_spinbox = QSpinBox()
        self.intensity_spinbox.setRange(0, 255)
        self.intensity_slider.valueChanged.connect(self.intensity_spinbox.setValue)
        self.intensity_spinbox.valueChanged.connect(self.intensity_slider.setValue)
        intensity_widget.addWidget(self.intensity_slider, 1)
        intensity_widget.addWidget(self.intensity_spinbox)
        intensity_layout.addRow("Intensity:", intensity_widget)

        # Percentage label
        self.intensity_percent_label = QLabel("100%")
        self.intensity_slider.valueChanged.connect(
            lambda v: self.intensity_percent_label.setText(f"{int(v/255*100)}%")
        )
        intensity_layout.addRow("", self.intensity_percent_label)

        intensity_group.setLayout(intensity_layout)
        layout.addWidget(intensity_group)

        # Strobe group
        strobe_group = QGroupBox("Strobe")
        strobe_layout = QFormLayout()

        # Strobe enable checkbox
        self.strobe_enabled = QCheckBox("Enable Strobe")
        self.strobe_enabled.toggled.connect(self._on_strobe_toggled)
        strobe_layout.addRow(self.strobe_enabled)

        # Strobe speed
        strobe_widget = QHBoxLayout()
        self.strobe_slider = QSlider(Qt.Orientation.Horizontal)
        self.strobe_slider.setRange(0, 200)  # 0-20 Hz in 0.1 increments
        self.strobe_spinbox = QDoubleSpinBox()
        self.strobe_spinbox.setRange(0.0, 20.0)
        self.strobe_spinbox.setSingleStep(0.5)
        self.strobe_spinbox.setSuffix(" Hz")
        self.strobe_slider.valueChanged.connect(
            lambda v: self.strobe_spinbox.setValue(v / 10.0)
        )
        self.strobe_spinbox.valueChanged.connect(
            lambda v: self.strobe_slider.setValue(int(v * 10))
        )
        strobe_widget.addWidget(self.strobe_slider, 1)
        strobe_widget.addWidget(self.strobe_spinbox)
        strobe_layout.addRow("Speed:", strobe_widget)

        strobe_group.setLayout(strobe_layout)
        layout.addWidget(strobe_group)

        # Iris group (for fixtures with iris)
        iris_group = QGroupBox("Iris")
        iris_layout = QFormLayout()

        iris_widget = QHBoxLayout()
        self.iris_slider = QSlider(Qt.Orientation.Horizontal)
        self.iris_slider.setRange(0, 255)
        self.iris_spinbox = QSpinBox()
        self.iris_spinbox.setRange(0, 255)
        self.iris_slider.valueChanged.connect(self.iris_spinbox.setValue)
        self.iris_spinbox.valueChanged.connect(self.iris_slider.setValue)
        iris_widget.addWidget(self.iris_slider, 1)
        iris_widget.addWidget(self.iris_spinbox)
        iris_layout.addRow("Opening:", iris_widget)

        # Percentage label
        self.iris_percent_label = QLabel("100%")
        self.iris_slider.valueChanged.connect(
            lambda v: self.iris_percent_label.setText(f"{int(v/255*100)}%")
        )
        iris_layout.addRow("", self.iris_percent_label)

        iris_group.setLayout(iris_layout)
        layout.addWidget(iris_group)

        # Add stretch to push content to top
        layout.addStretch()

        # Set up scroll area
        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)

        # Dialog buttons (outside scroll area)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setProperty("role", "primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

    def _on_effect_type_changed(self, effect_type):
        """Show/hide rudiment-specific controls based on selected effect type."""
        # Direction: visible for waterfall and fade
        show_direction = effect_type in ("waterfall", "fade")
        self.direction_label.setVisible(show_direction)
        self.direction_combo.setVisible(show_direction)
        if show_direction:
            if effect_type == "waterfall":
                # Show only down/up for waterfall
                self.direction_combo.clear()
                self.direction_combo.addItems(["down", "up"])
            elif effect_type == "fade":
                # Show only in/out for fade
                self.direction_combo.clear()
                self.direction_combo.addItems(["in", "out"])

        # Chase scope: visible for chase
        show_scope = effect_type == "chase"
        self.chase_scope_label.setVisible(show_scope)
        self.chase_scope_combo.setVisible(show_scope)

        # Phase offset: visible for pulse
        show_phase = effect_type == "pulse"
        self.phase_offset_label.setVisible(show_phase)
        self.phase_offset_check.setVisible(show_phase)

        # Build fraction: visible for cascade
        show_build = effect_type == "cascade"
        self.build_fraction_label.setVisible(show_build)
        self.build_fraction_spin.setVisible(show_build)

    def _on_strobe_toggled(self, enabled):
        """Handle strobe enable/disable."""
        self.strobe_slider.setEnabled(enabled)
        self.strobe_spinbox.setEnabled(enabled)
        if not enabled:
            self.strobe_slider.setValue(0)

    def load_current_values(self):
        """Load current block values into the dialog."""
        # Timing
        self.start_label.setText(f"{self.block.start_time:.2f}s")
        self.end_label.setText(f"{self.block.end_time:.2f}s")
        duration = self.block.end_time - self.block.start_time
        self.duration_label.setText(f"{duration:.2f}s")

        # Effect
        self.effect_type_combo.setCurrentText(self.block.effect_type)
        self.effect_speed_combo.setCurrentText(self.block.effect_speed)

        # Rudiment-specific parameters
        direction = getattr(self.block, 'direction', 'down')
        self.direction_combo.setCurrentText(direction)
        chase_scope = getattr(self.block, 'chase_scope', 'fixture')
        self.chase_scope_combo.setCurrentText(chase_scope)
        phase_offset = getattr(self.block, 'phase_offset_per_fixture', False)
        self.phase_offset_check.setChecked(phase_offset)
        build_fraction = getattr(self.block, 'build_fraction', 0.7)
        self.build_fraction_spin.setValue(build_fraction)

        # Trigger visibility update
        self._on_effect_type_changed(self.block.effect_type)

        # Intensity
        self.intensity_slider.setValue(int(self.block.intensity))

        # Strobe
        if self.block.strobe_speed > 0:
            self.strobe_enabled.setChecked(True)
            self.strobe_spinbox.setValue(self.block.strobe_speed)
        else:
            self.strobe_enabled.setChecked(False)
            self._on_strobe_toggled(False)

        # Iris
        self.iris_slider.setValue(int(self.block.iris))

    def accept(self):
        """Save parameters to block and close."""
        # Effect parameters
        self.block.effect_type = self.effect_type_combo.currentText()
        self.block.effect_speed = self.effect_speed_combo.currentText()

        # Rudiment-specific parameters
        self.block.direction = self.direction_combo.currentText()
        self.block.chase_scope = self.chase_scope_combo.currentText()
        self.block.phase_offset_per_fixture = self.phase_offset_check.isChecked()
        self.block.build_fraction = self.build_fraction_spin.value()

        # Intensity
        self.block.intensity = float(self.intensity_spinbox.value())

        # Strobe
        if self.strobe_enabled.isChecked():
            self.block.strobe_speed = self.strobe_spinbox.value()
        else:
            self.block.strobe_speed = 0.0

        # Iris
        self.block.iris = float(self.iris_spinbox.value())

        super().accept()
