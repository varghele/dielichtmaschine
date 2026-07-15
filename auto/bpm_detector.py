"""
BPM detection for Auto mode — tap tempo and auto-detection from audio.
"""

import time
import numpy as np
from typing import Optional, List
from audio.realtime_spectral import LiveFeatureFrame


class TapBPM:
    """Compute BPM from user tap intervals.

    Stores the last N tap timestamps, computes median interval,
    discards outliers, and returns BPM.
    """

    def __init__(self, max_taps: int = 8, timeout: float = 3.0):
        self._max_taps = max_taps
        self._timeout = timeout
        self._timestamps: List[float] = []

    def tap(self) -> Optional[float]:
        """Register a tap and return computed BPM (or None if not enough taps).

        Returns:
            BPM if >= 3 taps within timeout, else None
        """
        now = time.monotonic()

        # Reset if too long since last tap
        if self._timestamps and (now - self._timestamps[-1]) > self._timeout:
            self._timestamps.clear()

        self._timestamps.append(now)

        # Keep only last N taps
        if len(self._timestamps) > self._max_taps:
            self._timestamps = self._timestamps[-self._max_taps:]

        if len(self._timestamps) < 3:
            return None

        # Compute intervals
        intervals = []
        for i in range(1, len(self._timestamps)):
            intervals.append(self._timestamps[i] - self._timestamps[i - 1])

        # Remove outliers (> 2σ from median)
        median = np.median(intervals)
        std = np.std(intervals)
        if std > 0:
            filtered = [iv for iv in intervals if abs(iv - median) < 2.0 * std]
        else:
            filtered = intervals

        if not filtered:
            return None

        avg_interval = np.mean(filtered)
        if avg_interval <= 0:
            return None

        bpm = 60.0 / avg_interval
        return float(np.clip(bpm, 30.0, 300.0))

    def reset(self):
        """Clear tap history."""
        self._timestamps.clear()


