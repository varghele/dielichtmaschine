"""
Regression test for the embedded-visualizer DMX bridge - since the
arbiter pass (docs/output-sync-plan.md phase 1) the local callback is
dispatched by the OutputArbiter with the POST-MERGE frame, once per
config universe per tick, alongside the ArtNet send.

Each arbiter tick should:
- hand the merged DMX bytes to the ArtNet sender (wire path intact,
  0-based wire universes), AND
- invoke the local callback once per configured universe with the
  1-based config universe id and the raw 512-byte buffer.

A misbehaving callback must not poison the send loop, so an exception
inside the callback is swallowed without breaking the ArtNet send.
"""

from __future__ import annotations

import pytest

from config.models import Configuration, Fixture, FixtureMode, Universe
from utils.artnet.arbiter import OutputArbiter
from utils.artnet.shows_artnet_controller import ShowsArtNetController


class StubSender:
    def __init__(self, target_ip="255.255.255.255", target_port=6454):
        self.target_ip = target_ip
        self.sent = []

    def send_dmx(self, universe, dmx_data, force=False):
        self.sent.append((universe, bytes(dmx_data)))
        return True

    def close(self):
        pass


@pytest.fixture
def two_universe_config():
    """Configuration with one fixture per universe across two universes."""
    fixtures = [
        Fixture(
            universe=1, address=1, manufacturer="Mfr", model="A",
            name="A1", group="G", current_mode="Mode",
            available_modes=[FixtureMode(name="Mode", channels=4)],
            type="PAR",
        ),
        Fixture(
            universe=2, address=1, manufacturer="Mfr", model="B",
            name="B1", group="G", current_mode="Mode",
            available_modes=[FixtureMode(name="Mode", channels=4)],
            type="PAR",
        ),
    ]
    return Configuration(
        fixtures=fixtures,
        universes={
            1: Universe(id=1, name="Universe 1", output={}),
            2: Universe(id=2, name="Universe 2", output={}),
        },
    )


def _make_controller(config, callback=None):
    """A ShowsArtNetController on an arbiter with a stub sender - no
    UDP socket, ticks driven manually. ``fixture_definitions`` is
    empty: DMXManager leaves the universes at zeros, which is fine for
    the dispatch assertions."""
    sender = StubSender()
    arbiter = OutputArbiter(config=config, sender=sender)
    controller = ShowsArtNetController(
        config=config,
        fixture_definitions={},
        local_dmx_callback=callback,
        arbiter=arbiter,
    )
    return controller, sender


def test_callback_fires_once_per_universe(two_universe_config):
    received: list[tuple[int, bytes]] = []

    def callback(universe: int, dmx_bytes: bytes) -> None:
        received.append((universe, dmx_bytes))

    controller, sender = _make_controller(two_universe_config,
                                          callback=callback)
    controller.arbiter.tick_once(0.0)

    universes_seen = [u for u, _ in received]
    assert sorted(universes_seen) == [1, 2], (
        f"Expected callback for universes [1, 2], got {universes_seen}"
    )
    for _, payload in received:
        assert isinstance(payload, bytes)
        assert len(payload) == 512

    # The wire path stays intact: one packet per universe, 0-based.
    assert sorted(u for u, _ in sender.sent) == [0, 1]


def test_callback_exception_does_not_break_send(two_universe_config):
    def bad_callback(universe: int, dmx_bytes: bytes) -> None:
        raise RuntimeError("visualizer is unhappy")

    controller, sender = _make_controller(two_universe_config,
                                          callback=bad_callback)
    controller.arbiter.tick_once(0.0)   # must not raise
    assert len(sender.sent) == 2


def test_set_local_dmx_callback_swaps_in_place(two_universe_config):
    controller, _ = _make_controller(two_universe_config, callback=None)

    received: list[int] = []
    controller.set_local_dmx_callback(lambda u, _: received.append(u))
    controller.arbiter.tick_once(0.0)
    assert sorted(received) == [1, 2]

    # Clearing the callback stops further dispatch immediately.
    controller.set_local_dmx_callback(None)
    received.clear()
    controller.arbiter.tick_once(0.0)
    assert received == []


def test_no_callback_means_no_dispatch_but_sends(two_universe_config):
    controller, sender = _make_controller(two_universe_config,
                                          callback=None)
    controller.arbiter.tick_once(0.0)
    assert len(sender.sent) == 2
