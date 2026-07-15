# Beat tracking: architecture, performance ladder, latency

The Auto Mode BPM stack, rebuilt across July 2026 in four measured steps.
Every number below is reproducible:

    python scripts/evaluate_bpm_detector.py            # flux-level sweep (7 scenarios x 20 tempi)
    python scripts/evaluate_bpm_detector.py --phase    # beat-phase accuracy
    python scripts/compare_bpm_qlcplus.py              # audio-level head-to-head vs QLC+ ports
    python scripts/compare_bpm_qlcplus.py --songs <wavs> --structures <csvs>   # real songs

The real-song acceptance benchmark is the Shoo Bee Doom album (9 full
masters, ground truth from the legacy show-structure CSVs), scored as the
percentage of post-warmup time the estimate is within 4% of the
truth-at-that-time. See
[bpm-comparison-qlcplus.md](bpm-comparison-qlcplus.md) for the QLC+ side.

## Architecture

Two components. All constants live in the files named here.

**Front end** (`audio/realtime_spectral.py`, `_push_beat_samples`):
onset strength for beat tracking, separate from the seven display
metrics. Runs on the UNDECIMATED signal: hop 512 at 44100 = **86.13
onset values per second** (`beat_frame_rate_hz`), FFT window 2x n_fft =
4096 samples = 93 ms (matching the decimated feature path's temporal
integration; a 46 ms window resolves every micro-transient of sustained
instruments and buries the beat on real music). Per hop:

1. log1p magnitude spectrum, positive difference vs. previous hop;
2. split into three bands: <200 Hz (kick), 200-4000 Hz (snare/vocals),
   >4 kHz (hats/cymbals);
3. each band saturated against its own recent peak (~3 s decay
   follower): a kick and a snare onset spike near-equally, so a
   backbeat's every-beat periodicity survives;
4. each band reduced to its rising edge: a snare's noise tail produces
   "new energy" for several frames, a kick doesn't - shapes equalize;
5. weighted sum with the high band at 0.4: hats stay visibly weaker
   than beats, so subdivision does not read as double tempo.

Values reach the detector via `LiveFeatureFrame.flux_raw_hops` (~2 hops
per 43 Hz feature frame). The normalized `flux` display metric is
untouched by all of this.

**Detector** (`auto/bpm_detector.py`, `AutoBPMDetector`), per 2 s
analysis over an 8 s window:

1. unbiased autocorrelation of the onset train, pre-smoothed with a
   rate-scaled kernel (~+/-23 ms) that absorbs human timing jitter;
2. every candidate tempo on a fractional 0.25 BPM grid (50-240) scored
   by a harmonic comb: ACF at 1x..4x its period, each sampled as the
   local max within +/-1 lag, weights 1 / 0.7 / 0.45 / 0.3;
3. temporal belief filter over the grid (observation = scores^3,
   transition = small blur + 10% uniform jump) picks a stable base
   candidate - one noisy analysis cannot flip the estimate, a real
   tempo change wins within a few analyses;
4. octave-raise walk from the base: prefer the fastest 2x/3x candidate
   whose comb score holds >= 0.90 of the current one, with +/-0.04
   hysteresis toward the previously reported octave;
5. `get_bpm()` = median of the last 3 analyses, gated on confidence
   >= 0.15 (real music scores ~0.2-0.5, aperiodic noise < 0.1);
6. beat phase: the onset window is correlated with an impulse train at
   the found period (half-life-of-one-beat decay weighting);
   `get_next_beat()` returns seconds to the next predicted beat,
   extrapolated from the anchor between analyses.

Rejected on measurements (do not re-try without new evidence): a
log-normal tempo prior (systematically halves everything >= 190 BPM); a
continuity score bonus (locks in early wrong estimates); scalar log1p
compression in the detector (the alternation problem is spectral extent
and envelope shape, not scalar height - solved by the band front end).

## Performance ladder

Chronological; each row = cumulative state. "Flux suite" = 140-case
synthetic sweep at the detector API; "synthetic audio" = 64-case
head-to-head suite (kick/snare/hats/bass over a pad, 8 scenarios x 8
tempi); "album" = % of time correct on the 8 timeline-scored songs.
QLC+ references on the same benchmarks: **A = 48/64 and 63% album**,
B = 54/64 and 4% album.

