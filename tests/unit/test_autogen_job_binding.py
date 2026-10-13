# tests/unit/test_autogen_job_binding.py
"""Autogen runs are bound to the song they were launched for (v1.5.5 G8).

The worker runs for seconds. Before the fix, both autogen flows (the
Structure tab's own and the Shows/Timeline tab's) wrote the result onto
whatever song was open when generation FINISHED, handed the worker the
live config (which the generator mutates: default spots), and the
Structure tab's locked-song exit left the button stuck on
GENERATING... while its header refresh could re-enable it mid-run and
start a second worker over the first.

Workers are faked (no thread, no audio): a fake records what it was
given and the test delivers its result by emitting its signals.
"""

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QDialog, QMessageBox

from config.models import (Configuration, FixtureGroup, LightLane, ShowPart,
                           Song, Spot, TimelineData)


class FakeAutogenDialog:
    """Accepts at once with default parameters."""

    def __init__(self, parent=None):
        self.result_config = None
        self.result_key_signature = None
        self.result_palette = None

    def exec(self):
        return QDialog.DialogCode.Accepted


class FakeAutogenWorker(QObject):
    """Stands in for AutogenWorker: never runs, records its inputs."""
    generated = pyqtSignal(list, object)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    finished = pyqtSignal()

    instances = []

    def __init__(self, audio_path, song_structure, config, *rest):
        super().__init__()
        self.config = config
        self.running = False
        FakeAutogenWorker.instances.append(self)

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def deliver(self, lanes, report=None):
        """The worker's run() returning: result first, then QThread's
        own finished (the order Qt delivers them in)."""
        self.running = False
        self.generated.emit(lanes, report)
        self.finished.emit()

    def fail(self, message):
        self.running = False
        self.error.emit(message)
        self.finished.emit()


@pytest.fixture
def fakes(monkeypatch):
    import gui.dialogs.autogen_dialog as autogen_dialog
    FakeAutogenWorker.instances = []
    monkeypatch.setattr(autogen_dialog, "AutogenDialog", FakeAutogenDialog)
    monkeypatch.setattr(autogen_dialog, "AutogenWorker", FakeAutogenWorker)
    infos = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: infos.append(a[2])))
    monkeypatch.setattr(QMessageBox, "critical",
                        staticmethod(lambda *a, **k: infos.append(a[2])))
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    return infos


def _song(name):
    return Song(
        name=name,
        parts=[ShowPart(name="Intro", color="#FF0000", signature="4/4",
                        bpm=120.0, num_bars=4, transition="instant")],
        effects=[],
        timeline_data=TimelineData(),
    )


def _generated_lane(name="Auto - G"):
    return LightLane(name=name, fixture_targets=["G"], light_blocks=[])


def two_song_config(sample_fixture=None):
    config = Configuration()
    fixtures = [sample_fixture] if sample_fixture is not None else []
    config.fixtures = list(fixtures)
    config.groups["G"] = FixtureGroup(name="G", fixtures=list(fixtures))
    config.songs["Alpha"] = _song("Alpha")
    config.songs["Beta"] = _song("Beta")
    return config


# ---------------------------------------------------------------------------
# The job + snapshot helpers
# ---------------------------------------------------------------------------

