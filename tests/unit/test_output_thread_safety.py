# tests/unit/test_output_thread_safety.py
"""v1.5.5 hardening group G6: output and background-thread safety.

Each class pins one race from docs/v1.5.5-hardening-plan.md. A real
race is not reproducible on demand, so the tests force the losing
interleaving deterministically instead: a hook fires the "other
thread's" mutation exactly between the two reads that raced (a dict
that loses its key after the membership check, a block list that
shrinks mid-iteration, a stop() that lands between a drain's read and
its emit), or a gate holds a thread at the point that used to overrun.

- OutputArbiter: an abandoned loop (stop()'s join timed out) never
  sends after the blackout or into a closed socket, and a restart
  cannot revive it.
- ShowsArtNetController.render: lanes, blocks and universes edited on
  the UI thread mid-frame; one playback time per frame.
- LiveBuskLayer.render: LiveState / config mutated mid-frame.
- AutoShowEngine: the riffs-updated UI callback runs outside the lock.
- LTCInputService: _active_rate exists from construction; a drain
  cannot emit its state after stop().
- user_warnings: operation grouping is per thread.
- VisualizerTCPClient: a winding-down receive loop cannot close the
  NEXT connection's socket.
"""

import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from config.models import (
    Configuration, Fixture, FixtureGroup, FixtureMode, Universe,
)
from utils.artnet import arbiter as arbiter_mod
from utils.artnet.arbiter import OutputArbiter


def _fixture(name, address, universe=1, model="TestModel", x=0.0):
    return Fixture(
        universe=universe, address=address, manufacturer="TestMfr",
        model=model, name=name, group="G", current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
        type="MH", x=x,
    )


def _config(fixtures=None, universes=(1,)):
    fixtures = fixtures if fixtures is not None else [_fixture("MH1", 1)]
    return Configuration(
        fixtures=fixtures,
        groups={"G": FixtureGroup(name="G", fixtures=fixtures)},
        universes={u: Universe(id=u, name=f"U{u}", output={})
                   for u in universes},
    )


# ---------------------------------------------------------------------------
# OutputArbiter: stop() after a timed-out join
# ---------------------------------------------------------------------------

class GatedSender:
    """Records every send (with the sending thread and whether the
    socket was already closed). The arbiter LOOP's first send blocks on
    ``gate`` - a send that overruns stop()'s join timeout."""

    def __init__(self):
        self.target_ip = "127.0.0.1"
        self.sent = []
        self.closed = False
        self.gate = threading.Event()
        self.blocked = threading.Event()
        self._held_once = False

    def send_dmx(self, universe, dmx_data, force=False):
        thread = threading.current_thread()
        if thread.name == "OutputArbiter" and not self._held_once:
            self._held_once = True
            self.blocked.set()
            self.gate.wait(timeout=5.0)
        self.sent.append(SimpleNamespace(thread=thread, universe=universe,
                                         after_close=self.closed))
        return True

    def close(self):
        self.closed = True


class TestArbiterAbandonedLoop:

    @pytest.fixture(autouse=True)
    def _short_join(self, monkeypatch):
        monkeypatch.setattr(arbiter_mod, "STOP_JOIN_TIMEOUT", 0.1,
                            raising=False)

    def test_late_frame_never_follows_the_blackout_or_the_close(self):
        sender = GatedSender()
        arbiter = OutputArbiter(config=_config(), sender=sender)
        arbiter.start()
        loop = arbiter._thread
        assert sender.blocked.wait(2.0)       # loop is mid-send

        # The UI thread shuts down while the loop overruns: its join
        # times out. Release the overrunning send only afterwards.
        shutdown = threading.Thread(target=arbiter.shutdown)
        shutdown.start()
        shutdown.join(timeout=1.3)
        sender.gate.set()
        shutdown.join(timeout=5.0)
        loop.join(timeout=5.0)
        assert not shutdown.is_alive() and not loop.is_alive()

        assert sender.closed
        assert not any(s.after_close for s in sender.sent), \
            "the abandoned loop sent into a closed socket"
        # The blackout (sent by the shutting-down thread) is the LAST
        # thing on the wire - the stale frame went out before it.
        assert sender.sent[-1].thread is shutdown

    def test_restart_does_not_revive_the_abandoned_loop(self):
        sender = GatedSender()
        arbiter = OutputArbiter(config=_config(), sender=sender)
        arbiter.start()
        old_loop = arbiter._thread
        assert sender.blocked.wait(2.0)

        arbiter.stop(blackout=False)          # join times out
        arbiter.start()                       # a fresh run
        new_loop = arbiter._thread
        assert new_loop is not old_loop
        sender.gate.set()

        old_loop.join(timeout=1.0)
        try:
            assert not old_loop.is_alive(), \
                "restart cleared the abandoned loop's stop flag"
            assert new_loop.is_alive()
        finally:
            arbiter.stop(blackout=False)

    def test_tick_once_still_sends_without_a_loop(self):
        # The public single-frame path (tests, e2e) is not gated.
        sender = GatedSender()
        arbiter = OutputArbiter(config=_config(), sender=sender)
        arbiter.tick_once(0.0)
        assert len(sender.sent) == 1


