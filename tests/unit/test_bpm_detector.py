"""Tests for the Auto Mode BPM detectors (auto/bpm_detector.py).

Covers TapBPM (tap tempo) and AutoBPMDetector (autocorrelation over the
live onset-flux stream). Both classes read time.monotonic(), so the tests
swap the module's `time` reference for a fake clock: everything is
deterministic and runs instantly, no sleeping.

These tests double as the correctness evidence for extracting the beat
tracker into a standalone package; the characterization companion is
scripts/evaluate_bpm_detector.py.
"""

import numpy as np
import pytest

import auto.bpm_detector as bpm_detector
from auto.bpm_detector import TapBPM, AutoBPMDetector
from audio.realtime_spectral import LiveFeatureFrame

RATE = 86.0  # LiveFeatureFrames per second (44100 Hz / 512 hop)


class FakeTime:
    """Stand-in for the `time` module: only monotonic() is used."""

    def __init__(self, start: float = 1000.0):
        self._t = start

    def monotonic(self) -> float:
        return self._t

    def advance(self, dt: float):
        self._t += dt


@pytest.fixture
def fake_time(monkeypatch):
    ft = FakeTime()
    monkeypatch.setattr(bpm_detector, "time", ft)
    return ft


def make_frame(flux: float) -> LiveFeatureFrame:
    # The detector consumes the raw (unnormalized) flux channel; the
    # display `flux` field is deliberately left at a constant here so a
    # regression to reading it would break the click-train tests.
    return LiveFeatureFrame(
        timestamp=0.0, flux=0.5, transient=0.0, richness=0.0,
        vocal=0.0, centroid=0.0, rms=0.0, contrast=0.0,
        flux_raw=flux,
    )


def feed_click_train(det, fake_time, bpm, seconds, noise=0.0, rng=None):
    """Feed a synthetic onset-flux click train at the given tempo."""
    n = int(seconds * RATE)
    period = 60.0 * RATE / bpm  # frames per beat
    next_click = 0.0
    for i in range(n):
        flux = float(rng.random()) * noise if rng is not None else 0.0
        if i >= next_click:
            flux += 1.0
            next_click += period
        det.on_feature(make_frame(flux))
        fake_time.advance(1.0 / RATE)


class TestTapBPM:
    def do_taps(self, tap, fake_time, intervals):
        """First tap immediately, then one tap after each interval."""
        results = [tap.tap()]
        for iv in intervals:
            fake_time.advance(iv)
            results.append(tap.tap())
        return results

    def test_fewer_than_three_taps_returns_none(self, fake_time):
        tap = TapBPM()
        results = self.do_taps(tap, fake_time, [0.5])
        assert results == [None, None]

    def test_steady_120_bpm(self, fake_time):
        tap = TapBPM()
        results = self.do_taps(tap, fake_time, [0.5] * 5)
        assert results[-1] == pytest.approx(120.0, abs=0.01)

    def test_steady_90_bpm(self, fake_time):
        tap = TapBPM()
        results = self.do_taps(tap, fake_time, [60.0 / 90.0] * 5)
        assert results[-1] == pytest.approx(90.0, abs=0.01)

    def test_timeout_resets_history(self, fake_time):
        tap = TapBPM(timeout=3.0)
        self.do_taps(tap, fake_time, [0.5] * 4)
        fake_time.advance(5.0)  # past the timeout
        assert tap.tap() is None  # history cleared, this is tap #1 again
        fake_time.advance(0.5)
        assert tap.tap() is None  # tap #2

    def test_single_missed_tap_is_filtered_as_outlier(self, fake_time):
        # Six 0.5 s intervals and one 1.0 s gap (a missed tap): the outlier
        # interval is > 2 sigma from the median and must not drag the BPM.
        tap = TapBPM()
        intervals = [0.5, 0.5, 0.5, 1.0, 0.5, 0.5, 0.5]
        results = self.do_taps(tap, fake_time, intervals)
        assert results[-1] == pytest.approx(120.0, abs=0.5)

    def test_sliding_window_adapts_to_tempo_change(self, fake_time):
        # Old 120 BPM taps fall out of the 8-tap window after enough
        # 150 BPM taps; the estimate must converge on the new tempo.
        tap = TapBPM(max_taps=8)
        self.do_taps(tap, fake_time, [0.5] * 4)
        results = self.do_taps(tap, fake_time, [0.4] * 10)[1:]
        assert results[-1] == pytest.approx(150.0, abs=0.5)

    def test_clipped_to_upper_bound(self, fake_time):
        tap = TapBPM()
        results = self.do_taps(tap, fake_time, [0.1] * 5)  # 600 BPM raw
        assert results[-1] == pytest.approx(300.0)

    def test_clipped_to_lower_bound(self, fake_time):
        tap = TapBPM(timeout=3.0)
        results = self.do_taps(tap, fake_time, [2.5] * 5)  # 24 BPM raw
        assert results[-1] == pytest.approx(30.0)

    def test_reset_clears_history(self, fake_time):
        tap = TapBPM()
        self.do_taps(tap, fake_time, [0.5] * 4)
        tap.reset()
        fake_time.advance(0.5)
        assert tap.tap() is None