class AutoBPMDetector:
    """Automatic BPM detection from live audio onset flux.

    Autocorrelation of the onset strength function scored with harmonic
    (comb) reinforcement on a fractional-lag tempo grid, then an
    octave-raise walk that prefers the fastest tempo whose comb evidence
    is nearly as strong as the winner's. Updates every ~2 seconds.

    The harmonic scoring exists because a plain ACF argmax half-locks:
    at tempi whose beat period is a non-integer frame count the
    fundamental's peak splits across two lag bins and loses to the
    consolidated two-beat peak. Scoring each candidate tempo as a
    weighted sum of interpolated ACF values at 1x..4x its period makes
    the fundamental compete on all its harmonics, and evaluating on a
    fractional grid removes the lag quantization entirely (critical at
    low frame rates: 43 Hz gives only ~13 frames per beat at 190 BPM).

    The octave-raise walk exists because for a strongly periodic signal
    every subharmonic candidate (bpm/2, bpm/3) has an equally saturated
    comb, so the argmax alone tends to land an octave low. Genuine beat
    onsets at the faster tempo keep its fundamental ACF term high, while
    a mere subdivision (weaker off-beats) does not - so "raise while the
    faster candidate scores >= threshold x current" disambiguates both
    directions without a tempo prior.
    """

    def __init__(self, analysis_rate_hz: float = 86.0, window_seconds: float = 8.0,
                 octave_raise_threshold: float = 0.90):
        """
        Args:
            analysis_rate_hz: How many LiveFeatureFrames per second. Must be
                the REAL arrival rate: for RealtimeSpectralAnalyzer pass its
                `frame_rate_hz` property (~43.07 at 44100 input, because of
                the 2:1 decimation). A wrong rate scales every BPM estimate
                by the same factor.
            window_seconds: How much history to analyze
            octave_raise_threshold: A 2x/3x-faster candidate replaces the
                current one when its comb score is at least this fraction
                of the current score. Lower = more willing to double.
        """
        self._rate = analysis_rate_hz
        self._window_size = int(window_seconds * analysis_rate_hz)
        self._flux_buffer = np.zeros(self._window_size, dtype=np.float32)
        self._write_pos = 0
        self._count = 0
        self._last_analysis_time = 0.0
        self._analysis_interval = 2.0  # seconds between updates
        self._current_bpm: Optional[float] = None
        self._confidence: float = 0.0
        self._octave_raise_threshold = octave_raise_threshold
        # Last few per-analysis estimates; get_bpm() reports their median
        # so a single analysis flipping to the wrong octave (near-tied
        # comb scores on real music) doesn't flap the reported BPM. Costs
        # one extra analysis (~2 s) of lag after a genuine tempo change.
        self._recent_bpms: List[float] = []
        # Candidate tempo grid, 0.25 BPM steps over the supported range.
        self._bpm_grid = np.arange(50.0, 240.0 + 1e-9, 0.25)
        # Harmonic weights for the comb score (k = 1..4 multiples of the
        # candidate beat period). The fundamental dominates so that true
        # off-beat energy is needed to justify a faster octave.
        self._harmonic_weights = (1.0, 0.7, 0.45, 0.3)
        # Pre-ACF smoothing kernel, scaled so its absolute width (~+/-23
        # ms) is rate-independent: it absorbs human timing jitter, which
        # otherwise smears the ACF peak across more lags the finer the
        # frame rate gets.
        half = max(1, int(round(0.023 * analysis_rate_hz)))
        kernel = np.hanning(2 * half + 3)[1:-1]
        self._acf_smooth_kernel = kernel / kernel.sum()
        # Temporal tempo tracker: forward-filtered belief over the grid.
        # Transition model = small gaussian blur (tempo wobble between
        # 2 s analyses) mixed with a uniform jump probability (genuine
        # tempo changes); observation = comb scores sharpened by ^3. The
        # belief picks the BASE candidate each analysis, so a single
        # noisy analysis can't flip the estimate; the octave-raise then
        # applies fresh evidence on top.
        self._belief: Optional[np.ndarray] = None
        blur = np.exp(-0.5 * (np.arange(-7, 8) / 4.0) ** 2)
        self._belief_blur = blur / blur.sum()
        self._belief_jump_prob = 0.10
        # Beat phase: absolute frame index (fractional) of the most
        # recently identified beat, and the beat period in frames.
        # get_next_beat() extrapolates the grid from these.
        self._beat_anchor_frame: Optional[float] = None
        self._beat_period_frames: Optional[float] = None

    def on_feature(self, frame: LiveFeatureFrame):
        """Process a feature frame.

        Reads `flux_raw` (unnormalized onset strength), not the display
        `flux`: the normalized flux passes a 0.6 s output smoother that
        flattens beat-rate periodicity, which makes the autocorrelation
        peak at the shortest searched lag (a bogus 240 BPM) on real music.

        Instrument-height equalization happens upstream (the analyzer's
        per-band saturation, see LiveFeatureFrame.flux_raw), so values
        are buffered as-is. When the frame carries `flux_raw_hops` (the
        analyzer's undecimated ~86 Hz beat-flux path), every hop is
        buffered individually - construct the detector with the
        analyzer's `beat_frame_rate_hz` in that case.
        """
        values = frame.flux_raw_hops if frame.flux_raw_hops else (frame.flux_raw,)
        for value in values:
            self._flux_buffer[self._write_pos] = value
            self._write_pos = (self._write_pos + 1) % self._window_size
            self._count += 1

        # Re-analyze periodically
        now = time.monotonic()
        if (now - self._last_analysis_time) >= self._analysis_interval:
            self._last_analysis_time = now
            self._analyze()

    def get_bpm(self) -> Optional[float]:
        """Get current BPM estimate (median of the last 3 analyses), or
        None if confidence is low."""
        # Gate calibrated for the 86 Hz band-combined onset train: real
        # music scores ~0.2-0.5 (the rate-scaled smoothing spreads peak
        # energy), aperiodic noise stays well under 0.1.
        if self._confidence < 0.15:
            return None
        if not self._recent_bpms:
            return self._current_bpm
        return float(np.median(self._recent_bpms))

    def get_next_beat(self) -> Optional[float]:
        """Seconds from the most recently received frame to the next
        predicted beat, or None when there is no confident estimate.

        The value is relative to the audio position of the last
        on_feature() call; callers add their own pipeline latency. The
        beat grid extrapolates from the last analysis (up to ~2 s old),
        so expect the accuracy characterized by the phase benchmark
        (scripts/evaluate_bpm_detector.py --phase), not sample accuracy.
        """
        if (self._confidence < 0.15 or self._beat_anchor_frame is None
                or not self._beat_period_frames):
            return None
        frames_now = float(self._count - 1)
        period = self._beat_period_frames
        k = np.ceil((frames_now - self._beat_anchor_frame) / period)
        next_frame = self._beat_anchor_frame + k * period
        return float((next_frame - frames_now) / self._rate)

    @property
    def confidence(self) -> float:
        """Confidence of current BPM estimate (0-1)."""
        return self._confidence

    def reset(self):
        """Clear all state."""
        self._flux_buffer[:] = 0
        self._write_pos = 0
        self._count = 0
        self._current_bpm = None
        self._confidence = 0.0
        self._recent_bpms.clear()
        self._belief = None
        self._beat_anchor_frame = None
        self._beat_period_frames = None

    def _analyze(self):
        """Run harmonic-reinforced autocorrelation tempo estimation.

        The supported range is 50-240 BPM: wide enough to cover slow
        ballads (half-time feels) and fast punk / swing without going so
        wide that octave errors dominate. The spinbox accepts 30-300 so
        extreme tempi are still settable manually via TAP.
        """
        if self._count < self._window_size // 2:
            return  # Not enough data

        # Get the flux time series in order
        if self._count >= self._window_size:
            # Buffer is full, read in order
            signal = np.roll(self._flux_buffer, -self._write_pos)
        else:
            signal = self._flux_buffer[:self._count]

        if len(signal) < 100:
            return

        # Remove DC offset, then widen onset spikes (rate-scaled kernel,
        # ~+/-23 ms) so a beat period that falls between lag bins still
        # forms one coherent ACF peak and human timing jitter doesn't
        # smear it.
        signal = signal - np.mean(signal)
        signal = np.convolve(signal, self._acf_smooth_kernel, mode="same")

        # Autocorrelation via FFT, unbiased (each lag averaged over the
        # number of overlapping terms so long lags aren't discounted).
        n = len(signal)
        fft = np.fft.rfft(signal, n=2 * n)
        acf = np.fft.irfft(fft * np.conj(fft))[:n]
        acf = acf / (n - np.arange(n))

        if acf[0] <= 0:
            return
        acf = acf / acf[0]

        # Score every candidate tempo as a weighted sum of ACF values at
        # 1x..4x its (fractional) beat period. Each harmonic is sampled
        # as the local maximum within +/-1 lag: a real beat peak that
        # sits between lag bins (or is slightly detuned) still counts at
        # full height, while a genuinely weak off-beat stays weak - this
        # is what keeps the octave-raise ratio discriminative.
        periods = self._rate * 60.0 / self._bpm_grid
        lags = np.arange(n, dtype=np.float64)
        max_usable = n - 1
        scores = np.zeros_like(self._bpm_grid)
        weight_used = np.zeros_like(self._bpm_grid)
        offsets = (-1.0, -0.5, 0.0, 0.5, 1.0)
        for k, w in enumerate(self._harmonic_weights, start=1):
            h = k * periods
            valid = h <= max_usable
            if not np.any(valid):
                continue
            peak = np.max(
                [np.interp(np.clip(h[valid] + o, 0, max_usable), lags, acf)
                 for o in offsets], axis=0)
            scores[valid] += w * peak
            weight_used[valid] += w
        usable = weight_used > 0
        if not np.any(usable):
            return
        scores[usable] /= weight_used[usable]

        # Temporal filtering: predict (blur + jump) then update with the
        # sharpened scores. The belief argmax is the stable base; a real
        # tempo change wins within a few analyses via the jump mass.
        obs = scores.astype(np.float64) ** 3 + 1e-9
        if self._belief is None:
            self._belief = obs / obs.sum()
        else:
            pred = np.convolve(self._belief, self._belief_blur, mode="same")
            pred = ((1.0 - self._belief_jump_prob) * pred
                    + self._belief_jump_prob / pred.size)
            self._belief = pred * obs
            self._belief /= self._belief.sum()

        best = self._raise_octave(int(np.argmax(self._belief)), scores)
        # Confidence is the harmonic score itself: ~1 for a cleanly
        # periodic onset train, near 0 for aperiodic noise; get_bpm gates
        # on it before reporting.
        self._confidence = float(np.clip(scores[best], 0.0, 1.0))
        self._current_bpm = float(np.clip(self._bpm_grid[best], 50.0, 240.0))
        self._recent_bpms.append(self._current_bpm)
        if len(self._recent_bpms) > 3:
            self._recent_bpms.pop(0)
        self._estimate_phase(signal)

    def _estimate_phase(self, signal: np.ndarray):
        """Locate the most recent beat inside the analysis window.

        Correlates the (preprocessed) onset signal with an impulse train
        at the current period, weighted with a half-life of one beat so
        the most recent onsets dominate; the best fractional offset
        becomes the beat anchor for get_next_beat()'s grid.
        """
        if self._current_bpm is None:
            return
        period = self._rate * 60.0 / self._current_bpm
        n = len(signal)
        n_beats = min(int(n / period), 16)
        if n_beats < 2:
            return
        idx = np.arange(n, dtype=np.float64)
        offsets = np.arange(0.0, period, 0.25)
        decay = 0.5 ** np.arange(n_beats)  # half-life = one beat
        scores = np.zeros_like(offsets)
        for k in range(n_beats):
            pos = (n - 1) - offsets - k * period
            valid = pos >= 0
            scores[valid] += decay[k] * np.interp(pos[valid], idx, signal)
        best = float(offsets[int(np.argmax(scores))])
        # (self._count - 1) is the absolute index of the newest frame.
        self._beat_anchor_frame = (self._count - 1) - best
        self._beat_period_frames = period

    def _raise_octave(self, idx: int, scores: np.ndarray) -> int:
        """Walk up to 2x/3x-faster candidates while their comb evidence
        holds up. Searches a +/-2 BPM window around each multiple so
        slightly detuned harmonics still match. Terminates because each
        raise strictly increases the tempo within a bounded grid.

        Hysteresis: a candidate (or the current base) within ~0.06
        octaves of the previous reported estimate needs 0.04 less
        evidence, so a near-threshold octave decision doesn't flap
        between consecutive analyses."""
        step = self._bpm_grid[1] - self._bpm_grid[0]
        window = int(round(2.0 / step))

        def near_previous(bpm):
            return (self._current_bpm is not None
                    and abs(np.log2(bpm / self._current_bpm)) < 0.06)

        while True:
            bpm = self._bpm_grid[idx]
            best_cand = None
            for mult in (2.0, 3.0):
                target = bpm * mult
                if target > self._bpm_grid[-1] + 1e-9:
                    continue
                j = int(round((target - self._bpm_grid[0]) / step))
                lo = max(0, j - window)
                hi = min(len(scores), j + window + 1)
                k = lo + int(np.argmax(scores[lo:hi]))
                threshold = self._octave_raise_threshold
                if near_previous(self._bpm_grid[k]):
                    threshold -= 0.04
                elif near_previous(bpm):
                    threshold += 0.04
                if scores[k] >= threshold * scores[idx]:
                    if best_cand is None or scores[k] > scores[best_cand]:
                        best_cand = k
            if best_cand is None:
                return idx
            idx = best_cand
