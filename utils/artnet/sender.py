# utils/artnet/sender.py
# ArtNet DMX packet sender with 44Hz rate limiting

import socket
import struct
import time
from typing import Dict, Optional

from utils import user_warnings


class ArtNetSender:
    """
    Sends DMX data via ArtNet protocol (OpDmx packets).

    ArtNet OpDmx Packet Format:
    - Bytes 0-7: "Art-Net\0" (header)
    - Bytes 8-9: OpCode 0x5000 (little-endian)
    - Bytes 10-11: Protocol version 0x000e (big-endian, version 14)
    - Byte 12: Sequence counter (0-255, wraps around)
    - Byte 13: Physical port (0)
    - Bytes 14-15: Universe (little-endian, 15-bit)
    - Bytes 16-17: DMX data length (big-endian, max 512)
    - Bytes 18+: DMX data (up to 512 bytes)

    Rate limited to 44Hz (22.7ms minimum interval) to avoid overloading receivers.
    """

    # ArtNet constants
    ARTNET_HEADER = b'Art-Net\x00'
    ARTNET_OPCODE_DMX = 0x5000
    ARTNET_PROTOCOL_VERSION = 0x000e
    ARTNET_PORT = 6454

    # Rate limiting
    MAX_SEND_RATE_HZ = 44
    MIN_SEND_INTERVAL = 1.0 / MAX_SEND_RATE_HZ  # ~22.7ms

    def __init__(self, target_ip: str = "255.255.255.255", target_port: int = ARTNET_PORT):
        """
        Initialize ArtNet sender.

        Args:
            target_ip: Target IP address (default: broadcast)
            target_port: Target UDP port (default: 6454)
        """
        self.target_ip = target_ip
        self.target_port = target_port

        # Create UDP socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # Sequence counter (0-255, wraps around)
        self.sequence = 0

        # Rate limiting - track last send time per universe
        self.last_send_time: Dict[int, float] = {}

        print(f"ArtNet sender initialized: {target_ip}:{target_port}")

    def create_dmx_packet(self, universe: int, dmx_data: bytes) -> bytes:
        """
        Create an ArtNet OpDmx packet.

        Args:
            universe: Universe number (0-32767, 15-bit)
            dmx_data: DMX data bytes (up to 512 bytes)

        Returns:
            Complete ArtNet packet as bytes
        """
        # Ensure DMX data is not longer than 512 bytes
        if len(dmx_data) > 512:
            dmx_data = dmx_data[:512]

        # Pad to 512 bytes if shorter
        if len(dmx_data) < 512:
            dmx_data = dmx_data + bytes(512 - len(dmx_data))

        # Build packet
        packet = bytearray()

        # Header: "Art-Net\0" (8 bytes)
        packet.extend(self.ARTNET_HEADER)

        # OpCode: 0x5000 (little-endian, 2 bytes)
        packet.extend(struct.pack('<H', self.ARTNET_OPCODE_DMX))

        # Protocol version: 14 (big-endian, 2 bytes)
        packet.extend(struct.pack('>H', self.ARTNET_PROTOCOL_VERSION))

        # Sequence: 0-255 (1 byte)
        packet.append(self.sequence)

        # Physical port: 0 (1 byte)
        packet.append(0)

        # Universe: 15-bit value (little-endian, 2 bytes)
        # Bits 0-14: Universe number
        # Bit 15: Reserved (0)
        packet.extend(struct.pack('<H', universe & 0x7FFF))

        # Length: DMX data length (big-endian, 2 bytes)
        packet.extend(struct.pack('>H', len(dmx_data)))

        # DMX data (512 bytes)
        packet.extend(dmx_data)

        # Increment sequence counter (wraps at 255)
        self.sequence = (self.sequence + 1) % 256

        return bytes(packet)

    def send_dmx(self, universe: int, dmx_data: bytes, force: bool = False) -> bool:
        """
        Send DMX data for a universe via ArtNet.

        Rate limited to 44Hz unless force=True.

        Args:
            universe: Universe number (0-32767)
            dmx_data: DMX data bytes (up to 512 bytes)
            force: If True, bypass rate limiting

        Returns:
            True if packet was sent, False if rate-limited
        """
        current_time = time.time()

        # Check rate limiting (unless forced)
        if not force:
            last_time = self.last_send_time.get(universe, 0)
            time_since_last = current_time - last_time

            if time_since_last < self.MIN_SEND_INTERVAL:
                # Rate limited - too soon since last send
                return False

        # Create and send packet
        packet = self.create_dmx_packet(universe, dmx_data)

        try:
            self.socket.sendto(packet, (self.target_ip, self.target_port))
            self.last_send_time[universe] = current_time
            return True
        except Exception as e:
            # once_key folds a 44 Hz failure storm into one counted entry
            user_warnings.warn(
                f"ArtNet send to {self.target_ip} failed: {e}",
                category="output",
                once_key=f"artnet-send:{self.target_ip}")
            return False

    def close(self):
        """Close the UDP socket."""
        if self.socket:
            self.socket.close()
            print("ArtNet sender closed")

    def __del__(self):
        """Cleanup on deletion."""
        self.close()