class TestSnapshotAndJob:

    def test_snapshot_is_private_and_keeps_group_membership(self, sample_fixture):
        from gui.dialogs.autogen_dialog import autogen_config_snapshot
        config = two_song_config(sample_fixture)
        snap = autogen_config_snapshot(config)
        assert snap is not config
        assert snap.songs == {}
        assert snap.fixtures is not config.fixtures
        assert snap.fixtures[0] is not config.fixtures[0]
        # group membership points at the COPIED fixtures
        assert snap.groups["G"].fixtures[0] is snap.fixtures[0]
        # edits to the live rig mid-run do not reach the snapshot
        config.fixtures.clear()
        config.groups.clear()
        assert len(snap.fixtures) == 1 and "G" in snap.groups
        # the live project's songs are untouched
        assert set(config.songs) == {"Alpha", "Beta"}

    def test_generator_default_spots_stay_on_the_snapshot(self):
        from autogen.spatial import ensure_default_spots
        from gui.dialogs.autogen_dialog import AutogenJob
        config = two_song_config()
        job = AutogenJob(config, config.songs["Alpha"])
        ensure_default_spots(job.snapshot)        # what the worker does
        assert config.spots == {}
        job.adopt_new_spots()                     # on apply, UI thread
        assert set(config.spots) == {"Crowd", "Stage"}

    def test_adopt_never_overwrites_or_resurrects_spots(self):
        from gui.dialogs.autogen_dialog import AutogenJob
        config = two_song_config()
        config.spots["Mine"] = Spot(name="Mine", x=1.0, y=2.0, z=0.0)
        job = AutogenJob(config, config.songs["Alpha"])
        del config.spots["Mine"]                  # user deletes it mid-run
        job.adopt_new_spots()
        assert "Mine" not in config.spots

    def test_song_name_follows_rename_and_drops_on_delete_or_reload(self):
        from gui.dialogs.autogen_dialog import AutogenJob
        config = two_song_config()
        song = config.songs["Alpha"]
        job = AutogenJob(config, song)
        assert job.song_name(config) == "Alpha"
        config.songs["Renamed"] = config.songs.pop("Alpha")
        assert job.song_name(config) == "Renamed"
        assert job.song_name(two_song_config()) is None   # project reloaded
        del config.songs["Renamed"]
        assert job.song_name(config) is None

    def test_worker_result_signal_does_not_shadow_qthread_finished(self):
        from PyQt6.QtCore import QThread
        from gui.dialogs.autogen_dialog import AutogenWorker
        worker = AutogenWorker("a.wav", object(), Configuration(), None,
                               None, None)
        meta = worker.metaObject()
        finished = [bytes(meta.method(i).methodSignature()).decode()
                    for i in range(meta.methodCount())
                    if bytes(meta.method(i).name()).decode() == "finished"]
        assert finished == ["finished()"]
        assert hasattr(worker, "generated")
        assert type(worker).finished is QThread.finished


# ---------------------------------------------------------------------------
# Structure tab's own autogen flow
# ---------------------------------------------------------------------------

@pytest.fixture
def structure_tab(qapp, fakes, monkeypatch):
    from gui.tabs.structure_tab import StructureTab
    with patch("utils.midi_utils.discover_midi_profiles", return_value=[]):
        tab = StructureTab(two_song_config(), parent=None)
    tab.update_from_config()
    tab._load_show("Alpha")
    monkeypatch.setattr(tab, "_shows_tab_delegate", lambda: None)
    monkeypatch.setattr(tab, "_autogen_audio_path", lambda: "song.wav")
    yield tab
    tab.cleanup()
    tab.deleteLater()


class TestStructureTabAutogen:

    def test_result_lands_on_the_launch_song(self, structure_tab):
        tab = structure_tab
        tab.autogen_btn.click()
        worker = FakeAutogenWorker.instances[-1]
        assert worker.config is not tab.config            # a snapshot
        tab._load_show("Beta")                            # user moves on
        worker.deliver([_generated_lane()])
        alpha = tab.config.songs["Alpha"].timeline_data.lanes
        beta = tab.config.songs["Beta"].timeline_data.lanes
        assert [lane.name for lane in alpha] == ["Auto - G"]
        assert beta == []

    def test_default_spots_reach_the_project_on_apply(self, structure_tab):
        from autogen.spatial import ensure_default_spots
        tab = structure_tab
        tab.autogen_btn.click()
        worker = FakeAutogenWorker.instances[-1]
        ensure_default_spots(worker.config)
        assert tab.config.spots == {}
        worker.deliver([_generated_lane()])
        assert set(tab.config.spots) == {"Crowd", "Stage"}

    def test_locked_launch_song_resets_the_button(self, structure_tab):
        tab = structure_tab
        tab.autogen_btn.click()
        assert tab.autogen_btn.text() == "GENERATING..."
        tab.config.songs["Alpha"].locked = True
        FakeAutogenWorker.instances[-1].deliver([_generated_lane()])
        assert tab.autogen_btn.text() == "AUTOGENERATE SONG..."
        assert tab.config.songs["Alpha"].timeline_data.lanes == []

    def test_error_resets_the_button(self, structure_tab, fakes):
        tab = structure_tab
        tab.autogen_btn.click()
        FakeAutogenWorker.instances[-1].fail("boom")
        assert tab.autogen_btn.text() == "AUTOGENERATE SONG..."
        assert tab.autogen_btn.isEnabled()
        assert any("boom" in text for text in fakes)

    def test_header_refresh_mid_run_cannot_start_a_second_worker(
            self, structure_tab):
        tab = structure_tab
        tab.autogen_btn.click()
        tab._load_show("Beta")            # header refresh re-gates buttons
        assert not tab.autogen_btn.isEnabled()
        tab._on_autogenerate()
        assert len(FakeAutogenWorker.instances) == 1

    def test_deleted_launch_song_discards_the_result(self, structure_tab,
                                                     fakes):
        tab = structure_tab
        tab.autogen_btn.click()
        tab._load_show("Beta")
        del tab.config.songs["Alpha"]
        FakeAutogenWorker.instances[-1].deliver([_generated_lane()])
        assert tab.config.songs["Beta"].timeline_data.lanes == []
        assert any("no longer" in text for text in fakes)
        assert tab.autogen_btn.text() == "AUTOGENERATE SONG..."

    def test_thread_end_without_result_still_resets_the_button(
            self, structure_tab):
        tab = structure_tab
        tab.autogen_btn.click()
        worker = FakeAutogenWorker.instances[-1]
        worker.running = False
        worker.finished.emit()            # run() died without a signal
        assert tab.autogen_btn.text() == "AUTOGENERATE SONG..."
        assert not tab._autogen_running()