class TestAutoBPMDetector:
    # Mix of integer-lag tempi (60, 86, 120, 172 at 86 Hz) and
    # non-integer-lag tempi (100, 150, 174): the latter used to half-lock
    # with the plain ACF argmax because the fundamental's peak split
    # across two lag bins; the harmonic scoring on a fractional grid must
    # handle both.
    @pytest.mark.parametrize("bpm", [60.0, 86.0, 100.0, 120.0, 150.0, 172.0, 174.0])
    def test_detects_clean_click_train(self, fake_time, bpm):
        det = AutoBPMDetector(analysis_rate_hz=RATE)
        feed_click_train(det, fake_time, bpm, seconds=12.0)
        est = det.get_bpm()
        assert est is not None
        assert est == pytest.approx(bpm, rel=0.02)

    def test_alternating_accent_backbeat_keeps_beat_tempo(self, fake_time):
        # Kick/snare alternation modulates onset magnitude with a 2-beat
        # period; the estimate must stay at the beat rate, not half it.
        det = AutoBPMDetector(analysis_rate_hz=RATE)
        period = 60.0 * RATE / 140.0
        next_click, beat_idx = 0.0, 0
        n = int(12.0 * RATE)
        for i in range(n):
            flux = 0.0
            if i >= next_click:
                flux = 1.0 if beat_idx % 2 == 0 else 0.6
                next_click += period
                beat_idx += 1
            det.on_feature(make_frame(flux))
            fake_time.advance(1.0 / RATE)
        est = det.get_bpm()
        assert est is not None
        assert est == pytest.approx(140.0, rel=0.04)

    def test_detects_through_noise(self, fake_time):
        det = AutoBPMDetector(analysis_rate_hz=RATE)
        rng = np.random.default_rng(42)
        feed_click_train(det, fake_time, 120.0, seconds=12.0, noise=0.5, rng=rng)
        est = det.get_bpm()
        assert est is not None
        assert est == pytest.approx(120.0, abs=3.0)

    def test_confidence_high_on_clean_signal(self, fake_time):
        det = AutoBPMDetector(analysis_rate_hz=RATE)
        feed_click_train(det, fake_time, 120.0, seconds=12.0)
        assert det.confidence > 0.5

    def test_confidence_within_bounds(self, fake_time):
        det = AutoBPMDetector(analysis_rate_hz=RATE)
        feed_click_train(det, fake_time, 120.0, seconds=12.0)
        assert 0.0 <= det.confidence <= 1.0

    def test_insufficient_data_returns_none(self, fake_time):
        # The detector needs half its 8 s window before it estimates.
        det = AutoBPMDetector(analysis_rate_hz=RATE)
        feed_click_train(det, fake_time, 120.0, seconds=2.0)
        assert det.get_bpm() is None

    def test_aperiodic_noise_gives_no_estimate(self, fake_time):
        # Pure noise has no tempo; confidence must stay below the gate.
        det = AutoBPMDetector(analysis_rate_hz=RATE)
        rng = np.random.default_rng(7)
        n = int(12.0 * RATE)
        for _ in range(n):
            det.on_feature(make_frame(float(rng.random())))
            fake_time.advance(1.0 / RATE)
        assert det.get_bpm() is None

    def test_silence_gives_no_estimate(self, fake_time):
        det = AutoBPMDetector(analysis_rate_hz=RATE)
        n = int(12.0 * RATE)
        for _ in range(n):
            det.on_feature(make_frame(0.0))
            fake_time.advance(1.0 / RATE)
        assert det.get_bpm() is None

    def test_estimate_stays_within_clamp_range(self, fake_time):
        det = AutoBPMDetector(analysis_rate_hz=RATE)
        feed_click_train(det, fake_time, 55.0, seconds=12.0)
        est = det.get_bpm()
        assert est is not None
        assert 50.0 <= est <= 240.0

    def test_reset_clears_estimate(self, fake_time):
        det = AutoBPMDetector(analysis_rate_hz=RATE)
        feed_click_train(det, fake_time, 120.0, seconds=12.0)
        assert det.get_bpm() is not None
        det.reset()
        assert det.get_bpm() is None
        assert det.confidence == 0.0

    def test_recovers_after_reset(self, fake_time):
        det = AutoBPMDetector(analysis_rate_hz=RATE)
        feed_click_train(det, fake_time, 120.0, seconds=12.0)
        det.reset()
        feed_click_train(det, fake_time, 86.0, seconds=12.0)
        est = det.get_bpm()
        assert est is not None
        assert est == pytest.approx(86.0, abs=1.0)

    def test_reads_raw_flux_not_display_flux(self, fake_time):
        # Clicks only on the smoothed display channel must NOT produce an
        # estimate: the detector's onset input is flux_raw.
        det = AutoBPMDetector(analysis_rate_hz=RATE)
        n = int(12.0 * RATE)
        period = 60.0 * RATE / 120.0
        next_click = 0.0
        for i in range(n):
            display = 0.0
            if i >= next_click:
                display = 1.0
                next_click += period
            det.on_feature(LiveFeatureFrame(
                timestamp=0.0, flux=display, transient=0.0, richness=0.0,
                vocal=0.0, centroid=0.0, rms=0.0, contrast=0.0,
                flux_raw=0.0,
            ))
            fake_time.advance(1.0 / RATE)
        assert det.get_bpm() is None


