# timeline_ui/special_block_dialog.py
# Dialog for editing special sublane block parameters (gobo, beam, prism)

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QGroupBox, QSlider, QDoubleSpinBox, QSpinBox,
                             QLabel, QDialogButtonBox, QCheckBox, QComboBox,
                             QScrollArea, QWidget, QFrame)
from PyQt6.QtCore import Qt
from config.models import SpecialBlock


class SpecialBlockDialog(QDialog):
    """Dialog for editing special sublane block parameters."""

    def __init__(self, block: SpecialBlock, parent=None):
        """Create the special block dialog.

        Args:
            block: SpecialBlock to edit
            parent: Parent widget
        """
        super().__init__(parent)
        self.block = block

        self.setWindowTitle("Edit Special Block")
        self.setMinimumWidth(500)
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

        # Gobo group
        gobo_group = QGroupBox("Gobo")
        gobo_layout = QFormLayout()

        # Gobo selection
        self.gobo_combo = QComboBox()
        self.gobo_combo.addItem("Open (No Gobo)", 0)
        for i in range(1, 10):
            self.gobo_combo.addItem(f"Gobo {i}", i)
        gobo_layout.addRow("Gobo:", self.gobo_combo)

        # Gobo rotation
        rotation_row = QHBoxLayout()
        self.gobo_rotation_slider = QSlider(Qt.Orientation.Horizontal)
        self.gobo_rotation_slider.setRange(-255, 255)  # Negative = CCW, Positive = CW
        self.gobo_rotation_spinbox = QDoubleSpinBox()
        self.gobo_rotation_spinbox.setRange(-255, 255)
        self.gobo_rotation_spinbox.setDecimals(1)
        self.gobo_rotation_slider.valueChanged.connect(
            lambda v: self.gobo_rotation_spinbox.setValue(v)
        )
        self.gobo_rotation_spinbox.valueChanged.connect(
            lambda v: self.gobo_rotation_slider.setValue(int(v))
        )
        rotation_row.addWidget(self.gobo_rotation_slider, 1)
        rotation_row.addWidget(self.gobo_rotation_spinbox)
        gobo_layout.addRow("Rotation:", rotation_row)

        # Rotation direction label
        self.rotation_label = QLabel("Stopped")
        self.gobo_rotation_slider.valueChanged.connect(self._update_rotation_label)
        gobo_layout.addRow("", self.rotation_label)

        gobo_group.setLayout(gobo_layout)
        layout.addWidget(gobo_group)

        # Beam group
        beam_group = QGroupBox("Beam")
        beam_layout = QFormLayout()

        # Focus
        focus_row = QHBoxLayout()
        self.focus_slider = QSlider(Qt.Orientation.Horizontal)
        self.focus_slider.setRange(0, 255)
        self.focus_spinbox = QSpinBox()
        self.focus_spinbox.setRange(0, 255)
        self.focus_slider.valueChanged.connect(self.focus_spinbox.setValue)
        self.focus_spinbox.valueChanged.connect(self.focus_slider.setValue)
        focus_row.addWidget(self.focus_slider, 1)
        focus_row.addWidget(self.focus_spinbox)
        beam_layout.addRow("Focus:", focus_row)

        # Focus labels
        focus_labels = QHBoxLayout()
        focus_labels.addWidget(QLabel("Near"))
        focus_labels.addStretch()
        focus_labels.addWidget(QLabel("Far"))
        beam_layout.addRow("", focus_labels)

        # Zoom
        zoom_row = QHBoxLayout()
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(0, 255)
        self.zoom_spinbox = QSpinBox()
        self.zoom_spinbox.setRange(0, 255)
        self.zoom_slider.valueChanged.connect(self.zoom_spinbox.setValue)
        self.zoom_spinbox.valueChanged.connect(self.zoom_slider.setValue)
        zoom_row.addWidget(self.zoom_slider, 1)
        zoom_row.addWidget(self.zoom_spinbox)
        beam_layout.addRow("Zoom:", zoom_row)

        # Zoom labels
        zoom_labels = QHBoxLayout()
        zoom_labels.addWidget(QLabel("Narrow"))
        zoom_labels.addStretch()
        zoom_labels.addWidget(QLabel("Wide"))
        beam_layout.addRow("", zoom_labels)

        beam_group.setLayout(beam_layout)
        layout.addWidget(beam_group)

        # Prism group
        prism_group = QGroupBox("Prism")
        prism_layout = QFormLayout()

        # Prism enabled
        self.prism_enabled = QCheckBox("Enable Prism")
        self.prism_enabled.toggled.connect(self._on_prism_toggled)
        prism_layout.addRow(self.prism_enabled)

        # Prism rotation
        prism_rotation_row = QHBoxLayout()
        self.prism_rotation_slider = QSlider(Qt.Orientation.Horizontal)
        self.prism_rotation_slider.setRange(-255, 255)
        self.prism_rotation_spinbox = QDoubleSpinBox()
        self.prism_rotation_spinbox.setRange(-255, 255)
        self.prism_rotation_spinbox.setDecimals(1)
        self.prism_rotation_slider.valueChanged.connect(
            lambda v: self.prism_rotation_spinbox.setValue(v)
        )
        self.prism_rotation_spinbox.valueChanged.connect(
            lambda v: self.prism_rotation_slider.setValue(int(v))
        )
        prism_rotation_row.addWidget(self.prism_rotation_slider, 1)
        prism_rotation_row.addWidget(self.prism_rotation_spinbox)
        prism_layout.addRow("Rotation:", prism_rotation_row)

        # Prism rotation direction label
        self.prism_rotation_label = QLabel("Stopped")
        self.prism_rotation_slider.valueChanged.connect(self._update_prism_rotation_label)
        prism_layout.addRow("", self.prism_rotation_label)

        prism_group.setLayout(prism_layout)
        layout.addWidget(prism_group)

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

    def _update_rotation_label(self, value):
        """Update the gobo rotation direction label."""
        if value < -10:
            self.rotation_label.setText(f"Counter-clockwise ({abs(value)})")
        elif value > 10:
            self.rotation_label.setText(f"Clockwise ({value})")
        else:
            self.rotation_label.setText("Stopped")

    def _update_prism_rotation_label(self, value):
        """Update the prism rotation direction label."""
        if value < -10:
            self.prism_rotation_label.setText(f"Counter-clockwise ({abs(value)})")
        elif value > 10:
            self.prism_rotation_label.setText(f"Clockwise ({value})")
        else:
            self.prism_rotation_label.setText("Stopped")

    def _on_prism_toggled(self, enabled):
        """Handle prism enable/disable."""
        self.prism_rotation_slider.setEnabled(enabled)
        self.prism_rotation_spinbox.setEnabled(enabled)
        if not enabled:
            self.prism_rotation_slider.setValue(0)

    def load_current_values(self):
        """Load current block values into the dialog."""
        # Timing
        self.start_label.setText(f"{self.block.start_time:.2f}s")
        self.end_label.setText(f"{self.block.end_time:.2f}s")
        duration = self.block.end_time - self.block.start_time
        self.duration_label.setText(f"{duration:.2f}s")

        # Gobo
        gobo_idx = self.gobo_combo.findData(self.block.gobo_index)
        if gobo_idx >= 0:
            self.gobo_combo.setCurrentIndex(gobo_idx)
        self.gobo_rotation_slider.setValue(int(self.block.gobo_rotation))

        # Beam
        self.focus_slider.setValue(int(self.block.focus))
        self.zoom_slider.setValue(int(self.block.zoom))

        # Prism
        self.prism_enabled.setChecked(self.block.prism_enabled)
        self.prism_rotation_slider.setValue(int(self.block.prism_rotation))
        self._on_prism_toggled(self.block.prism_enabled)

    def accept(self):
        """Save parameters to block and close."""
        # Gobo
        self.block.gobo_index = self.gobo_combo.currentData()
        self.block.gobo_rotation = self.gobo_rotation_spinbox.value()

        # Beam
        self.block.focus = float(self.focus_spinbox.value())
        self.block.zoom = float(self.zoom_spinbox.value())

        # Prism
        self.block.prism_enabled = self.prism_enabled.isChecked()
        self.block.prism_rotation = self.prism_rotation_spinbox.value()

        super().accept()
