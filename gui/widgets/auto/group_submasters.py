"""
Group submaster faders for Auto mode.
One horizontal slider per physical fixture group, controlling intensity multiplier.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSlider, QLabel,
    QScrollArea, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from typing import List


class GroupSubmasterPanel(QWidget):
    """Panel of intensity submaster sliders, one per fixture group.

    Rows live inside a ``QScrollArea`` so a config with many groups
    doesn't push the rest of the Auto tab's right column (Audio Input,
    Movement Target, START/STOP) off-screen — which in the vertical
    splitter also squeezed the embedded 3D visualizer down to nothing.
    """

    submaster_changed = pyqtSignal(str, float)  # group_name, value (0.0-1.0)

    def __init__(self, group_names: List[str], parent=None):
        super().__init__(parent)
        self._sliders = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        title = QLabel("Group Submasters")
        title.setStyleSheet("font-weight: bold; font-size: 11px;")
        layout.addWidget(title)

        # Scroll area for group rows — mirrors the GroupRiffConstraintPanel
        # treatment so the panel has a stable upper bound on the vertical
        # space it claims regardless of group count.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Cap how much vertical real estate the panel takes by default;
        # ~5 rows fit before the scrollbar kicks in. Without this cap a
        # tall row count still claims its full sizeHint and squeezes the
        # visualizer pane above.
        scroll.setMaximumHeight(150)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(2)

        for name in group_names:
            row = QHBoxLayout()
            row.setSpacing(4)

            label = QLabel(name)
            label.setFixedWidth(80)
            label.setStyleSheet("font-size: 10px;")

            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(100)
            slider.setFixedHeight(20)

            value_label = QLabel("100%")
            value_label.setFixedWidth(35)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value_label.setStyleSheet("font-size: 10px;")

            slider.valueChanged.connect(
                lambda v, n=name, vl=value_label: self._on_value_changed(n, v, vl)
            )

            row.addWidget(label)
            row.addWidget(slider)
            row.addWidget(value_label)
            scroll_layout.addLayout(row)

            self._sliders[name] = slider

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

    def _on_value_changed(self, group_name: str, value: int, value_label: QLabel):
        value_label.setText(f"{value}%")
        self.submaster_changed.emit(group_name, value / 100.0)

    def set_value(self, group_name: str, value: float):
        """Set a submaster value programmatically (0.0-1.0)."""
        slider = self._sliders.get(group_name)
        if slider:
            slider.blockSignals(True)
            slider.setValue(int(value * 100))
            slider.blockSignals(False)

    def get_values(self) -> dict:
        """Return current submaster values as {group_name: 0-100 int}."""
        return {name: slider.value() for name, slider in self._sliders.items()}
