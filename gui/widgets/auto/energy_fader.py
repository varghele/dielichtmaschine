"""
Energy sensitivity fader for Auto mode.
Controls how strongly the lighting algorithm reacts to audio features.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSlider, QLabel
from PyQt6.QtCore import Qt, pyqtSignal


class EnergySensitivityFader(QWidget):
    """Vertical slider controlling energy sensitivity (0-100%)."""

    sensitivity_changed = pyqtSignal(float)  # 0.0-1.0

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        title = QLabel("Energy")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-weight: bold; font-size: 11px;")
        layout.addWidget(title)

        self._slider = QSlider(Qt.Orientation.Vertical)
        self._slider.setRange(0, 100)
        self._slider.setValue(70)  # Default 70%
        self._slider.setFixedWidth(30)
        self._slider.valueChanged.connect(self._on_changed)
        layout.addWidget(self._slider, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._value_label = QLabel("70%")
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value_label.setStyleSheet("font-size: 10px;")
        layout.addWidget(self._value_label)

    def _on_changed(self, value: int):
        self._value_label.setText(f"{value}%")
        self.sensitivity_changed.emit(value / 100.0)

    def value(self) -> float:
        return self._slider.value() / 100.0

    def set_value(self, value: float) -> None:
        """Set the slider position (0.0-1.0) without emitting signals."""
        clamped = max(0, min(100, int(round(value * 100))))
        self._slider.blockSignals(True)
        self._slider.setValue(clamped)
        self._slider.blockSignals(False)
        self._value_label.setText(f"{clamped}%")
