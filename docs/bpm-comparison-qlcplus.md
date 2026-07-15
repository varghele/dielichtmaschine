# BPM tracking: this repo vs. QLC+ upstream

Comparison of our Auto Mode BPM detection against both QLC+ beat tracking
implementations, run 2026-07-06. Reproduce with
`python scripts/compare_bpm_qlcplus.py` (synthetic suite) and
`--audio <file>` (real audio). The QLC+ side (both implementations, their
integration contract in `audiocapture.cpp` / `inputoutputmap.cpp`, and
their defect list) was analyzed from a local checkout of upstream branch
`beattracker`, commit 41778df01; that point-by-point reference now lives
with the C++ port in the qlcplus working copy. The comparison script
contains faithful Python ports of both implementations, which double as
executable documentation of their behavior.

## Contenders

| Tracker | What it is |
|---|---|
| QLC+ A (`BeatTracking`) | ACF tempo induction: full-spectrum onset flux at 86 Hz hops, unbiased autocorrelation + comb filter, Rayleigh prior at 110 BPM, tps2/tps3 octave disambiguation, two-state continuity lock. Ported **without** its live integration bugs (channel-count/OOB read, dead build flag), i.e. its best case. |
| QLC+ B (`BeatTracker`) | Reactive onset detector: 40-400 Hz spectral flux, adaptive mean threshold, 0.2 s refractory. No tempo model; BPM = mean of the last 16 inter-onset intervals. We score its internal estimate, which is kinder than the wall-clock number QLC+ actually displays. |
| ours (app wiring) | The Auto tab path exactly as wired today: `RealtimeSpectralAnalyzer` (2:1 decimation, 2048-pt STFT, hop 512, normalized + 0.6 s-smoothed flux at ~43 frames/s) into `AutoBPMDetector()` at its default 86 Hz rate assumption. |
| ours (rate-corrected) | Same front end, detector told the true ~43.07 Hz frame rate. |

## Synthetic suite (8 scenarios x 8 tempi, 60-180 BPM, 24 s clips, 4% tolerance)

Scenarios are synthesized 44.1 kHz PCM (kick / snare / hats / 8th-note bass
over a sustained pad), so each tracker runs its native front end.

| tracker | correct | octave | related | wrong | none | mean err % | lock s |
|---|---|---|---|---|---|---|---|
| QLC+ A (BeatTracking) | 48/64 | 16 | 0 | 0 | 0 | 0.82 | 8.1 |
| QLC+ B (BeatTracker) | 54/64 | 1 | 0 | **9** | 0 | 0.49 | 6.5 |
| ours (app wiring) | 25/64 | 34 | 4 | 1 | 0 | 0.64 | 17.1 |
| **ours (rate-corrected)** | **59/64** | 5 | 0 | 0 | 0 | 1.58 | 12.1 |

Per-scenario correct counts (out of 8):

| scenario | QLC+ A | QLC+ B | ours (app) | ours (corrected) |
|---|---|---|---|---|
| kick four-on-floor | 7 | 8 | 2 | 8 |
| kick + 8th hats | 4 | 8 | 2 | 8 |
| kick/snare backbeat | 7 | 7 | 8 | 3 |
| 8th-note bassline | 4 | **1** | 3 | 8 |
| swung hats | 6 | 8 | 2 | 8 |
| tempo drift +/-3% | 6 | 8 | 3 | 8 |
| 2.5 s dropout | 7 | 6 | 2 | 8 |
| tempo step +30% | 7 | 8 | 3 | 8 |

## Real audio (demos/shows/audiofiles/monsters_demo.ogg, librosa reference 95.7 BPM)

| tracker | estimate |
|---|---|
| QLC+ A | 189.6 BPM (double) |
| QLC+ B | 94.8 BPM (correct) |
| ours (app wiring) | 240.0 BPM (clamp ceiling, garbage) |
| ours (rate-corrected) | 240.0 BPM (clamp ceiling, garbage) |
| ours, detector fed **raw** flux at 43 Hz | **95.7 BPM** (== librosa, confidence 0.37) |

## Findings

