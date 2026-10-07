"""Smoke tests for the visualizer TCP feed server (v1.5.5 hardening, G10).

``utils/tcp/server.py`` had no direct test: the e2e VISUALIZER flow
stubs the class out. These tests run the real server on a loopback
port with a real client socket.

Bug pinned here: when the port could not be bound (another app or a
second Lichtmaschine already listening), the server thread died but
``is_running()`` kept answering True. The shell's VISUALIZER toggle and
status chip derive from ``is_running()``, so the chip claimed a feed
that did not exist and the next press "stopped" it instead of retrying.
start() now binds before it returns, so the failure is visible to the
toggle's launch decision right after the call.
"""

from __future__ import annotations

import json
import os
import socket
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import Configuration, Fixture, FixtureGroup, FixtureMode, Universe
from utils import user_warnings
from utils.tcp.protocol import VisualizerProtocol
from utils.tcp.server import VisualizerTCPServer


def _free_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _config() -> Configuration:
    fixture = Fixture(
        universe=1, address=1, manufacturer="Generic", model="Generic RGB",
        name="Par 1", group="Pars", current_mode="RGB",
        available_modes=[FixtureMode(name="RGB", channels=3)], type="PAR",
    )
    return Configuration(
        fixtures=[fixture],
        groups={"Pars": FixtureGroup(name="Pars", fixtures=[fixture])},
        universes={1: Universe(id=1, name="Universe 1", output={})},
    )


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _connect(port: int) -> socket.socket:
    deadline = time.monotonic() + 5.0
    while True:
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=5.0)
        except ConnectionRefusedError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.02)


def _read_messages(client: socket.socket, count: int, timeout=5.0) -> list:
    """Read newline-delimited JSON messages until ``count`` arrived."""
    buf = b""
    client.settimeout(timeout)
    while buf.count(b"\n") < count:
        chunk = client.recv(65536)
        if not chunk:
            break
        buf += chunk
    return [json.loads(line) for line in buf.split(b"\n") if line.strip()]


@pytest.fixture
def server():
    srv = VisualizerTCPServer(_config(), port=_free_port())
    yield srv
    srv.stop()


class TestServeAndStop:
    def test_new_client_receives_the_full_config(self, server):
        server.start()
        client = _connect(server.port)
        try:
            expected = len(
                VisualizerProtocol.serialize_full_config(server.config))
            messages = _read_messages(client, expected)
            assert len(messages) == expected
            assert all("type" in m for m in messages)
            assert _wait_for(lambda: server.get_client_count() == 1)
        finally:
            client.close()

    def test_send_update_reaches_connected_client(self, server):
        server.start()
        client = _connect(server.port)
        try:
            initial = len(VisualizerProtocol.serialize_full_config(server.config))
            _read_messages(client, initial)
            server.send_update("fixtures", {"probe": 1})
            update = _read_messages(client, 1)
            assert update and update[-1].get("data", {}).get("probe") == 1
        finally:
            client.close()

    def test_stop_disconnects_clients_and_reports_not_running(self, server):
        server.start()
        client = _connect(server.port)
        try:
            assert _wait_for(lambda: server.get_client_count() == 1)
            server.stop()
            assert not server.is_running()
            assert server.get_client_count() == 0
            # Drain whatever config was in flight: the server end is
            # closed, so the stream ends (EOF or reset), never hangs.
            client.settimeout(5.0)
            ended = False
            try:
                while client.recv(65536):
                    pass
                ended = True
            except ConnectionError:
                ended = True
            assert ended
        finally:
            client.close()

    def test_restart_after_stop_listens_again(self, server):
        server.start()
        _connect(server.port).close()
        server.stop()
        server.start()
        client = _connect(server.port)
        try:
            assert server.is_running()
            assert _wait_for(lambda: server.get_client_count() == 1)
        finally:
            client.close()


def _blocker() -> socket.socket:
    """A listener that holds a port the server must fail to bind.

    On Windows a plain listener does not block a later SO_REUSEADDR
    bind (that option lets the second socket share the port), so the
    blocker claims the port exclusively there."""
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    blocker.bind(("0.0.0.0", 0))
    blocker.listen(1)
    return blocker


class TestListenFailure:
    def test_port_in_use_leaves_server_not_running(self, monkeypatch):
        log = user_warnings.UserWarningsLog()
        monkeypatch.setattr(user_warnings, "_log", log)

        blocker = _blocker()
        port = blocker.getsockname()[1]
        srv = VisualizerTCPServer(_config(), port=port)
        errors = []
        srv.error_occurred.connect(errors.append)
        try:
            srv.start()
            # The failure is known when start() returns: the VISUALIZER
            # toggle reads is_running() right after the call to decide
            # whether to launch the viewer, so a bind that fails later
            # on a thread would still launch it.
            assert not srv.is_running()
            assert srv.server_thread is None
            assert errors
            assert any(str(port) in e.message and e.category == "output"
                       for e in log.entries())
        finally:
            srv.stop()
            blocker.close()

    def test_failed_start_can_be_retried_once_the_port_frees(self):
        blocker = _blocker()
        port = blocker.getsockname()[1]
        srv = VisualizerTCPServer(_config(), port=port)
        try:
            srv.start()
            assert not srv.is_running()
            blocker.close()
            srv.start()   # a no-op while the stale flag said "running"
            client = _connect(port)
            try:
                assert srv.is_running()
                assert _wait_for(lambda: srv.get_client_count() == 1)
            finally:
                client.close()
        finally:
            srv.stop()
            blocker.close()
