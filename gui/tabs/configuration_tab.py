# gui/tabs/configuration_tab.py

from PyQt6 import QtWidgets, QtCore
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtCore import Qt
from config.models import Configuration, Universe
from utils.dmx_device_detection import get_device_display_names, get_device_port_by_display_name
from .base_tab import BaseTab


# Mid-grey applied to the *foreground* of disabled cells so the dim
# state is visible in both light and dark themes. We can't paint the
# background (the previous ``Qt.GlobalColor.lightGray`` looked bright
# in dark mode and broke `setBackground` row-tinting elsewhere via the
# ``QTableView::item`` QSS gotcha if we tried to fix it that way), and
# QSS has no `QTableView::item:disabled` selector for the same reason.
# A neutral 127-grey is dimmer than the primary text in dark mode
# (#e0e0e0) and dimmer than the primary text in light mode (#222222),
# so the disabled affordance reads consistently in both. Applied via
# `setForeground` because per-item brushes still work — only the
# `QTableView::item` selector would block them.
_DISABLED_FG = QBrush(QColor(127, 127, 127))

# Shared toolbar icon-button width for the +/-/duplicate buttons in
# this tab and FixturesTab. We deliberately do NOT use
# ``density="compact"`` — at this size the default theme padding
# (``QPushButton { padding: 6px 14px; min-height: 22px; }``) renders
# the glyph with the same proportions as the surrounding text
# buttons (Refresh / Update), so a row of mixed icon-and-text
# buttons reads as a uniform set. Compact-density buttons sat
# snugly with 2×4 padding which made them look like a different
# class of widget. Width is fixed at 40 to give the wider ``⎘``
# glyph a little headroom; height is left free so the natural
# ~36 px from the QSS min-height + padding wins.
TOOLBAR_BTN_WIDTH = 40
TOOLBAR_BTN_SIZE = TOOLBAR_BTN_WIDTH  # back-compat alias for tests
_TOOLBAR_BTN_WIDTH = TOOLBAR_BTN_WIDTH