1. **Our detector core wins.** Fed a proper onset-flux signal at the correct
   frame rate, `AutoBPMDetector` beats both QLC+ implementations: 92%
   correct on the synthetic sweep (QLC+ A: 75%, QLC+ B: 84%) with zero
   non-octave errors, and it matches librosa exactly on real audio. Its
   losses are half-tempo octave errors on the alternating kick/snare
   backbeat, a known and bounded failure mode (flux pattern genuinely has a
   2-beat period; QLC+ A's comb filter handles this better).
2. **QLC+ B fails unbounded, not just by octaves.** On the 8th-note
   bassline (in-band energy on every 8th, the documented issue #1881
   symptom) it returns non-harmonic garbage (e.g. 152 for a 90 BPM track,
   "wrong" 9/64 times) because averaging raw inter-onset intervals has no
   tempo model. Our errors are always musically related (x2 / x0.5); B's
   are not.
3. **QLC+ A is solid but slow and biased.** ~6 s minimum latency and
   re-estimation only every ~6 s by design; 25% octave errors concentrated
   where its 110 BPM Rayleigh prior pulls estimates down (140+ BPM read at
   half). And this is its ported best case: the shipping integration has a
   channel-count bug that corrupts its input (`audiocapture.cpp` constructs
   it with 2 channels against a 1-channel capture default, and its mixdown
   loop treats total samples as a frame count - out-of-bounds reads).
4. **Our app wiring is broken, in two compounding ways.** This is the
   actionable outcome:
   - **Rate mismatch (2x)**: `AutoBPMDetector()` defaults to
     `analysis_rate_hz=86`, but `RealtimeSpectralAnalyzer` decimates to
     22.05 kHz and emits frames at 44100/1024 = **43.07 Hz**
     (`gui/tabs/auto_tab.py:68` + `auto/bpm_detector.py:79`). Every in-app
     estimate is doubled: a 120 BPM track reads ~240.
   - **Wrong flux signal**: the detector consumes
     `LiveFeatureFrame.flux`, which is the *display* metric: envelope-
     normalized and smoothed with a 0.6 s time constant
     (`audio/realtime_spectral.py`, `_compute_frame`). On sparse synthetic
     kicks the periodicity survives; on real music the smoothed signal's
     short-lag autocorrelation dominates and argmax collapses to the
     minimum searched lag, i.e. the 240 BPM clamp. Feeding the *raw*
     spectral flux fixes it outright (95.7 BPM above).

## Wiring fix (applied 2026-07-06)

`LiveFeatureFrame` gained a `flux_raw` field (unnormalized, unsmoothed
spectral flux, same pattern as `centroid_hz`); `AutoBPMDetector.on_feature`
consumes it instead of the display `flux`; the Auto tab constructs the
detector with the analyzer's true `frame_rate_hz` (~43.07) instead of the
86 default. Regression tests in `tests/unit/test_bpm_detector.py`
(`TestAnalyzerToDetectorWiring`), including an end-to-end audio-to-BPM
test through the real analyzer front end. In the tables below,
"ours (pre-fix wiring)" reproduces the old behaviour, "ours (fixed
wiring)" is what the app now does.

## Post-fix results

Synthetic suite after the fix (same 8x8 sweep as above):

| tracker | correct | octave | wrong+related | demo track |
|---|---|---|---|---|
| QLC+ A | 48/64 | 16 | 0 | 189.6 (double) |
| QLC+ B | 54/64 | 1 | 9 | 94.8 (correct) |
| ours (pre-fix wiring) | 25/64 | 34 | 5 | 240.0 (garbage) |
| ours (fixed wiring) | 46/64 | 18 | 0 | **95.7 (== librosa)** |

The fixed path scores slightly below the old smoothed-flux path on
*synthetic clicks* (46 vs 59): the 0.6 s smoothing incidentally widened
the synthetic 1-frame spikes, masking the non-integer-lag peak-splitting
weakness, which is more visible at the true 43 Hz rate (halved lag
resolution). On real audio the trade is entirely one-sided: smoothed flux
was unusable (240 clamp), raw flux matches librosa.

## Real-album evaluation (Shoo Bee Doom, Devil's Dance, 9 songs scored)

Full masters (~4 min each), ground truth from the legacy show-structure
CSVs (per-part BPM x bars -> a tempo timeline). Scored as % of
post-warmup time the estimate is within 4% of the truth-at-that-time
(Devil's Dance scored against its dominant tempo only: its CSV covers the
intro track too, so the timeline does not align). Swing metal, mostly
fast (183-193 BPM), some tempo changes mid-song.

| tracker | time correct | time octave | notes |
|---|---|---|---|
| QLC+ A | **63%** | 32% | 92-100% on the five fast swing tunes; fails Black and Blues (40/80) and Cycle of a Psycho (103.5, reads double) |
| QLC+ B | 4% | 8% | collapses on real music, as on the synthetic bassline |
| ours (pre-fix wiring) | 14% | 24% | finals pinned at the 240 clamp on 7/9 songs |
| ours (fixed wiring) | 35% | 44% | estimates are now tempo-related (correct or half/double) instead of garbage; loses to A on fast swing |

