# tests/unit/test_audio_loader_lifetime.py
"""Audio loader + waveform generator thread lifetimes (v1.5.5 G8).

Before the fix, a new load "cancelled" the previous one with
quit()/wait(): quit() does nothing to a run() without an event loop,
so wait() froze the UI for the rest of the old decode - and the old
thread's queued ``audio_loaded`` still landed afterwards. clear_audio
(a song without audio) did not touch the loader at all, so the previous
song's audio landed on the new song. The waveform widget replaced the
only reference to a still-running generator thread, which aborts the
process ("QThread: Destroyed while thread is still running").

Threads here are real QThreads whose run() blocks on a gate the test
opens, so the ordering is deterministic. Also pinned: the ``audio``
package no longer imports QtWidgets just because a Qt-free submodule
(``audio.spectral_analysis``, used by autogen and the headless morph
CLI) was imported.
"""

import gc
import os
import subprocess
import sys
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QThread, pyqtSignal

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


class FakeAudio:
    """Payload a loader delivers. is_loaded() False keeps the waveform
    widget from starting a real analysis."""

    def __init__(self, path, loaded=False):
        self.path = path
        self._loaded = loaded

    def is_loaded(self):
        return self._loaded


class GatedLoader(QThread):
    audio_loaded = pyqtSignal(object)
    error_occurred = pyqtSignal(str)
    instances = []

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self.gate = threading.Event()
        GatedLoader.instances.append(self)

    def run(self):
        self.gate.wait(10)
        self.audio_loaded.emit(FakeAudio(self.file_path))


class GatedGenerator(QThread):
    waveform_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(str)
    instances = []

    def __init__(self, audio_file, analyzer):
        super().__init__()
        self.audio_file = audio_file
        self.gate = threading.Event()
        GatedGenerator.instances.append(self)

    def run(self):
        self.gate.wait(10)
        self.waveform_ready.emit(("waveform", self.audio_file.path))


def _finish(qapp, thread):
    thread.gate.set()
    assert thread.wait(5000)
    qapp.processEvents()


def _release_all(threads):
    for thread in threads:
        thread.gate.set()
    for thread in threads:
        thread.wait(5000)


@pytest.fixture
def lane(qapp, monkeypatch, tmp_path):
    import timeline_ui.audio_lane_widget as lane_module
    GatedLoader.instances = []
    monkeypatch.setattr(lane_module, "AudioLoaderThread", GatedLoader)
    widget = lane_module.AudioLaneWidget()
    paths = []
    for name in ("a.wav", "b.wav"):
        path = tmp_path / name
        path.write_bytes(b"RIFF")
        paths.append(str(path))
    yield widget, paths
    _release_all(GatedLoader.instances)
    qapp.processEvents()
    widget.deleteLater()


class TestAudioLoader:

    def test_a_new_load_does_not_block_on_the_old_decode(self, lane, qapp):
        widget, (a, b) = lane
        widget.load_audio_file(a)
        started = time.monotonic()
        widget.load_audio_file(b)
        assert time.monotonic() - started < 2.0

    def test_superseded_result_does_not_land(self, lane, qapp):
        widget, (a, b) = lane
        widget.load_audio_file(a)
        widget.load_audio_file(b)
        first, second = GatedLoader.instances
        _finish(qapp, first)
        assert widget.audio_file is None
        assert widget.audio_file_path == b
        _finish(qapp, second)
        assert widget.audio_file.path == b

    def test_clear_audio_drops_the_load_in_flight(self, lane, qapp):
        widget, (a, _b) = lane
        widget.load_audio_file(a)
        widget.clear_audio()                 # song without audio opened
        assert widget.load_button.isEnabled()
        _finish(qapp, GatedLoader.instances[0])
        assert widget.audio_file is None
        assert widget.audio_file_path == ""
        assert widget.file_path_edit.text() == ""

    def test_superseded_loader_stays_alive_until_it_ends(self, lane, qapp):
        from audio.audio_waveform_widget import _PARKED_THREADS
        widget, (a, b) = lane
        widget.load_audio_file(a)
        widget.load_audio_file(b)
        gc.collect()
        first = GatedLoader.instances[0]
        assert first.isRunning()
        assert first in _PARKED_THREADS


@pytest.fixture
def waveform(qapp, monkeypatch):
    import audio.audio_waveform_widget as waveform_module
    GatedGenerator.instances = []
    monkeypatch.setattr(waveform_module, "WaveformGeneratorThread",
                        GatedGenerator)
    widget = waveform_module.AudioWaveformWidget()
    yield widget
    _release_all(GatedGenerator.instances)
    qapp.processEvents()
    widget.deleteLater()


class TestWaveformGenerator:

    def test_superseded_analysis_is_parked_and_ignored(self, waveform, qapp):
        waveform.load_audio_file(FakeAudio("a", loaded=True))
        waveform.load_audio_file(FakeAudio("b", loaded=True))
        gc.collect()                         # old code aborts around here
        first, second = GatedGenerator.instances
        assert first.isRunning()
        _finish(qapp, first)
        assert waveform.waveform_data is None
        assert waveform.is_loading
        _finish(qapp, second)
        assert waveform.waveform_data == ("waveform", "b")
        assert not waveform.is_loading


def test_audio_submodule_import_does_not_pull_in_qtwidgets():
    code = ("import sys, audio.spectral_analysis; "
            "print('PyQt6.QtWidgets' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


def test_package_exports_still_resolve():
    import audio
    for name in audio.__all__:
        assert getattr(audio, name) is not None
    from audio import AudioLoaderThread, AudioWaveformWidget
    from audio.audio_waveform_widget import (
        AudioLoaderThread as direct_loader)
    assert AudioLoaderThread is direct_loader
    assert AudioWaveformWidget.__name__ == "AudioWaveformWidget"
    with pytest.raises(AttributeError):
        audio.NoSuchThing


def test_wait_parked_threads_lets_them_end(qapp):
    from audio.audio_waveform_widget import (_PARKED_THREADS,
                                             park_running_thread,
                                             wait_parked_threads)
    thread = GatedLoader("x.wav")
    thread.start()
    park_running_thread(thread)
    assert thread in _PARKED_THREADS
    threading.Timer(0.05, thread.gate.set).start()
    wait_parked_threads(5000)
    assert not thread.isRunning()
    assert thread not in _PARKED_THREADS


def test_main_window_close_waits_for_uninterruptible_workers(qapp):
    """Quitting the app must not tear down a running autogen worker or a
    parked decode (a running QThread destroyed at exit aborts)."""
    from types import SimpleNamespace
    from PyQt6.QtGui import QCloseEvent
    from audio.audio_waveform_widget import park_running_thread
    from gui.gui import MainWindow

    autogen = GatedLoader("autogen")
    parked = GatedLoader("parked")
    for thread in (autogen, parked):
        thread.start()
    park_running_thread(parked)
    shell = SimpleNamespace(
        shows_tab=SimpleNamespace(_autogen_worker=autogen),
        structure_tab=SimpleNamespace(_autogen_worker=None))
    for thread in (autogen, parked):
        threading.Timer(0.05, thread.gate.set).start()
    event = QCloseEvent()
    MainWindow.closeEvent(shell, event)
    assert event.isAccepted()
    assert not autogen.isRunning()
    assert not parked.isRunning()
