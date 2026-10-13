# visualizer/tcp/client.py
# TCP client for receiving configuration from Show Creator

import socket
import threading
import json
from typing import Optional, Dict, Any, List

from PyQt6.QtCore import QObject, pyqtSignal


class VisualizerTCPClient(QObject):
    """
    TCP client for receiving stage/fixture configuration from Show Creator.

    Connects to Show Creator's TCP server and receives:
    - Stage dimensions
    - Fixture list with positions and DMX addresses
    - Fixture groups
    - Configuration updates

    Runs in a background thread to avoid blocking the UI.
    """

    # Signals for UI updates (emitted on main thread via Qt's signal mechanism)
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    connection_error = pyqtSignal(str)

    # Configuration signals
    stage_received = pyqtSignal(float, float, float)  # width, height, grid_size
    fixtures_received = pyqtSignal(list)  # list of fixture dicts
    groups_received = pyqtSignal(list)  # list of group dicts
    update_received = pyqtSignal(str, dict)  # update_type, data

    # Default connection settings
    DEFAULT_HOST = "localhost"
    DEFAULT_PORT = 9000
    BUFFER_SIZE = 4096
    RECONNECT_DELAY = 5.0  # seconds

    def __init__(self, host: str = None, port: int = None):
        """
        Initialize TCP client.

        Args:
            host: Server hostname (default: localhost)
            port: Server port (default: 9000)
        """
        super().__init__()

        self.host = host or self.DEFAULT_HOST
        self.port = port or self.DEFAULT_PORT

        self.socket: Optional[socket.socket] = None
        self.receive_thread: Optional[threading.Thread] = None
        self.running = False
        self.is_connected = False

        # Connection bookkeeping shared with the receive thread. Every
        # connect()/disconnect() bumps the generation; a receive loop
        # only touches the shared state (socket, is_connected, the
        # disconnected signal) while its generation is current, so a
        # loop still winding down after disconnect() can never close or
        # disown the NEXT connection's socket.
        self._state_lock = threading.Lock()
        self._generation = 0

        # Buffer for incomplete messages
        self.buffer = ""

        # Stored configuration
        self.stage_width: float = 10.0
        self.stage_height: float = 8.0
        self.grid_size: float = 0.5
        self.fixtures: List[Dict] = []
        self.groups: List[Dict] = []

    def connect(self) -> bool:
        """
        Connect to Show Creator TCP server.

        Returns:
            True if connection initiated, False if already connected
        """
        with self._state_lock:
            if self.is_connected:
                return False
            self._generation += 1
            generation = self._generation
            self.running = True
            self.buffer = ""
        self.receive_thread = threading.Thread(
            target=self._receive_loop, args=(generation,), daemon=True)
        self.receive_thread.start()
        return True

    def disconnect(self):
        """Disconnect from server."""
        with self._state_lock:
            self.running = False
            self._generation += 1
            sock, self.socket = self.socket, None
            was_connected = self.is_connected
            self.is_connected = False

        if sock is not None:
            # shutdown() wakes the receive thread out of recv(); it then
            # finds its generation retired and exits without side effects.
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

        if was_connected:
            self.disconnected.emit()

    def _is_current(self, generation: int) -> bool:
        return self.running and generation == self._generation

    def _receive_loop(self, generation: Optional[int] = None):
        """Background thread: connect and receive messages.

        Works on its OWN socket object: disconnect() nulls ``self.socket``
        from the UI thread, so the loop never reads it back."""
        if generation is None:
            generation = self._generation
        sock = None
        try:
            # Create socket and connect
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            with self._state_lock:
                if not self._is_current(generation):
                    return   # disconnected before we even started
                self.socket = sock
            sock.settimeout(5.0)  # Connection timeout

            print(f"Connecting to {self.host}:{self.port}...")
            sock.connect((self.host, self.port))

            with self._state_lock:
                if not self._is_current(generation):
                    return   # disconnected while connecting
                self.is_connected = True
            sock.settimeout(None)  # No timeout for receiving
            self.connected.emit()
            print(f"Connected to Show Creator at {self.host}:{self.port}")

            # Receive loop
            while self._is_current(generation):
                try:
                    data = sock.recv(self.BUFFER_SIZE)
                    if not data:
                        # Server closed connection
                        print("Server closed connection")
                        break
                    if not self._is_current(generation):
                        break   # retired mid-recv: the buffer is not ours

                    # Decode and add to buffer
                    self.buffer += data.decode('utf-8')

                    # Process complete messages (newline-delimited)
                    self._process_buffer()

                except socket.timeout:
                    continue
                except ConnectionResetError:
                    print("Connection reset by server")
                    break
                except OSError as e:
                    if self._is_current(generation):
                        print(f"Socket error: {e}")
                    break

        except socket.timeout:
            error_msg = f"Connection timeout: {self.host}:{self.port}"
            print(error_msg)
            if self._is_current(generation):
                self.connection_error.emit(error_msg)

        except ConnectionRefusedError:
            error_msg = f"Connection refused: {self.host}:{self.port}"
            print(error_msg)
            if self._is_current(generation):
                self.connection_error.emit(error_msg)

        except OSError as e:
            error_msg = f"Connection error: {e}"
            print(error_msg)
            if self._is_current(generation):
                self.connection_error.emit(error_msg)

        finally:
            # Only the CURRENT connection's loop owns the shared state; a
            # retired loop (disconnect() already reset it, maybe a new
            # connection is up) just closes its own socket.
            with self._state_lock:
                current = generation == self._generation
                was_connected = current and self.is_connected
                if current:
                    self.is_connected = False
                    if self.socket is sock:
                        self.socket = None
            if was_connected:
                self.disconnected.emit()

            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    def _process_buffer(self):
        """Process complete messages from buffer."""
        while '\n' in self.buffer:
            # Split at first newline
            line, self.buffer = self.buffer.split('\n', 1)
            line = line.strip()

            if not line:
                continue

            try:
                message = json.loads(line)
                self._handle_message(message)
            except json.JSONDecodeError as e:
                print(f"Invalid JSON: {e}")

    def _handle_message(self, message: Dict[str, Any]):
        """
        Handle incoming message based on type.

        Args:
            message: Parsed JSON message
        """
        msg_type = message.get('type', '')

        if msg_type == 'stage':
            self._handle_stage(message)

        elif msg_type == 'fixtures':
            self._handle_fixtures(message)

        elif msg_type == 'groups':
            self._handle_groups(message)

        elif msg_type == 'update':
            self._handle_update(message)

        elif msg_type == 'heartbeat':
            # Heartbeat - just acknowledge silently
            pass

        else:
            print(f"Unknown message type: {msg_type}")

    def _handle_stage(self, message: Dict[str, Any]):
        """Handle stage dimensions message."""
        self.stage_width = message.get('width', 10.0)
        self.stage_height = message.get('height', 8.0)
        self.grid_size = message.get('grid_size', 0.5)

        print(f"Stage: {self.stage_width}m x {self.stage_height}m (grid: {self.grid_size}m)")
        self.stage_received.emit(self.stage_width, self.stage_height, self.grid_size)

    def _handle_fixtures(self, message: Dict[str, Any]):
        """Handle fixtures list message."""
        self.fixtures = message.get('fixtures', [])

        print(f"Fixtures: {len(self.fixtures)} received")
        for i, fixture in enumerate(self.fixtures[:3]):  # Show first 3
            name = fixture.get('name', 'Unknown')
            pos = fixture.get('position', {})
            print(f"  [{i+1}] {name} at ({pos.get('x', 0)}, {pos.get('y', 0)}, {pos.get('z', 0)})")
        if len(self.fixtures) > 3:
            print(f"  ... and {len(self.fixtures) - 3} more")

        self.fixtures_received.emit(self.fixtures)

    def _handle_groups(self, message: Dict[str, Any]):
        """Handle groups list message."""
        self.groups = message.get('groups', [])

        print(f"Groups: {len(self.groups)} received")
        for group in self.groups[:3]:
            name = group.get('name', 'Unknown')
            color = group.get('color', '#808080')
            fixtures = group.get('fixtures', [])
            print(f"  - {name} ({color}): {len(fixtures)} fixtures")
        if len(self.groups) > 3:
            print(f"  ... and {len(self.groups) - 3} more")

        self.groups_received.emit(self.groups)

    def _handle_update(self, message: Dict[str, Any]):
        """Handle configuration update message."""
        update_type = message.get('update_type', '')
        data = message.get('data', {})

        print(f"Update: {update_type}")
        self.update_received.emit(update_type, data)

    def set_host(self, host: str):
        """Set server hostname."""
        self.host = host

    def set_port(self, port: int):
        """Set server port."""
        self.port = port

    def get_fixtures(self) -> List[Dict]:
        """Get stored fixtures list."""
        return self.fixtures

    def get_groups(self) -> List[Dict]:
        """Get stored groups list."""
        return self.groups

    def get_stage_dimensions(self) -> tuple:
        """Get stored stage dimensions."""
        return (self.stage_width, self.stage_height)