Takeaway: the wiring fix moves us from useless to usable (14% -> 35%
time-correct, and 79% of the time the estimate is now the right tempo or
a musically-related octave of it), but on fast swing material QLC+ A's
full tempo-induction stack wins - specifically its comb filter and
tps2/tps3 harmonic reinforcement, which is exactly the octave
disambiguation our roadmap follow-up proposes for `AutoBPMDetector`.
QLC+ A's own weaknesses stand: ~6 s latency, ~6 s re-lock, halving of
100-125 BPM material (Rayleigh prior), and its shipping integration bug.
"I Gotta Sing" and "The Invitation" were skipped (no matching structure
CSV; supply BPMs to include them). Reproduce with:

    python scripts/compare_bpm_qlcplus.py --songs <dir-of-wavs> --structures <dir-of-csvs>

## Detector upgrade: harmonic scoring + octave-raise (2026-07-06, same day)

The octave weakness was then fixed in `AutoBPMDetector._analyze`:

- **Fractional tempo grid.** Candidates are scored on a 0.25 BPM grid with
  ACF values read at fractional lags, removing lag quantization outright
  (critical at 43 Hz, where 190 BPM is only ~13.6 frames per beat).
- **Harmonic (comb) scoring.** Each candidate's score is a weighted sum of
  the ACF at 1x..4x its beat period, each sampled as the local max within
  +/-1 lag so split or slightly detuned peaks count at full height.
- **Octave-raise walk.** For a strongly periodic signal every subharmonic
  has an equally saturated comb, so after the argmax the estimate walks up
  to 2x/3x-faster candidates while their score stays >= 0.92 of the
  current one. Genuine beats keep the faster candidate's fundamental
  strong; weak off-beat subdivision does not - this disambiguates octaves
  in both directions without a tempo prior (a prior was tried first and
  systematically halved everything above ~190).
- **3-analysis median output.** `get_bpm()` reports the median of the
  last 3 analyses, ending octave flapping between near-tied 2 s analyses
  (+3-4 points time-correct on the album sweep; costs ~2 s after a real
  tempo change).

Results after the upgrade (vs. the tables above):

- Flux-level sweep (`evaluate_bpm_detector.py`, 7 scenarios x 20 tempi):
  **140/140 correct, zero octave errors** (argmax version: 111/140), mean
  error ~0.4%, one analysis pass 0.6 ms.
- Synthetic audio suite: **ours 59/64 - best of all four trackers**
  (QLC+ A 48, QLC+ B 54). Only remaining loss: kick/snare backbeat
  alternation (3/8), where the 2-beat timbre period is genuine evidence.
- Demo track: 95.8 BPM (librosa: 95.7).
- Real album: **47% time-correct + 36% octave** (argmax fixed wiring: 35%;
  pre-fix: 5-14%). QLC+ A still leads at 63% on this material. Where it
  wins: the fast swing tunes, where two factors compound against us -
  (a) our 43 Hz flux rate is a structural handicap at 183-193 BPM
  (~14 frames/beat even with fractional scoring), and (b) the CSV "truth"
  is the notated click tempo; on Monsters in my Head the audio's dominant
  periodicity really is ~96 (librosa agrees with us), while A's ~6 s
  window + comb happens to land the notated 192. Ours now beats A
  clearly on Black and Blues (50% vs 2%) and Cycle of a Psycho (19% vs
  0%), and is within ~20 points on the other swing tunes.

A threshold/smoothing sweep (0.88-0.94 x median 1/3) showed the current
config is at the plateau (~47-51%); the next real lever is feeding the
detector an undecimated (86 Hz) flux stream, which is front-end work in
`RealtimeSpectralAnalyzer`, not detector tuning.

## Final state (July 2026, four-step rebuild)

The levers above were then implemented as a measured four-step program:
multi-band saturated rising-edge onset front end, undecimated 86 Hz
beat-flux stream, a temporal belief filter with octave hysteresis, and
beat-phase output. Full ladder, architecture, and latency
characterization: [beat-tracking.md](beat-tracking.md). Bottom line on
the same benchmarks as this document: **ours 64/64 on the synthetic
audio suite (QLC+ A: 48, B: 54) and 65% time-correct on the real album
(A: 63%, B: 4%)** - the detector now leads on both synthetic and real
material, with the two remaining album failures (Burning Out, Cycle of
a Psycho) being songs both QLC+ trackers also misread.

## Caveats

- QLC+ ports are Python; throughput is not compared (all candidates are
  30x+ realtime here; both QLC+ trackers are cheap in C++).
- QLC+ B is scored on its internal BPM. What QLC+ *displays* is derived
  from wall-clock spacing of emitted beat signals with 1-beat memory
  (`inputoutputmap.cpp`, `slotProcessBeat`), which is strictly noisier.
- Tolerance is 4%; "octave" = 2x, 0.5x, 3x or 1/3x; "related" = 1.5x, 2/3x,
  0.75x or 4/3x; "wrong" = none of those.