# ---------------------------------------------------------------------------
# ShowsArtNetController.render on the arbiter thread
# ---------------------------------------------------------------------------

class _StubSender:
    def __init__(self, *args, **kwargs):
        self.target_ip = "127.0.0.1"
        self.sent = []

    def send_dmx(self, universe, dmx_data, force=False):
        self.sent.append(universe)
        return True

    def close(self):
        pass


def _playing_controller(config):
    from utils.artnet.shows_artnet_controller import ShowsArtNetController
    arbiter = OutputArbiter(config=config, sender=_StubSender())
    controller = ShowsArtNetController(config, {}, arbiter=arbiter)
    controller.output_enabled = True
    assert controller.start_playback()
    return controller


class _Block:
    """A sub-block whose start_time read can fire a hook - the moment
    the UI thread edits the lane while render() walks it."""

    def __init__(self, start, end):
        self._start = start
        self.end_time = end
        self.on_read = None

    @property
    def start_time(self):
        hook, self.on_read = self.on_read, None
        if hook is not None:
            hook()
        return self._start


def _light_block(dimmer=(), colour=()):
    return SimpleNamespace(dimmer_blocks=list(dimmer),
                           colour_blocks=list(colour),
                           movement_blocks=[], special_blocks=[])


class TestShowsRenderSnapshots:

    def test_universe_added_mid_frame_does_not_raise(self):
        config = _config()
        controller = _playing_controller(config)
        manager = controller.dmx_manager
        real_get_frame = manager.get_frame

        def get_frame(universe):
            # The Setup tab adds a universe while the frame renders.
            config.universes.setdefault(
                7, Universe(id=7, name="U7", output={}))
            return real_get_frame(universe)

        manager.get_frame = get_frame
        frames = controller.render(0.0)       # used to raise RuntimeError
        assert 1 in frames
        controller.cleanup()

    def test_block_deleted_mid_iteration_does_not_end_its_sibling(self):
        config = _config()
        controller = _playing_controller(config)
        dimmer = _Block(0.0, 10.0)
        colour = _Block(0.0, 10.0)
        first, second = _light_block(dimmer=[dimmer]), \
            _light_block(colour=[colour])
        lane = SimpleNamespace(name="L", muted=False,
                               fixture_targets=["G"],
                               light_blocks=[first, second])
        started, ended = [], []
        controller.dmx_manager.block_started = \
            lambda key, fx, block, kind, t: started.append(kind)
        controller.dmx_manager.block_ended = \
            lambda key, kind: ended.append(kind)
        controller.set_light_lanes([lane])
        controller.set_position_callback(lambda: 1.0)

        controller.render(0.0)
        assert sorted(started) == ["colour", "dimmer"]

        # Next frame: the UI deletes the FIRST light block exactly while
        # render() reads it. The second block is still on the timeline
        # and must keep running - not be ended (and restarted next frame).
        dimmer.on_read = lambda: lane.light_blocks.remove(first)
        controller.render(0.0)
        assert "colour" not in ended
        controller.cleanup()

    def test_one_playback_time_per_frame(self):
        config = _config()
        controller = _playing_controller(config)
        block = _Block(0.0, 10.0)
        lane = SimpleNamespace(name="L", muted=False,
                               fixture_targets=["G"],
                               light_blocks=[_light_block(dimmer=[block])])
        seen = {}

        def block_started(key, fixtures, sub_block, kind, t):
            seen["block"] = t
            # The UI thread seeks while the frame is mid-render.
            seeker = threading.Thread(
                target=controller.update_position, args=(99.0,))
            seeker.start()
            seeker.join(timeout=0.2)
            seen["seeker"] = seeker

        real_update = controller.dmx_manager.update_dmx

        def update_dmx(t):
            seen["dmx"] = t
            return real_update(t)

        controller.dmx_manager.block_started = block_started
        controller.dmx_manager.block_ended = lambda key, kind: None
        controller.dmx_manager.update_dmx = update_dmx
        controller.set_light_lanes([lane])
        controller.current_time = 1.0
        controller.render(0.0)
        seen["seeker"].join(timeout=2.0)

        assert seen["block"] == seen["dmx"] == 1.0
        assert controller.current_time == 99.0    # the seek still lands
        controller.cleanup()


