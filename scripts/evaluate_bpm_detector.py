"""Performance evaluator for the Auto Mode BPM detector.

Benchmarks auto.bpm_detector.AutoBPMDetector against synthetic onset-flux
scenarios with known ground-truth tempo, and optionally against a real
audio file. Reports, per scenario: accuracy, octave-error rate, mean
estimate error, time to lock, and confidence, plus overall processing
throughput. Intended as the evidence base for reusing the beat tracker
outside this repo.

Usage:
    python scripts/evaluate_bpm_detector.py                    # full synthetic suite
    python scripts/evaluate_bpm_detector.py --quick            # 6 tempi instead of 20
    python scripts/evaluate_bpm_detector.py --json results.json
    python scripts/evaluate_bpm_detector.py --audio song.ogg --bpm 128

The synthetic path needs only numpy. The --audio path additionally needs
librosa (already a project dependency for offline analysis): the file is
run through librosa's onset-strength function, i.e. the same kind of flux
envelope the live pipeline produces.
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
from audio.realtime_spectral import LiveFeatureFrame

RATE = 86.0        # analysis frames per second (44100 / 512)
TOL = 0.04         # relative tolerance for "correct" (4%)
DUR = 14.0         # seconds of audio per synthetic run
# Onset shape in flux frames (~70 ms attack + decay), matching the width of
# real onset-strength envelopes at 86 Hz rather than a 1-frame impulse.
CLICK_DECAY = (0.35, 1.0, 0.75, 0.5, 0.3, 0.15)


class FakeTime:
    """Replaces the `time` module inside bpm_detector so a run is paced by
    audio time, not wall-clock time (the detector re-analyzes every 2 s)."""

    def __init__(self):
        self._t = 0.0

    def monotonic(self) -> float:
        return self._t

    def advance(self, dt: float):
        self._t += dt


def make_frame(flux: float) -> LiveFeatureFrame:
    # The detector consumes the unnormalized flux_raw channel.
    return LiveFeatureFrame(
        timestamp=0.0, flux=0.0, transient=0.0, richness=0.0,
        vocal=0.0, centroid=0.0, rms=0.0, contrast=0.0,
        flux_raw=flux,
    )


# ---------------------------------------------------------------- scenarios

def beat_events(bpm_fn, seconds, amp=1.0):
    """Beat onset times for a (possibly time-varying) tempo function."""
    events, t = [], 0.0
    while t < seconds:
        events.append((t, amp))
        t += 60.0 / bpm_fn(t)
    return events


def rasterize(events, seconds, noise, rng, gap=None):
    """Turn (time, amplitude) onsets into a per-frame flux array."""
    n = int(seconds * RATE)
    flux = rng.random(n) * noise if noise > 0 else np.zeros(n)
    for t, amp in events:
        idx = int(round(t * RATE))
        for k, d in enumerate(CLICK_DECAY):
            if 0 <= idx + k < n:
                flux[idx + k] += amp * d
    if gap is not None:
        a, b = int(gap[0] * RATE), int(gap[1] * RATE)
        flux[a:b] = rng.random(b - a) * 0.05
    return flux


def s_clean(bpm, rng):
    return rasterize(beat_events(lambda t: bpm, DUR), DUR, 0.0, rng), bpm, DUR


def s_noisy(bpm, rng):
    return rasterize(beat_events(lambda t: bpm, DUR), DUR, 0.5, rng), bpm, DUR


def s_eighths(bpm, rng):
    # Strong downbeats with weaker eighth-note offbeats (hi-hat pattern).
    # Characterizes the detector's octave behaviour on subdivided material.
    # Offbeat amplitude 0.4 models what the analyzer front end delivers
    # since the multi-band onset rework: hat-band onsets arrive at the
    # 0.4 band weight, already saturation-equalized within their band.
    # (Same-band amplitude coding of subdivision is no longer the
    # detector's discriminator; the band split upstream is.)
    ev = beat_events(lambda t: bpm, DUR)
    half = 30.0 / bpm
    ev += [(t + half, 0.4) for t, _ in ev]
    return rasterize(ev, DUR, 0.2, rng), bpm, DUR


def s_swing(bpm, rng):
    # Swung eighths: offbeat at 2/3 of the beat period.
    ev = beat_events(lambda t: bpm, DUR)
    ev += [(t + (2.0 / 3.0) * 60.0 / bpm, 0.5) for t, _ in ev]
    return rasterize(ev, DUR, 0.2, rng), bpm, DUR


def s_drift(bpm, rng):
    # Tempo drifts linearly from -3% to +3% around the nominal value.
    ev = beat_events(lambda t: bpm * (0.97 + 0.06 * t / DUR), DUR)
    return rasterize(ev, DUR, 0.2, rng), bpm, DUR


def s_dropout(bpm, rng):
    # 2.5 s of near-silence mid-song (breakdown), truth unchanged.
    seconds = 16.0
    ev = beat_events(lambda t: bpm, seconds)
    return rasterize(ev, seconds, 0.2, rng, gap=(6.0, 8.5)), bpm, seconds


def s_step(bpm, rng):
    # Tempo steps up 30% at t=7 s, landing on the nominal tempo so the
    # truth stays inside the detector's 50-240 clamp; truth is post-step.
    seconds = 18.0
    ev = beat_events(lambda t: bpm / 1.3 if t < 7.0 else bpm, seconds)
    return rasterize(ev, seconds, 0.2, rng), bpm, seconds


SCENARIOS = [
    ("clean click train", s_clean),
    ("noisy clicks (SNR 2:1)", s_noisy),
    ("eighth-note subdivision", s_eighths),
    ("swung eighths", s_swing),
    ("tempo drift +/-3%", s_drift),
    ("2.5 s dropout", s_dropout),
    ("tempo step +30% at 7 s", s_step),
]


# ------------------------------------------------------------------ scoring

def classify(est, truth, tol=TOL):
    if est is None:
        return "none"
    if abs(est - truth) <= tol * truth:
        return "correct"
    for m in (2.0, 0.5, 3.0, 1.0 / 3.0):
        if abs(est - truth * m) <= tol * truth * m:
            return "octave"
    for m in (1.5, 2.0 / 3.0, 0.75, 4.0 / 3.0):
        if abs(est - truth * m) <= tol * truth * m:
            return "related"
    return "wrong"


def time_to_lock(history, truth):
    """Earliest audio time after which the estimate stays correct."""
    lock = None
    for t, est, _conf in history:
        if est is not None and classify(est, truth) == "correct":
            if lock is None:
                lock = t
        else:
            lock = None
    return lock


def run_detector(flux, rate=RATE):
    """Feed a flux array through a fresh detector under a fake clock.

    Returns (detector, history, wall_seconds); history is one
    (audio_time, estimate, confidence) sample per frame.
    """
    fake = FakeTime()
    saved = bpm_detector.time
    bpm_detector.time = fake
    try:
        det = AutoBPMDetector(analysis_rate_hz=rate)
        history = []
        t0 = real_time.perf_counter()
        for f in flux:
            det.on_feature(make_frame(float(f)))
            fake.advance(1.0 / rate)
            history.append((fake.monotonic(), det.get_bpm(), det.confidence))
        wall = real_time.perf_counter() - t0
    finally:
        bpm_detector.time = saved
    return det, history, wall


# -------------------------------------------------------------- suite runner

def run_suite(tempi, seed=1234):
    rng = np.random.default_rng(seed)
    rows, runs = [], []
    total_frames, total_wall = 0, 0.0

    for name, builder in SCENARIOS:
        outcomes = {"correct": 0, "octave": 0, "related": 0, "wrong": 0, "none": 0}
        errs, locks, confs = [], [], []
        for bpm in tempi:
            flux, truth, _seconds = builder(float(bpm), rng)
            det, history, wall = run_detector(flux)
            total_frames += len(flux)
            total_wall += wall
            est = det.get_bpm()
            verdict = classify(est, truth)
            outcomes[verdict] += 1
            confs.append(det.confidence)
            lock = time_to_lock(history, truth)
            if verdict == "correct":
                errs.append(abs(est - truth) / truth * 100.0)
                if lock is not None:
                    locks.append(lock)
            runs.append({
                "scenario": name, "input_bpm": float(bpm), "truth_bpm": truth,
                "estimate": est, "verdict": verdict,
                "confidence": round(det.confidence, 3),
                "lock_seconds": None if lock is None else round(lock, 2),
            })
        rows.append({
            "scenario": name, "n": len(tempi), **outcomes,
            "mean_abs_err_pct": float(np.mean(errs)) if errs else None,
            "mean_lock_s": float(np.mean(locks)) if locks else None,
            "mean_confidence": float(np.mean(confs)),
        })

    perf = measure_perf(total_frames, total_wall)
    return rows, runs, perf


def measure_perf(total_frames, total_wall):
    frames_per_s = total_frames / total_wall if total_wall > 0 else float("inf")
    # Isolate the cost of one autocorrelation analysis on a full window.
    fake = FakeTime()
    saved = bpm_detector.time
    bpm_detector.time = fake
    try:
        det = AutoBPMDetector(analysis_rate_hz=RATE)
        rng = np.random.default_rng(0)
        flux = rasterize(beat_events(lambda t: 120.0, 10.0), 10.0, 0.2, rng)
        for f in flux:
            det.on_feature(make_frame(float(f)))
            fake.advance(1.0 / RATE)
        t0 = real_time.perf_counter()
        reps = 200
        for _ in range(reps):
            det._analyze()
        analyze_ms = (real_time.perf_counter() - t0) / reps * 1000.0
    finally:
        bpm_detector.time = saved
    return {
        "frames_per_second": frames_per_s,
        "realtime_factor": frames_per_s / RATE,
        "us_per_frame": 1e6 / frames_per_s,
        "analyze_call_ms": analyze_ms,
    }


# ------------------------------------------------------------------- report

def fmt(value, spec, none="-"):
    return none if value is None else format(value, spec)


def print_report(rows, perf, tempi):
    print(f"AutoBPMDetector evaluation: {len(tempi)} tempi "
          f"({min(tempi):g}-{max(tempi):g} BPM), {len(SCENARIOS)} scenarios, "
          f"tolerance {TOL:.0%}")
    print()
    header = (f"{'scenario':<26} {'correct':>8} {'octave':>7} {'related':>8} "
              f"{'wrong':>6} {'none':>5} {'err%':>6} {'lock s':>7} {'conf':>5}")
    print(header)
    print("-" * len(header))
    for r in rows:
        print(f"{r['scenario']:<26} {r['correct']:>5}/{r['n']:<2} {r['octave']:>7} "
              f"{r['related']:>8} {r['wrong']:>6} {r['none']:>5} "
              f"{fmt(r['mean_abs_err_pct'], '5.2f'):>6} "
              f"{fmt(r['mean_lock_s'], '5.1f'):>7} "
              f"{r['mean_confidence']:>5.2f}")
    print()
    total = sum(r["n"] for r in rows)
    correct = sum(r["correct"] for r in rows)
    octave = sum(r["octave"] for r in rows)
    print(f"overall: {correct}/{total} correct ({correct / total:.0%}), "
          f"{octave} octave errors ({octave / total:.0%})")
    print()
    print(f"throughput: {perf['frames_per_second']:,.0f} frames/s "
          f"({perf['realtime_factor']:,.0f}x realtime at {RATE:g} Hz), "
          f"{perf['us_per_frame']:.1f} us/frame, "
          f"one analysis pass {perf['analyze_call_ms']:.2f} ms")
    print()
    print("notes: 'octave' = estimate is 2x/0.5x/3x the truth - the usual "
          "failure mode of\nargmax autocorrelation on subdivided material; "
          "'lock s' = seconds of audio until\nthe estimate is stably correct "
          "(the detector needs 4 s of signal by design).")


def run_phase_eval(seed=1234):
    """Characterize beat-phase accuracy: feed click trains, then compare
    each frame's predicted next-beat time against the true click grid."""
    rng = np.random.default_rng(seed)
    print("Beat phase accuracy (predicted next beat vs true click grid,"
          " sampled every frame after 6 s warmup):")
    print(f"{'scenario':<28} {'bpm':>5} {'mean |off| ms':>14} "
          f"{'p95 ms':>8} {'avail':>7}")
    fake = FakeTime()
    saved = bpm_detector.time
    bpm_detector.time = fake
    try:
        for label, noise, alt in [("clean clicks", 0.0, False),
                                  ("noisy clicks", 0.4, False),
                                  ("alternating accents", 0.2, True)]:
            for bpm in (60.0, 90.0, 120.0, 150.0, 180.0):
                det = AutoBPMDetector(analysis_rate_hz=RATE)
                n = int(20.0 * RATE)
                period = 60.0 * RATE / bpm
                clicks, next_click, beat_i = [], 0.0, 0
                offsets, avail, total = [], 0, 0
                for i in range(n):
                    flux = float(rng.random()) * noise
                    if i >= next_click:
                        flux += 0.6 if (alt and beat_i % 2) else 1.0
                        clicks.append(i)
                        next_click += period
                        beat_i += 1
                    det.on_feature(make_frame(flux))
                    fake.advance(1.0 / RATE)
                    t = (i + 1) / RATE
                    if t < 6.0:
                        continue
                    total += 1
                    nb = det.get_next_beat()
                    if nb is None:
                        continue
                    avail += 1
                    t_pred = i / RATE + nb
                    grid = np.array(clicks, dtype=float) / RATE
                    # extend the grid one period past the end
                    grid = np.append(grid, grid[-1] + period / RATE)
                    offsets.append(float(np.min(np.abs(grid - t_pred))) * 1000.0)
                print(f"{label:<28} {bpm:>5.0f} "
                      f"{np.mean(offsets) if offsets else float('nan'):>14.1f} "
                      f"{np.percentile(offsets, 95) if offsets else float('nan'):>8.1f} "
                      f"{avail / total if total else 0:>6.0%}")
    finally:
        bpm_detector.time = saved
    print()
    print("note: predictions extrapolate from an analysis up to 2 s old;"
          " one frame at\n86 Hz is 11.6 ms, and the +/-23 ms pre-ACF"
          " smoothing bounds the achievable phase\nsharpness.")
    return 0