class ConfigurationTab(BaseTab):
    """Universe configuration management tab

    Handles DMX universe configuration including E1.31, ArtNet, and DMX USB settings.
    Provides table-based interface with protocol-specific fields.
    """

    # Column indices
    COL_UNIVERSE_ID = 0
    COL_OUTPUT_TYPE = 1
    COL_MULTICAST = 2
    COL_IP_ADDRESS = 3
    COL_PORT = 4
    COL_SUBNET = 5
    COL_ARTNET_UNIVERSE = 6
    COL_DMX_DEVICE = 7

    def __init__(self, config: Configuration, parent=None):
        """Initialize configuration tab

        Args:
            config: Shared Configuration object
            parent: Parent widget (typically MainWindow)
        """
        # Initialize universes before setup_ui is called
        if not hasattr(config, 'universes'):
            config.universes = {}
            config.initialize_default_universes()

        super().__init__(config, parent)

    def setup_ui(self):
        """Set up universe configuration UI"""
        # Main layout
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # Button toolbar
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(8)

        # Add Universe button. Width is fixed (so the icon buttons
        # line up uniformly), height is left to the theme's natural
        # ~36 px so the icon buttons share the same row height as the
        # Refresh / Update text buttons next to them. We deliberately
        # don't use ``density="compact"`` — see TOOLBAR_BTN_WIDTH for
        # the rationale.
        self.add_universe_btn = QtWidgets.QPushButton("+")
        self.add_universe_btn.setFixedWidth(_TOOLBAR_BTN_WIDTH)
        self.add_universe_btn.setToolTip("Add Universe")
        toolbar.addWidget(self.add_universe_btn)

        # Remove Universe button
        self.remove_universe_btn = QtWidgets.QPushButton("-")
        self.remove_universe_btn.setFixedWidth(_TOOLBAR_BTN_WIDTH)
        self.remove_universe_btn.setToolTip("Remove Universe")
        toolbar.addWidget(self.remove_universe_btn)

        # Refresh Devices button
        self.refresh_devices_btn = QtWidgets.QPushButton("Refresh Devices")
        self.refresh_devices_btn.setFixedWidth(115)
        self.refresh_devices_btn.setToolTip("Refresh USB DMX device list")
        toolbar.addWidget(self.refresh_devices_btn)

        # Update Config button
        self.update_config_btn = QtWidgets.QPushButton("Update Config")
        self.update_config_btn.setFixedWidth(115)
        self.update_config_btn.setToolTip("Update Configuration")
        toolbar.addWidget(self.update_config_btn)

        toolbar.addStretch()
        main_layout.addLayout(toolbar)

        # Config label with tooltip (brand display typography)
        from gui.typography import DisplayLabel
        self.config_label = DisplayLabel("Universe Configuration",
                                         point_size=14,
                                         weight=QFont.Weight.Bold)
        self.config_label.setToolTip(
            "Universe mapping to QLC+:\n"
            "  Universe 1 → QLC+ Line 2 (Gerät 3)\n"
            "  Universe 2 → QLC+ Line 3 (Gerät 4)\n"
            "  etc.\n\n"
            "Note: QLC+ Lines 0-1 are reserved for hardcoded interfaces\n"
            "(10.2.0.2 and 127.0.0.1) and are skipped."
        )
        main_layout.addWidget(self.config_label)

        # Universe list table
        self.universe_list = QtWidgets.QTableWidget()
        self.universe_list.setColumnCount(8)
        self.universe_list.setHorizontalHeaderLabels([
            "Universe ID",       # 0
            "Protocol",          # 1
            "Multicast",         # 2 - E1.31 only
            "IP Address",        # 3 - ArtNet, E1.31
            "Port",              # 4 - E1.31 only
            "Subnet",            # 5 - ArtNet only
            "Universe/Net",      # 6 - ArtNet, E1.31
            "DMX Device"         # 7 - DMX USB only
        ])

        # Set tooltip for Universe ID column header
        header_item = self.universe_list.horizontalHeaderItem(self.COL_UNIVERSE_ID)
        if header_item:
            header_item.setToolTip(
                "Universe ID in Show Creator\n"
                "Maps to QLC+ Line (ID + 1):\n"
                "  Universe 1 → Line 2\n"
                "  Universe 2 → Line 3\n"
                "  etc."
            )

        # Modern table styling (alternating rows, no grid, row selection,
        # padded headers). Visuals come from the active theme stylesheet.
        from gui.widgets.modern_table import apply_modern_table_style
        apply_modern_table_style(self.universe_list)

        # Make table stretch to fill available space
        self.universe_list.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding
        )
        self.universe_list.horizontalHeader().setStretchLastSection(True)
        self.universe_list.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Interactive
        )

        # Set initial column widths
        self.universe_list.setColumnWidth(0, 90)   # Universe ID
        self.universe_list.setColumnWidth(1, 100)  # Protocol
        self.universe_list.setColumnWidth(2, 80)   # Multicast
        self.universe_list.setColumnWidth(3, 120)  # IP Address
        self.universe_list.setColumnWidth(4, 70)   # Port
        self.universe_list.setColumnWidth(5, 70)   # Subnet
        self.universe_list.setColumnWidth(6, 100)  # Universe/Net
        self.universe_list.setColumnWidth(7, 200)  # DMX Device

        main_layout.addWidget(self.universe_list)

        # Load initial data
        self.update_from_config()

    def connect_signals(self):
        """Connect widget signals to handlers"""
        self.add_universe_btn.clicked.connect(self._add_universe)
        self.remove_universe_btn.clicked.connect(self._remove_universe)
        self.refresh_devices_btn.clicked.connect(self._refresh_devices)
        self.update_config_btn.clicked.connect(self.save_to_config)
        self.universe_list.itemChanged.connect(self._on_universe_item_changed)

    def update_from_config(self):
        """Load universes from configuration to table"""
        # Block signals to prevent triggering itemChanged during population
        self.universe_list.blockSignals(True)

        # Clear the table first
        self.universe_list.setRowCount(0)

        if hasattr(self.config, 'universes'):
            for universe_id, universe in sorted(self.config.universes.items()):
                self._add_universe_row(universe)

        # Re-enable signals
        self.universe_list.blockSignals(False)

    def _add_universe_row(self, universe: Universe):
        """Add a row for a universe with protocol-specific fields"""
        row = self.universe_list.rowCount()
        self.universe_list.insertRow(row)

        protocol = universe.output.get('plugin', 'E1.31')
        params = universe.output.get('parameters', {})

        # Universe ID (always shown)
        id_item = QtWidgets.QTableWidgetItem(str(universe.id))
        id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # Read-only
        self.universe_list.setItem(row, self.COL_UNIVERSE_ID, id_item)

        # Protocol selector (always shown)
        protocol_combo = QtWidgets.QComboBox()
        protocol_combo.addItems(["E1.31", "ArtNet", "DMX USB"])
        protocol_combo.setCurrentText(protocol)
        protocol_combo.currentTextChanged.connect(
            lambda text, r=row: self._on_protocol_changed(r, text)
        )
        self.universe_list.setCellWidget(row, self.COL_OUTPUT_TYPE, protocol_combo)

        # Create all widgets (we'll show/hide based on protocol)
        self._populate_row_widgets(row, protocol, params)

        # Update visibility for initial protocol
        self._update_row_visibility(row, protocol)

    def _populate_row_widgets(self, row: int, protocol: str, params: dict):
        """Populate all widgets for a row based on protocol"""

        # Multicast checkbox (E1.31 only)
        multicast_widget = QtWidgets.QWidget()
        multicast_layout = QtWidgets.QHBoxLayout(multicast_widget)
        multicast_layout.setContentsMargins(4, 0, 4, 0)
        multicast_checkbox = QtWidgets.QCheckBox()
        multicast_checkbox.setChecked(params.get('multicast', 'true').lower() == 'true')
        multicast_checkbox.setToolTip(
            "E1.31 Multicast mode\n"
            "Checked: Uses multicast IP (auto-calculated from universe)\n"
            "Unchecked: Uses unicast IP (manual entry)"
        )
        multicast_checkbox.stateChanged.connect(
            lambda state, r=row: self._on_multicast_changed(r, state)
        )
        multicast_layout.addWidget(multicast_checkbox)
        multicast_layout.addStretch()
        self.universe_list.setCellWidget(row, self.COL_MULTICAST, multicast_widget)

        # IP Address (ArtNet, E1.31)
        ip_item = QtWidgets.QTableWidgetItem(params.get('ip', ''))
        self.universe_list.setItem(row, self.COL_IP_ADDRESS, ip_item)

        # Port (E1.31 only)
        port_item = QtWidgets.QTableWidgetItem(params.get('port', '5568'))
        self.universe_list.setItem(row, self.COL_PORT, port_item)

        # Subnet (ArtNet only)
        subnet_item = QtWidgets.QTableWidgetItem(params.get('subnet', '0'))
        self.universe_list.setItem(row, self.COL_SUBNET, subnet_item)

        # Universe (ArtNet, E1.31)
        universe_item = QtWidgets.QTableWidgetItem(params.get('universe', '1'))
        self.universe_list.setItem(row, self.COL_ARTNET_UNIVERSE, universe_item)

        # DMX Device (DMX USB only)
        device_combo = QtWidgets.QComboBox()
        device_names = get_device_display_names()
        device_combo.addItems(device_names)

        # Try to select the stored device
        stored_device = params.get('device', '')
        if stored_device:
            # Find matching device
            for i, name in enumerate(device_names):
                if stored_device in name:
                    device_combo.setCurrentIndex(i)
                    break

        # Connect to auto-save on device change
        device_combo.currentTextChanged.connect(
            lambda text, r=row: self._on_device_changed(r, text)
        )

        self.universe_list.setCellWidget(row, self.COL_DMX_DEVICE, device_combo)

    def _update_row_visibility(self, row: int, protocol: str):
        """Update which columns are visible/enabled for a row based on protocol"""

        # Reset all items to enabled state first. Clearing the brushes
        # (``QBrush()`` is the default invalid brush) lets the active
        # theme paint the cell — previously this hardcoded
        # ``Qt.GlobalColor.white`` which made the dark theme look like
        # a checker-board of glaring white cells.
        for col in range(self.COL_MULTICAST, self.COL_DMX_DEVICE + 1):
            item = self.universe_list.item(row, col)
            widget = self.universe_list.cellWidget(row, col)

            if item:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable)
                item.setBackground(QBrush())
                item.setForeground(QBrush())
            if widget:
                widget.setEnabled(True)

        # Disable irrelevant columns based on protocol
        if protocol == "ArtNet":
            # Show: IP Address, Subnet, Universe
            # Hide: Multicast, Port, DMX Device
            self._disable_cell(row, self.COL_MULTICAST)
            self._disable_cell(row, self.COL_PORT)
            self._disable_cell(row, self.COL_DMX_DEVICE)

        elif protocol == "E1.31":
            # Show: Multicast, IP Address (if not multicast), Port, Universe
            # Hide: Subnet, DMX Device
            self._disable_cell(row, self.COL_SUBNET)
            self._disable_cell(row, self.COL_DMX_DEVICE)

            # Update IP address based on multicast state
            multicast_widget = self.universe_list.cellWidget(row, self.COL_MULTICAST)
            if multicast_widget:
                checkbox = multicast_widget.findChild(QtWidgets.QCheckBox)
                if checkbox and checkbox.isChecked():
                    # Multicast mode - IP is auto-calculated
                    ip_item = self.universe_list.item(row, self.COL_IP_ADDRESS)
                    if ip_item:
                        ip_item.setFlags(ip_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        ip_item.setForeground(_DISABLED_FG)

        elif protocol == "DMX USB":
            # Show: DMX Device
            # Hide: Multicast, IP Address, Port, Subnet, Universe
            self._disable_cell(row, self.COL_MULTICAST)
            self._disable_cell(row, self.COL_IP_ADDRESS)
            self._disable_cell(row, self.COL_PORT)
            self._disable_cell(row, self.COL_SUBNET)
            self._disable_cell(row, self.COL_ARTNET_UNIVERSE)

    def _disable_cell(self, row: int, col: int):
        """Disable and gray out a cell"""
        item = self.universe_list.item(row, col)
        widget = self.universe_list.cellWidget(row, col)

        if item:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable & ~Qt.ItemFlag.ItemIsEnabled)
            # Theme-neutral dim. Background stays at the theme's default
            # so we don't punch a bright hole in the dark theme's table;
            # the foreground tint plus Qt's flag-based unclickable state
            # are enough to communicate "disabled".
            item.setForeground(_DISABLED_FG)
            item.setText("")  # Clear irrelevant data

        if widget:
            widget.setEnabled(False)

    def _on_protocol_changed(self, row: int, protocol: str):
        """Handle protocol type changes"""
        self._update_row_visibility(row, protocol)

        # Update universe ID from row
        universe_id_item = self.universe_list.item(row, self.COL_UNIVERSE_ID)
        if universe_id_item:
            universe_id = int(universe_id_item.text())
            if universe_id in self.config.universes:
                self.config.universes[universe_id].output['plugin'] = protocol

                # Clear old parameters and set protocol-specific defaults
                params = self.config.universes[universe_id].output['parameters']
                params.clear()  # Clear old protocol parameters

                if protocol == "ArtNet":
                    params['ip'] = '192.168.1.100'
                    params['subnet'] = '0'
                    params['universe'] = '0'
                elif protocol == "E1.31":
                    params['multicast'] = 'true'
                    params['ip'] = '239.255.0.1'
                    params['port'] = '5568'
                    params['universe'] = '1'
                elif protocol == "DMX USB":
                    params['device'] = ''

                # Reload the row with new defaults
                self.universe_list.blockSignals(True)
                self._populate_row_widgets(row, protocol, params)
                self._update_row_visibility(row, protocol)
                self.universe_list.blockSignals(False)

    def _on_multicast_changed(self, row: int, state: int):
        """Handle multicast checkbox changes for E1.31"""
        is_multicast = (state == Qt.CheckState.Checked.value)

        # Update IP address editability
        ip_item = self.universe_list.item(row, self.COL_IP_ADDRESS)
        universe_item = self.universe_list.item(row, self.COL_ARTNET_UNIVERSE)

        if is_multicast:
            # Calculate multicast IP from universe number
            if universe_item and universe_item.text():
                universe_num = int(universe_item.text())
                multicast_ip = f"239.255.{universe_num >> 8}.{universe_num & 0xFF}"
                if ip_item:
                    ip_item.setText(multicast_ip)
                    ip_item.setFlags(ip_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    ip_item.setForeground(_DISABLED_FG)
        else:
            # Allow manual IP entry
            if ip_item:
                ip_item.setFlags(ip_item.flags() | Qt.ItemFlag.ItemIsEditable)
                ip_item.setForeground(QBrush())

        # Update config
        universe_id_item = self.universe_list.item(row, self.COL_UNIVERSE_ID)
        if universe_id_item:
            universe_id = int(universe_id_item.text())
            if universe_id in self.config.universes:
                self.config.universes[universe_id].output['parameters']['multicast'] = str(is_multicast).lower()

    def _on_device_changed(self, row: int, device_display_name: str):
        """Handle DMX device selection changes"""
        universe_id_item = self.universe_list.item(row, self.COL_UNIVERSE_ID)
        if universe_id_item:
            try:
                universe_id = int(universe_id_item.text())
                if universe_id in self.config.universes:
                    device_port = get_device_port_by_display_name(device_display_name)
                    self.config.universes[universe_id].output['parameters']['device'] = (
                        device_port if device_port else device_display_name
                    )
            except (ValueError, AttributeError) as e:
                print(f"Error updating DMX device: {e}")

    def save_to_config(self):
        """Update universe configuration from table values"""
        for row in range(self.universe_list.rowCount()):
            universe_id_item = self.universe_list.item(row, self.COL_UNIVERSE_ID)
            if universe_id_item is None or not universe_id_item.text():
                continue

            try:
                universe_id = int(universe_id_item.text())
                if universe_id not in self.config.universes:
                    continue

                # Get protocol
                protocol_combo = self.universe_list.cellWidget(row, self.COL_OUTPUT_TYPE)
                if protocol_combo:
                    protocol = protocol_combo.currentText()
                    self.config.universes[universe_id].output['plugin'] = protocol

                params = self.config.universes[universe_id].output['parameters']
                params.clear()  # Clear old parameters before saving new ones

                # Save protocol-specific parameters
                if protocol == "ArtNet":
                    # IP, Subnet, Universe (only save non-empty values)
                    ip_item = self.universe_list.item(row, self.COL_IP_ADDRESS)
                    subnet_item = self.universe_list.item(row, self.COL_SUBNET)
                    uni_item = self.universe_list.item(row, self.COL_ARTNET_UNIVERSE)

                    if ip_item and ip_item.text():
                        params['ip'] = ip_item.text()
                    if subnet_item and subnet_item.text():
                        params['subnet'] = subnet_item.text()
                    if uni_item and uni_item.text():
                        params['universe'] = uni_item.text()

                elif protocol == "E1.31":
                    # Multicast, IP, Port, Universe (only save non-empty values)
                    multicast_widget = self.universe_list.cellWidget(row, self.COL_MULTICAST)
                    ip_item = self.universe_list.item(row, self.COL_IP_ADDRESS)
                    port_item = self.universe_list.item(row, self.COL_PORT)
                    uni_item = self.universe_list.item(row, self.COL_ARTNET_UNIVERSE)

                    if multicast_widget:
                        checkbox = multicast_widget.findChild(QtWidgets.QCheckBox)
                        if checkbox:
                            params['multicast'] = str(checkbox.isChecked()).lower()

                    if ip_item and ip_item.text():
                        params['ip'] = ip_item.text()
                    if port_item and port_item.text():
                        params['port'] = port_item.text()
                    if uni_item and uni_item.text():
                        params['universe'] = uni_item.text()

                elif protocol == "DMX USB":
                    # Device
                    device_combo = self.universe_list.cellWidget(row, self.COL_DMX_DEVICE)
                    if device_combo:
                        device_display_name = device_combo.currentText()
                        device_port = get_device_port_by_display_name(device_display_name)
                        if device_port or device_display_name:
                            params['device'] = device_port if device_port else device_display_name

            except (ValueError, AttributeError) as e:
                print(f"Error updating universe {row}: {e}")

        print("Universe configuration updated from table")

    def _add_universe(self):
        """Add a new universe configuration"""
        # Find next available universe ID
        existing_ids = list(self.config.universes.keys()) if self.config.universes else [0]
        universe_id = max(existing_ids) + 1

        # Create new universe with E1.31 defaults
        new_universe = Universe(
            id=universe_id,
            name=f"Universe {universe_id}",
            output={
                'plugin': 'E1.31',
                'line': '0',
                'parameters': {
                    'multicast': 'true',
                    'ip': f'239.255.0.{universe_id}',
                    'port': '5568',
                    'universe': str(universe_id)
                }
            }
        )

        self.config.universes[universe_id] = new_universe

        # Add row to table
        self.universe_list.blockSignals(True)
        self._add_universe_row(new_universe)
        self.universe_list.blockSignals(False)

    def _remove_universe(self):
        """Remove selected universe configuration"""
        current_row = self.universe_list.currentRow()
        if current_row >= 0:
            universe_id_item = self.universe_list.item(current_row, self.COL_UNIVERSE_ID)
            if universe_id_item:
                universe_id = int(universe_id_item.text())
                if universe_id in self.config.universes:
                    del self.config.universes[universe_id]
                self.universe_list.removeRow(current_row)

    def _refresh_devices(self):
        """Refresh USB DMX device list"""
        # Get new device list
        device_names = get_device_display_names()

        # Update all DMX device combo boxes
        for row in range(self.universe_list.rowCount()):
            protocol_combo = self.universe_list.cellWidget(row, self.COL_OUTPUT_TYPE)
            if protocol_combo and protocol_combo.currentText() == "DMX USB":
                device_combo = self.universe_list.cellWidget(row, self.COL_DMX_DEVICE)
                if device_combo:
                    current_device = device_combo.currentText()
                    device_combo.clear()
                    device_combo.addItems(device_names)

                    # Try to restore previous selection
                    index = device_combo.findText(current_device)
                    if index >= 0:
                        device_combo.setCurrentIndex(index)

        print("USB DMX device list refreshed")

    def _on_universe_item_changed(self, item):
        """Handle changes to universe table items - update config in real-time"""
        row = item.row()
        col = item.column()

        # Get universe ID for this row
        universe_id_item = self.universe_list.item(row, self.COL_UNIVERSE_ID)
        if not universe_id_item or not universe_id_item.text():
            return

        try:
            universe_id = int(universe_id_item.text())
            if universe_id not in self.config.universes:
                return

            params = self.config.universes[universe_id].output['parameters']

            # Update the specific parameter based on column
            if col == self.COL_IP_ADDRESS:
                params['ip'] = item.text()
            elif col == self.COL_PORT:
                params['port'] = item.text()
            elif col == self.COL_SUBNET:
                params['subnet'] = item.text()
            elif col == self.COL_ARTNET_UNIVERSE:
                params['universe'] = item.text()
                # Update multicast IP if E1.31 multicast is enabled
                protocol_combo = self.universe_list.cellWidget(row, self.COL_OUTPUT_TYPE)
                if protocol_combo and protocol_combo.currentText() == "E1.31":
                    multicast_widget = self.universe_list.cellWidget(row, self.COL_MULTICAST)
                    if multicast_widget:
                        checkbox = multicast_widget.findChild(QtWidgets.QCheckBox)
                        if checkbox and checkbox.isChecked():
                            universe_num = int(item.text()) if item.text() else 1
                            multicast_ip = f"239.255.{universe_num >> 8}.{universe_num & 0xFF}"
                            ip_item = self.universe_list.item(row, self.COL_IP_ADDRESS)
                            if ip_item:
                                self.universe_list.blockSignals(True)
                                ip_item.setText(multicast_ip)
                                params['ip'] = multicast_ip
                                self.universe_list.blockSignals(False)

        except (ValueError, AttributeError) as e:
            print(f"Error updating universe config: {e}")