# ---------------------------------------------------------------------------
# LiveBuskLayer.render reads LiveState on the arbiter thread
# ---------------------------------------------------------------------------

class _VanishingDict(dict):
    """The UI thread removes ``key`` right after the Nth successful
    membership test - the window between "in" and "[...]"."""

    def __init__(self, data, key, on_hit=2):
        super().__init__(data)
        self._key = key
        self._hits_left = on_hit

    def __contains__(self, key):
        present = dict.__contains__(self, key)
        if present and key == self._key and self._hits_left:
            self._hits_left -= 1
            if not self._hits_left:
                self.pop(key)
        return present


def _busk_setup(mock_fixture_def, groups=None):
    from gui.tabs.live_tab import COLOUR_SWATCHES, LiveState
    from utils.artnet.dmx_manager import FixtureChannelMap
    from utils.artnet.live_layer import LiveBuskLayer

    fixtures = [_fixture("MH1", 1, x=-1.0), _fixture("MH2", 11, x=1.0)]
    groups = groups(fixtures) if groups else {
        "Movers": FixtureGroup(name="Movers", fixtures=fixtures)}
    config = Configuration(
        fixtures=fixtures, groups=groups,
        universes={1: Universe(id=1, name="U1", output={})})
    maps = {f.name: FixtureChannelMap(f, mock_fixture_def, config)
            for f in fixtures}
    state = LiveState()
    state.update_from_config(list(groups.keys()))
    layer = LiveBuskLayer(state, config_provider=lambda: config,
                          swatches=COLOUR_SWATCHES)
    layer.set_fixture_maps(maps)
    return state, layer, config


class TestBuskLayerSnapshot:
    RED = 1   # mock def channel layout: dimmer 0, red 1

    def test_swatch_released_mid_frame_still_renders(self, qapp,
                                                     mock_fixture_def):
        state, layer, _ = _busk_setup(mock_fixture_def)
        state.colours = _VanishingDict({"Movers": "red"}, "Movers")
        frame = layer.render(0.0)              # used to raise KeyError
        values, mask = frame[1]
        assert mask[self.RED] and values[self.RED] == 0xFF

    def test_group_level_survives_a_submaster_rebuild(self, qapp):
        from gui.tabs.live_tab import LiveState
        state = LiveState()
        state.update_from_config(["Movers"])
        state.submasters = _VanishingDict({"Movers": 80}, "Movers",
                                          on_hit=1)
        # One lookup reads 80 consistently; "in" then "[...]" lost the
        # key in between and raised KeyError.
        assert state.group_level_local("Movers") == pytest.approx(0.8)

    def test_group_added_mid_frame_does_not_raise(self, qapp,
                                                  mock_fixture_def):
        class _HookedGroup:
            capabilities = None

            def __init__(self, fixtures, on_read):
                self._fixtures = fixtures
                self._on_read = on_read

            @property
            def fixtures(self):
                hook, self._on_read = self._on_read, None
                if hook is not None:
                    hook()
                return self._fixtures

        holder = {}

        def groups(fixtures):
            def add_group():
                holder["config"].groups["Late"] = FixtureGroup(
                    name="Late", fixtures=[])
            return {"Movers": _HookedGroup(fixtures, add_group)}

        state, layer, config = _busk_setup(mock_fixture_def, groups)
        holder["config"] = config
        state.positions = {"Movers": "preset:centre"}
        frame = layer.render(0.0)              # used to raise RuntimeError
        assert 1 in frame

    def test_snapshot_copies_the_state_containers(self, qapp):
        from gui.tabs.live_tab import LiveState
        from utils.artnet.live_layer import BuskStateSnapshot
        state = LiveState()
        state.update_from_config(["A"])
        state.colours["A"] = "red"
        state.flash.add("A")
        snap = BuskStateSnapshot(state)
        state.colours.clear()
        state.flash.clear()
        assert snap.colours == {"A": "red"}
        assert snap.group_level_local("A") == 1.0
        assert state.group_level_local("A") == 1.0   # submaster 100


