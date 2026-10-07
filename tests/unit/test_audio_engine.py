"""Smoke tests for the sounddevice playback path (v1.5.5 hardening, G10).

``audio/audio_engine.py`` and ``audio/playback_synchronizer.py`` back the
Shows tab's fallback audio player and had no test. The PortAudio stream
is replaced by a fake, and the real-time callback is driven by hand, so
nothing here opens an audio device.

Bug pinned here: the engine promised a position report "every ~100ms"
but only fired when ``current_frame % 4410 == 0``. With the default
512-frame blocks the frame counter is a multiple of 4410 once every
2205 blocks (~25.6 s), and never at all after a seek to an odd frame.
It now reports whenever a block crosses a 100 ms boundary.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import audio.audio_engine as audio_engine_mod
from audio.audio_engine import AudioEngine


class FakeStream:
    """Stands in for sounddevice.OutputStream: records lifecycle calls."""

    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.active = False
        self.calls = []
        FakeStream.instances.append(self)

    def start(self):
        self.calls.append("start")
        self.active = True

    def abort(self):
        self.calls.append("abort")
        self.active = False

    def close(self):
        self.calls.append("close")
        self.active = False


class FakeMixer:
    """Mixer double: a constant signal plus a log of seeks and resets."""

    def __init__(self, value=0.25):
        self.value = value
        self.seeks = []
        self.resets = 0

    def mix_frames(self, frames):
        return np.full((frames, 2), self.value, dtype=np.float32)

    def seek_all_lanes(self, t):
        self.seeks.append(t)

    def reset_all_lanes(self):
        self.resets += 1


@pytest.fixture
def fake_sd(monkeypatch):
    FakeStream.instances.clear()
    monkeypatch.setattr(audio_engine_mod.sd, "OutputStream", FakeStream)
    return FakeStream


@pytest.fixture
def engine(fake_sd):
    eng = AudioEngine(sample_rate=44100, buffer_size=512)
    assert eng.initialize()
    eng.set_mixer(FakeMixer())
    yield eng
    eng.cleanup()


def _pump(eng, blocks, frames=512):
    """Run the real-time callback ``blocks`` times; return the last buffer."""
    out = np.ones((frames, 2), dtype=np.float32)
    for _ in range(blocks):
        eng._audio_callback(out, frames, None, None)
    return out


class TestLifecycle:
    def test_initialize_opens_a_stereo_float_stream_with_the_callback(self, engine, fake_sd):
        stream = fake_sd.instances[-1]
        assert stream.kwargs["channels"] == 2
        assert stream.kwargs["dtype"] == "float32"
        assert stream.kwargs["samplerate"] == 44100
        assert stream.kwargs["blocksize"] == 512
        assert stream.kwargs["callback"] == engine._audio_callback

    def test_initialize_failure_reports_false_and_stays_uninitialised(self, monkeypatch):
        def boom(**kwargs):
            raise RuntimeError("no device")
        monkeypatch.setattr(audio_engine_mod.sd, "OutputStream", boom)
        eng = AudioEngine()
        assert eng.initialize() is False
        assert eng.start_playback(0.0) is False

    def test_start_seeks_mixer_and_starts_stream(self, engine, fake_sd):
        assert engine.start_playback(2.0)
        assert engine.is_playing()
        assert engine.get_current_position() == pytest.approx(2.0)
        assert engine.mixer.seeks == [2.0]
        assert fake_sd.instances[-1].active

    def test_pause_keeps_position_stop_rewinds(self, engine):
        engine.start_playback(1.0)
        _pump(engine, 10)
        engine.pause_playback()
        assert not engine.is_playing()
        paused_at = engine.get_current_position()
        assert paused_at == pytest.approx(1.0 + 5120 / 44100)
        engine.stop_playback()
        assert engine.get_current_position() == 0.0
        assert engine.mixer.resets == 1

    def test_cleanup_closes_the_stream(self, fake_sd):
        eng = AudioEngine()
        eng.initialize()
        stream = fake_sd.instances[-1]
        eng.cleanup()
        assert "close" in stream.calls
        assert eng._sd_stream is None


class TestCallback:
    def test_silence_while_not_playing(self, engine):
        out = _pump(engine, 1)
        assert not out.any()

    def test_plays_mixed_audio_and_advances(self, engine):
        engine.start_playback(0.0)
        out = _pump(engine, 4)
        assert np.allclose(out, 0.25)
        assert engine.get_current_position() == pytest.approx(4 * 512 / 44100)

    def test_seek_lands_on_the_next_block(self, engine):
        engine.start_playback(0.0)
        engine.seek(10.0)
        _pump(engine, 1)
        assert engine.mixer.seeks[-1] == pytest.approx(10.0)
        assert engine.get_current_position() == pytest.approx(10.0 + 512 / 44100)

    def test_mixer_error_outputs_silence_instead_of_raising(self, engine):
        def broken(frames):
            raise RuntimeError("decoder hiccup")
        engine.start_playback(0.0)
        engine.mixer.mix_frames = broken
        out = _pump(engine, 1)
        assert not out.any()

    @pytest.mark.parametrize("block", [512, 256, 1024, 441])
    def test_position_reported_about_every_100ms(self, engine, block):
        reports = []
        engine.set_position_callback(reports.append)
        engine.start_playback(0.0)
        seconds = 3.0
        _pump(engine, int(seconds * 44100 / block), frames=block)
        # ~10 reports per second whatever the block size; the old modulo
        # test produced none at all for 512/256/1024 within 3 s.
        assert len(reports) == pytest.approx(seconds * 10, abs=1)
        assert reports == sorted(reports)
        assert all(0.0 < p <= seconds + 0.1 for p in reports)

    def test_position_reports_survive_an_odd_seek(self, engine):
        reports = []
        engine.set_position_callback(reports.append)
        engine.start_playback(0.0)
        engine.seek(1.0 + 1 / 44100)   # odd frame number
        _pump(engine, 100)
        assert len(reports) >= 10

    def test_callback_errors_never_reach_the_audio_thread(self, engine):
        def bad(position):
            raise ValueError("ui gone")
        engine.set_position_callback(bad)
        engine.start_playback(0.0)
        _pump(engine, 50)   # must not raise
        assert engine.is_playing()


class TestPlaybackSynchronizer:
    @pytest.fixture
    def sync(self, qapp, engine):
        from audio.audio_mixer import AudioMixer
        from audio.playback_synchronizer import PlaybackSynchronizer
        sync = PlaybackSynchronizer(engine, AudioMixer())
        yield sync
        sync._drift_check_timer.stop()

    def test_wires_mixer_and_position_callback_into_the_engine(self, sync, engine):
        assert engine.mixer is sync.audio_mixer
        assert engine._position_callback == sync._on_audio_position_update

    def test_play_pause_stop_drive_engine_and_drift_timer(self, sync, engine):
        assert sync.on_play_requested(1.5)
        assert engine.is_playing()
        assert sync._drift_check_timer.isActive()
        assert sync.get_accurate_position() == pytest.approx(1.5)

        sync.on_pause_requested()
        assert not engine.is_playing()
        assert not sync._drift_check_timer.isActive()

        sync.on_play_requested(0.0)
        sync.on_stop_requested()
        assert sync.get_accurate_position() == 0.0
        assert not sync._drift_check_timer.isActive()

    def test_play_reports_failure_when_engine_cannot_start(self, qapp, fake_sd):
        from audio.audio_mixer import AudioMixer
        from audio.playback_synchronizer import PlaybackSynchronizer
        uninitialised = AudioEngine()
        sync = PlaybackSynchronizer(uninitialised, AudioMixer())
        assert sync.on_play_requested(0.0) is False
        assert not sync._drift_check_timer.isActive()

    def test_seek_forwards_to_the_engine(self, sync, engine):
        sync.on_play_requested(0.0)
        sync.on_seek_requested(42.0)
        _pump(engine, 1)
        assert engine.get_current_position() == pytest.approx(42.0 + 512 / 44100)

    def test_audio_thread_position_is_reemitted_as_a_signal(self, sync):
        seen = []
        sync.position_updated.connect(seen.append)
        sync._on_audio_position_update(3.25)
        assert seen == [3.25]

    def test_update_lanes_skips_lanes_without_audio(self, sync):
        class Lane:
            audio_file_path = ""
            volume = 1.0
            muted = False
            solo = False
        sync.update_lanes([Lane(), Lane()])
        assert sync.audio_mixer.get_lane_count() == 0

    def test_lane_controls_on_unknown_lanes_are_harmless(self, sync):
        sync.update_lane_volume(123, 0.5)
        sync.update_lane_mute(123, True)
        sync.update_lane_solo(123, True)
        assert sync.audio_mixer.get_lane_count() == 0
