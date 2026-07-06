# gui/tabs/fixtures_tab.py

from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QComboBox
from PyQt6.QtGui import QFont
from config.models import Configuration, Fixture, FixtureMode, FixtureGroup
from utils.fixture_utils import get_cached_fixture_definitions
from utils.dmx_conflicts import (
    AddressConflict,
    DMX_MAX_ADDRESS,
    fixture_channel_count,
    lint_dmx_addresses,
)
from .base_tab import BaseTab

# Warning tint for Universe / Address cells of conflicting fixtures.
# A fixed red (not theme-derived) so it reads as "error" on both themes
# and can't collide with the pastel group tints.
CONFLICT_CELL_QSS = "background-color: #d9534f; color: #ffffff;"


class FixturesTab(BaseTab):
    """Fixture inventory and group management tab

    Handles fixture CRUD operations, QLC+ fixture scanning, group management,
    and color-coded table display. This is the central tab for fixture configuration.
    """

    def __init__(self, config: Configuration, parent=None):
        """Initialize fixtures tab

        Args:
            config: Shared Configuration object
            parent: Parent widget (typically MainWindow)
        """
        # Initialize color management before super().__init__()
        self.group_colors = {}
        self.color_index = 0
        self.predefined_colors = [
            QtGui.QColor(255, 182, 193),  # Light pink
            QtGui.QColor(173, 216, 230),  # Light blue
            QtGui.QColor(144, 238, 144),  # Light green
            QtGui.QColor(255, 218, 185),  # Peach
            QtGui.QColor(221, 160, 221),  # Plum
            QtGui.QColor(176, 196, 222),  # Light steel blue
            QtGui.QColor(255, 255, 224),  # Light yellow
            QtGui.QColor(230, 230, 250)   # Lavender
        ]
        self.existing_groups = set()
        self.fixture_paths = []

        # Track fixture state to avoid unnecessary rebuilds
        self._last_fixture_fingerprint = None
        # Lazy loading flag - update when tab becomes visible
        self._pending_update = False
        # Reentrancy and rebuild guards
        self._is_activating = False
        self._is_rebuilding = False

        super().__init__(config, parent)

    def showEvent(self, event):
        """Handle tab becoming visible - trigger pending update if needed."""
        super().showEvent(event)
        if self._pending_update:
            self._pending_update = False
            # Use QTimer to defer update slightly, avoiding Qt stack issues
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(50, self._deferred_update)

    def _deferred_update(self):
        """Deferred update callback - only run if tab is still visible."""
        if self.isVisible() and not self._is_rebuilding:
            self.update_from_config(force=True)

    def schedule_update(self):
        """Schedule an update for when the tab becomes visible."""
        self._pending_update = True
        # If already visible, update now
        if self.isVisible():
            self._pending_update = False
            self.update_from_config(force=True)

    def on_tab_activated(self):
        """Called when tab becomes visible. Only reload if pending update."""
        if self._is_activating:
            return
        try:
            self._is_activating = True
            if self._pending_update:
                self._pending_update = False
                self.update_from_config(force=True)
            else:
                self.update_from_config()
        finally:
            self._is_activating = False

    def setup_ui(self):
        """Set up fixture management UI"""
        # Main layout
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # Button toolbar
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(8)

        # Toolbar +/-/duplicate buttons share styling with
        # ConfigurationTab via TOOLBAR_BTN_WIDTH. Default theme
        # padding (no compact-density) so the icon buttons render
        # with the same proportions as default text buttons elsewhere
        # — when the user compared this tab to ConfigurationTab the
        # compact-density flavour was reading as a different class
        # of widget than the Refresh / Update buttons that share
        # ConfigurationTab's toolbar. Default styling everywhere is
        # the simplest way to keep them visually consistent.
        from gui.tabs.configuration_tab import TOOLBAR_BTN_WIDTH

        self.add_btn = QtWidgets.QPushButton("+")
        self.add_btn.setFixedWidth(TOOLBAR_BTN_WIDTH)
        self.add_btn.setToolTip("Add Fixture")
        toolbar.addWidget(self.add_btn)

        self.remove_btn = QtWidgets.QPushButton("-")
        self.remove_btn.setFixedWidth(TOOLBAR_BTN_WIDTH)
        self.remove_btn.setToolTip("Remove Fixture")
        toolbar.addWidget(self.remove_btn)

        self.duplicate_btn = QtWidgets.QPushButton("⎘")
        self.duplicate_btn.setFixedWidth(TOOLBAR_BTN_WIDTH)
        self.duplicate_btn.setToolTip("Duplicate Fixture")
        toolbar.addWidget(self.duplicate_btn)

        toolbar.addStretch()
        main_layout.addLayout(toolbar)

        # Fixtures label + DMX conflict summary on the same line
        label_row = QtWidgets.QHBoxLayout()
        label_row.setSpacing(12)

        self.label = QtWidgets.QLabel("Fixtures")
        self.label.setFont(QFont("", 14, QFont.Weight.Bold))
        label_row.addWidget(self.label)

        self.conflict_label = QtWidgets.QLabel("")
        self.conflict_label.setStyleSheet("color: #d9534f; font-weight: bold;")
        self.conflict_label.hide()
        label_row.addWidget(self.conflict_label)

        label_row.addStretch()
        main_layout.addLayout(label_row)

        # Fixtures table — RowOutlineTableWidget paints a continuous
        # selection outline around the entire row, including across cells
        # that host widgets via setCellWidget (Universe spin, Address spin,
        # Mode/Group/Role combos). See gui/widgets/row_outline_table.py and
        # docs/qt-gotchas.md for why a per-cell delegate can't do this.
        from gui.widgets.row_outline_table import RowOutlineTableWidget
        self.table = RowOutlineTableWidget()

        # Setup table structure
        self._setup_table()

        main_layout.addWidget(self.table)

        # Load initial data
        self.update_from_config()

    def _setup_table(self):
        """Initialize table structure and properties"""
        headers = ['Universe', 'Address', 'Manufacturer', 'Model', 'Channels',
                   'Mode', 'Name', 'Group', 'Role']
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)

        # Make table stretch to fill available space
        self.table.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Interactive
        )

        # Set initial column widths (these are now resizable)
        self.table.setColumnWidth(0, 80)   # Universe
        self.table.setColumnWidth(1, 80)   # Address
        self.table.setColumnWidth(2, 180)  # Manufacturer
        self.table.setColumnWidth(3, 180)  # Model
        self.table.setColumnWidth(4, 80)   # Channels
        self.table.setColumnWidth(5, 170)  # Mode (wider — values like "14-Channel" + dropdown arrow)
        self.table.setColumnWidth(6, 140)  # Name
        self.table.setColumnWidth(7, 190)  # Group (wider — editable combo + dropdown arrow + group name)

        # Modern table styling — alternating rows, no grid, padded headers.
        # Visuals come from the active theme stylesheet.
        from gui.widgets.modern_table import apply_modern_table_style
        apply_modern_table_style(self.table)
        # Selection delegate — strips State_Selected before super().paint
        # so Qt doesn't fill the cell with the opaque selection brush and
        # cover the per-row group tint. The visible selection outline is
        # drawn by RowOutlineTableWidget at the table (overlay) level.
        from gui.widgets.group_row_delegate import GroupRowDelegate
        self._group_row_delegate = GroupRowDelegate(self.table)
        self.table.setItemDelegate(self._group_row_delegate)
        self.table.setSortingEnabled(True)
        # Header alignment now comes from apply_modern_table_style so
        # every table in the app reads the same.

    def connect_signals(self):
        """Connect widget signals to handlers"""
        self.add_btn.clicked.connect(self._add_fixture)
        self.remove_btn.clicked.connect(self._remove_fixture)
        self.duplicate_btn.clicked.connect(self._duplicate_fixture)
        self.table.itemChanged.connect(self.save_to_config)

    def _get_fixture_fingerprint(self) -> str:
        """Generate fingerprint of fixtures and groups for change detection."""
        parts = []
        for f in self.config.fixtures:
            parts.append(f"{f.name}:{f.universe}:{f.address}:{f.manufacturer}:{f.model}:{f.current_mode}:{f.group}")
        # Also include groups in fingerprint
        parts.append(f"groups:{','.join(sorted(self.config.groups.keys()))}")
        return "|".join(parts)

    def update_from_config(self, force: bool = False):
        """Refresh fixture table from configuration.

        Args:
            force: If True, rebuild even if no changes detected
        """
        if self._is_rebuilding:
            return

        # Check if rebuild is needed
        current_fingerprint = self._get_fixture_fingerprint()
        if not force and current_fingerprint == self._last_fixture_fingerprint:
            return  # No changes, skip expensive rebuild

        self._is_rebuilding = True
        try:
            self._update_from_config_inner(current_fingerprint)
        finally:
            self._is_rebuilding = False

    def _update_from_config_inner(self, current_fingerprint):
        """Inner implementation of update_from_config."""
        self._last_fixture_fingerprint = current_fingerprint

        # Block signals during population
        self.table.blockSignals(True)
        self.table.setRowCount(0)

        # Process events periodically to avoid Qt stack overflow with large configs
        from PyQt6.QtWidgets import QApplication

        # Update existing groups set
        self.existing_groups = set(self.config.groups.keys())

        for idx, fixture in enumerate(self.config.fixtures):
            row = self.table.rowCount()
            self.table.insertRow(row)

            # Process events every 3 rows to prevent Qt stack overflow
            if idx > 0 and idx % 3 == 0:
                QApplication.processEvents()

            # Universe spinbox
            universe_spin = QtWidgets.QSpinBox()
            universe_spin.setRange(1, 16)
            universe_spin.setValue(fixture.universe)
            universe_spin.valueChanged.connect(self.save_to_config)
            self.table.setCellWidget(row, 0, universe_spin)

            # Address spinbox
            address_spin = QtWidgets.QSpinBox()
            address_spin.setRange(1, 512)
            address_spin.setValue(fixture.address)
            address_spin.valueChanged.connect(self.save_to_config)
            self.table.setCellWidget(row, 1, address_spin)

            # Manufacturer and Model — no inline background; theme + the
            # group-tint logic in _update_row_colors set it.
            manufacturer_item = QtWidgets.QTableWidgetItem(fixture.manufacturer)
            self.table.setItem(row, 2, manufacturer_item)

            model_item = QtWidgets.QTableWidgetItem(fixture.model)
            self.table.setItem(row, 3, model_item)

            # Mode combo box
            mode_combo = QtWidgets.QComboBox()
            if fixture.available_modes:
                for mode in fixture.available_modes:
                    mode_combo.addItem(f"{mode.name} ({mode.channels}ch)")

                # Set current mode
                current_mode_text = next(
                    (f"{mode.name} ({mode.channels}ch)"
                     for mode in fixture.available_modes
                     if mode.name == fixture.current_mode),
                    fixture.current_mode
                )
                index = mode_combo.findText(current_mode_text)
                if index >= 0:
                    mode_combo.setCurrentIndex(index)
                    channels = fixture.available_modes[index].channels
                else:
                    # current_mode doesn't exactly match any available_modes
                    # entry — fall back to the first mode rather than leaving
                    # the cell empty. This path triggered the "channels lost
                    # on duplicate" bug whenever stored current_mode drifted
                    # out of sync with available_modes (e.g. saved + reloaded
                    # configs, or any path that mutates one without the other).
                    channels = fixture.available_modes[0].channels
                # Always set the channels item; never leave it empty when the
                # fixture has any modes at all.
                channels_item = QtWidgets.QTableWidgetItem(str(channels))
                self.table.setItem(row, 4, channels_item)

                # Create closure for mode change handler
                def create_mode_handler(current_row, modes):
                    def handle_mode_change(index):
                        if 0 <= index < len(modes):
                            channels = modes[index].channels
                            channels_item = QtWidgets.QTableWidgetItem(str(channels))
                            self.table.setItem(current_row, 4, channels_item)
                            self.config.fixtures[current_row].current_mode = modes[index].name
                            self._update_row_colors()
                            # Notify main window of changes
                            main_window = self.window()
                            if main_window and hasattr(main_window, 'on_groups_changed'):
                                main_window.on_groups_changed()
                    return handle_mode_change

                mode_combo.currentIndexChanged.connect(
                    create_mode_handler(row, fixture.available_modes)
                )
            else:
                mode_combo.addItem(fixture.current_mode)
                channels_item = QtWidgets.QTableWidgetItem("0")
                self.table.setItem(row, 4, channels_item)

            self.table.setCellWidget(row, 5, mode_combo)

            # Name — theme + group-tint handle background.
            name_item = QtWidgets.QTableWidgetItem(fixture.name)
            self.table.setItem(row, 6, name_item)

            # Group combo box
            group_combo = QtWidgets.QComboBox()
            group_combo.setEditable(True)
            group_combo.addItem("")
            for group in sorted(self.config.groups.keys()):
                group_combo.addItem(group)
            group_combo.addItem("Add New...")
            group_combo.setCurrentText(fixture.group)

            # Create closure for group change handler
            def create_group_handler(current_row, combo):
                def handle_group_change(text):
                    if text == "Add New...":
                        self._handle_new_group(combo)
                    elif text:
                        self.config.fixtures[current_row].group = text
                        self._update_groups()
                        # If this is a new group, add it to all other comboboxes
                        self._add_group_to_all_combos(text, combo)
                    else:
                        self.config.fixtures[current_row].group = ""
                        self._update_groups()
                    self._update_row_colors()
                    # Notify main window of changes
                    main_window = self.window()
                    if main_window and hasattr(main_window, 'on_groups_changed'):
                        main_window.on_groups_changed()
                return handle_group_change

            group_combo.currentTextChanged.connect(create_group_handler(row, group_combo))
            self.table.setCellWidget(row, 7, group_combo)

            # Role combo box (per group — all fixtures in the same group share a role)
            role_combo = QComboBox()
            role_combo.addItems(["", "wash", "key", "texture", "accent"])
            # Read current role from group if fixture has one
            if fixture.group and fixture.group in self.config.groups:
                current_role = self.config.groups[fixture.group].lighting_role or ""
                idx = role_combo.findText(current_role)
                if idx >= 0:
                    role_combo.setCurrentIndex(idx)

            def create_role_handler(current_row):
                def handle_role_change(text):
                    if self._is_rebuilding:
                        return
                    fix = self.config.fixtures[current_row]
                    if fix.group and fix.group in self.config.groups:
                        self.config.groups[fix.group].lighting_role = text
                        # Update all other rows in the same group
                        self._sync_role_combos(fix.group, text)
                return handle_role_change

            role_combo.currentTextChanged.connect(create_role_handler(row))
            self.table.setCellWidget(row, 8, role_combo)

        # Re-enable signals and update colors
        self.table.blockSignals(False)
        self._update_row_colors()

    def save_to_config(self, item=None):
        """Update configuration from table values"""
        if self._is_rebuilding:
            return
        # Update all fixtures from table
        for row in range(self.table.rowCount()):
            if row >= len(self.config.fixtures):
                continue

            fixture = self.config.fixtures[row]

            # Update universe and address
            universe_spin = self.table.cellWidget(row, 0)
            if universe_spin and isinstance(universe_spin, QtWidgets.QSpinBox):
                fixture.universe = universe_spin.value()

            address_spin = self.table.cellWidget(row, 1)
            if address_spin and isinstance(address_spin, QtWidgets.QSpinBox):
                fixture.address = address_spin.value()

            # Update manufacturer
            manufacturer_item = self.table.item(row, 2)
            if manufacturer_item and manufacturer_item.text():
                fixture.manufacturer = manufacturer_item.text()

            # Update model
            model_item = self.table.item(row, 3)
            if model_item and model_item.text():
                fixture.model = model_item.text()

            # Update mode
            mode_combo = self.table.cellWidget(row, 5)
            if mode_combo and isinstance(mode_combo, QtWidgets.QComboBox):
                mode_text = mode_combo.currentText()
                if " (" in mode_text:
                    mode_name = mode_text.split(" (")[0]
                    fixture.current_mode = mode_name

            # Update name
            name_item = self.table.item(row, 6)
            if name_item and name_item.text():
                fixture.name = name_item.text()

            # Update group
            group_combo = self.table.cellWidget(row, 7)
            if group_combo and isinstance(group_combo, QtWidgets.QComboBox):
                group_name = group_combo.currentText()
                if group_name and group_name != "Add New...":
                    fixture.group = group_name
                else:
                    fixture.group = ""

        self._update_groups()

        # Ensure universes exist for all fixtures (auto-create if fixture uses new universe)
        self.config.ensure_universes_for_fixtures()

        # Update fingerprint to reflect saved changes
        self._last_fixture_fingerprint = self._get_fixture_fingerprint()

        # Universe / address spins route here without a row-color pass,
        # so re-lint now to flag or clear conflicts as the user types.
        self._update_conflict_indicators()

        # Notify main window of group changes if needed
        main_window = self.window()
        if main_window and hasattr(main_window, 'on_groups_changed'):
            main_window.on_groups_changed()

    def _update_groups(self):
        """Rebuild groups from fixtures, preserving colors, orientation defaults, and lighting roles"""
        # Apply any pending role from new group creation
        pending_role = getattr(self, '_pending_group_role', None)

        # Store existing group properties (colors and orientation defaults)
        existing_props = {
            name: {
                'color': getattr(group, 'color', '#808080'),
                'default_mounting': getattr(group, 'default_mounting', 'hanging'),
                'default_yaw': getattr(group, 'default_yaw', 0.0),
                'default_pitch': getattr(group, 'default_pitch', 0.0),
                'default_roll': getattr(group, 'default_roll', 0.0),
                'default_z_height': getattr(group, 'default_z_height', 3.0),
                'lighting_role': getattr(group, 'lighting_role', ''),
            }
            for name, group in self.config.groups.items()
        }

        # Clear and rebuild groups
        self.config.groups = {}

        for fixture in self.config.fixtures:
            if fixture.group:
                if fixture.group not in self.config.groups:
                    props = existing_props.get(fixture.group, {})
                    self.config.groups[fixture.group] = FixtureGroup(
                        fixture.group,
                        [],
                        color=props.get('color', '#808080'),
                        default_mounting=props.get('default_mounting', 'hanging'),
                        default_yaw=props.get('default_yaw', 0.0),
                        default_pitch=props.get('default_pitch', 0.0),
                        default_roll=props.get('default_roll', 0.0),
                        default_z_height=props.get('default_z_height', 3.0),
                        lighting_role=props.get('lighting_role', ''),
                    )
                self.config.groups[fixture.group].fixtures.append(fixture)

        # Apply pending lighting role from new group creation
        if pending_role:
            group_name, role = pending_role
            if group_name in self.config.groups:
                self.config.groups[group_name].lighting_role = role
            self._pending_group_role = None

        # Update existing groups set
        self.existing_groups = set(self.config.groups.keys())

    def _handle_new_group(self, group_combo):
        """Show dialog to create new group with optional lighting role"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Add New Group")
        layout = QFormLayout()
        new_group_input = QLineEdit()
        layout.addRow("Group Name:", new_group_input)

        role_combo = QComboBox()
        role_combo.addItems(["", "wash", "key", "texture", "accent"])
        layout.addRow("Lighting Role:", role_combo)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        dialog.setLayout(layout)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_group = new_group_input.text().strip()
            if new_group:
                # Store the role for when the group gets created in _update_groups
                self._pending_group_role = (new_group, role_combo.currentText())

                # Update the current fixture's group combobox
                current_index = group_combo.findText("Add New...")
                group_combo.removeItem(current_index)
                group_combo.addItem(new_group)
                group_combo.addItem("Add New...")
                group_combo.setCurrentText(new_group)

                # Update all other fixtures' group comboboxes with the new group
                self._add_group_to_all_combos(new_group, group_combo)

    def _add_group_to_all_combos(self, group_name, exclude_combo=None):
        """Add a group name to all group comboboxes if it doesn't exist

        Args:
            group_name: The group name to add
            exclude_combo: Optional combobox to exclude from update
        """
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 7)
            if combo and combo != exclude_combo:
                # Check if group already exists in this combo
                if combo.findText(group_name) == -1:
                    # Find "Add New..." item and insert new group before it
                    add_new_index = combo.findText("Add New...")
                    if add_new_index != -1:
                        combo.insertItem(add_new_index, group_name)

    def _sync_role_combos(self, group_name: str, role: str):
        """Sync all role combos for fixtures in the same group."""
        for row in range(self.table.rowCount()):
            if row >= len(self.config.fixtures):
                continue
            if self.config.fixtures[row].group == group_name:
                combo = self.table.cellWidget(row, 8)
                if combo and isinstance(combo, QComboBox):
                    combo.blockSignals(True)
                    idx = combo.findText(role)
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
                    combo.blockSignals(False)

    def _update_row_colors(self):
        """Apply group colors to table rows"""
        # Note: setUpdatesEnabled removed to avoid Qt stack overflow with large configs
        try:
            # Track which colors are already in use to avoid duplicates
            used_colors = set()
            for existing_color in self.group_colors.values():
                used_colors.add(existing_color.name())

            for row in range(self.table.rowCount()):
                group_combo = self.table.cellWidget(row, 7)
                if group_combo:
                    group_name = group_combo.currentText()
                    if group_name and group_name != "Add New...":
                        # Get or create color for group
                        if group_name not in self.group_colors:
                            # First, check if group has a saved color in config
                            if group_name in self.config.groups and self.config.groups[group_name].color:
                                saved_color = self.config.groups[group_name].color
                                # Only use saved color if it's not the default gray
                                if saved_color != '#808080':
                                    self.group_colors[group_name] = QtGui.QColor(saved_color)
                                    used_colors.add(saved_color)

                            # If still no color, assign a new unique color
                            if group_name not in self.group_colors:
                                # Find a color that's not already in use
                                for _ in range(len(self.predefined_colors)):
                                    candidate_color = self.predefined_colors[
                                        self.color_index % len(self.predefined_colors)]
                                    self.color_index += 1
                                    if candidate_color.name() not in used_colors:
                                        self.group_colors[group_name] = candidate_color
                                        used_colors.add(candidate_color.name())
                                        break
                                else:
                                    # All colors used, cycle back (shouldn't happen with 8 colors)
                                    self.group_colors[group_name] = self.predefined_colors[
                                        self.color_index % len(self.predefined_colors)]
                                    self.color_index += 1

                        color = self.group_colors[group_name]
                        # Pick text foreground from background luminance so
                        # readability survives any group color (predefined
                        # pastels resolve to black; a dark custom color
                        # would automatically flip to white).
                        luminance = (
                            0.299 * color.red()
                            + 0.587 * color.green()
                            + 0.114 * color.blue()
                        ) / 255.0
                        fg = QtGui.QColor(0, 0, 0) if luminance > 0.5 else QtGui.QColor(255, 255, 255)
                        fg_hex = fg.name()

                        # Iterate every column once; text cells get
                        # item.setBackground / setForeground (Qt paints those
                        # via the delegate now that the QTableView::item rule
                        # is gone), widget cells get a per-widget stylesheet
                        # that overrides only background-color + color while
                        # the global theme still supplies border / padding.
                        widget_qss = (
                            f"background-color: {color.name()}; color: {fg_hex};"
                        )
                        for col in range(self.table.columnCount()):
                            item = self.table.item(row, col)
                            if item is not None:
                                item.setBackground(color)
                                item.setForeground(fg)
                            cell_widget = self.table.cellWidget(row, col)
                            if cell_widget is not None:
                                cell_widget.setStyleSheet(widget_qss)

                        if group_name in self.config.groups:
                            self.config.groups[group_name].color = color.name()
                    else:
                        # Ungrouped — clear every per-cell override so theme
                        # defaults apply on both items and cell widgets.
                        empty_brush = QtGui.QBrush()
                        for col in range(self.table.columnCount()):
                            item = self.table.item(row, col)
                            if item is not None:
                                item.setBackground(empty_brush)
                                item.setForeground(empty_brush)
                            cell_widget = self.table.cellWidget(row, col)
                            if cell_widget is not None:
                                cell_widget.setStyleSheet("")
            # Conflict warnings paint over the fresh group tint on the
            # Universe/Address cells, so they must re-apply last.
            self._update_conflict_indicators()
        finally:
            # Force a viewport repaint. Cell widgets repaint themselves
            # synchronously when their stylesheet changes, but
            # QTableWidgetItem.setBackground / setForeground only mark
            # cells dirty — Qt batches the actual repaint, which can lag
            # a frame behind interactive events like typing in a combo.
            # Without this, text cells would only catch up once another
            # event triggered the next paint cycle.
            self.table.viewport().update()

    def _group_widget_qss(self, row) -> str:
        """The group-tint stylesheet a row's cell widgets carry ('' if ungrouped).

        Mirrors what _update_row_colors applies, so clearing a conflict
        restores the exact tint instead of a blank cell.
        """
        group_combo = self.table.cellWidget(row, 7)
        if not group_combo:
            return ""
        group_name = group_combo.currentText()
        if not group_name or group_name == "Add New..." or group_name not in self.group_colors:
            return ""
        color = self.group_colors[group_name]
        luminance = (
            0.299 * color.red()
            + 0.587 * color.green()
            + 0.114 * color.blue()
        ) / 255.0
        fg_hex = "#000000" if luminance > 0.5 else "#ffffff"
        return f"background-color: {color.name()}; color: {fg_hex};"

    def _describe_dmx_finding(self, row, finding, fixtures) -> str:
        if isinstance(finding, AddressConflict):
            other_idx = finding.index_b if finding.index_a == row else finding.index_a
            other = fixtures[other_idx]
            return (
                f"Overlaps '{other.name}' on universe {finding.universe}, "
                f"channels {finding.overlap_start}-{finding.overlap_end}"
            )
        return (
            f"Runs past the end of universe {finding.universe} "
            f"(ends at channel {finding.end_address}, max {DMX_MAX_ADDRESS})"
        )

    def _update_conflict_indicators(self):
        """Flag DMX address overlaps / overflow on the Universe + Address cells.

        Only touches cell *widgets* (the spinboxes) and the summary label —
        never table items — so it can run from save_to_config without
        re-triggering itemChanged.
        """
        fixtures = self.config.fixtures
        lint = lint_dmx_addresses(fixtures)
        findings_by_fixture = lint.by_fixture()

        for row in range(self.table.rowCount()):
            if row >= len(fixtures):
                continue
            findings = findings_by_fixture.get(row)
            if findings:
                qss = CONFLICT_CELL_QSS
                tooltip = "\n".join(
                    self._describe_dmx_finding(row, f, fixtures) for f in findings
                )
            else:
                qss = self._group_widget_qss(row)
                tooltip = ""
            for col in (0, 1):  # Universe, Address
                widget = self.table.cellWidget(row, col)
                if widget is not None:
                    widget.setStyleSheet(qss)
                    widget.setToolTip(tooltip)

        issue_count = len(lint.conflicts) + len(lint.overflows)
        if issue_count:
            noun = "issue" if issue_count == 1 else "issues"
            self.conflict_label.setText(f"⚠ {issue_count} DMX addressing {noun}")
            self.conflict_label.show()
        else:
            self.conflict_label.hide()

    def _scan_fixture_files(self) -> list:
        """Every .qxf reachable in the bundled + platform QLC+ fixture
        directories, as dicts the browser dialog consumes. The bundled
        custom_fixtures/ come first and are tagged 'bundled'."""
        from utils.fixture_library import all_fixture_files
        return all_fixture_files()

    def _add_fixture(self):
        """Open the fixture browser and add the picked fixture(s)."""
        from gui.dialogs.fixture_browser_dialog import FixtureBrowserDialog
        try:
            fixture_files = self._scan_fixture_files()
            if not fixture_files:
                raise Exception("No fixture files found in QLC+ directories")

            dialog = FixtureBrowserDialog(fixture_files, parent=self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                selected = dialog.selection()
                if selected:
                    path, quantity = selected
                    self._add_fixtures_from_qxf(path, quantity)

        except Exception as e:
            print(f"Error adding fixture: {e}")
            import traceback
            traceback.print_exc()

    def _find_next_available_address(self, channel_count: int) -> tuple:
        """Find the next available DMX address that can fit the given channel count.

        Returns:
            tuple: (universe, address) for the next available slot
        """
        # Build a map of used addresses per universe
        used_addresses = {}  # universe -> list of (start, end) tuples

        for fixture in self.config.fixtures:
            universe = fixture.universe
            if universe not in used_addresses:
                used_addresses[universe] = []

            start = fixture.address
            end = fixture.address + fixture_channel_count(fixture) - 1
            used_addresses[universe].append((start, end))

        # Try to find space in existing universes first
        for universe in range(1, 17):
            if universe not in used_addresses:
                # Empty universe, use address 1
                return (universe, 1)

            # Sort ranges by start address
            ranges = sorted(used_addresses[universe], key=lambda x: x[0])

            # Check if there's space at the beginning
            if ranges[0][0] > channel_count:
                return (universe, 1)

            # Check for gaps between fixtures
            for i in range(len(ranges) - 1):
                gap_start = ranges[i][1] + 1
                gap_end = ranges[i + 1][0] - 1
                if gap_end - gap_start + 1 >= channel_count:
                    return (universe, gap_start)

            # Check if there's space after the last fixture
            last_end = ranges[-1][1]
            if last_end + channel_count <= 512:
                return (universe, last_end + 1)

        # Fallback to universe 1, address 1 if all universes are somehow full
        return (1, 1)

    def _unique_fixture_name(self, base_name: str) -> str:
        """base_name, or 'base_name (2)', 'base_name (3)', ... if taken."""
        existing = {f.name for f in self.config.fixtures}
        if base_name not in existing:
            return base_name
        n = 2
        while f"{base_name} ({n})" in existing:
            n += 1
        return f"{base_name} ({n})"

    def _add_fixtures_from_qxf(self, fixture_path: str, quantity: int = 1):
        """Parse a .qxf and add ``quantity`` fixtures to the config.

        Each copy is patched at the next free (universe, address) slot —
        the free-slot search re-runs after every append, so multi-adds
        come out at consecutive non-overlapping addresses.
        """
        from utils.fixture_library import parse_fixture_file
        defn = parse_fixture_file(fixture_path)

        manufacturer = defn.manufacturer
        model = defn.model
        fixture_type = defn.legacy_type

        mode_data = [
            {'name': mode.name, 'channels': len(mode.channels)}
            for mode in defn.modes
        ]
        first_mode_channels = mode_data[0]['channels'] if mode_data else 1

        for _ in range(quantity):
            universe, address = self._find_next_available_address(first_mode_channels)
            new_fixture = Fixture(
                universe=universe,
                address=address,
                manufacturer=manufacturer,
                model=model,
                name=self._unique_fixture_name(model),
                group="",
                current_mode=mode_data[0]['name'],
                available_modes=[
                    FixtureMode(name=mode['name'], channels=mode['channels'])
                    for mode in mode_data
                ],
                type=fixture_type,
                x=0.0,
                y=0.0,
                z=0.0,
                definition_source=defn.source,
                gdtf_fixture_type_id=defn.gdtf_fixture_type_id,
            )
            self.config.fixtures.append(new_fixture)

        # Check if this fixture model is already cached
        from utils.fixture_utils import _fixture_definitions_cache
        fixture_key = f"{manufacturer}_{model}"
        alt_key = f"{manufacturer}_{model.replace(' ', '_')}"
        needs_caching = fixture_key not in _fixture_definitions_cache and alt_key not in _fixture_definitions_cache

        if needs_caching:
            # Show loading dialog with animated progress bar
            # Run the slow operation in a thread so animation keeps moving
            loading_dialog = QtWidgets.QDialog(self)
            loading_dialog.setWindowTitle("Loading Fixture")
            loading_dialog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
            loading_dialog.setFixedSize(320, 100)
            loading_dialog.setWindowFlags(
                loading_dialog.windowFlags() & ~QtCore.Qt.WindowType.WindowCloseButtonHint
            )

            layout = QtWidgets.QVBoxLayout(loading_dialog)
            layout.setContentsMargins(20, 15, 20, 15)

            label = QtWidgets.QLabel(f"Loading {manufacturer} {model}...")
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)

            # Indeterminate progress bar (animated)
            progress_bar = QtWidgets.QProgressBar()
            progress_bar.setMinimum(0)
            progress_bar.setMaximum(0)  # This makes it indeterminate/animated
            progress_bar.setTextVisible(False)
            layout.addWidget(progress_bar)

            loading_dialog.show()
            QtWidgets.QApplication.processEvents()

            # Run caching in a background thread
            from PyQt6.QtCore import QThread, pyqtSignal

            class CacheWorker(QThread):
                finished = pyqtSignal()

                def __init__(self, mfr, mdl):
                    super().__init__()
                    self.mfr = mfr
                    self.mdl = mdl

                def run(self):
                    get_cached_fixture_definitions({(self.mfr, self.mdl)})
                    self.finished.emit()

            worker = CacheWorker(manufacturer, model)
            worker.finished.connect(loading_dialog.accept)
            worker.start()

            # Block until worker finishes (but event loop keeps running for animation)
            loading_dialog.exec()
            worker.wait()  # Ensure thread is fully done
        else:
            # Already cached, no need for loading dialog
            get_cached_fixture_definitions({(manufacturer, model)})

        # Refresh table
        self.update_from_config()

        # Notify main window of changes
        main_window = self.window()
        if main_window and hasattr(main_window, 'on_groups_changed'):
            main_window.on_groups_changed()

        print(f"Added {quantity}x fixture: {manufacturer} {model}")

    def _remove_fixture(self):
        """Remove selected fixture from configuration"""
        selected_rows = self.table.selectedItems()
        if selected_rows:
            row = selected_rows[0].row()

            if row < len(self.config.fixtures):
                fixture = self.config.fixtures[row]

                # Remove from group
                if fixture.group and fixture.group in self.config.groups:
                    group = self.config.groups[fixture.group]
                    group.fixtures = [f for f in group.fixtures if f != fixture]

                    # Remove empty group
                    if not group.fixtures:
                        del self.config.groups[fixture.group]

                # Remove fixture
                self.config.fixtures.pop(row)

            # Remove table row
            self.table.removeRow(row)

            # Clean up fixture paths
            if row < len(self.fixture_paths):
                self.fixture_paths.pop(row)

            self._update_groups()
            self._update_row_colors()

            # Notify main window
            main_window = self.window()
            if main_window and hasattr(main_window, 'on_groups_changed'):
                main_window.on_groups_changed()

    def _find_next_free_address(self, universe: int, channel_count: int, exclude_fixture=None) -> tuple:
        """Find the next free DMX address in a universe.

        Args:
            universe: The universe to search in
            channel_count: Number of channels needed
            exclude_fixture: Optional fixture to exclude from conflict check

        Returns:
            Tuple of (universe, address) for the next free slot
        """
        max_address = 512

        # Collect all used address ranges in this universe
        used_ranges = []
        for fixture in self.config.fixtures:
            if fixture is exclude_fixture:
                continue
            if fixture.universe == universe:
                fixture_channels = fixture_channel_count(fixture)
                used_ranges.append((fixture.address, fixture.address + fixture_channels - 1))

        # Sort by start address
        used_ranges.sort(key=lambda x: x[0])

        # Find first gap that fits
        current_address = 1
        for start, end in used_ranges:
            if current_address + channel_count - 1 < start:
                # Found a gap before this fixture
                return (universe, current_address)
            # Move past this fixture
            current_address = max(current_address, end + 1)

        # Check if there's room at the end
        if current_address + channel_count - 1 <= max_address:
            return (universe, current_address)

        # No room in this universe, try next universe
        return self._find_next_free_address(universe + 1, channel_count, exclude_fixture)

    def _generate_unique_copy_name(self, base_name: str) -> str:
        """Generate a unique copy name for a fixture.

        Args:
            base_name: The original fixture name (e.g., "M1")

        Returns:
            A unique name like "M1 (Copy)", "M1 (Copy 2)", "M1 (Copy 3)", etc.
        """
        existing_names = {f.name for f in self.config.fixtures}

        # Try simple "(Copy)" first
        candidate = f"{base_name} (Copy)"
        if candidate not in existing_names:
            return candidate

        # Try numbered copies
        copy_num = 2
        while True:
            candidate = f"{base_name} (Copy {copy_num})"
            if candidate not in existing_names:
                return candidate
            copy_num += 1

    def _duplicate_fixture(self):
        """Duplicate selected fixture with next available address"""
        selected_rows = self.table.selectedItems()
        if not selected_rows:
            QtWidgets.QMessageBox.warning(
                self,
                "No Selection",
                "Please select a fixture to duplicate.",
                QtWidgets.QMessageBox.StandardButton.Ok
            )
            return

        row = selected_rows[0].row()

        if row >= len(self.config.fixtures):
            return

        # Get original fixture
        original_fixture = self.config.fixtures[row]

        # Get channel count
        channel_count = fixture_channel_count(original_fixture)

        # Find next free address (starting from same universe)
        new_universe, new_address = self._find_next_free_address(
            original_fixture.universe, channel_count
        )

        # Generate unique copy name
        new_name = self._generate_unique_copy_name(original_fixture.name)

        # Create duplicate
        new_fixture = Fixture(
            universe=new_universe,
            address=new_address,
            manufacturer=original_fixture.manufacturer,
            model=original_fixture.model,
            name=new_name,
            group=original_fixture.group,
            current_mode=original_fixture.current_mode,
            available_modes=[
                FixtureMode(name=mode.name, channels=mode.channels)
                for mode in original_fixture.available_modes
            ],
            type=original_fixture.type,
            x=original_fixture.x,
            y=original_fixture.y,
            z=original_fixture.z,
            # Copy orientation settings
            mounting=original_fixture.mounting,
            yaw=original_fixture.yaw,
            pitch=original_fixture.pitch,
            roll=original_fixture.roll,
            orientation_uses_group_default=original_fixture.orientation_uses_group_default,
            z_uses_group_default=original_fixture.z_uses_group_default
        )

        # Add to configuration
        self.config.fixtures.append(new_fixture)

        # Add to group
        if new_fixture.group and new_fixture.group in self.config.groups:
            self.config.groups[new_fixture.group].fixtures.append(new_fixture)

        # Refresh table
        self.update_from_config()

        # Notify main window of changes
        main_window = self.window()
        if main_window and hasattr(main_window, 'on_groups_changed'):
            main_window.on_groups_changed()

        print(f"Duplicated fixture: {original_fixture.manufacturer} {original_fixture.model}")
