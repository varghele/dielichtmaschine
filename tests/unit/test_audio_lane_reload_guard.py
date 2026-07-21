# tests/unit/test_audio_lane_reload_guard.py
"""AudioLaneWidget.load_audio_file's same-path guard (2026-07-21).

Structure tab activation re-runs the whole song load, which used to
re-decode the same audio file and re-analyze its waveform on EVERY tab
visit (two chained worker threads, real time on real projects, and the
waveform row sat in its loading paint whenever the visit was brief -
the 720p golden suite caught the band flickering per run). Config
refresh paths now no-op when the requested path is already loaded or
loading; ``force=True`` (the explicit LOAD file dialogs) always
reloads, because the user may be re-picking a file that changed on
disk. clear_audio resets the path, so a no-audio song in between never
leaves the guard stuck.

The loader thread is observed, not run: load_audio_file is judged by
whether it spawns a NEW AudioLoaderThread instance.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def lane(qapp, tmp_path):
    from timeline_ui.audio_lane_widget import AudioLaneWidget
    widget = AudioLaneWidget()
    yield widget
    if widget.audio_loader_thread is not None:
        widget.audio_loader_thread.quit()
        widget.audio_loader_thread.wait()
    widget.deleteLater()


@pytest.fixture
def wav(tmp_path):
    """A tiny valid-enough file; the loader thread may fail on it later,
    but the guard decides BEFORE the thread starts and the tests only
    compare thread identities."""
    path = tmp_path / "song.wav"
    path.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
    return str(path)


class TestSamePathGuard:

    def test_second_call_same_path_is_a_no_op(self, lane, wav):
        lane.load_audio_file(wav)
        first_thread = lane.audio_loader_thread
        assert first_thread is not None
        lane.load_audio_file(wav)          # tab-activation refresh
        assert lane.audio_loader_thread is first_thread

    def test_force_reloads_the_same_path(self, lane, wav):
        lane.load_audio_file(wav)
        first_thread = lane.audio_loader_thread
        lane.load_audio_file(wav, force=True)
        assert lane.audio_loader_thread is not first_thread

    def test_different_path_reloads(self, lane, wav, tmp_path):
        lane.load_audio_file(wav)
        first_thread = lane.audio_loader_thread
        other = tmp_path / "other.wav"
        other.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
        lane.load_audio_file(str(other))
        assert lane.audio_loader_thread is not first_thread
        assert lane.audio_file_path == str(other)

    def test_clear_audio_rearms_the_guard(self, lane, wav):
        lane.load_audio_file(wav)
        first_thread = lane.audio_loader_thread
        if first_thread is not None:
            first_thread.quit()
            first_thread.wait()
        lane.clear_audio()                 # no-audio song selected
        lane.load_audio_file(wav)          # back to the audio song
        assert lane.audio_loader_thread is not first_thread
        assert lane.audio_file_path == wav

    def test_guard_holds_after_load_completes(self, lane, wav):
        from audio.audio_file import AudioFile
        lane.load_audio_file(wav)
        first_thread = lane.audio_loader_thread
        if first_thread is not None:
            first_thread.quit()
            first_thread.wait()
        lane._is_loading_audio = False
        lane.audio_file = object.__new__(AudioFile)  # "loaded" marker
        lane.load_audio_file(wav)
        assert lane.audio_loader_thread is first_thread
