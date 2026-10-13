"""ArtNet listener source lock (2026-07-17 twitch fix).

With a broadcast primary target the arbiter's every universe arrives
at a LOCAL viewer twice: the yoke-converted hardware frame (broadcast
loops back) and the solver-convention loopback mirror. Rendering
whichever packet came last flipped every mover between two poses at
44 Hz - heads "twitching between two positions" at the idle floor
(pan 170 vs 127, tilt 42 vs 127 on the gig rig). One universe must
render ONE sender: loopback preferred, others first-come with a
silence failover.

No sockets: packets go straight into _process_packet with a fake
source address.
"""
from __future__ import annotations

import os
import struct

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from visualizer.artnet.listener import ArtNetListener

LAN_A = ("192.168.178.20", 6454)     # broadcast hardware frame source
LAN_B = ("192.168.178.99", 6454)     # a second desk (QLC+ etc.)
LOOPBACK = ("127.0.0.1", 6454)       # the arbiter's solver mirror


def packet(universe=0, first_byte=0):
    dmx = bytes([first_byte]) + bytes(511)
    return (b"Art-Net\x00" + struct.pack("<H", 0x5000)
            + struct.pack(">H", 14) + bytes([0, 0])
            + struct.pack("<H", universe) + struct.pack(">H", len(dmx))
            + dmx)


@pytest.fixture
def listener():
    lis = ArtNetListener()          # never start()ed - no socket
    yield lis


def first_byte(listener, universe=0):
    return listener.dmx_data[universe][0]


class TestSourceLock:
    def test_first_source_locks_the_universe(self, listener):
        listener._process_packet(packet(first_byte=10), LAN_A)
        listener._process_packet(packet(first_byte=99), LAN_B)
        assert first_byte(listener) == 10
        assert listener.packets_foreign == 1

    def test_loopback_takes_over_immediately(self, listener):
        listener._process_packet(packet(first_byte=10), LAN_A)
        listener._process_packet(packet(first_byte=42), LOOPBACK)
        assert first_byte(listener) == 42

    def test_no_alternation_between_mirror_and_broadcast(self, listener):
        """The reported bug: hardware and mirror frames interleave at
        44 Hz. After the first loopback packet the rendered data must
        stay the mirror's, however many broadcast frames arrive."""
        listener._process_packet(packet(first_byte=170), LAN_A)   # hw
        listener._process_packet(packet(first_byte=127), LOOPBACK)
        for _ in range(20):
            listener._process_packet(packet(first_byte=170), LAN_A)
            assert first_byte(listener) == 127
            listener._process_packet(packet(first_byte=127), LOOPBACK)
            assert first_byte(listener) == 127

    def test_failover_after_silence(self, listener):
        listener._process_packet(packet(first_byte=10), LAN_A)
        # Age the lock past the failover window.
        ip, t = listener.source_lock[0]
        listener.source_lock[0] = (ip, t - ArtNetListener.SOURCE_FAILOVER_S
                                   - 0.1)
        listener._process_packet(packet(first_byte=99), LAN_B)
        assert first_byte(listener) == 99
        # ...and the new source now holds the lock.
        listener._process_packet(packet(first_byte=10), LAN_A)
        assert first_byte(listener) == 99

    def test_universes_lock_independently(self, listener):
        listener._process_packet(packet(universe=0, first_byte=10), LAN_A)
        listener._process_packet(packet(universe=1, first_byte=99), LAN_B)
        assert first_byte(listener, 0) == 10
        assert first_byte(listener, 1) == 99

    def test_loopback_holds_against_loopback_variants(self, listener):
        """::1 and 127.x are both loopback: no takeover ping-pong
        between them - the second is foreign while the first is
        fresh."""
        listener._process_packet(packet(first_byte=42), LOOPBACK)
        listener._process_packet(packet(first_byte=43), ("::1", 6454))
        assert first_byte(listener) == 42