class TestBeatPhase:
    def test_no_prediction_without_estimate(self, fake_time):
        det = AutoBPMDetector(analysis_rate_hz=RATE)
        assert det.get_next_beat() is None
        feed_click_train(det, fake_time, 120.0, seconds=2.0)  # too little
        assert det.get_next_beat() is None

    def test_next_beat_aligns_with_click_grid(self, fake_time):
        det = AutoBPMDetector(analysis_rate_hz=RATE)
        # Reproduce the feeder's click placement to know the truth grid.
        n = int(12.0 * RATE)
        period = 60.0 * RATE / 120.0
        clicks, next_click = [], 0.0
        for i in range(n):
            flux = 0.0
            if i >= next_click:
                flux = 1.0
                clicks.append(i)
                next_click += period
            det.on_feature(make_frame(flux))
            fake_time.advance(1.0 / RATE)
        nb = det.get_next_beat()
        assert nb is not None
        assert 0.0 <= nb <= 60.0 / 120.0 + 0.05
        # The predicted beat must land on the click grid (within ~2
        # frames: quantization + the smoothing kernel).
        t_pred = (n - 1) / RATE + nb
        grid = [(c + k * period) / RATE for c in clicks[-2:] for k in range(4)]
        assert min(abs(t_pred - g) for g in grid) < 0.035

    def test_reset_clears_phase(self, fake_time):
        det = AutoBPMDetector(analysis_rate_hz=RATE)
        feed_click_train(det, fake_time, 120.0, seconds=12.0)
        assert det.get_next_beat() is not None
        det.reset()
        assert det.get_next_beat() is None


