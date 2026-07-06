# QLC+ Beat Tracking — Reference for Algorithm Comparison

Purpose: accurate description of the two beat-tracking implementations in QLC+ (upstream
`mcallegari/qlcplus`), their integration contract, and their known defects — so an
independent implementation (e.g. this repo's beat tracker) can be compared against them
point by point.

Source of truth: local checkout at `C:\Users\varghele\PycharmProjects\qlcplus`,
branch `beattracker`, HEAD commit `41778df01` ("engine: re-import beat tracker proposed
by @Wazzledi"). All file:line references below refer to that state. Related upstream
issue: https://github.com/mcallegari/qlcplus/issues/1881 ("[Feature] full beat tracking").

---

## 1. The two implementations at a glance

| | **A: `BeatTracking`** (Wazzledi / Dennis Suermann) | **B: `BeatTracker`** (Massimo Callegari) |
|---|---|---|
| Files | `engine/audio/src/beattracking.h/.cpp` | `engine/audio/src/beattracker.h/.cpp` |
| Approach | Full tempo induction: onset detection → autocorrelation + comb filter → Rayleigh-weighted lag pick → tempo state machine → phase estimation → **predicted** beat grid | Reactive onset detector: band-limited spectral flux + adaptive threshold + refractory period; beats = detected onsets, BPM = mean of recent inter-onset intervals |
| Origin | PR #1876 (merged, then reworked); re-imported on branch `beattracker` | Written by the maintainer while investigating #1881; currently active on `master` |
| Active when | `NEW_TRACKER` **not** defined (current state of branch `beattracker`, see `audiocapture.h:46`) | `NEW_TRACKER` defined (and unconditionally on current `master`) |
| Latency to first beat | ~5.9 s (onset window must fill) | one FFT block (~46 ms), after threshold history warms up |
| Beat timing | Predicted grid, quantized to 512-sample hops (11.61 ms @ 44.1 kHz) | Onset-triggered, quantized to 2048-sample blocks (46.4 ms) |

Both process **int16 interleaved PCM** pushed in blocks from a capture thread; both use
FFTW3 (`HAS_FFTW3`) for spectra.

---

## 2. Integration contract (what any replacement must plug into)

### Audio input side — `engine/audio/src/audiocapture.{h,cpp}`

- `AudioCapture` is a `QThread` subclass; platform backends (ALSA/PortAudio/Qt5/Qt6/WaveIn)
  implement `readAudio()`.
- Format defaults (`audiocapture.h:38-40`): **44100 Hz, 1 channel, 2048 frames per block**
  (`AUDIO_DEFAULT_SAMPLE_RATE`, `AUDIO_DEFAULT_CHANNELS`, `AUDIO_DEFAULT_BUFFER_SIZE`).
  Sample rate and channel count are user-overridable via QSettings keys
  `audio/samplerate` and `audio/channels` (`audiocapture.h:34-36`, read in ctor
  `audiocapture.cpp:54-63`). So **stereo and 48 kHz configurations are legal inputs.**
- `m_captureSize = m_bufferSize * m_channels` (`audiocapture.cpp:67`) — i.e. the buffer
  length handed around is **total samples (frames × channels), not frames**.
- Capture loop `AudioCapture::run()` (`audiocapture.cpp:297-337`): per iteration it reads
  one block, runs the spectrum FFT for the UI (`processData()`), then:
  ```cpp
  #ifdef FULL_BEATTRACKING                       // audiocapture.cpp:317
      if (m_beatTracker->processAudio(m_audioBuffer, m_captureSize))
          emit beatDetected();
  #endif
  ```
  The tracker therefore gets the **raw interleaved int16 buffer** and returns a bool
  "beat occurred somewhere in this 46 ms block".
- Tracker construction (`audiocapture.cpp:79-86`):
  - `NEW_TRACKER` path: `new BeatTracker(m_sampleRate, m_bufferSize, m_channels, 86, 1.3)`
    then `setBand(40.0, 400.0)`, `setFluxSmoothing(0.6)`, `setMinBeatInterval(0.20)`.
  - default path: `new BeatTracking(2)` — **channel count hard-coded to 2** (defect, §5.1).

### Consumer side — `engine/src/inputoutputmap.cpp`

- When the user selects beat generator "Audio" (`setBeatGeneratorType`,
  `inputoutputmap.cpp:1043-1053`): `beatDetected()` is connected to `slotProcessBeat()`
  and 4 spectrum bands are registered (which is what actually starts the capture thread —
  `registerBandsNumber`, `audiocapture.cpp:110-135`).
- `slotProcessBeat()` (`inputoutputmap.cpp:1115-1133`):
  ```
  elapsed = wall-clock ms since previous beatDetected()
  bpm     = round(60000 / elapsed)
  if |elapsed - 60000/currentBPM| > 1 ms:  setBpmNumber(bpm)
  masterTimer->requestBeat();  emit beat();
  ```
  **Key consequence:** the BPM number QLC+ displays is *not* the tracker's internal tempo
  estimate — it is re-derived from wall-clock spacing of emitted beat signals, one beat at
  a time, with only ±1 ms hysteresis. A single missed/extra emission or one hop of jitter
  (11.6 ms ≈ ±2 BPM at 120 BPM) immediately changes the displayed BPM. Neither tracker's
  internal BPM value (`BeatTracking::m_currentBPM`, `BeatTracker::getCurrentBpm()`) is
  ever read by the engine.

### Build-flag state (matters for reproducing behavior)

- `FULL_BEATTRACKING` is **defined nowhere** in any build file → on branch `beattracker`
  the emit is compiled out; testers must add the define manually.
- On current `master` the guard was removed (call is unconditional) and only
  implementation B exists/runs.
- `NEW_TRACKER` (`audiocapture.h:46`, commented out) switches include, member type and
  construction between B and A (`audiocapture.cpp:27-31`, `79-86`; `audiocapture.h:48-52`,
  `179-183`).

---

## 3. Implementation A — `BeatTracking` (ACF tempo induction, Wazzledi/Suermann)

Constants (`beattracking.h:32-36`): sample rate **44100 hard-coded**, analysis window
**1024**, hop **512**, onset window **512 onset values**, Rayleigh prior target
**110 BPM**. Ctor (`beattracking.cpp:34-71`): initial BPM 120, silence-gate RMS threshold
0.001 (≈ −60 dBFS), `m_continuityDerivation = targetLag/8` where
`targetLag = (44100·60)/(110·512) ≈ 46.9 hops`.

Pipeline per `processAudio(buffer, bufferSize)` call (`beattracking.cpp:118-362`):

1. **Mixdown & accumulate** (`:124-133`): for `i in [0, bufferSize)` append
   `mean over channels of buffer[i*channels + j] / 32768` to a growing `m_windowBuffer`.
   (Note `bufferSize` is *total samples* — see defect §5.1.)
2. **Hop loop** (`:136`): while ≥1024 samples buffered, take the first 1024, apply a Hann
   window (`:141-142`), then drop 512 samples at the end of the iteration (`:358`) →
   50 % overlap, one "block" = 512 samples = **11.61 ms**.
3. **Silence gate** (`:144-160`): RMS of the *windowed* block < 0.001 → skip FFT, onset
   value = 0.
4. **Onset detection function** (`:163-179`): 1024-point real FFT; onset value =
   Σ over bins 0..511 of positive magnitude increase vs. previous block
   (linear magnitude, no log compression, full spectrum, no band limiting).
5. **Onset post-processing** (`:330-343`): keep last 8 raw onset values; run
   `calculateBiquadFilter` (`:431-464`) — nominally a forward-backward (zero-phase)
   biquad low-pass, **but the backward pass overwrites rather than composes with the
   forward pass** (the second loop restarts from `processed[i] = b0·values[i]`), so
   effectively only an anti-causal biquad of the raw values (quirk). Then
   `thresholded = filtered[5] − median(filtered) − 0.1·mean(filtered)` is appended to
   `m_tOnsetValues`.
6. **Tempo induction** — runs only when `m_tOnsetValues` reaches 512 entries
   (512 hops ≈ **5.94 s**) (`:182`):
   - Autocorrelation of the onset signal, unbiased (÷ (N−lag)), then a comb filter
     summing harmonics a=1..4 (`getOnsetCorrelation`, `:364-396`).
   - Multiply by Rayleigh filter bank peaked at ~46.9 hops ≈ 110 BPM
     (`getRaileighFilterBank`, `:95-105`) — this is the tempo prior.
   - Lag pick with octave disambiguation: score each lag r with 2r and 3r harmonic
     reinforcement (tps2/tps3), take the better maximum
     (`getPredictedAcfLag`, `:398-429`); refine with quadratic (parabolic)
     interpolation (`getQuadraticValue`, `:489-503`).
   - **Two-state tempo model** (`:200-258`): `ACF` (free) vs `CONTINUITY` (locked).
     Locks when the last 3 raw ACF lags satisfy `|2·L2 − L1 − L0| < targetLag/8`;
     while locked, the lag is re-picked from the *unweighted* ACF under a Gaussian
     centered on the current lag (σ = lag/8); unlocks after the ACF lag disagrees with
     the continuity lag by ≥ targetLag/8 on >2 consecutive estimates.
   - `BPM = (44100·60)/(512·lag)` (`:260`).
7. **Phase estimation & beat grid** (`:263-321`): correlate the time-reversed,
   exponentially decayed onset window (half-life = one beat period) with an impulse
   train at the identified lag; when locked, additionally Gaussian-weight phases near
   the previously predicted next beat; parabolic-refine; then fill
   `m_beatPredictions` with beat positions `beat, beat+lag, beat+2·lag, …` for the next
   **512 blocks (≈ 5.94 s)**.
8. **Onset window flush** (`:324-325`): erases `windowSize/2 = 512` entries — i.e. **the
   entire onset window** (onset window is also 512). Tempo/phase are therefore
   re-estimated only every ~5.94 s, and the beat grid runs open-loop in between.
   (Likely intended as a 50 % overlap of the *onset* window, i.e. erase 256.)
9. **Beat emission** (`:344-356`): a hop counter `m_blockPosition` (reset to −1 at each
   tempo re-estimation) is compared against `qFloor(prediction)`; on match,
   `processAudio` returns true → `beatDetected()` fires. Emission resolution is
   therefore one hop = 11.61 ms, and beat *positions* are only meaningful relative to
   the last ACF run.

**Behavioral summary A:** strong tempo prior at 110 BPM; needs ~6 s of music before the
first beat; corrects tempo/phase only every ~6 s; internally robust octave handling
(comb + tps2/tps3) but the emitted-beat wall-clock BPM (§2) inherits ±11.6 ms hop jitter.

---

## 4. Implementation B — `BeatTracker` (spectral-flux onset detector, Callegari)

Ctor/defaults (`beattracker.cpp:42-108`, overridden at `audiocapture.cpp:80-83`):
FFT size = next pow2 of block size (2048), flux history 86 blocks ≈ 2 s, sensitivity
1.3, flux smoothing α 0.7 (→ 0.6 in integration), min beat interval 0.25 s (→ 0.20 s),
silence threshold 0.01 peak (≈ −40 dBFS), analysis band 40–2000 Hz (→ 40–400 Hz).
Handles format changes at runtime (`setFormat`, `:194-253`).

Pipeline per `processAudio(buffer, bufferSize)` (`beattracker.cpp:321-527`), one FFT per
2048-frame block (no overlap, ~46.4 ms cadence):

1. **Mixdown** (`:327-331`, `:349-367`): `frames = bufferSize / channels` (correct
   interleaving handling), average channels, normalize /32768, Hann window, track peak
   amplitude.
2. **Silence gate** (`:369-423`): peak < 0.01 → no FFT; smoothed flux decays by α;
   history still updated; after ~2 s of silence the BPM interval memory is cleared.
3. **Spectral flux** (`computeSpectralFlux`, `:256-288`): over bins 40–400 Hz only, with
   `log1p` magnitude compression, positive differences only, linearly weighted 1.5× at
   the low edge → 1.0× at the high edge.
4. **Smoothing** (`:443-445`): 1-pole low-pass, α = 0.6.
5. **Adaptive threshold** (`computeAdaptiveThreshold`, `:290-302`): mean of the last 86
   smoothed-flux values × sensitivity 1.3.
6. **Peak pick** (`:460-466`): beat iff smoothed flux > threshold AND > previous value
   AND ≥ 0.20 s since last beat (refractory). Returns true immediately → beat latency is
   one block.
7. **BPM estimate** (`:469-489`, `getCurrentBpm` `:304-318`): store inter-beat intervals
   (accepted only if 0.25 s < dt < 2.0 s, i.e. 30–240 BPM), keep last 16, BPM = 60 /
   mean. **Never consumed by the engine** — display BPM comes from §2 wall-clock logic.

**Behavioral summary B:** no tempo model at all — every super-threshold low-band onset
is "a beat". On real music it fires on kicks *and* snares/bass notes within 40–400 Hz,
so on a 90 BPM track firing on 8th-note energy it reads ~180 BPM; syncopation produces
irregular emission. This matches the #1881 symptoms ("180 BPM", "beats not emitted at a
reliable rate"). Debug logging available via `BEAT_DEBUG` (`beattracker.cpp:29`).

---

## 5. Known/suspected defects (as of branch `beattracker`)

1. **Channel-count integration bug (impl. A)** — `new BeatTracking(2)`
   (`audiocapture.cpp:85`) vs. capture default of 1 channel, combined with the mixdown
   loop treating its `bufferSize` argument (total samples) as a frame count
   (`beattracking.cpp:124-133`, indexes `buffer[i*channels + j]` for `i` up to
   `bufferSize`): with mono capture it averages adjacent samples (≈2× decimation of the
   valid half) **and reads up to one full buffer past the end** (undefined behavior,
   garbage onsets). With stereo capture it produces 2× too many mono samples (time base
   stretched 2×, BPM halved) and still reads out of bounds. Either way: corrupted onset
   function → wrong tempo and erratic beats.
2. **Hard-coded 44.1 kHz (impl. A)** — `BEAT_DEFAULT_SAMPLE_RATE` (`beattracking.h:32`);
   a 48 kHz capture skews BPM and phase by ~8.8 %.
3. **`FULL_BEATTRACKING` undefined** — beat emission dead in normal builds of this
   branch (`audiocapture.cpp:317`).
4. **Onset-window flush erases 100 % instead of 50 %** (impl. A, `beattracking.cpp:324-325`)
   — tempo/phase corrections only every ~5.9 s; grid drifts open-loop in between.
5. **Biquad "zero-phase" filter discards its forward pass** (impl. A,
   `beattracking.cpp:431-464`).
6. **Displayed BPM derived from wall-clock signal spacing** (`inputoutputmap.cpp:1115-1133`)
   — amplifies any emission jitter from either tracker; no averaging beyond 1-beat memory.
7. **No tempo induction at all in impl. B** — inter-onset BPM is octave/level ambiguous
   by construction.

---

## 6. Comparison checklist for an independent implementation

Input contract to replicate for a fair comparison: int16 interleaved PCM, blocks of
2048 frames, 44.1 kHz mono default (but must tolerate 48 kHz and stereo), silence
possible, per-block boolean "beat" decision (streaming/causal — no lookahead beyond the
current block).

Suggested metrics, chosen so both QLC+ implementations' weaknesses are measurable:

- **Tempo accuracy**: detected vs. ground-truth BPM; count octave errors (×2, ×½, ×⅔)
  separately from small errors. (Issue #1881 reference case: ~180 reported on a track
  it shouldn't be; YouTube id 6oz0ivczNSY.)
- **Beat F-measure / continuity**: standard beat-tracking scoring (e.g. ±70 ms window)
  against annotated beats; impl. B will score low on continuity, impl. A on the first
  ~6 s and across tempo changes.
- **Time to first beat** and **time to re-lock after a tempo change** (A: ≥ 5.9 s by
  design; B: instant but never truly "locks").
- **Inter-beat-interval jitter** of *emitted* beats (A quantizes to 11.6 ms hops, B to
  46.4 ms blocks) — this is what QLC+'s wall-clock BPM display amplifies.
- **Silence behavior**: no beats during silence; recovery time after music resumes
  (A gates at RMS 0.001 on windowed samples; B gates at peak 0.01 and clears tempo
  memory after 2 s).
- **Format robustness**: same audio at 44.1/48 kHz and mono/stereo must yield the same
  BPM (impl. A currently fails both; see §5.1–5.2).
- **CPU per block** (both do one ≤2048-point real FFT per hop/block on the capture
  thread; a replacement should stay in that budget).

---

## 7. Repo/branch state notes (upstream)

- `master`: only impl. B exists (`beattracker.*`); called unconditionally from
  `AudioCapture::run()`; `audiocapture.cpp` has since gained log-spaced spectrum bands
  and power smoothing (diverged from the `beattracker` branch).
- branch `beattracker` (basis of this document): both implementations present,
  impl. A selected (`NEW_TRACKER` commented out), emission behind undefined
  `FULL_BEATTRACKING`.
- Issue #1881 is the umbrella "make beat tracking actually work" ticket; PR #1876 was
  the original contribution of impl. A.
