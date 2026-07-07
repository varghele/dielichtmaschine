# visualizer/main.py
# QLC+ Show Creator - 3D Visualizer Entry Point
#
# Real-time 3D visualization of lighting effects.
# - Receives configuration via TCP from Show Creator
# - Receives DMX data via ArtNet from Show Creator or QLC+

import sys
import os

# Add parent directory to path for shared module imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QStatusBar, QToolBar, QPushButton, QFrame, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction

# Import shared modules from Show Creator
from config.models import Configuration, Fixture, FixtureGroup
from utils.fixture_utils import determine_fixture_type

# Import visualizer modules
from visualizer.tcp import VisualizerTCPClient
from visualizer.artnet import ArtNetListener
from visualizer.renderer import RenderEngine


class VisualizerWindow(QMainWindow):
    """
    Main window for the QLC+ Show Creator Visualizer.

    Provides 3D visualization of lighting effects by:
    - Receiving stage/fixture configuration via TCP
    - Receiving DMX data via ArtNet
    - Rendering fixtures and volumetric beams
    """

    def __init__(self):
        super().__init__()
        from utils.app_identity import APP_NAME
        self.setWindowTitle(f"{APP_NAME} · Visualizer")
        self.setMinimumSize(1024, 768)

        # Configuration state (received via TCP)
        self.stage_width: float = 10.0  # meters
        self.stage_height: float = 8.0  # meters
        self.fixtures: list = []
        self.groups: dict = {}

        # Connection state
        self.tcp_connected: bool = False
        self.artnet_receiving: bool = False

        # TCP client for receiving configuration
        self.tcp_client = VisualizerTCPClient()
        self._connect_tcp_signals()

        # ArtNet listener for receiving DMX data
        self.artnet_listener = ArtNetListener()
        self._connect_artnet_signals()
        self.artnet_listener.start()

        # Initialize UI (toolbar must be before statusbar due to connect_action reference)
        self._init_ui()
        self._init_toolbar()
        self._init_statusbar()

        # Status update timer
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(1000)  # Update every second

    def _connect_tcp_signals(self):
        """Connect TCP client signals to UI handlers."""
        self.tcp_client.connected.connect(self._on_tcp_connected)
        self.tcp_client.disconnected.connect(self._on_tcp_disconnected)
        self.tcp_client.connection_error.connect(self._on_tcp_error)
        self.tcp_client.stage_received.connect(self.set_stage_dimensions)
        self.tcp_client.fixtures_received.connect(self.set_fixtures)
        self.tcp_client.groups_received.connect(self.set_groups)
        self.tcp_client.update_received.connect(self._on_config_update)

    def _connect_artnet_signals(self):
        """Connect ArtNet listener signals to UI handlers."""
        self.artnet_listener.dmx_received.connect(self._on_dmx_received)
        self.artnet_listener.receiving_started.connect(self._on_artnet_started)
        self.artnet_listener.receiving_stopped.connect(self._on_artnet_stopped)
        self.artnet_listener.error_occurred.connect(self._on_artnet_error)

    def _on_dmx_received(self, universe: int, dmx_data: bytes):
        """Handle DMX data received from ArtNet."""
        # Convert 0-based ArtNet universe to 1-based internal universe
        internal_universe = universe + 1
        # Update render engine with DMX data
        if hasattr(self, 'render_engine') and self.render_engine:
            self.render_engine.update_dmx(internal_universe, dmx_data)

    def _on_artnet_started(self):
        """Handle ArtNet receiving started."""
        self._update_artnet_indicator(True)
        print("ArtNet: Receiving DMX data")

    def _on_artnet_stopped(self):
        """Handle ArtNet receiving stopped."""
        self._update_artnet_indicator(False)
        print("ArtNet: No longer receiving DMX data")

    def _on_artnet_error(self, error_msg: str):
        """Handle ArtNet error."""
        print(f"ArtNet error: {error_msg}")
        self.statusbar.showMessage(f"ArtNet error: {error_msg}", 5000)

    def _on_tcp_connected(self):
        """Handle TCP connected event."""
        self._update_tcp_indicator(True)
        print("TCP connected to Show Creator")

    def _on_tcp_disconnected(self):
        """Handle TCP disconnected event."""
        self._update_tcp_indicator(False)
        print("TCP disconnected from Show Creator")

    def _on_tcp_error(self, error_msg: str):
        """Handle TCP connection error."""
        self._update_tcp_indicator(False)
        self.statusbar.showMessage(f"Connection error: {error_msg}", 5000)

    def _on_config_update(self, update_type: str, data: dict):
        """Handle configuration update from Show Creator."""
        print(f"Config update received: {update_type}")
        # Re-request full config on update
        # (The server will send new stage/fixtures/groups messages)

    def _init_ui(self):
        """Initialize the main UI layout."""
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # 3D render engine
        self.render_engine = RenderEngine(self)
        self.render_engine.set_stage_size(self.stage_width, self.stage_height)
        layout.addWidget(self.render_engine)

    def _init_statusbar(self):
        """Initialize the status bar with connection indicators."""
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)

        # TCP connection status
        self.tcp_status_label = QLabel()
        self._update_tcp_indicator(False)
        self.statusbar.addWidget(self.tcp_status_label)

        # Separator
        separator1 = QLabel(" | ")
        separator1.setStyleSheet("color: #666;")
        self.statusbar.addWidget(separator1)

        # ArtNet status
        self.artnet_status_label = QLabel()
        self._update_artnet_indicator(False)
        self.statusbar.addWidget(artnet_label := QLabel("ArtNet: "))
        self.statusbar.addWidget(self.artnet_status_label)

        # Separator
        separator2 = QLabel(" | ")
        separator2.setStyleSheet("color: #666;")
        self.statusbar.addWidget(separator2)

        # Stage info
        self.stage_info_label = QLabel()
        self._update_stage_info()
        self.statusbar.addWidget(self.stage_info_label)

        # FPS counter (right side)
        self.fps_label = QLabel("FPS: --")
        self.fps_label.setStyleSheet("color: #888;")
        self.statusbar.addPermanentWidget(self.fps_label)

        # Separator
        separator3 = QLabel(" | ")
        separator3.setStyleSheet("color: #666;")
        self.statusbar.addPermanentWidget(separator3)

        # Fixture count (right side)
        self.fixture_count_label = QLabel("Fixtures: 0")
        self.statusbar.addPermanentWidget(self.fixture_count_label)

    def _init_toolbar(self):
        """Initialize the toolbar."""
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # Connect button
        self.connect_action = QAction("Connect", self)
        self.connect_action.setToolTip("Connect to Show Creator (TCP port 9000)")
        self.connect_action.triggered.connect(self._on_connect_clicked)
        toolbar.addAction(self.connect_action)

        toolbar.addSeparator()

        # Reset view button
        self.reset_view_action = QAction("Reset View", self)
        self.reset_view_action.setToolTip("Reset camera to default position")
        self.reset_view_action.triggered.connect(self._on_reset_view)
        toolbar.addAction(self.reset_view_action)

        toolbar.addSeparator()

        # Help button
        self.help_action = QAction("Help", self)
        self.help_action.setToolTip("How to connect QLC+ to the Visualizer")
        self.help_action.triggered.connect(self._on_help_clicked)
        toolbar.addAction(self.help_action)

    def _update_tcp_indicator(self, connected: bool):
        """Update TCP connection indicator."""
        self.tcp_connected = connected
        if connected:
            self.tcp_status_label.setText("TCP: Connected")
            self.tcp_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            self.connect_action.setText("Disconnect")
        else:
            self.tcp_status_label.setText("TCP: Disconnected")
            self.tcp_status_label.setStyleSheet("color: #f44336;")
            self.connect_action.setText("Connect")

    def _update_artnet_indicator(self, receiving: bool):
        """Update ArtNet receiving indicator."""
        self.artnet_receiving = receiving
        if receiving:
            self.artnet_status_label.setText("Receiving")
            self.artnet_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        else:
            self.artnet_status_label.setText("No Data")
            self.artnet_status_label.setStyleSheet("color: #666;")

    def _update_stage_info(self):
        """Update stage dimensions display."""
        self.stage_info_label.setText(f"Stage: {self.stage_width:.1f}m x {self.stage_height:.1f}m")

    def _update_fixture_count(self):
        """Update fixture count display."""
        self.fixture_count_label.setText(f"Fixtures: {len(self.fixtures)}")

    def _update_status(self):
        """Periodic status update (called by timer)."""
        # Update FPS display
        if hasattr(self, 'render_engine') and self.render_engine:
            fps = self.render_engine.get_fps()
            self.fps_label.setText(f"FPS: {fps:.0f}")

    def _on_connect_clicked(self):
        """Handle connect/disconnect button click."""
        if self.tcp_connected:
            print("Disconnecting from Show Creator...")
            self.tcp_client.disconnect()
        else:
            print(f"Connecting to Show Creator at {self.tcp_client.host}:{self.tcp_client.port}...")
            self.tcp_client.connect()

    def _on_reset_view(self):
        """Reset camera to default position."""
        if hasattr(self, 'render_engine') and self.render_engine:
            self.render_engine.reset_camera()
            print("Camera reset to default position")

    def _on_help_clicked(self):
        """Show help dialog for connecting QLC+ to the Visualizer."""
        QMessageBox.information(
            self,
            "Connecting QLC+ to the Visualizer",
            "To send DMX data from QLC+ to this Visualizer:\n\n"
            "1. Open QLC+ and go to the Input/Output settings\n"
            "2. Select an available universe\n"
            "3. Enable ArtNet output for that universe\n"
            "4. Set the output address to 255.255.255.255\n"
            "5. The Visualizer will automatically receive DMX data\n"
            "   on port 6454 (standard ArtNet port)\n\n"
            "The ArtNet status in the bottom bar will show\n"
            "\"Receiving\" once data is coming through."
        )

    # --- Configuration Handling (will be called by TCP client in Phase V2) ---

    def set_stage_dimensions(self, width: float, height: float, grid_size: float = 0.5):
        """
        Set stage dimensions from TCP message.

        Args:
            width: Stage width in meters
            height: Stage height in meters
            grid_size: Grid spacing in meters
        """
        self.stage_width = width
        self.stage_height = height
        self._update_stage_info()

        # Update renderer stage size and grid
        if hasattr(self, 'render_engine') and self.render_engine:
            self.render_engine.set_stage_size(width, height)
            self.render_engine.set_grid_size(grid_size)

        print(f"Stage dimensions updated: {width}m x {height}m (grid: {grid_size}m)")

    def set_fixtures(self, fixtures_data: list):
        """
        Set fixtures from TCP message.

        Args:
            fixtures_data: List of fixture dictionaries from protocol
        """
        self.fixtures = fixtures_data
        self._update_fixture_count()

        # Update render engine with fixtures
        if hasattr(self, 'render_engine') and self.render_engine:
            self.render_engine.update_fixtures(fixtures_data)

        print(f"Loaded {len(fixtures_data)} fixtures")

    def set_groups(self, groups_data: list):
        """
        Set groups from TCP message.

        Args:
            groups_data: List of group dictionaries from protocol
        """
        self.groups = {g['name']: g for g in groups_data}
        print(f"Loaded {len(groups_data)} groups")

    # --- DMX Handling ---

    def update_dmx(self, universe: int, channels: bytes):
        """
        Update DMX values from ArtNet packet.

        Args:
            universe: DMX universe number
            channels: 512 bytes of DMX channel data
        """
        # Update render engine with DMX data
        if hasattr(self, 'render_engine') and self.render_engine:
            self.render_engine.update_dmx(universe, channels)
        self._update_artnet_indicator(True)

    def closeEvent(self, event):
        """Clean up on window close."""
        print("Closing Visualizer...")
        self.status_timer.stop()

        # Disconnect TCP client
        if self.tcp_client:
            self.tcp_client.disconnect()

        # Stop ArtNet listener
        if self.artnet_listener:
            self.artnet_listener.stop()

        # Cleanup renderer
        if hasattr(self, 'render_engine') and self.render_engine:
            self.render_engine.cleanup()

        event.accept()


def main():
    """Entry point for the Visualizer application."""
    try:
        # Verify shared module imports work
        print("Lichtmaschine Visualizer starting...")
        print(f"  - Shared modules imported successfully")
        print(f"  - Configuration model: {Configuration.__name__}")
        print(f"  - Fixture model: {Fixture.__name__}")
        print(f"  - fixture_utils: determine_fixture_type available")

        # Create application
        app = QApplication(sys.argv)
        app.setApplicationName("Lichtmaschine Visualizer")

        # Create and show main window
        window = VisualizerWindow()
        window.show()

        print("Visualizer window opened")
        print("  - TCP client ready (click Connect to link with Show Creator)")
        print("  - ArtNet listener active on port 6454")
        print("  - 3D renderer active (use mouse to orbit/pan/zoom)")
        print("  - Camera controls: Left=Orbit, Right=Pan, Scroll=Zoom, Home=Reset")

        sys.exit(app.exec())

    except Exception as e:
        print(f"Error starting Visualizer: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