def evaluate_audio(path, truth):
    try:
        import librosa
    except ImportError:
        print("librosa is required for --audio (pip install librosa)")
        return 2
    y, sr = librosa.load(path, sr=44100, mono=True)
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=512)
    rate = sr / 512.0
    det, history, wall = run_detector(env, rate=rate)
    est = det.get_bpm()
    ref_tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    ref_tempo = float(np.atleast_1d(ref_tempo)[0])
    print(f"file: {path} ({len(y) / sr:.1f} s)")
    print(f"AutoBPMDetector: {fmt(est, '.1f')} BPM "
          f"(confidence {det.confidence:.2f})")
    print(f"librosa beat_track reference: {ref_tempo:.1f} BPM")
    if truth is not None:
        verdict = classify(est, truth)
        lock = time_to_lock(history, truth)
        print(f"ground truth: {truth:.1f} BPM -> {verdict}"
              + (f", locked after {lock:.1f} s" if lock is not None else ""))
    print(f"processed {len(env)} frames in {wall:.3f} s "
          f"({len(env) / wall / rate:,.0f}x realtime)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true",
                    help="6 representative tempi instead of the 50-240 sweep")
    ap.add_argument("--json", metavar="FILE",
                    help="also dump per-run results as JSON")
    ap.add_argument("--audio", metavar="FILE",
                    help="evaluate a real audio file instead of the synthetic suite")
    ap.add_argument("--bpm", type=float, default=None,
                    help="ground-truth BPM for --audio")
    ap.add_argument("--phase", action="store_true",
                    help="benchmark beat-phase (next-beat prediction) accuracy")
    ap.add_argument("--seed", type=int, default=1234)
    args = ap.parse_args()

    if args.phase:
        return run_phase_eval(seed=args.seed)
    if args.audio:
        return evaluate_audio(args.audio, args.bpm)

    tempi = [60, 90, 120, 150, 180, 220] if args.quick else list(range(50, 241, 10))
    rows, runs, perf = run_suite(tempi, seed=args.seed)
    print_report(rows, perf, tempi)
    if args.json:
        Path(args.json).write_text(
            json.dumps({"rows": rows, "runs": runs, "perf": perf}, indent=2))
        print(f"\nper-run results written to {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