# ---------------------------------------------------------------------------
# Shows (Timeline) tab's autogen flow
# ---------------------------------------------------------------------------

@pytest.fixture
def shows_tab(qapp, fakes, monkeypatch, sample_fixture, tmp_path):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QApplication
    from gui.theme_manager import ThemeManager
    from tests.unit.test_shows_tab_chrome import _stub_heavy_widgets

    _stub_heavy_widgets(monkeypatch)
    ThemeManager().apply(qapp, "dark")
    from gui.tabs.shows_tab import ShowsTab
    tab = ShowsTab(two_song_config(sample_fixture), parent=None)
    tab.artnet_enabled = False
    tab.tcp_enabled = False
    tab._load_show("Alpha")
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"RIFF")
    monkeypatch.setattr(tab.audio_lane, "get_audio_file_path",
                        lambda: str(audio))
    try:
        yield tab
    finally:
        tab.cleanup()
        tab.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        QApplication.processEvents()


class TestShowsTabAutogen:

    def test_result_lands_on_the_launch_song(self, shows_tab):
        tab = shows_tab
        tab._on_autogenerate()
        worker = FakeAutogenWorker.instances[-1]
        assert worker.config is not tab.config            # a snapshot
        tab._load_show("Beta")
        worker.deliver([_generated_lane()])
        alpha = tab.config.songs["Alpha"].timeline_data.lanes
        assert [lane.name for lane in alpha] == ["Auto - G"]
        # nothing appeared on the open song, on screen or in the model
        assert tab.lane_widgets == []
        assert tab.config.songs["Beta"].timeline_data.lanes == []
        assert tab.autogen_btn.text() == "AUTOGEN"

    def test_current_song_path_still_builds_lane_widgets(self, shows_tab):
        tab = shows_tab
        tab._on_autogenerate()
        FakeAutogenWorker.instances[-1].deliver([_generated_lane()])
        assert [w.lane.name for w in tab.lane_widgets] == ["Auto - G"]
        assert [lane.name for lane in
                tab.config.songs["Alpha"].timeline_data.lanes] == ["Auto - G"]

    def test_lock_check_uses_the_launch_song(self, shows_tab):
        tab = shows_tab
        tab._on_autogenerate()
        tab.config.songs["Alpha"].locked = True
        tab._load_show("Beta")                 # open song is NOT locked
        FakeAutogenWorker.instances[-1].deliver([_generated_lane()])
        assert tab.config.songs["Alpha"].timeline_data.lanes == []

    def test_error_on_a_locked_song_keeps_the_button_disabled(self, shows_tab):
        tab = shows_tab
        tab._on_autogenerate()
        tab.config.songs["Alpha"].locked = True
        FakeAutogenWorker.instances[-1].fail("boom")
        assert tab.autogen_btn.text() == "AUTOGEN"
        assert not tab.autogen_btn.isEnabled()

    def test_second_launch_refused_while_running(self, shows_tab):
        tab = shows_tab
        tab._on_autogenerate()
        tab._on_autogenerate()
        assert len(FakeAutogenWorker.instances) == 1
