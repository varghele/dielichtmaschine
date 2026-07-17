# visualizer/artnet/listener.py
# ArtNet UDP listener for receiving DMX data

import socket
import struct
import threading
import time
from typing import Dict, Optional, Callable

from PyQt6.QtCore import QObject, pyqtSignal


class ArtNetListener(QObject):
    """
    Listens for ArtNet OpDmx packets and stores DMX values.

    Receives DMX data from Show Creator or QLC+ via ArtNet protocol.
    Runs in a background thread to avoid blocking the UI.

    ArtNet OpDmx Packet Format:
    - Bytes 0-7: "Art-Net\0" (header)
    - Bytes 8-9: OpCode 0x5000 (little-endian)
    - Bytes 10-11: Protocol version (big-endian)
    - Byte 12: Sequence counter
    - Byte 13: Physical port
    - Bytes 14-15: Universe (little-endian, 15-bit)
    - Bytes 16-17: DMX data length (big-endian)
    - Bytes 18+: DMX data (up to 512 bytes)
    """

    # Qt signals for thread-safe UI updates
    dmx_received = pyqtSignal(int, bytes)  # universe, dmx_data (512 bytes)
    receiving_started = pyqtSignal()
    receiving_stopped = pyqtSignal()
    error_occurred = pyqtSignal(str)

    # ArtNet constants
    ARTNET_HEADER = b'Art-Net\x00'
    ARTNET_OPCODE_DMX = 0x5000
    ARTNET_PORT = 6454
    BUFFER_SIZE = 1024  # Max ArtNet packet is ~530 bytes

    # Timeout for "receiving" status (seconds)
    RECEIVE_TIMEOUT = 2.0

    # Per-universe source lock: how long the locked sender may stay
    # silent before another source can take the universe over.
    SOURCE_FAILOVER_S = 1.5

    def __init__(self, port: int = ARTNET_PORT, universes: list = None):
        """
        Initialize ArtNet listener.

        Args:
            port: UDP port to listen on (default: 6454)
            universes: List of universe numbers to accept (None = all)
        """
        super().__init__()

        self.port = port
        self.universes = universes  # None means accept all

        self.socket: Optional[socket.socket] = None
        self.listen_thread: Optional[threading.Thread] = None
        self.running = False
        self.is_receiving = False

        # DMX data storage - thread-safe via lock
        self.dmx_lock = threading.Lock()
        self.dmx_data: Dict[int, bytes] = {}  # universe -> 512 bytes

        # Last receive time per universe
        self.last_receive_time: Dict[int, float] = {}

        # Packet statistics
        self.packets_received = 0
        self.packets_invalid = 0
        # Frames dropped because another source holds the universe.
        self.packets_foreign = 0

        # Per-universe SOURCE LOCK: universe -> (source ip, last time).
        # The arbiter sends every universe TWICE on one machine when
        # its primary target is broadcast: the yoke-converted hardware
        # frame (broadcast, received locally too) and the solver-frame
        # loopback mirror. Rendering whichever packet arrived last
        # flipped every mover between two poses at 44 Hz - the
        # "twitching heads at idle" bug (2026-07-17). One universe
        # therefore renders ONE sender: loopback wins when present
        # (the mirror is the authoritative solver-convention feed for
        # a local viewer - this viewer converts the yoke itself), any
        # other source is first-come and only replaced after
        # SOURCE_FAILOVER_S of silence.
        self.source_lock: Dict[int, tuple] = {}

    def start(self) -> bool:
        """
        Start listening for ArtNet packets.

        Returns:
            True if started successfully, False on error
        """
        if self.running:
            return True

        try:
            # Create UDP socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # Bind to all interfaces
            self.socket.bind(('0.0.0.0', self.port))
            self.socket.settimeout(0.5)  # Allow periodic checks

            self.running = True

            # Start listener thread
            self.listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.listen_thread.start()

            print(f"ArtNet listener started on port {self.port}")
            return True

        except OSError as e:
            error_msg = f"Failed to start ArtNet listener: {e}"
            print(error_msg)
            self.error_occurred.emit(error_msg)
            return False

    def stop(self):
        """Stop listening for ArtNet packets."""
        self.running = False

        if self.socket:
            try:
                self.socket.close()
            except OSError:
                pass
            self.socket = None

        if self.listen_thread:
            self.listen_thread.join(timeout=1.0)
            self.listen_thread = None

        if self.is_receiving:
            self.is_receiving = False
            self.receiving_stopped.emit()

        print("ArtNet listener stopped")

    def _listen_loop(self):
        """Background thread: receive and parse ArtNet packets."""
        while self.running:
            try:
                data, addr = self.socket.recvfrom(self.BUFFER_SIZE)
                self._process_packet(data, addr)

            except socket.timeout:
                # Check if we've stopped receiving
                self._check_receive_timeout()
                continue

            except OSError:
                if self.running:
                    break

    @staticmethod
    def _is_loopback(ip: str) -> bool:
        return ip.startswith("127.") or ip == "::1"

    def _accept_source(self, universe: int, addr: tuple) -> bool:
        """Whether this packet's sender may drive ``universe``.

        Lock rules: the locked sender always may; a loopback sender
        takes the lock from a non-loopback one immediately (the local
        mirror outranks the broadcast hardware frame); anyone else
        takes over only after the locked sender has been silent for
        SOURCE_FAILOVER_S (so a viewer keeps following QLC+ or a
        remote desk when the local feed stops).
        """
        source_ip = addr[0] if addr else ""
        now = time.time()
        locked = self.source_lock.get(universe)
        if locked is not None:
            locked_ip, locked_time = locked
            if source_ip != locked_ip:
                loopback_takeover = (self._is_loopback(source_ip)
                                     and not self._is_loopback(locked_ip))
                if not loopback_takeover \
                        and now - locked_time <= self.SOURCE_FAILOVER_S:
                    return False
        self.source_lock[universe] = (source_ip, now)
        return True

    def _process_packet(self, data: bytes, addr: tuple):
        """
        Process received ArtNet packet.

        Args:
            data: Raw packet data
            addr: Source address (ip, port)
        """
        # Minimum packet size: header(8) + opcode(2) + version(2) + seq(1) + phys(1) + universe(2) + length(2) + data(1) = 19
        if len(data) < 19:
            self.packets_invalid += 1
            return

        # Check header
        if data[:8] != self.ARTNET_HEADER:
            self.packets_invalid += 1
            return

        # Check opcode (little-endian)
        opcode = struct.unpack('<H', data[8:10])[0]
        if opcode != self.ARTNET_OPCODE_DMX:
            # Not an OpDmx packet - ignore silently
            return

        # Parse universe (little-endian, bytes 14-15)
        universe = struct.unpack('<H', data[14:16])[0] & 0x7FFF

        # Filter by universe if configured
        if self.universes is not None and universe not in self.universes:
            return

        # Source lock (see __init__): one sender per universe.
        if not self._accept_source(universe, addr):
            self.packets_foreign += 1
            return

        # Parse DMX data length (big-endian, bytes 16-17)
        dmx_length = struct.unpack('>H', data[16:18])[0]

        # Extract DMX data (bytes 18+)
        dmx_data = data[18:18 + dmx_length]

        # Pad to 512 bytes if needed
        if len(dmx_data) < 512:
            dmx_data = dmx_data + bytes(512 - len(dmx_data))
        elif len(dmx_data) > 512:
            dmx_data = dmx_data[:512]

        # Store DMX data (thread-safe)
        with self.dmx_lock:
            self.dmx_data[universe] = dmx_data

        # Update receive time
        current_time = time.time()
        self.last_receive_time[universe] = current_time
        self.packets_received += 1

        # Update receiving status
        if not self.is_receiving:
            self.is_receiving = True
            self.receiving_started.emit()

        # Emit signal for UI update
        self.dmx_received.emit(universe, dmx_data)

    def _check_receive_timeout(self):
        """Check if we've stopped receiving packets."""
        if not self.is_receiving:
            return

        current_time = time.time()
        any_recent = False

        for universe, last_time in self.last_receive_time.items():
            if current_time - last_time < self.RECEIVE_TIMEOUT:
                any_recent = True
                break

        if not any_recent:
            self.is_receiving = False
            self.receiving_stopped.emit()

    def get_dmx(self, universe: int) -> Optional[bytes]:
        """
        Get current DMX values for a universe.

        Args:
            universe: Universe number

        Returns:
            512 bytes of DMX data, or None if no data received
        """
        with self.dmx_lock:
            return self.dmx_data.get(universe)

    def get_channel(self, universe: int, channel: int) -> int:
        """
        Get a single DMX channel value.

        Args:
            universe: Universe number
            channel: Channel number (1-512)

        Returns:
            Channel value (0-255), or 0 if no data
        """
        with self.dmx_lock:
            data = self.dmx_data.get(universe)
            if data and 1 <= channel <= 512:
                return data[channel - 1]
            return 0

    def get_universes(self) -> list:
        """Get list of universes that have received data."""
        with self.dmx_lock:
            return list(self.dmx_data.keys())

    def get_statistics(self) -> dict:
        """Get packet statistics."""
        return {
            'packets_received': self.packets_received,
            'packets_invalid': self.packets_invalid,
            'universes': len(self.dmx_data),
            'is_receiving': self.is_receiving
        }

    def clear_data(self):
        """Clear all stored DMX data."""
        with self.dmx_lock:
            self.dmx_data.clear()
            self.last_receive_time.clear()