| state | flux suite | synthetic audio | album (octave) |
|---|---|---|---|
| original: plain ACF argmax + both wiring bugs | 87/140 | 21-25/64 | 5-14% (garbage finals) |
| wiring fixed (raw flux, true rate) | 111/140 | 46/64 | 35% (44%) |
| comb scoring + octave-raise + median-3 | 140/140 | 59/64 | 47% (36%) |
| step 1: multi-band saturated rising-edge onset | 140/140 | 63/64 | 48% (25%) |
| step 2: undecimated 86 Hz, 93 ms window, rate-scaled kernel, gate 0.15 | 140/140 | **64/64** | 60% (30%) |
| step 3: belief filter + raise hysteresis | 139/140 | **64/64** | **65% (29%)** |
| step 4: beat phase output | unchanged | unchanged | unchanged |

Notes per step:

- **Step 1** fixed the kick/snare backbeat half-lock (audio suite 3/8 ->
  8/8). Root cause was not loudness but spectral extent and envelope
  shape; per-bin and scalar log compression both failed (measured), the
  band split + saturation + rising edge worked.
- **Step 2** is where fast swing became winnable: at 43 Hz a 190 BPM
  beat is ~13.6 frames; at 86 Hz it is ~27. Two pitfalls cost a full
  benchmark round each: the beat FFT window must stay ~93 ms in
  SECONDS, and the pre-ACF smoothing must scale with the rate or human
  timing jitter smears the ACF peak. The confidence gate moved 0.3 ->
  0.15 (the sharper onset train scores lower absolute ACF values while
  being more reliable - on a 139 BPM song the estimates were 138-140
  and 64% of them were being discarded by the old gate).
- **Step 3** turned near-parity into a win: per-song, the belief filter
  + hysteresis took Old School Medicine 86->98%, Swingin It 85->96%,
  Take the Wheel 77->99%, Party of One 79->93%. Cost: one flux-suite
  drift case flips octave once (139/140), and re-lock after a tempo
  step takes ~12-16 s instead of ~8 (measured, deliberate trade).
  Raise-threshold sweep 0.90-0.94 is flat on the album: the two
  remaining failures (Burning Out 6%, Cycle of a Psycho 2%, both read
  double) are evidence-driven - the 8th-note activity genuinely
  dominates those mixes; QLC+ A fails both too (13% / 0%).
- **Step 4** adds phase: predicted next-beat vs true click grid is
  0-12 ms mean error (p95 <= 30 ms) across 60-180 BPM, clean and noisy,
  100% availability after warmup. Known corner: strongly alternating
  accents at an exact-integer-period tempo (120 at 86 Hz) can anchor a
  beat off (p95 500 ms there). Not yet consumed by the UI.

Final album per song (ours vs QLC+ A): Black and Blues 55% vs 2%,
Burning Out 6% vs 13%, Cycle of a Psycho 2% vs 0%, Devil's Dance correct
vs correct, Monsters in my Head 76% vs 92%, Old School Medicine 98% vs
100%, Party of One 93% vs 100%, Swingin It 96% vs 97%, Take the Wheel
99% vs 100%. On the demo excerpt the detector reads 191.5 = the notated
192 (librosa reads the felt half-time 95.7; both are defensible octaves
of the same pulse).

## When is the BPM safe to use? (estimate-onset latency)

Measured on the flux-level benchmark (clean + noisy clicks):

| window | first estimate | typically correct by | notes |
|---|---|---|---|
| 8 s (default) | ~4.0 s | 4-8 s | needs half its window; analyses every 2 s |
| 4 s (scout) | ~2.0 s | 2-6 s | fewer beats in window: less reliable at slow tempi (4 beats at 60 BPM) |

- After a genuine tempo change the default configuration re-locks in
  ~12-16 s (belief stickiness + 3-analysis median, both deliberate);
  the flux suite's tempo-step scenario pins this.
- Confidence (`AutoBPMDetector.confidence`) is the calibrated "safe"
  signal: >= 0.15 gates reporting at all; sustained >= 0.3 on real
  music means a stable lock. Silence and noise never report.
- **On the 43 + 86 Hz concurrent idea:** frame rate does NOT set the
  latency - the window length does (both rates fill an 8 s window in
  8 s). The undecimated 86 Hz stream is strictly better signal, so
  running a 43 Hz detector alongside buys nothing. The quick-then-
  correct scheme that DOES work: a second `AutoBPMDetector` scout with
  `window_seconds=4` fed the same `flux_raw_hops` (cheap: one extra
  0.6 ms analysis every 2 s). Report the scout's estimate from ~2 s,
  switch to the 8 s detector once it reports at ~4 s, exactly as
  measured above. Not currently wired into the Auto tab; the detector
  API supports it as-is.
