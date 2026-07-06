"""Head-to-head BPM tracking comparison: this repo vs. QLC+ upstream.

Compares four trackers on identical synthesized 44.1 kHz PCM audio:

  1. "QLC+ A (BeatTracking)"    - faithful Python port of Dennis Suermann's
     ACF tempo-induction tracker (engine/audio/src/beattracking.cpp, branch
     `beattracker`, commit 41778df01): full-spectrum onset flux at 86 Hz
     hops, unbiased autocorrelation + comb filter, Rayleigh prior at
     110 BPM, tps2/tps3 octave disambiguation, two-state continuity model.
     Only the tempo path is ported (phase / beat emission is not needed for
     a BPM comparison). The integration defects listed in
     QLCPLUS_BEATTRACKING_REFERENCE.md section 5 (channel-count bug, dead
     build flag) are deliberately NOT reproduced: the port gets clean mono
     float audio, i.e. the algorithm's best case.
  2. "QLC+ B (BeatTracker)"     - faithful port of Massimo Callegari's
     reactive onset detector (beattracker.cpp) with the integration
     parameters from audiocapture.cpp: band 40-400 Hz, flux smoothing 0.6,
     sensitivity 1.3, min beat interval 0.20 s, history 86 blocks. BPM is
     its internal inter-onset-interval mean (kinder than the wall-clock
     display BPM QLC+ actually shows).
  3. "ours (app wiring)"        - this repo's real live path exactly as the
     Auto tab wires it: RealtimeSpectralAnalyzer (decimation to 22.05 kHz,
     2048-pt STFT, hop 512 -> ~43 frames/s, normalized + smoothed flux)
     feeding AutoBPMDetector at its default 86 Hz rate assumption.
  4. "ours (rate-corrected)"    - same front end, detector told the true
     ~43.07 Hz frame rate (diagnostic for the rate-assumption mismatch).

Synthetic scenarios use real percussion-like audio (kick, snare, hats,
bass) over a sustained pad so every tracker's silence gate stays open.
Ports are Python, so the throughput column is not a C++-vs-C++ CPU
comparison; it is only there to show all candidates are far above realtime.

Usage:
    python scripts/compare_bpm_qlcplus.py            # 8 tempi x 8 scenarios
    python scripts/compare_bpm_qlcplus.py --full     # 50-240 BPM sweep
    python scripts/compare_bpm_qlcplus.py --json out.json
    python scripts/compare_bpm_qlcplus.py --audio demos/shows/audiofiles/monsters_demo.ogg --bpm 96
"""

import argparse
import json
import sys
import time as real_time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import auto.bpm_detector as bpm_detector
from auto.bpm_detector import AutoBPMDetector
from audio.realtime_spectral import RealtimeSpectralAnalyzer

from evaluate_bpm_detector import FakeTime, classify, time_to_lock

SR = 44100
BLOCK = 2048                      # QLC+ capture block (frames)
APP_FRAME_RATE = SR / 1024.0      # our analyzer's true frame rate (~43.07 Hz)
DUR = 24.0                        # seconds per synthetic clip


# ------------------------------------------------------- QLC+ port: impl. A

