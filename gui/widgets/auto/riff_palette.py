"""
Per-group riff constraint panel for Auto mode.

Each fixture group gets a row showing the currently active riff and a
multi-select popup to constrain which riffs the engine may choose from.
Three control levels: AUTO (unconstrained), CURATED (subset), LOCKED (one).
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QMenu, QWidgetAction, QCheckBox, QScrollArea, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal
from typing import Dict, List, Optional, Set

from rudiments.registry import get_intensity_rudiments


class _RiffChecklistMenu(QMenu):
    """Popup menu with checkable rudiment entries."""

    selection_changed = pyqtSignal()

    def __init__(self, rudiment_names: List[str], parent=None):
        super().__init__(parent)
        self._checkboxes: Dict[str, QCheckBox] = {}

        for name in rudiment_names:
            cb = QCheckBox(name)
            cb.setStyleSheet("padding: 2px 8px; font-size: 10px;")
            cb.toggled.connect(lambda _: self.selection_changed.emit())
            action = QWidgetAction(self)
            action.setDefaultWidget(cb)
            self.addAction(action)
            self._checkboxes[name] = cb

        self.addSeparator()

        select_all = self.addAction("Select All")
        select_all.triggered.connect(self._select_all)
        clear_all = self.addAction("Clear All")
        clear_all.triggered.connect(self._clear_all)

    def get_selected(self) -> Set[str]:
        return {name for name, cb in self._checkboxes.items() if cb.isChecked()}

    def _select_all(self):
        for cb in self._checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(True)
            cb.blockSignals(False)
        self.selection_changed.emit()

    def _clear_all(self):
        for cb in self._checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        self.selection_changed.emit()


class GroupRiffConstraintPanel(QWidget):
    """Per-group riff constraint panel with active riff display."""

    constraints_changed = pyqtSignal(str, object)  # group_name, Set[str] or None

    def __init__(self, group_names: List[str], parent=None):
        super().__init__(parent)
        self._group_names = group_names
        self._rudiment_names = sorted(get_intensity_rudiments().keys())

        self._active_labels: Dict[str, QLabel] = {}
        self._select_buttons: Dict[str, QPushButton] = {}
        self._mode_labels: Dict[str, QLabel] = {}
        self._menus: Dict[str, _RiffChecklistMenu] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        title = QLabel("Riff Constraints")
        title.setStyleSheet("font-weight: bold; font-size: 11px;")
        layout.addWidget(title)

        # Scroll area for group rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(2)

        for group_name in group_names:
            row = self._build_group_row(group_name)
            scroll_layout.addLayout(row)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

    def _build_group_row(self, group_name: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(4)

        # Group name
        name_label = QLabel(group_name)
        name_label.setFixedWidth(80)
        name_label.setStyleSheet("font-size: 10px;")
        row.addWidget(name_label)

        # Active riff readout (engine-owned, read-only). Shows the
        # currently-playing rudiment for this group, prefixed with ▶ so
        # the cell is recognisable even when the engine hasn't pushed a
        # name yet ("▶ —" reads as "this slot will fill with the live
        # riff"). Background comes from the theme — earlier versions
        # hardcoded a dark navy block that looked like a black blob
        # against either theme.
        active_label = QLabel("▶ —")
        active_label.setFixedWidth(90)
        active_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        active_label.setToolTip("Currently active riff (engine-driven)")
        active_label.setStyleSheet("font-size: 10px; font-weight: bold;")
        self._active_labels[group_name] = active_label
        row.addWidget(active_label)

        # Select button (opens checklist popup)
        select_btn = QPushButton("All")
        select_btn.setFixedWidth(80)
        select_btn.setFixedHeight(24)
        select_btn.setStyleSheet("font-size: 10px;")
        select_btn.clicked.connect(lambda _, g=group_name: self._open_menu(g))
        self._select_buttons[group_name] = select_btn
        row.addWidget(select_btn)

        # Mode badge
        mode_label = QLabel("AUTO")
        mode_label.setFixedWidth(70)
        mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mode_label.setStyleSheet(
            "font-size: 9px; font-weight: bold; color: #4CAF50; "
            "border: 1px solid #4CAF50; border-radius: 3px; padding: 1px;"
        )
        self._mode_labels[group_name] = mode_label
        row.addWidget(mode_label)

        # Create the popup menu for this group
        menu = _RiffChecklistMenu(self._rudiment_names, self)
        menu.selection_changed.connect(lambda g=group_name: self._on_selection_changed(g))
        self._menus[group_name] = menu

        return row

    def _open_menu(self, group_name: str):
        btn = self._select_buttons[group_name]
        menu = self._menus[group_name]
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _on_selection_changed(self, group_name: str):
        menu = self._menus[group_name]
        selected = menu.get_selected()
        count = len(selected)
        total = len(self._rudiment_names)

        btn = self._select_buttons[group_name]
        mode_label = self._mode_labels[group_name]

        if count == 0 or count == total:
            # All or none selected = fully automatic
            btn.setText("All")
            mode_label.setText("AUTO")
            mode_label.setStyleSheet(
                "font-size: 9px; font-weight: bold; color: #4CAF50; "
                "border: 1px solid #4CAF50; border-radius: 3px; padding: 1px;"
            )
            self.constraints_changed.emit(group_name, None)
        elif count == 1:
            # Locked to one riff
            name = next(iter(selected))
            btn.setText(name)
            mode_label.setText("LOCKED")
            mode_label.setStyleSheet(
                "font-size: 9px; font-weight: bold; color: #ff9800; "
                "border: 1px solid #ff9800; border-radius: 3px; padding: 1px;"
            )
            self.constraints_changed.emit(group_name, selected)
        else:
            # Curated subset
            btn.setText(f"{count} sel.")
            mode_label.setText(f"CURATED")
            mode_label.setStyleSheet(
                "font-size: 9px; font-weight: bold; color: #2196F3; "
                "border: 1px solid #2196F3; border-radius: 3px; padding: 1px;"
            )
            self.constraints_changed.emit(group_name, selected)

    def update_active_riffs(self, per_group: Dict[str, str]):
        """Update the active riff display labels (engine-owned state).

        Only touches the read-only labels, never the user's checkbox selections.
        """
        for group_name, riff_name in per_group.items():
            label = self._active_labels.get(group_name)
            if label:
                label.setText(f"▶ {riff_name}" if riff_name else "▶ —")

    def set_constraint(self, group_name: str, allowed: Optional[Set[str]]) -> None:
        """Programmatically restore a group's checked rudiments.

        None or empty = AUTO (all unchecked). Updates the menu, button label,
        and mode badge to match — same logic as a user clicking checkboxes.
        """
        menu = self._menus.get(group_name)
        if menu is None:
            return

        target = allowed or set()
        for name, cb in menu._checkboxes.items():
            cb.blockSignals(True)
            cb.setChecked(name in target)
            cb.blockSignals(False)
        # Re-run the same UI-state logic that handles user-driven changes.
        self._on_selection_changed(group_name)

    def get_constraints(self) -> Dict[str, Set[str]]:
        """Return current per-group selections (only groups with non-AUTO state).

        AUTO means either nothing is checked or all are checked — those are
        excluded from the result so callers can persist only meaningful state.
        """
        result: Dict[str, Set[str]] = {}
        total = len(self._rudiment_names)
        for g, menu in self._menus.items():
            selected = menu.get_selected()
            if 0 < len(selected) < total:
                result[g] = selected
        return result
