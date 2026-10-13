# tests/unit/test_worker_threads.py
"""Worker-thread contracts (v1.5.5 G8).

- No QThread subclass redeclares ``finished``. A worker that did
  (AutogenWorker, RenderWorker, the add-fixture CacheWorker) hid
  QThread's own end-of-thread signal behind one it emitted as run()'s
  last line, so an exception skipped it: the add-fixture loading
  dialog's wait loop then hung forever.
- The GDTF auto-pull worker reads a snapshot of the fixtures, never the
  live config it would otherwise walk for the length of a network pull.
- The auto-pull runs on a daemon thread that quitting cancels and never
  waits on (a QThread destroyed mid-download aborted the process).
"""

import ast
import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = pathlib.Path(__file__).resolve().parents[2]
SCANNED = ("gui", "audio", "timeline_ui", "timeline", "utils", "visualizer",
           "auto", "autogen", "config")


def _qthread_subclasses_redeclaring_finished():
    hits = []
    for package in SCANNED:
        for path in (REPO / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                bases = {ast.unparse(base) for base in node.bases}
                if not any(base.endswith("QThread") for base in bases):
                    continue
                for stmt in node.body:
                    targets = (stmt.targets if isinstance(stmt, ast.Assign)
                               else [stmt.target] if isinstance(
                                   stmt, ast.AnnAssign) else [])
                    if any(isinstance(t, ast.Name) and t.id == "finished"
                           for t in targets):
                        hits.append(f"{path.relative_to(REPO)}:{node.name}")
    return hits


def test_no_qthread_subclass_shadows_finished():
    assert _qthread_subclasses_redeclaring_finished() == []


class TestDefinitionCacheWorker:

    def _run_to_end(self, qapp, worker):
        from PyQt6.QtCore import QEventLoop, QTimer
        loop = QEventLoop()
        ended = []
        worker.finished.connect(lambda: ended.append(True))
        worker.finished.connect(loop.quit)
        QTimer.singleShot(5000, loop.quit)       # never hang the suite
        worker.start()
        loop.exec()
        worker.wait(5000)
        return ended

    def test_finished_fires_when_parsing_raises(self, qapp, monkeypatch):
        import gui.tabs.fixtures_tab as fixtures_tab

        def boom(_keys):
            raise ValueError("broken definition")

        monkeypatch.setattr(fixtures_tab, "get_cached_fixture_definitions",
                            boom)
        worker = fixtures_tab.DefinitionCacheWorker("Mfr", "Model")
        assert self._run_to_end(qapp, worker) == [True]
        assert isinstance(worker.error, ValueError)

    def test_finished_fires_on_success(self, qapp, monkeypatch):
        import gui.tabs.fixtures_tab as fixtures_tab
        seen = []
        monkeypatch.setattr(fixtures_tab, "get_cached_fixture_definitions",
                            lambda keys: seen.append(keys))
        worker = fixtures_tab.DefinitionCacheWorker("Mfr", "Model")
        assert self._run_to_end(qapp, worker) == [True]
        assert seen == [{("Mfr", "Model")}]
        assert worker.error is None


class TestGdtfAutopullSnapshot:

    def test_snapshot_carries_identity_and_patched_footprint(
            self, sample_configuration):
        from utils.gdtf_share import (_footprints_for_identity,
                                      autopull_snapshot)
        config = sample_configuration
        snap = autopull_snapshot(config)
        assert snap is not config
        fixture = config.fixtures[0]
        assert (snap.fixtures[0].manufacturer, snap.fixtures[0].model) == \
            (fixture.manufacturer, fixture.model)
        assert _footprints_for_identity(snap, "TestMfr", "TestModel") == \
            _footprints_for_identity(config, "TestMfr", "TestModel") == {10}
        # live edits mid-pull do not reach the snapshot
        fixture.current_mode = "Other"
        config.fixtures.clear()
        assert _footprints_for_identity(snap, "TestMfr", "TestModel") == {10}

    def test_start_gdtf_autopull_hands_the_worker_a_snapshot(
            self, qapp, monkeypatch, sample_configuration):
        from PyQt6.QtCore import QObject
        import utils.gdtf_share as gdtf_share
        from gui.gui import MainWindow

        received = []
        monkeypatch.setattr(gdtf_share, "auto_pull_enabled", lambda: True)
        monkeypatch.setattr(gdtf_share, "stored_username", lambda: "user")
        monkeypatch.setattr(gdtf_share, "stored_password", lambda user: "pw")
        monkeypatch.setattr(
            gdtf_share, "pull_missing_gdtf",
            lambda config, dest, cancel=None: received.append(config) or [])

        class Shell(QObject):
            def __init__(self, config):
                super().__init__()
                self.config = config

            def _on_gdtf_autopull_done(self, kept):
                pass

        shell = Shell(sample_configuration)
        MainWindow._start_gdtf_autopull(shell)
        worker = shell._gdtf_autopull_worker
        worker.join(5)
        assert not worker.is_alive()
        assert len(received) == 1
        assert received[0] is not sample_configuration
        assert [f.model for f in received[0].fixtures] == ["TestModel"]


class TestGdtfAutopullQuit:
    """docs/v1.5.5-hardening-plan.md handover #3: quitting mid-pull
    destroyed a running QThread. The pull now runs on a daemon thread
    with a cancel event that closeEvent sets."""

    def _shell(self, monkeypatch, config, pull):
        from PyQt6.QtCore import QObject
        import utils.gdtf_share as gdtf_share
        monkeypatch.setattr(gdtf_share, "auto_pull_enabled", lambda: True)
        monkeypatch.setattr(gdtf_share, "stored_username", lambda: "user")
        monkeypatch.setattr(gdtf_share, "stored_password", lambda user: "pw")
        monkeypatch.setattr(gdtf_share, "pull_missing_gdtf", pull)

        class Shell(QObject):
            def __init__(self):
                super().__init__()
                self.config = config
                self.done = []
                self.shows_tab = None

            def _on_gdtf_autopull_done(self, kept):
                self.done.append(kept)

            def wait_for_background_workers(self, timeout_ms=10000):
                pass
        return Shell()

    def test_worker_is_a_daemon_thread_not_a_qthread(
            self, qapp, monkeypatch, sample_configuration):
        import threading
        from gui.gui import MainWindow
        shell = self._shell(monkeypatch, sample_configuration,
                            lambda config, dest, cancel=None: ["a.gdtf"])
        MainWindow._start_gdtf_autopull(shell)
        worker = shell._gdtf_autopull_worker
        assert isinstance(worker, threading.Thread) and worker.daemon
        worker.join(5)
        qapp.processEvents()
        assert shell.done == [["a.gdtf"]]

    def test_close_cancels_without_waiting(
            self, qapp, monkeypatch, sample_configuration):
        import threading
        import time
        from unittest import mock
        from gui.gui import MainWindow
        started, release = threading.Event(), threading.Event()
        seen_cancel = []

        def slow_pull(config, dest, cancel=None):
            started.set()
            release.wait(10)            # a request blocking on the network
            seen_cancel.append(cancel.is_set())
            return ["late.gdtf"]
        shell = self._shell(monkeypatch, sample_configuration, slow_pull)
        MainWindow._start_gdtf_autopull(shell)
        assert started.wait(5)

        t0 = time.monotonic()
        MainWindow.closeEvent(shell, mock.Mock())
        assert time.monotonic() - t0 < 2.0     # never joins the pull
        assert shell._gdtf_autopull_worker.is_alive()

        release.set()
        shell._gdtf_autopull_worker.join(5)
        qapp.processEvents()
        assert seen_cancel == [True]
        assert shell.done == []                # a cancelled pull reports nothing


class TestWaitForBackgroundWorkers:
    """MainWindow.wait_for_background_workers is closeEvent's wait AND
    what the e2e fixture calls before destroying an unclosed window: an
    autosave write still running at teardown aborted the e2e process."""

    def test_waits_for_a_running_autosave_write(self, qapp):
        import threading
        from PyQt6.QtCore import QThread
        from types import SimpleNamespace
        from gui.gui import MainWindow

        release = threading.Event()

        class Writer(QThread):
            def run(self):
                release.wait(5)
        writer = Writer()
        writer.start()
        shell = SimpleNamespace(_autosave_worker=writer, shows_tab=None,
                                structure_tab=None)
        threading.Timer(0.2, release.set).start()
        MainWindow.wait_for_background_workers(shell)
        assert writer.isFinished()

    def test_close_event_uses_it(self):
        import inspect
        from gui.gui import MainWindow
        assert "MainWindow.wait_for_background_workers(self)" in \
            inspect.getsource(MainWindow.closeEvent)
