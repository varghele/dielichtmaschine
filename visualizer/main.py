# visualizer/main.py
# Die Lichtmaschine - standalone 3D visualizer entry point
#
# Real-time 3D visualization of lighting effects.
# - Receives configuration via TCP from Die Lichtmaschine
# - Receives DMX data via ArtNet from Die Lichtmaschine or QLC+
#
# The window frame wears the brand (dark theme tokens, Barlow/IBM Plex
# Mono, rotor glyph + wordmark header, token-driven status colors);
# the GL scene itself is renderer territory.

import sys
import os

# Add parent directory to path for shared module imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QStatusBar, QPushButton, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QIcon, QPixmap

# Import shared modules from Die Lichtmaschine
from utils.app_identity import APP_NAME, APP_WORDMARK, app_icon_path

# Import visualizer modules
from visualizer.tcp import VisualizerTCPClient
from visualizer.artnet import ArtNetListener
from visualizer.renderer import RenderEngine
from visualizer.build_mode import build_mode_buffers


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
        self.setWindowTitle(f"{APP_NAME} · Visualizer")
        self.setMinimumSize(1024, 768)

        # Theme tokens for the status colors (the QSS handles the
        # chrome; per-state label colors are set inline from the same
        # token dict, never hardcoded hex).
        from gui.theme_manager import ThemeManager
        from gui.theme_tokens import THEMES
        theme_name = ThemeManager().current() or "dark"
        self._tokens = THEMES.get(theme_name, THEMES["dark"])

        # Configuration state (received via TCP)
        self.stage_width: float = 10.0  # meters
        self.stage_height: float = 8.0  # meters
        self.fixtures: list = []
        self.groups: dict = {}

        # Connection state
        self.tcp_connected: bool = False
        self.artnet_receiving: bool = False

        # BUILD look: synthesise a full-on buffer from the received rig
        # (dimmer up, shutter open, pan/tilt centred) so orientation and
        # beam direction can be checked without live DMX. While on, live
        # DMX is ignored.
        self.build_mode: bool = False

        # TCP client for receiving configuration
        self.tcp_client = VisualizerTCPClient()
        self._connect_tcp_signals()

        # ArtNet listener for receiving DMX data
        self.artnet_listener = ArtNetListener()
        self._connect_artnet_signals()
        self.artnet_listener.start()

        # Initialize UI (the header owns connect_btn, which the
        # statusbar's indicator update touches - build order matters)
        self._init_ui()
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
        if self.build_mode:
            return  # BUILD look owns the frame; live DMX is ignored
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
        """Initialize the main UI layout: brand header over the 3D
        viewport."""
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header())

        # 3D render engine
        self.render_engine = RenderEngine(self)
        self.render_engine.set_stage_size(self.stage_width, self.stage_height)
        layout.addWidget(self.render_engine, 1)

    def _build_header(self) -> QWidget:
        """The brand header (the main app's topbar anatomy): rotor
        glyph + wordmark + a VISUALIZER tag, then the window's three
        actions as chips. Replaces the stock QToolBar."""
        from gui.typography import MicroLabel, display_font, mono_font

        header = QWidget()
        header.setObjectName("TopBar")   # inherits the themed strip
        header.setFixedHeight(48)
        row = QHBoxLayout(header)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(8)

        glyph = QLabel()
        glyph.setObjectName("TopBarGlyph")
        pixmap = QPixmap(app_icon_path())
        if not pixmap.isNull():
            glyph.setPixmap(pixmap.scaled(
                22, 22, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        row.addWidget(glyph)

        wordmark = QLabel(APP_WORDMARK)
        wordmark.setObjectName("TopBarWordmark")
        wordmark.setFont(display_font(15, QFont.Weight.ExtraBold,
                                      tracking_em=0.08))
        row.addWidget(wordmark)

        tag = MicroLabel("Visualizer", point_size=8, tracking_em=0.18)
        row.addWidget(tag)

        row.addSpacing(16)

        def _chip(text: str, tip: str, slot=None) -> QPushButton:
            btn = QPushButton(text)
            btn.setProperty("role", "output-select")
            btn.setProperty("density", "compact")
            btn.setFont(mono_font(8, QFont.Weight.DemiBold))
            btn.setFixedHeight(22)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tip)
            if slot is not None:
                btn.clicked.connect(slot)
            row.addWidget(btn)
            return btn

        self.connect_btn = _chip(
            "CONNECT", f"Connect to {APP_NAME} (TCP port 9000)",
            self._on_connect_clicked)
        self.reset_view_btn = _chip(
            "RESET VIEW", "Reset camera to default position",
            self._on_reset_view)
        self.build_btn = _chip(
            "BUILD",
            "Light the whole rig with a synthetic look (dimmer up, "
            "shutter open, pan/tilt centred) to check orientation and "
            "beam direction. Live DMX is ignored while on.")
        # A mode toggle, not an action: checkable, wired via toggled so
        # setChecked() from code follows the same path as a click.
        self.build_btn.setCheckable(True)
        self.build_btn.toggled.connect(self._on_build_toggled)
        self.help_btn = _chip(
            "HELP", "How to feed DMX into the visualizer",
            self._on_help_clicked)

        row.addStretch(1)
        return header

    def _mono_status_label(self, text: str = "") -> QLabel:
        from gui.typography import mono_font
        label = QLabel(text)
        label.setFont(mono_font(8, tracking_em=0.08))
        return label

    def _separator(self) -> QLabel:
        label = self._mono_status_label("·")   # the brand separator
        label.setStyleSheet(f"color: {self._tokens['border']};")
        return label

    def _init_statusbar(self):
        """Initialize the status bar with connection indicators - mono
        caps, token-driven state colors, the brand separator."""
        self.statusbar = QStatusBar()
        self.statusbar.setSizeGripEnabled(False)
        self.setStatusBar(self.statusbar)

        # TCP connection status
        self.tcp_status_label = self._mono_status_label()
        self._update_tcp_indicator(False)
        self.statusbar.addWidget(self.tcp_status_label)

        self.statusbar.addWidget(self._separator())

        # ArtNet status
        self.artnet_status_label = self._mono_status_label()
        self._update_artnet_indicator(False)
        self.statusbar.addWidget(self.artnet_status_label)

        self.statusbar.addWidget(self._separator())

        # Stage info
        self.stage_info_label = self._mono_status_label()
        self._update_stage_info()
        self.statusbar.addWidget(self.stage_info_label)

        # FPS counter (right side)
        self.fps_label = self._mono_status_label("FPS --")
        self.fps_label.setStyleSheet(
            f"color: {self._tokens['text_secondary']};")
        self.statusbar.addPermanentWidget(self.fps_label)

        self.statusbar.addPermanentWidget(self._separator())

        # Fixture count (right side)
        self.fixture_count_label = self._mono_status_label("FIXTURES 0")
        self.statusbar.addPermanentWidget(self.fixture_count_label)

    def _update_tcp_indicator(self, connected: bool):
        """Update TCP connection indicator."""
        self.tcp_connected = connected
        if connected:
            self.tcp_status_label.setText("TCP CONNECTED")
            self.tcp_status_label.setStyleSheet(
                f"color: {self._tokens['success']}; font-weight: bold;")
            self.connect_btn.setText("DISCONNECT")
        else:
            self.tcp_status_label.setText("TCP OFFLINE")
            self.tcp_status_label.setStyleSheet(
                f"color: {self._tokens['destructive']};")
            self.connect_btn.setText("CONNECT")

    def _update_artnet_indicator(self, receiving: bool):
        """Update ArtNet receiving indicator."""
        self.artnet_receiving = receiving
        if receiving:
            self.artnet_status_label.setText("ARTNET RECEIVING")
            self.artnet_status_label.setStyleSheet(
                f"color: {self._tokens['success']}; font-weight: bold;")
        else:
            self.artnet_status_label.setText("ARTNET NO DATA")
            self.artnet_status_label.setStyleSheet(
                f"color: {self._tokens['text_disabled']};")

    def _update_stage_info(self):
        """Update stage dimensions display."""
        self.stage_info_label.setText(
            f"STAGE {self.stage_width:.1f} x {self.stage_height:.1f} m")

    def _update_fixture_count(self):
        """Update fixture count display."""
        self.fixture_count_label.setText(f"FIXTURES {len(self.fixtures)}")

    def _update_status(self):
        """Periodic status update (called by timer)."""
        # Update FPS display
        if hasattr(self, 'render_engine') and self.render_engine:
            fps = self.render_engine.get_fps()
            self.fps_label.setText(f"FPS {fps:.0f}")

    def _on_connect_clicked(self):
        """Handle connect/disconnect button click."""
        if self.tcp_connected:
            print(f"Disconnecting from {APP_NAME}...")
            self.tcp_client.disconnect()
        else:
            print(f"Connecting to {APP_NAME} at "
                  f"{self.tcp_client.host}:{self.tcp_client.port}...")
            self.tcp_client.connect()

    def _on_reset_view(self):
        """Reset camera to default position."""
        if hasattr(self, 'render_engine') and self.render_engine:
            self.render_engine.reset_camera()
            print("Camera reset to default position")

    def _on_build_toggled(self, checked: bool):
        """BUILD chip: synthesise a full-on rig look, or return to live.

        Off pushes zeroed buffers for the universes the look filled, so
        the view goes back to reality (dark until DMX arrives) instead
        of freezing the synthetic frame."""
        self.build_mode = checked
        if checked:
            self._push_build_look()
            print("BUILD look on (live DMX ignored)")
        else:
            engine = getattr(self, 'render_engine', None)
            if engine:
                for universe in build_mode_buffers(self.fixtures):
                    engine.update_dmx(universe, bytes(512))
            print("BUILD look off (live DMX)")

    def _push_build_look(self):
        """Push the synthetic build-look buffers for the current rig."""
        engine = getattr(self, 'render_engine', None)
        if not engine:
            return
        for universe, buffer in build_mode_buffers(self.fixtures).items():
            engine.update_dmx(universe, buffer)

    def _on_help_clicked(self):
        """Show help dialog for feeding DMX into the visualizer."""
        QMessageBox.information(
            self,
            "Feeding the visualizer",
            f"From {APP_NAME}: use the topbar's VISUALIZER button - it\n"
            "starts the TCP feed (rig + stage data on port 9000) and\n"
            "this window connects on CONNECT. DMX arrives via ArtNet\n"
            "whenever OUTPUT is enabled there.\n\n"
            "From QLC+ (or any ArtNet source):\n"
            "1. Open the Input/Output settings\n"
            "2. Select an available universe\n"
            "3. Enable ArtNet output for that universe\n"
            "4. Set the output address to 255.255.255.255\n"
            "5. DMX is received on port 6454 (standard ArtNet)\n\n"
            "The bottom bar reads ARTNET RECEIVING once data\n"
            "is coming through."
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

        # A rig update while the BUILD look is on refreshes the look so
        # newly patched fixtures light immediately.
        if self.build_mode:
            self._push_build_look()

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
        if self.build_mode:
            return  # BUILD look owns the frame; live DMX is ignored
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
        print(f"{APP_NAME} Visualizer starting...")

        # Create application
        app = QApplication(sys.argv)
        app.setApplicationName(f"{APP_NAME} Visualizer")

        # Brand boot, same order as the main app (main.py): fonts
        # before any widget so the stylesheet families resolve on
        # first paint, then the icon, then the persisted theme.
        from gui.fonts import register_brand_fonts
        register_brand_fonts()

        icon_path = app_icon_path()
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))

        from gui.theme_manager import ThemeManager
        theme_manager = ThemeManager()
        theme_manager.apply(app, theme_manager.current() or "dark")

        # Create and show main window
        window = VisualizerWindow()
        window.show()

        print("Visualizer window opened")
        print(f"  - TCP client ready (CONNECT links with {APP_NAME})")
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
