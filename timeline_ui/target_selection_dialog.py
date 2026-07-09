# timeline_ui/target_selection_dialog.py
# Dialog for selecting multiple fixture targets for a lane

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QDialogButtonBox, QLabel, QGroupBox
)
from PyQt6.QtCore import Qt
from typing import List
from utils.target_resolver import parse_target


class TargetSelectionDialog(QDialog):
    """Dialog for selecting fixture targets with tree checkboxes."""

    def __init__(self, current_targets: List[str], config, parent=None):
        """Create the target selection dialog.

        Args:
            current_targets: Currently selected target strings
            config: Configuration object with groups dict
            parent: Parent widget
        """
        super().__init__(parent)
        self.config = config
        self.current_targets = set(current_targets)

        self.setWindowTitle("Select Fixture Targets")
        self.setMinimumSize(400, 500)

        self._setup_ui()
        self._populate_tree()
        self._apply_current_selection()

    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Instructions
        instructions = QLabel("Select groups and/or individual fixtures to target.")
        instructions.setProperty("role", "stat-caption")
        layout.addWidget(instructions)

        # Tree group
        tree_group = QGroupBox("Fixture Targets")
        tree_layout = QVBoxLayout()

        # Tree widget
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemChanged.connect(self._on_item_changed)
        tree_layout.addWidget(self.tree)

        tree_group.setLayout(tree_layout)
        layout.addWidget(tree_group)

        # Quick action buttons
        btn_layout = QHBoxLayout()

        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self._select_all)
        btn_layout.addWidget(select_all_btn)

        clear_btn = QPushButton("Clear All")
        clear_btn.clicked.connect(self._clear_all)
        btn_layout.addWidget(clear_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setProperty("role", "primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate_tree(self):
        """Populate tree with groups and fixtures."""
        self.tree.blockSignals(True)
        self.tree.clear()

        for group_name in sorted(self.config.groups.keys()):
            group = self.config.groups[group_name]

            # Create group item
            group_item = QTreeWidgetItem(self.tree, [group_name])
            group_item.setFlags(group_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            group_item.setCheckState(0, Qt.CheckState.Unchecked)
            group_item.setData(0, Qt.ItemDataRole.UserRole, {
                "type": "group",
                "name": group_name
            })

            # Add fixture children
            for idx, fixture in enumerate(group.fixtures):
                fixture_name = fixture.name or f"Fixture {idx + 1}"
                fixture_item = QTreeWidgetItem(group_item, [fixture_name])
                fixture_item.setFlags(fixture_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                fixture_item.setCheckState(0, Qt.CheckState.Unchecked)
                fixture_item.setData(0, Qt.ItemDataRole.UserRole, {
                    "type": "fixture",
                    "group": group_name,
                    "index": idx
                })

            group_item.setExpanded(True)

        self.tree.blockSignals(False)

    def _apply_current_selection(self):
        """Apply current targets to tree checkboxes."""
        self.tree.blockSignals(True)

        # Build a map of what's selected
        selected_groups = set()
        selected_fixtures = {}  # group_name -> set of indices

        for target in self.current_targets:
            group_name, index = parse_target(target)
            if index is None:
                selected_groups.add(group_name)
            else:
                if group_name not in selected_fixtures:
                    selected_fixtures[group_name] = set()
                selected_fixtures[group_name].add(index)

        # Apply to tree
        for i in range(self.tree.topLevelItemCount()):
            group_item = self.tree.topLevelItem(i)
            data = group_item.data(0, Qt.ItemDataRole.UserRole)
            group_name = data["name"]

            if group_name in selected_groups:
                # Whole group selected
                group_item.setCheckState(0, Qt.CheckState.Checked)
                for j in range(group_item.childCount()):
                    group_item.child(j).setCheckState(0, Qt.CheckState.Checked)
            elif group_name in selected_fixtures:
                # Some fixtures selected
                indices = selected_fixtures[group_name]
                for j in range(group_item.childCount()):
                    fixture_data = group_item.child(j).data(0, Qt.ItemDataRole.UserRole)
                    if fixture_data["index"] in indices:
                        group_item.child(j).setCheckState(0, Qt.CheckState.Checked)
                # Update parent state
                self._update_parent_state(group_item)

        self.tree.blockSignals(False)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        """Handle checkbox changes with parent/child sync."""
        self.tree.blockSignals(True)
        data = item.data(0, Qt.ItemDataRole.UserRole)

        if data["type"] == "group":
            # Update all children to match parent
            check_state = item.checkState(0)
            for i in range(item.childCount()):
                item.child(i).setCheckState(0, check_state)
        else:
            # Update parent based on children
            parent = item.parent()
            if parent:
                self._update_parent_state(parent)

        self.tree.blockSignals(False)

    def _update_parent_state(self, parent: QTreeWidgetItem):
        """Update parent checkbox based on children states."""
        checked = 0
        total = parent.childCount()

        for i in range(total):
            if parent.child(i).checkState(0) == Qt.CheckState.Checked:
                checked += 1

        if checked == 0:
            parent.setCheckState(0, Qt.CheckState.Unchecked)
        elif checked == total:
            parent.setCheckState(0, Qt.CheckState.Checked)
        else:
            parent.setCheckState(0, Qt.CheckState.PartiallyChecked)

    def _select_all(self):
        """Select all groups."""
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            group_item = self.tree.topLevelItem(i)
            group_item.setCheckState(0, Qt.CheckState.Checked)
            for j in range(group_item.childCount()):
                group_item.child(j).setCheckState(0, Qt.CheckState.Checked)
        self.tree.blockSignals(False)

    def _clear_all(self):
        """Clear all selections."""
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            group_item = self.tree.topLevelItem(i)
            group_item.setCheckState(0, Qt.CheckState.Unchecked)
            for j in range(group_item.childCount()):
                group_item.child(j).setCheckState(0, Qt.CheckState.Unchecked)
        self.tree.blockSignals(False)

    def get_selected_targets(self) -> List[str]:
        """Get list of selected target strings.

        Returns:
            List of target strings like ["Front Wash", "Moving Heads:0"]
        """
        targets = []

        for i in range(self.tree.topLevelItemCount()):
            group_item = self.tree.topLevelItem(i)
            data = group_item.data(0, Qt.ItemDataRole.UserRole)
            group_name = data["name"]

            check_state = group_item.checkState(0)

            if check_state == Qt.CheckState.Checked:
                # Whole group selected
                targets.append(group_name)
            elif check_state == Qt.CheckState.PartiallyChecked:
                # Some fixtures selected - add individual targets
                for j in range(group_item.childCount()):
                    child = group_item.child(j)
                    if child.checkState(0) == Qt.CheckState.Checked:
                        fixture_data = child.data(0, Qt.ItemDataRole.UserRole)
                        targets.append(f"{group_name}:{fixture_data['index']}")

        return targets