class TestAnalyzerToDetectorWiring:
    """Regression tests for the two Auto tab wiring bugs found by
    scripts/compare_bpm_qlcplus.py: the analyzer emits frames at ~43 Hz
    (not the detector's old 86 Hz assumption), and beat tracking must run
    on the raw flux, not the 0.6 s-smoothed display flux."""

    SR = 44100

    def _make_kick_audio(self, bpm, seconds):
        sr = self.SR
        t = np.arange(int(0.09 * sr)) / sr
        freq = 150.0 * np.exp(-t * 25.0) + 45.0
        kick = np.sin(2 * np.pi * np.cumsum(freq) / sr) * np.exp(-t * 30.0) * 0.9
        n = int(seconds * sr)
        ts = np.arange(n) / sr
        audio = 0.05 * np.sin(2 * np.pi * 110.0 * ts)
        beat = 0.0
        while beat < seconds:
            i = int(beat * sr)
            j = min(n, i + kick.size)
            audio[i:j] += kick[:j - i]
            beat += 60.0 / bpm
        return audio.astype(np.float32)

    def _run_pipeline(self, audio, fake_time):
        from audio.realtime_spectral import RealtimeSpectralAnalyzer

        analyzer = RealtimeSpectralAnalyzer(sample_rate=self.SR)
        det = AutoBPMDetector(analysis_rate_hz=analyzer.beat_frame_rate_hz)
        hop, read = analyzer.hop_length, analyzer.hop_length * 2
        for start in range(0, audio.size - read + 1, read):
            chunk = audio[start:start + read]
            analyzer._push_beat_samples(chunk.astype(np.float32))
            samples = ((chunk[0::2] + chunk[1::2]) * 0.5).astype(np.float32)
            analyzer._sliding_buffer[:analyzer.n_fft - hop] = \
                analyzer._sliding_buffer[hop:]
            analyzer._sliding_buffer[analyzer.n_fft - hop:] = samples
            det.on_feature(analyzer._compute_frame())
            fake_time.advance(read / self.SR)
        return det

    def test_frame_rate_property_reflects_decimation(self):
        from audio.realtime_spectral import RealtimeSpectralAnalyzer

        analyzer = RealtimeSpectralAnalyzer(sample_rate=44100)
        assert analyzer.frame_rate_hz == pytest.approx(22050 / 512)
        # The beat-flux path is undecimated: twice the feature rate.
        assert analyzer.beat_frame_rate_hz == pytest.approx(44100 / 512)

    def test_frame_carries_beat_onset_flux(self):
        from audio.realtime_spectral import RealtimeSpectralAnalyzer

        analyzer = RealtimeSpectralAnalyzer(sample_rate=self.SR)
        rng = np.random.default_rng(3)
        frames = []
        for i in range(40):
            # Alternate quiet and loud chunks: each quiet->loud
            # transition is an onset the beat flux must spike on.
            level = 0.3 if (i // 4) % 2 else 0.003
            chunk = rng.standard_normal(1024).astype(np.float32) * level
            analyzer._push_beat_samples(chunk)
            analyzer._sliding_buffer[:analyzer.n_fft - 512] = \
                analyzer._sliding_buffer[512:]
            analyzer._sliding_buffer[analyzer.n_fft - 512:] = \
                ((chunk[0::2] + chunk[1::2]) * 0.5)
            frames.append(analyzer._compute_frame())
        # Display flux is normalized to 0-1 and smoothed; the beat flux is
        # the band-combined rising-edge onset signal (range ~0..2.4),
        # delivered as ~2 undecimated hops per feature frame, and must
        # spike on onsets rather than sit at a smoothed level.
        assert all(0.0 <= f.flux <= 1.0 for f in frames)
        assert all(len(f.flux_raw_hops) == 2 for f in frames)
        hops = [v for f in frames for v in f.flux_raw_hops]
        assert max(hops) > 0.5
        assert min(hops) == 0.0  # rising-edge signal rests at zero

    def test_end_to_end_audio_to_bpm(self, fake_time):
        # A kick pattern through the real analyzer front end at the
        # analyzer's true frame rate must read the actual tempo, not the
        # doubled estimate the old 86 Hz assumption produced. 117.5 BPM =
        # exactly 22 flux frames per beat at 43.07 Hz, so the assertion
        # isolates the wiring from the separate (known, documented)
        # half-tempo weakness at non-integer-lag tempi.
        audio = self._make_kick_audio(117.5, seconds=16.0)
        det = self._run_pipeline(audio, fake_time)
        est = det.get_bpm()
        assert est is not None
        assert est == pytest.approx(117.5, rel=0.04)
        assert det.confidence > 0.5