# ---------------------------------------------------------------------------
# AutoShowEngine: UI callback outside the engine lock
# ---------------------------------------------------------------------------

class TestAutoEngineCallback:

    def _engine(self):
        from auto.engine import AutoShowEngine
        return AutoShowEngine(_config(), {})

    def test_riffs_callback_runs_without_the_lock(self):
        engine = self._engine()
        calls = []
        engine.set_on_riffs_updated(
            lambda riffs: calls.append((riffs, engine._lock.locked())))
        engine.start()
        assert calls, "start() selects riffs and must notify"
        riffs, locked = calls[-1]
        assert "G" in riffs
        assert locked is False

    def test_callback_may_read_engine_properties(self):
        engine = self._engine()
        seen = []
        # Reading a property takes the (non-reentrant) lock: from inside
        # the old under-lock callback this deadlocked.
        engine.set_on_riffs_updated(
            lambda riffs: seen.append(engine.per_group_rudiments))
        worker = threading.Thread(target=engine.start, daemon=True)
        worker.start()
        worker.join(timeout=5.0)
        assert not worker.is_alive(), "callback deadlocked on the lock"
        assert seen and "G" in seen[-1]

    def test_tick_cycle_reselection_notifies(self):
        engine = self._engine()
        calls = []
        engine.set_on_riffs_updated(calls.append)
        engine.start()
        start = engine._cycle.cycle_start_time
        # Past the 4-bar cycle at 120 BPM (8 s): riffs are re-selected.
        engine.tick(start + 9.0)
        assert len(calls) == 2
        engine.tick(start + 9.1)              # mid-bar: nothing new
        assert len(calls) == 2


# ---------------------------------------------------------------------------
# LTCInputService
# ---------------------------------------------------------------------------

class _HookLock:
    """Wraps the service lock; fires ``hook`` once, right after the
    next release - between a drain's locked read and its emit."""

    def __init__(self, inner):
        self._inner = inner
        self.hook = None

    def __enter__(self):
        self._inner.acquire()
        return self

    def __exit__(self, *exc):
        self._inner.release()
        hook, self.hook = self.hook, None
        if hook is not None:
            hook()
        return False


class TestLTCService:

    def test_active_rate_initialised_at_construction(self, qapp):
        from audio.ltc_input import LTCInputService
        service = LTCInputService(sample_rate=48000)
        assert service._active_rate == 48000

    def test_drain_cannot_emit_its_state_after_stop(self, qapp):
        from tests.unit.test_ltc_input import make_service, push_and_drain
        from utils.timecode import FPS_25, Timecode, generate_ltc

        service, created, clock = make_service()
        states = []
        service.state_changed.connect(states.append)
        service.start(run_reader=False)
        audio = generate_ltc(Timecode.parse("00:05:00:00", FPS_25), 2.5)
        push_and_drain(service, created[0], clock, audio[:-2205])
        assert states[-1] == "locked"

        # The UI thread stops the service between the reader's locked
        # read ("locked") and its emit.
        hooked = _HookLock(service._lock)
        service._lock = hooked
        hooked.hook = service.stop
        created[0].ring_buffer.write(
            np.asarray(audio[-2205:]).reshape(-1, 1))
        clock.t += 0.05
        service.drain_once()
        assert states[-1] == "no_signal", \
            "a stale 'locked' landed after stop()"


# ---------------------------------------------------------------------------
# user_warnings: per-thread operation grouping
# ---------------------------------------------------------------------------