class QlcBeatTracking:
    """Port of BeatTracking (beattracking.cpp), tempo-induction path only."""

    WINDOW = 1024
    HOP = 512
    ONSET_WINDOW = 512
    RAYLEIGH_BPM = 110.0
    COEFF_A = (1.0, 0.23484048, 0.0)
    COEFF_B = (0.15998789, 0.31997577, 0.15998789)

    def __init__(self, sample_rate=SR):
        self.sr = sample_rate  # upstream hard-codes 44100; we feed 44100
        self.win = 0.5 * (1.0 - np.cos(2 * np.pi * np.arange(self.WINDOW)
                                       / (self.WINDOW - 1)))
        self.prev_mag = np.zeros(self.WINDOW // 2)
        target_lag = (44100.0 * 60.0) / (self.RAYLEIGH_BPM * self.HOP)
        self.continuity_dev = target_lag / 8.0
        i = np.arange(self.ONSET_WINDOW, dtype=float)
        b2 = target_lag ** 2
        self.rayleigh = (i / b2) * np.exp(-(i ** 2) / (2 * b2))
        self.buffer = np.zeros(0)
        self.onsets_raw = []          # m_onsetValuesProcessed (last 7)
        self.onset_values = []        # m_tOnsetValues
        self.state = "ACF"
        self.identified_lag = 0.0
        self.last_lag = 0.0
        self.last_lags = []
        self.consistency_count = 0
        self.gauss = None
        self.bpm = None               # upstream inits 120; we track "no estimate yet"

    def process(self, block):
        """Feed a float mono block; mirrors processAudio's hop loop."""
        self.buffer = np.concatenate([self.buffer, block])
        while self.buffer.size > self.WINDOW:
            frame = self.buffer[:self.WINDOW] * self.win
            rms = np.sqrt(np.mean(frame ** 2))
            onset = 0.0
            if rms >= 0.001:  # silence gate
                mag = np.abs(np.fft.rfft(frame))[:self.WINDOW // 2]
                inc = mag - self.prev_mag
                onset = float(np.sum(inc[inc > 0]))
                self.prev_mag = mag
            if len(self.onset_values) == self.ONSET_WINDOW:
                self._induction()
                del self.onset_values[:self.ONSET_WINDOW]  # flushes 100%
            self.onsets_raw.append(onset)
            if len(self.onsets_raw) > 7:
                self.onsets_raw.pop(0)
                filt = self._biquad(self.onsets_raw)
                thresholded = filt[5] - np.median(filt) - np.mean(filt) * 0.1
                self.onset_values.append(float(thresholded))
            self.buffer = self.buffer[self.HOP:]

    def _biquad(self, values):
        # Faithful to the C++ quirk: the backward pass restarts from
        # b0*x[i] and overwrites the forward pass entirely.
        n = len(values)
        out = np.zeros(n)
        for i in range(n):
            out[i] = self.COEFF_B[0] * values[i]
            for order in (1, 2):
                if i - order >= 0:
                    out[i] += self.COEFF_B[order] * values[i - order]
                    out[i] -= self.COEFF_A[order] * out[i - order]
        for i in range(n - 1, -1, -1):
            out[i] = self.COEFF_B[0] * values[i]
            for order in (1, 2):
                if i + order < n:
                    out[i] += self.COEFF_B[order] * values[i + order]
                    out[i] -= self.COEFF_A[order] * out[i + order]
        return out

    def _onset_correlation(self, x):
        n = x.size
        acf = np.zeros(n)
        for lag in range(n):
            acf[lag] = np.dot(x[lag:], x[:n - lag]) / (n - lag)
        acf[0] = 0.0
        acf[-1] = 0.0
        comb = np.zeros(n)
        for lag in range(1, n):
            for a in range(1, 5):
                for b in range(1 - a, 2 * a):
                    idx = lag * a + b - 1
                    if 0 < idx < n:
                        comb[lag] += acf[idx] / (2 * a - 1)
        return comb

    @staticmethod
    def _quadratic(pos, v):
        if pos <= 0 or pos >= len(v) - 1:
            return float(pos)
        y0, y1, y2 = v[pos - 1], v[pos], v[pos + 1]
        denom = y0 - 2 * y1 + y2
        if denom == 0.0:
            return float(pos)
        return pos + 0.5 * (y0 - y2) / denom

    def _predicted_lag(self, ro):
        n = ro.size
        max2i = max3i = 0
        max2 = max3 = 0.0
        for r in range(1, n // 2 - 1):
            v = ro[r] + 0.5 * ro[2 * r] + 0.25 * ro[2 * r - 1] + 0.25 * ro[2 * r + 1]
            if v > max2:
                max2, max2i = v, r
        for r in range(1, n // 3 - 1):
            v = ro[r] + 0.33 * (ro[3 * r] + ro[3 * r - 1] + ro[3 * r + 1])
            if v > max3:
                max3, max3i = v, r
        return max2i if max2 >= max3 else max3i

    def _induction(self):
        ocorr = self._onset_correlation(np.array(self.onset_values))
        rocorr = ocorr * self.rayleigh
        rocorr[0] = 0.0
        acf_idx = self._predicted_lag(rocorr)
        if acf_idx == 0:
            return
        acf_lag = self._quadratic(acf_idx, rocorr)
        continuity_lag = 0.0
        if self.state == "CONTINUITY":
            if self.last_lag != self.identified_lag:
                i = np.arange(self.ONSET_WINDOW, dtype=float)
                var = 2 * (self.identified_lag / 8.0) ** 2
                self.gauss = np.exp(-((i - self.identified_lag) ** 2) / var)
                self.last_lag = self.identified_lag
            weighted = ocorr * self.gauss
            weighted[0] = 0.0
            cont_idx = int(np.argmax(weighted[1:]) + 1)
            continuity_lag = self._quadratic(cont_idx, ocorr)
            self.identified_lag = continuity_lag
        else:
            self.identified_lag = acf_lag
            self.last_lag = 0.0
        if self.state == "CONTINUITY" and abs(acf_lag - continuity_lag) >= self.continuity_dev:
            if self.consistency_count > 1:
                self.state = "ACF"
                self.last_lags.clear()
            self.consistency_count += 1
        else:
            self.consistency_count = 0
        self.last_lags.append(acf_lag)
        if len(self.last_lags) > 3:
            self.last_lags.pop(0)
            if (self.state == "ACF"
                    and abs(2 * self.last_lags[2] - self.last_lags[1]
                            - self.last_lags[0]) < self.continuity_dev):
                self.state = "CONTINUITY"
        if self.identified_lag > 0:
            self.bpm = (44100.0 * 60.0) / (self.HOP * self.identified_lag)


# ------------------------------------------------------- QLC+ port: impl. B

class QlcBeatTracker:
    """Port of BeatTracker (beattracker.cpp) with audiocapture.cpp params."""

    def __init__(self, sample_rate=SR, frame_size=BLOCK, history=86,
                 sensitivity=1.3, alpha=0.6, min_beat_s=0.20,
                 band=(40.0, 400.0)):
        self.sr = sample_rate
        self.frame = frame_size
        self.fft_size = frame_size  # already a power of two
        n = np.arange(frame_size)
        self.win = 0.5 * (1.0 - np.cos(2 * np.pi * n / (frame_size - 1)))
        self.min_bin = int(np.floor(band[0] * self.fft_size / self.sr))
        self.max_bin = int(np.floor(band[1] * self.fft_size / self.sr))
        self.prev_mag = np.zeros(self.fft_size // 2 + 1)
        self.history = np.zeros(history)
        self.hist_idx = 0
        self.hist_filled = False
        self.sensitivity = sensitivity
        self.alpha = alpha
        self.last_flux = 0.0
        self.smoothed = 0.0
        self.min_beat_samples = int(min_beat_s * self.sr)
        self.samples_since_beat = self.min_beat_samples
        self.intervals = []
        self.last_beat_sample = -1
        self.total = 0
        self.silent_frames = 0
        self.silence_reset = int(self.sr / self.frame * 2.0)

    def _push_history(self, value):
        self.history[self.hist_idx] = value
        self.hist_idx += 1
        if self.hist_idx >= self.history.size:
            self.hist_idx = 0
            self.hist_filled = True

    def process(self, block):
        frames = block.size
        peak = float(np.max(np.abs(block))) if frames else 0.0
        if peak < 0.01:  # silence gate
            self.smoothed *= self.alpha
            self._push_history(self.smoothed)
            self.last_flux = self.smoothed
            self.samples_since_beat = min(self.samples_since_beat + frames,
                                          self.min_beat_samples)
            self.silent_frames += 1
            if self.silent_frames >= self.silence_reset:
                self.intervals.clear()
                self.last_beat_sample = -1
            self.total += frames
            return False
        self.silent_frames = 0
        spec = np.fft.rfft(block * self.win[:frames], n=self.fft_size)
        mag = np.log1p(np.abs(spec))
        flux = 0.0
        for k in range(self.min_bin, self.max_bin + 1):
            diff = mag[k] - self.prev_mag[k]
            if diff > 0.0:
                t = ((k - self.min_bin) / (self.max_bin - self.min_bin)
                     if self.max_bin > self.min_bin else 0.0)
                flux += diff * (1.5 - 0.5 * t)
            self.prev_mag[k] = mag[k]
        self.smoothed = self.alpha * self.smoothed + (1.0 - self.alpha) * flux
        self._push_history(self.smoothed)
        count = self.history.size if self.hist_filled else self.hist_idx
        threshold = (np.mean(self.history[:count]) * self.sensitivity
                     if count > 0 else np.inf)
        candidate = self.smoothed > threshold and self.smoothed > self.last_flux
        self.last_flux = self.smoothed
        is_beat = candidate and self.samples_since_beat >= self.min_beat_samples
        if is_beat:
            beat_sample = self.total + frames // 2
            if self.last_beat_sample >= 0:
                dt = (beat_sample - self.last_beat_sample) / self.sr
                if 0.25 < dt < 2.0:
                    self.intervals.append(dt)
                    if len(self.intervals) > 16:
                        self.intervals.pop(0)
            self.last_beat_sample = beat_sample
        self.samples_since_beat = min(self.samples_since_beat + frames,
                                      self.min_beat_samples)
        if is_beat:
            self.samples_since_beat = 0
        self.total += frames
        return is_beat

    @property
    def bpm(self):
        if not self.intervals:
            return None
        return 60.0 / float(np.mean(self.intervals))


# --------------------------------------------------------- tracker adapters

def run_qlc_a(audio):
    det = QlcBeatTracking()
    history = []
    t0 = real_time.perf_counter()
    for start in range(0, audio.size - BLOCK + 1, BLOCK):
        det.process(audio[start:start + BLOCK])
        history.append(((start + BLOCK) / SR, det.bpm, None))
    return history, real_time.perf_counter() - t0


def run_qlc_b(audio):
    det = QlcBeatTracker()
    history = []
    t0 = real_time.perf_counter()
    for start in range(0, audio.size - BLOCK + 1, BLOCK):
        det.process(audio[start:start + BLOCK])
        history.append(((start + BLOCK) / SR, det.bpm, None))
    return history, real_time.perf_counter() - t0


def run_ours(audio, pre_fix=False):
    """Replicates the Auto tab path synchronously: RealtimeSpectralAnalyzer's
    processing loop (mono in, 2:1 decimation, sliding 2048-pt STFT, hop 512)
    feeding AutoBPMDetector under a fake clock paced by audio time.

    pre_fix=True reproduces the wiring before the July 2026 fix: the
    detector assumed 86 Hz frames and consumed the normalized, 0.6 s-
    smoothed display flux instead of flux_raw."""
    import dataclasses

    analyzer = RealtimeSpectralAnalyzer(sample_rate=SR)
    hop, read = analyzer.hop_length, analyzer.hop_length * 2
    fake = FakeTime()
    saved = bpm_detector.time
    bpm_detector.time = fake
    try:
        rate = 86.0 if pre_fix else analyzer.beat_frame_rate_hz
        det = AutoBPMDetector(analysis_rate_hz=rate)
        history = []
        t0 = real_time.perf_counter()
        for start in range(0, audio.size - read + 1, read):
            chunk = audio[start:start + read]
            analyzer._push_beat_samples(chunk.astype(np.float32))
            samples = ((chunk[0::2] + chunk[1::2]) * 0.5).astype(np.float32)
            analyzer._sliding_buffer[:analyzer.n_fft - hop] = \
                analyzer._sliding_buffer[hop:]
            analyzer._sliding_buffer[analyzer.n_fft - hop:] = samples
            frame = analyzer._compute_frame()
            if pre_fix:
                frame = dataclasses.replace(frame, flux_raw=frame.flux,
                                            flux_raw_hops=())
            det.on_feature(frame)
            fake.advance(read / SR)
            history.append(((start + read) / SR, det.get_bpm(), det.confidence))
        wall = real_time.perf_counter() - t0
    finally:
        bpm_detector.time = saved
    return history, wall


TRACKERS = [
    ("QLC+ A (BeatTracking)", run_qlc_a),
    ("QLC+ B (BeatTracker)", run_qlc_b),
    ("ours (pre-fix wiring)", lambda a: run_ours(a, pre_fix=True)),
    ("ours (fixed wiring)", lambda a: run_ours(a)),
]


# ------------------------------------------------------------ audio synthesis

def _kick():
    t = np.arange(int(0.09 * SR)) / SR
    freq = 150.0 * np.exp(-t * 25.0) + 45.0
    phase = 2 * np.pi * np.cumsum(freq) / SR
    return np.sin(phase) * np.exp(-t * 30.0) * 0.9


def _snare(rng):
    n = int(0.12 * SR)
    t = np.arange(n) / SR
    body = np.sin(2 * np.pi * 190.0 * t) * np.exp(-t * 40.0) * 0.4
    rattle = rng.standard_normal(n) * np.exp(-t * 35.0) * 0.25
    return body + rattle


def _hat(rng):
    n = int(0.03 * SR)
    x = rng.standard_normal(n) * np.exp(-np.arange(n) / (0.005 * SR))
    return np.diff(x, prepend=0.0) * 0.20  # crude high-pass, >4 kHz emphasis


def _bass_note():
    t = np.arange(int(0.18 * SR)) / SR
    env = np.minimum(t / 0.005, 1.0) * np.exp(-t * 12.0)
    return np.sin(2 * np.pi * 85.0 * t) * env * 0.45


def beat_times(bpm_fn, seconds):
    times, t = [], 0.0
    while t < seconds:
        times.append(t)
        t += 60.0 / bpm_fn(t)
    return times


def render(events, seconds, rng, gap=None):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    audio = (0.05 * np.sin(2 * np.pi * 110.0 * t)
             + 0.02 * np.sin(2 * np.pi * 220.0 * t)
             + 0.015 * np.sin(2 * np.pi * 330.5 * t)
             + rng.standard_normal(n) * 0.002)
    for time_s, sample in events:
        i = int(time_s * SR)
        j = min(n, i + sample.size)
        if 0 <= i < n:
            audio[i:j] += sample[:j - i]
    if gap is not None:
        audio[int(gap[0] * SR):int(gap[1] * SR)] = 0.0
    audio = np.clip(audio, -1.0, 1.0)
    # int16 round trip: every tracker sees quantized PCM like a real capture
    return (audio * 32767.0).astype(np.int16).astype(np.float64) / 32768.0


def sc_kick(bpm, rng):
    k = _kick()
    ev = [(t, k) for t in beat_times(lambda t: bpm, DUR)]
    return render(ev, DUR, rng), bpm, DUR


def sc_kick_hats(bpm, rng):
    k, h = _kick(), _hat(rng)
    beats = beat_times(lambda t: bpm, DUR)
    ev = [(t, k) for t in beats] + [(t + 30.0 / bpm, h) for t in beats]
    return render(ev, DUR, rng), bpm, DUR


def sc_backbeat(bpm, rng):
    k, s = _kick(), _snare(rng)
    beats = beat_times(lambda t: bpm, DUR)
    ev = [(t, k if i % 2 == 0 else s) for i, t in enumerate(beats)]
    return render(ev, DUR, rng), bpm, DUR


def sc_bassline(bpm, rng):
    # Eighth-note bass inside 40-400 Hz: QLC+ B's documented failure mode.
    k, b = _kick(), _bass_note()
    beats = beat_times(lambda t: bpm, DUR)
    ev = [(t, k) for t in beats] + [(t + 30.0 / bpm, b) for t in beats]
    return render(ev, DUR, rng), bpm, DUR


def sc_swing(bpm, rng):
    k, h = _kick(), _hat(rng)
    beats = beat_times(lambda t: bpm, DUR)
    ev = [(t, k) for t in beats] + [(t + 40.0 / bpm, h) for t in beats]
    return render(ev, DUR, rng), bpm, DUR


def sc_drift(bpm, rng):
    k = _kick()
    ev = [(t, k) for t in beat_times(
        lambda t: bpm * (0.97 + 0.06 * t / DUR), DUR)]
    return render(ev, DUR, rng), bpm, DUR


def sc_dropout(bpm, rng):
    k = _kick()
    ev = [(t, k) for t in beat_times(lambda t: bpm, DUR)]
    return render(ev, DUR, rng, gap=(10.0, 12.5)), bpm, DUR


def sc_step(bpm, rng):
    seconds = 28.0
    k = _kick()
    ev = [(t, k) for t in beat_times(
        lambda t: bpm / 1.3 if t < 12.0 else bpm, seconds)]
    return render(ev, seconds, rng), bpm, seconds


SCENARIOS = [
    ("kick four-on-floor", sc_kick),
    ("kick + 8th hats", sc_kick_hats),
    ("kick/snare backbeat", sc_backbeat),
    ("8th-note bassline", sc_bassline),
    ("swung hats", sc_swing),
    ("tempo drift +/-3%", sc_drift),
    ("2.5 s dropout", sc_dropout),
    ("tempo step +30%", sc_step),
]


# ------------------------------------------------------------------- runner

def fmt(value, spec, none="-"):
    return none if value is None else format(value, spec)


def run_suite(tempi, seed):
    rng = np.random.default_rng(seed)
    per = {name: {"outcomes": {"correct": 0, "octave": 0, "related": 0,
                               "wrong": 0, "none": 0},
                  "errs": [], "locks": [], "wall": 0.0, "audio_s": 0.0}
           for name, _ in TRACKERS}
    runs = []
    for sc_name, builder in SCENARIOS:
        for bpm in tempi:
            audio, truth, seconds = builder(float(bpm), rng)
            for name, runner in TRACKERS:
                history, wall = runner(audio)
                est = history[-1][1] if history else None
                verdict = classify(est, truth)
                agg = per[name]
                agg["outcomes"][verdict] += 1
                agg["wall"] += wall
                agg["audio_s"] += seconds
                lock = time_to_lock(history, truth)
                if verdict == "correct":
                    agg["errs"].append(abs(est - truth) / truth * 100.0)
                    if lock is not None:
                        agg["locks"].append(lock)
                runs.append({"scenario": sc_name, "tracker": name,
                             "input_bpm": float(bpm), "truth": truth,
                             "estimate": est, "verdict": verdict,
                             "lock_s": None if lock is None else round(lock, 2)})
    return per, runs


def print_report(per, runs, tempi):
    n_per_tracker = len(SCENARIOS) * len(tempi)
    print(f"BPM tracking comparison: {len(tempi)} tempi "
          f"({min(tempi):g}-{max(tempi):g}), {len(SCENARIOS)} scenarios, "
          f"{DUR:.0f}+ s clips, tolerance 4%")
    print()
    header = (f"{'tracker':<24} {'correct':>9} {'octave':>7} {'related':>8} "
              f"{'wrong':>6} {'none':>5} {'err%':>6} {'lock s':>7} {'xRT':>7}")
    print(header)
    print("-" * len(header))
    for name, agg in per.items():
        o = agg["outcomes"]
        xrt = agg["audio_s"] / agg["wall"] if agg["wall"] > 0 else 0.0
        print(f"{name:<24} {o['correct']:>6}/{n_per_tracker:<3} {o['octave']:>6} "
              f"{o['related']:>8} {o['wrong']:>6} {o['none']:>5} "
              f"{fmt(np.mean(agg['errs']) if agg['errs'] else None, '5.2f'):>6} "
              f"{fmt(np.mean(agg['locks']) if agg['locks'] else None, '5.1f'):>7} "
              f"{xrt:>6.0f}x")
    print()
    print("per-scenario correct counts:")
    width = max(len(s) for s, _ in SCENARIOS) + 2
    print(" " * width + "".join(f"{name.split(' (')[0]:>18}" for name, _ in TRACKERS))
    for sc_name, _ in SCENARIOS:
        row = f"{sc_name:<{width}}"
        for name, _ in TRACKERS:
            n_ok = sum(1 for r in runs
                       if r["scenario"] == sc_name and r["tracker"] == name
                       and r["verdict"] == "correct")
            row += f"{n_ok:>15}/{len(tempi):<2}"
        print(row)
    print()
    print("caveats: QLC+ ports are Python (xRT is not a language-fair CPU "
          "number); QLC+ A\ngets clean mono audio, i.e. WITHOUT its live "
          "channel-count integration bug; QLC+ B\nBPM is its internal "
          "interval mean, not the wall-clock number QLC+ displays.")


# ------------------------------------------------------------ real song mode

WARMUP_S = 12.0  # skip the first seconds of each song when scoring


def _norm_name(s):
    import re
    return re.sub(r"[^a-z0-9]", "", s.lower())


def parse_structure_csv(path):
    """Parse a legacy show-structure CSV into [(bpm, seconds)] parts."""
    import csv as csvmod
    parts = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csvmod.DictReader(f):
            bpm = float(row["bpm"])
            bars = float(row["num_bars"])
            beats_per_bar = float(row["signature"].split("/")[0])
            parts.append((bpm, bars * beats_per_bar * 60.0 / bpm))
    return parts


def make_truth_fn(parts):
    """Piecewise-constant BPM timeline; clamps to the last part beyond it."""
    edges, t = [], 0.0
    for bpm, dur in parts:
        t += dur
        edges.append((t, bpm))

    def truth(at):
        for end, bpm in edges:
            if at < end:
                return bpm
        return edges[-1][1]

    return truth, t


def dominant_bpm(parts):
    weight = {}
    for bpm, dur in parts:
        weight[bpm] = weight.get(bpm, 0.0) + dur
    return max(weight, key=weight.get)


def match_structure(wav_stem, csv_paths):
    import difflib
    best, best_score = None, 0.0
    for p in csv_paths:
        stem = p.stem
        for prefix in ("SBD_",):
            if stem.startswith(prefix):
                stem = stem[len(prefix):]
        score = difflib.SequenceMatcher(
            None, _norm_name(wav_stem), _norm_name(stem)).ratio()
        if score > best_score:
            best, best_score = p, score
    return (best, best_score) if best_score >= 0.6 else (None, best_score)


def run_songs(songs_dir, structures_dir, json_path=None):
    try:
        import soundfile as sf
    except ImportError:
        print("soundfile is required for --songs")
        return 2
    wavs = sorted(Path(songs_dir).glob("*.wav"))
    csvs = sorted(Path(structures_dir).glob("*.csv"))
    if not wavs or not csvs:
        print("no .wav files or structure .csv files found")
        return 2

    agg = {name: {"time_correct": [], "time_octave": [], "verdicts": []}
           for name, _ in TRACKERS}
    song_results = []

    for wav in wavs:
        struct, score = match_structure(wav.stem, csvs)
        if struct is None:
            print(f"{wav.stem}: no matching structure CSV (best score "
                  f"{score:.2f}) - skipped\n")
            continue
        data, sr = sf.read(wav, dtype="float64", always_2d=True)
        audio = data.mean(axis=1)
        if sr != SR:
            import librosa
            audio = librosa.resample(audio, orig_sr=sr, target_sr=SR)
        audio = (np.clip(audio, -1, 1) * 32767.0).astype(np.int16) \
            .astype(np.float64) / 32768.0
        duration = audio.size / SR

        parts = parse_structure_csv(struct)
        truth_fn, timeline_dur = make_truth_fn(parts)
        dom = dominant_bpm(parts)
        aligned = abs(timeline_dur - duration) / duration <= 0.15
        tempi = sorted({bpm for bpm, _ in parts})
        print(f"{wav.stem}  ({duration:.0f} s, structure {struct.name}, "
              f"tempi {'/'.join(f'{t:g}' for t in tempi)} BPM, "
              f"dominant {dom:g})"
              + ("" if aligned else
                 f"  [timeline {timeline_dur:.0f} s != audio: scoring vs "
                 f"dominant tempo only]"))
        entry = {"song": wav.stem, "structure": struct.name,
                 "duration_s": round(duration, 1), "dominant_bpm": dom,
                 "aligned": aligned, "trackers": {}}
        for name, runner in TRACKERS:
            history, wall = runner(audio)
            samples = [(t, est) for t, est, _ in history if t >= WARMUP_S]
            if aligned and samples:
                verdicts = [classify(est, truth_fn(t)) for t, est in samples]
                frac = {v: verdicts.count(v) / len(verdicts)
                        for v in ("correct", "octave", "related", "wrong", "none")}
                final = history[-1][1]
                print(f"  {name:<24} correct {frac['correct']:>4.0%}  "
                      f"octave {frac['octave']:>4.0%}  "
                      f"other {frac['related'] + frac['wrong'] + frac['none']:>4.0%}"
                      f"   final {fmt(final, '6.1f')} BPM")
                agg[name]["time_correct"].append(frac["correct"])
                agg[name]["time_octave"].append(frac["octave"])
                entry["trackers"][name] = {"mode": "timeline", **{
                    k: round(v, 3) for k, v in frac.items()},
                    "final": final}
            else:
                half = [est for t, est in samples[len(samples) // 2:]
                        if est is not None]
                med = float(np.median(half)) if half else None
                verdict = classify(med, dom)
                print(f"  {name:<24} median (last half) {fmt(med, '6.1f')} BPM"
                      f" -> {verdict} vs dominant")
                agg[name]["verdicts"].append(verdict)
                entry["trackers"][name] = {"mode": "dominant",
                                           "median": med, "verdict": verdict}
        song_results.append(entry)
        print()

    print("summary over songs:")
    for name, a in agg.items():
        line = f"  {name:<24}"
        if a["time_correct"]:
            line += (f" timeline songs: {np.mean(a['time_correct']):.0%} of "
                     f"time correct, {np.mean(a['time_octave']):.0%} octave"
                     f" (n={len(a['time_correct'])})")
        if a["verdicts"]:
            ok = a["verdicts"].count("correct")
            oct_ = a["verdicts"].count("octave")
            line += (f"   dominant-scored: {ok}/{len(a['verdicts'])} correct,"
                     f" {oct_} octave")
        print(line)
    if json_path:
        Path(json_path).write_text(json.dumps(song_results, indent=2))
        print(f"\nper-song results written to {json_path}")
    return 0


def evaluate_audio(path, truth):
    try:
        import librosa
    except ImportError:
        print("librosa is required for --audio")
        return 2
    y, _sr = librosa.load(path, sr=SR, mono=True)
    y = (np.clip(y, -1, 1) * 32767.0).astype(np.int16).astype(np.float64) / 32768.0
    ref, _ = librosa.beat.beat_track(y=y.astype(np.float32), sr=SR)
    ref = float(np.atleast_1d(ref)[0])
    print(f"file: {path} ({y.size / SR:.1f} s), librosa reference {ref:.1f} BPM"
          + (f", ground truth {truth:g} BPM" if truth else ""))
    for name, runner in TRACKERS:
        history, wall = runner(y)
        est = history[-1][1] if history else None
        base = truth if truth else ref
        print(f"  {name:<24} {fmt(est, '6.1f')} BPM   ({classify(est, base)}"
              f" vs {'truth' if truth else 'librosa'}, {y.size / SR / wall:,.0f}x RT)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--full", action="store_true",
                    help="sweep 50-240 BPM in steps of 10 (slow)")
    ap.add_argument("--json", metavar="FILE")
    ap.add_argument("--audio", metavar="FILE",
                    help="compare all trackers on a real audio file")
    ap.add_argument("--bpm", type=float, default=None)
    ap.add_argument("--songs", metavar="DIR",
                    help="directory of .wav songs to evaluate")
    ap.add_argument("--structures", metavar="DIR",
                    help="directory of legacy show-structure CSVs providing "
                         "ground-truth BPM (matched to songs by name)")
    ap.add_argument("--seed", type=int, default=1234)
    args = ap.parse_args()

    if args.songs:
        if not args.structures:
            print("--songs requires --structures")
            return 2
        return run_songs(args.songs, args.structures, args.json)
    if args.audio:
        return evaluate_audio(args.audio, args.bpm)

    tempi = list(range(50, 241, 10)) if args.full else [60, 75, 90, 105, 120, 140, 160, 180]
    per, runs = run_suite(tempi, args.seed)
    print_report(per, runs, tempi)
    if args.json:
        serializable = {name: {**agg, "errs": list(map(float, agg["errs"])),
                               "locks": list(map(float, agg["locks"]))}
                        for name, agg in per.items()}
        Path(args.json).write_text(json.dumps(
            {"aggregate": serializable, "runs": runs}, indent=2))
        print(f"\nper-run results written to {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
