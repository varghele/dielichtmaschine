# tests/unit/test_worker_threads.py
"""Worker-thread contracts (v1.5.5 G8).

- No QThread subclass redeclares ``finished``. A worker that did
  (AutogenWorker, RenderWorker, the add-fixture CacheWorker) hid
  QThread's own end-of-thread signal behind one it emitted as run()'s
  last line, so an exception skipped it: the add-fixture loading
  dialog's wait loop then hung forever.
- The GDTF auto-pull worker reads a snapshot of the fixtures, never the
  live config it would otherwise walk for the length of a network pull.
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
        monkeypatch.setattr(gdtf_share, "pull_missing_gdtf",
                            lambda config, dest: received.append(config) or [])

        class Shell(QObject):
            def __init__(self, config):
                super().__init__()
                self.config = config

            def _on_gdtf_autopull_done(self, kept):
                pass

        shell = Shell(sample_configuration)
        MainWindow._start_gdtf_autopull(shell)
        worker = shell._gdtf_autopull_worker
        assert worker.wait(5000)
        assert len(received) == 1
        assert received[0] is not sample_configuration
        assert [f.model for f in received[0].fixtures] == ["TestModel"]