class TestWarningOperationsPerThread:

    def test_other_threads_warning_is_not_grouped_into_the_operation(self):
        from utils.user_warnings import UserWarningsLog
        log = UserWarningsLog()
        with log.operation("Export QLC+ workspace"):
            worker = threading.Thread(
                target=log.warn, args=("ArtNet send failed",),
                kwargs={"category": "output"})
            worker.start()
            worker.join()
            log.warn("lane skipped", category="export")
        by_message = {e.message: e for e in log.entries()}
        assert by_message["ArtNet send failed"].operation == ""
        assert by_message["lane skipped"].operation == \
            "Export QLC+ workspace"
        name, entries = log.last_operation()
        assert [e.message for e in entries] == ["lane skipped"]

    def test_operation_on_a_worker_groups_its_own_warnings(self):
        from utils.user_warnings import UserWarningsLog
        log = UserWarningsLog()

        def work():
            with log.operation("Load project"):
                log.warn("fixture missing")

        worker = threading.Thread(target=work)
        worker.start()
        worker.join()
        log.warn("outside")
        by_message = {e.message: e for e in log.entries()}
        assert by_message["fixture missing"].operation == "Load project"
        assert by_message["outside"].operation == ""
        assert log._op_stacks == {}           # nothing leaks per thread


# ---------------------------------------------------------------------------
# VisualizerTCPClient: one receive loop per connection
# ---------------------------------------------------------------------------

class _FakeSocket:
    """recv() blocks until ``release`` - shutdown() deliberately does
    NOT wake it, so the old loop is still winding down when the next
    connection is already up."""

    def __init__(self, *args, **kwargs):
        self.release = threading.Event()
        self.closed = False
        self.shut = False

    def settimeout(self, value):
        pass

    def connect(self, address):
        pass

    def recv(self, size):
        self.release.wait(timeout=5.0)
        return b""

    def shutdown(self, how):
        self.shut = True

    def close(self):
        self.closed = True


class TestTCPClientReconnect:

    @pytest.fixture
    def fake_sockets(self, monkeypatch):
        import socket as real_socket
        from visualizer.tcp import client as client_mod
        created = []

        def factory(*args, **kwargs):
            sock = _FakeSocket()
            created.append(sock)
            return sock

        monkeypatch.setattr(client_mod, "socket", SimpleNamespace(
            socket=factory, AF_INET=real_socket.AF_INET,
            SOCK_STREAM=real_socket.SOCK_STREAM,
            SHUT_RDWR=real_socket.SHUT_RDWR,
            timeout=real_socket.timeout))
        yield created
        for sock in created:
            sock.release.set()

    @staticmethod
    def _wait(predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.005)
        return False

    def test_old_loop_cannot_close_the_next_connection(self, qapp,
                                                       fake_sockets):
        from visualizer.tcp.client import VisualizerTCPClient
        client = VisualizerTCPClient()
        disconnects = []
        client.disconnected.connect(lambda: disconnects.append(1))

        client.connect()
        assert self._wait(lambda: client.is_connected)
        first_loop = client.receive_thread
        first = fake_sockets[0]

        client.disconnect()
        assert first.shut and first.closed
        assert disconnects == [1]

        client.connect()
        assert self._wait(lambda: client.is_connected
                          and len(fake_sockets) == 2)
        second = fake_sockets[1]

        # The first loop's recv() finally returns: it must wind down
        # without touching the live second connection.
        first.release.set()
        first_loop.join(timeout=2.0)
        assert not first_loop.is_alive()
        assert client.is_connected
        assert client.socket is second
        assert not second.closed
        assert disconnects == [1]

        client.disconnect()
        assert second.closed
        assert disconnects == [1, 1]

    def test_disconnect_while_receiving_exits_cleanly(self, qapp,
                                                      fake_sockets):
        from visualizer.tcp.client import VisualizerTCPClient
        errors = []
        previous_hook = threading.excepthook
        threading.excepthook = lambda args: errors.append(args.exc_value)
        try:
            client = VisualizerTCPClient()
            client.connect()
            assert self._wait(lambda: client.is_connected)
            loop = client.receive_thread
            client.disconnect()
            fake_sockets[0].release.set()
            loop.join(timeout=2.0)
            assert not loop.is_alive()
        finally:
            threading.excepthook = previous_hook
        assert errors == []
        assert client.socket is None and not client.is_connected
