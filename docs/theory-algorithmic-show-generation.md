# Algorithmic Light Show Generation — Theory & Framework

**Version:** 3.0
**Last Updated:** April 2026

### Changelog

- **v3.0 (April 2026)**: Major revision based on empirical testing against 8 songs with hand-made show comparisons. Replaced spectral flux with RMS energy as primary energy driver. Replaced spectral richness with spectral contrast as secondary energy signal. Updated vocal detection to HPSS + MFCC delta method. Replaced zone-based fixture activation with user-assignable lighting roles (wash, key, texture, accent). Added rhythm and movement as algorithmic attributes rather than roles. Added empirical metric validation data. See `docs/metric_analysis_results.md` for detailed analysis.
- **v2.0 (March 2026)**: Initial framework with rudiment system, audio analysis, and spatial model.


---

## 1. Introduction

This document defines a theoretical framework for algorithmically generating light shows that follow live or recorded music. The core concept is analogous to drum rudiments: pre-defined, composable lighting patterns ("rudiments") that are intelligently selected and combined based on multi-dimensional audio analysis.

The system operates in two modes:

- **Prepared mode**: The operator pre-sets song structure (BPM, time signature, bar count, section markers). The algorithm generates a complete show ahead of time. The user can then review and edit the result in the timeline editor.
- **Live mode** (future): The algorithm runs in real-time, detecting audio input and generating lighting decisions on the fly. Live mode favors steady groove patterns without automatic fills, keeping the output homogeneous and predictable. A rolling analysis window smooths transitions by looking ahead and behind the current moment. The operator can override the algorithm via manual triggers (e.g., "play fill now", "vocals active") to inject intentional changes.

### 1.1 Design Principles

1. **Rudiments are atomic.** Every lighting pattern decomposes into one or more rudiments. If you can't describe a pattern as a rudiment or a sequence of rudiments, the vocabulary is incomplete.
2. **Intensity and movement are independent.** They occupy separate sublanes and are never combined into a single rudiment. They layer naturally because they control different fixture parameters.
3. **Color is not a rudiment property.** Color is determined by the mood/spectral analysis system and applied separately. A rudiment describes *how* intensity or position changes over time, never *what color* it is.
4. **Special effects are parameter-driven.** Gobos and prisms are activated by spectral richness thresholds, not by rudiment selection. Focus follows beam distance.
5. **The output is blocks on a timeline.** Rudiments produce sublane blocks (DimmerBlock, MovementBlock) that slot into the existing show editor. The user can always override, edit, or replace any generated block.

### 1.2 Naming Convention

| Term | Definition |
|------|-----------|
| **Rudiment** | The smallest atomic lighting pattern with a clearly defined intensity or movement logic. Analogous to a drum rudiment. |
| **Block** | A placed instance of a rudiment on the timeline, with concrete parameters (start time, duration, intensity, color, etc.). Maps to existing sublane blocks (DimmerBlock, ColourBlock, MovementBlock, SpecialBlock). |
| **Riff** | A named, reusable, beat-based composition of multiple blocks across sublanes. The existing riff system. A riff is to blocks what a drum fill is to individual strokes. |
| **Groove** | The repeating base lighting pattern for a section. Typically spans 3 bars of a 4-bar phrase. |
| **Fill** | A higher-flux transitional pattern at phrase boundaries. Typically the 4th bar. |
| **Section** | A structural division of the song (verse, chorus, bridge, etc.) defined by the operator or detected automatically. |
| **Fixture Group** | A named set of fixtures that receive the same rudiment assignment. Defined in the show creator. |

---

## 2. Rudiment System

### 2.1 Classification Rule

**If two patterns share the same underlying intensity or movement logic, they are variants of the same rudiment. If they require different logic, they are distinct rudiments.**

For example: a chase running left-to-right and a chase running top-to-bottom are spatial variants of the same "chase" rudiment. But a chase (sequential activation) and a ping pong (alternating activation) are distinct rudiments because their logic differs.

### 2.2 Intensity Rudiments

Intensity rudiments control the dimmer channel. Each rudiment defines how brightness changes over time across the fixtures in a group.

| Rudiment | Logic | Flux Envelope Shape | Parameters |
|----------|-------|-------------------|------------|
| **Static** | All fixtures at constant intensity | Flat | `intensity` |
| **Stroke** | All fixtures activate simultaneously, single pulse | Spike | `intensity`, `attack`, `decay` |
| **Ping Pong** | Intensity alternates between two discrete fixture subsets in a predictable sequence | Square oscillation | `intensity`, `speed`, `split_point` |
| **Chase** | Fixtures activate sequentially in one direction, continuously | Sawtooth (per fixture), rolling (aggregate) | `intensity`, `speed`, `direction`, `tail_length` |
| **Wave** | Intensity moves smoothly from one point to another with a decaying tail | Sine-like with decay | `intensity`, `speed`, `direction`, `decay_rate` |
| **Waterfall / Starfall** | Like wave but multi-point, with pronounced decay | Multi-peak with steep decay | `intensity`, `speed`, `direction`, `point_count`, `decay_rate` |
| **Fill / Infill** | Progressive fill-in or fill-out of fixture group | Ramp (up or down) | `intensity`, `speed`, `direction` |
| **Random Stroke** | Fixtures activate in unpredictable order, creating organic texture | Irregular spikes | `intensity`, `density`, `min_interval`, `max_interval` |
| **Sparkle / Twinkle** | Short random flashes of individual fixtures | Stochastic short pulses | `intensity`, `density`, `flash_duration` |
| **Pulse / Throb** | All or groups of fixtures rhythmically dim and brighten | Sine oscillation | `intensity_min`, `intensity_max`, `speed` |
| **Strobe** | Rapid discrete on/off flashing, synchronized | Square wave (high frequency) | `intensity`, `speed` |
| **Fade / Swell** | Smooth intensity ramp up or down | Linear ramp | `intensity_start`, `intensity_end` |
| **Cascade** | Accumulative intensity build followed by release | Ramp up → sharp drop | `intensity`, `build_speed`, `release_speed` |
| **Heartbeat** | Double-pulse pattern (bump-bump... pause...) mimicking a heartbeat rhythm | Double spike + rest | `intensity`, `speed` |
| **Throb** | Sharp attack with sustained high floor, rhythmic punch that stays bright | Spike with high floor | `intensity`, `speed`, `floor` |

**Spatial variants**: Each intensity rudiment can have spatial variants based on direction, axis, and fixture arrangement. For example:
- Chase: left→right, right→left, center→out, out→center, top→down, bottom→up
- Ping pong: horizontal, vertical, diagonal
- Wave: any directional axis

Spatial direction is a parameter of the rudiment, not a separate rudiment.

### 2.3 Movement Rudiments

Movement rudiments control pan and tilt channels on moving head fixtures. They define how the beam position changes over time.

| Rudiment | Logic | Parameters |
|----------|-------|------------|
| **Static Position** | Fixed pan/tilt | `pan`, `tilt` |
| **Circle** | Circular sweep | `center_pan`, `center_tilt`, `amplitude`, `speed` |
| **Figure-8** | Figure-eight pattern | `center_pan`, `center_tilt`, `amplitude`, `speed` |
| **Lissajous** | Configurable frequency ratio pattern | `center_pan`, `center_tilt`, `amplitude`, `speed`, `freq_ratio` |
| **Linear Sweep** | Back-and-forth along one axis | `start_pan`, `start_tilt`, `end_pan`, `end_tilt`, `speed` |
| **Diamond** | 4-corner diamond path | `center_pan`, `center_tilt`, `amplitude`, `speed` |
| **Square** | 4-corner square path | `center_pan`, `center_tilt`, `amplitude`, `speed` |
| **Triangle** | 3-corner triangular path | `center_pan`, `center_tilt`, `amplitude`, `speed` |
| **Random** | Smooth pseudo-random motion (multi-sine) | `center_pan`, `center_tilt`, `amplitude`, `speed` |
| **Bounce** | Triangle wave back and forth | `start_pan`, `start_tilt`, `end_pan`, `end_tilt`, `speed` |
| **Fan** | Synchronized spread/converge across fixture group | `center_pan`, `center_tilt`, `spread_angle`, `speed` |

Movement rudiments are assigned per fixture group. Different groups can run different movement rudiments simultaneously (e.g., front movers on circle, back movers on linear sweep).

### 2.4 What Is Not a Rudiment

- **Color**: Applied to blocks by the mood/color system (Section 4). Choosing a color is like choosing which drum to play a rudiment on.
- **Gobos**: Activated when spectral richness exceeds a threshold (Section 3.3). Gobo selection is parameter-driven.
- **Prisms**: Same as gobos — activated by spectral richness, not by rudiment selection.
- **Focus**: Follows beam-to-floor distance automatically.
- **Rotation** (gobo rotation): A continuous parameter, not a pattern.

### 2.5 Flux Envelope

Every rudiment has a characteristic **flux envelope** — a normalized curve describing how much visual change the rudiment produces over one cycle. The envelope is represented as a small time-series (normalized to 0.0–1.0 on both axes) sampled at a fixed resolution (e.g., 32 points).

#### Per-Cycle vs. Per-Duration Envelopes

Rudiments fall into two categories based on how their envelope relates to the block duration:

**Cycling rudiments** repeat their pattern multiple times within a block. The envelope describes **one cycle** of the pattern, independent of block duration or tempo. Examples: pulse, strobe, ping pong, chase, wave, sparkle. A pulse rudiment always has a single sine period as its envelope — whether the block plays that cycle 4 times or 64 times depends on BPM and speed multiplier, but the shape of each cycle is the same.

**One-shot rudiments** play their pattern exactly once across the entire block duration. The envelope describes the **full pattern**. Examples: static, fade in, fade out, cascade, fill, stroke. A fade-in rudiment always ramps from 0 to 1 over its block duration regardless of how long the block is.

#### Repetition Rate

For cycling rudiments, a second parameter is needed beyond the envelope shape: the **repetition rate** — how many cycles occur per bar (or per second). This is driven by `BPM × speed_multiplier`.

The repetition rate maps to the *frequency* of visual change:
- High spectral flux that changes rapidly → fast repetition rate (many cycles per bar)
- Low, steady spectral flux → slow repetition rate (one cycle per bar or slower)

The actual flux behavior of a block on the timeline is therefore: `envelope_shape × intensity`, repeating at the cycle rate. The envelope shape determines the *character* of the flux; the repetition rate determines the *frequency* of the flux.

#### Three-Dimensional Matching

When matching rudiments to audio analysis targets, three dimensions are compared:

1. **Envelope shape** — does the rudiment's single-cycle shape match the character of the audio? Percussive audio → spike/square-shaped envelopes. Sustained audio → smooth/sine-shaped envelopes. This comparison is tempo-independent.

2. **Repetition rate** — does the cycle frequency match the rate of change in the audio? High spectral flux frequency → fast cycling rudiments. This only applies to cycling rudiments; one-shot rudiments match by shape alone.

3. **Average flux level** — the single-cycle envelope's average value, combined with the repetition rate, gives the aggregate flux level over time. This must fall within the section's target flux range.

#### Envelope Shape Categories

For quick candidate filtering before detailed comparison, envelope shapes are classified into broad categories:
- **Flat**: Static, constant states (one-shot)
- **Spike**: Single sharp peaks — stroke, cascade release (one-shot)
- **Oscillating**: Repeating symmetric patterns — pulse, strobe, ping pong (cycling)
- **Ramp**: Monotonic increase or decrease — fade, swell, fill (one-shot)
- **Rolling**: Continuous sequential activity — chase, wave (cycling)
- **Stochastic**: Irregular, random patterns — sparkle, random stroke (cycling)

---

## 3. Audio Analysis

The algorithm extracts multiple parameters from the audio to drive lighting decisions. Each parameter maps to specific lighting dimensions.

Parameters are divided into two tiers based on empirical testing across 8 songs (see Section 3.8):

- **Tier 1 (energy drivers)**: RMS energy and spectral contrast. These determine section intensity and fixture activation.
- **Tier 2 (character drivers)**: Spectral flux, transient sharpness, vocal presence, spectral centroid. These drive rudiment matching, color, and spatial rules but do NOT determine energy.

### 3.1 RMS Energy (Tier 1 — Primary)

**What it measures**: Root mean square amplitude — direct measurement of loudness. Computed via `librosa.feature.rms()`.

**What it drives**: Primary input to the section energy composite (Section 3.8). Determines overall visual intensity, fixture activation thresholds, and movement amplitude scaling.
- High RMS → more fixture groups active, higher intensities, wider movements
- Low RMS → fewer groups, dimmer output, tighter movements

**Why RMS over spectral flux**: Empirical testing showed spectral flux has an average range of 0.028 across sections (USELESS for energy differentiation). RMS has an average range of 0.346 (GOOD). RMS is also immune to metronome/click tracks present in backing tracks, which create constant onset strength that masks musical dynamics in flux measurements.

**Resolution**: Per-frame, normalized to 0-1 against song maximum, averaged per section.

### 3.2 Spectral Contrast (Tier 1 — Secondary)

**What it measures**: Peak-to-valley prominence across frequency bands. Computed via `librosa.feature.spectral_contrast()`, averaged across the default 7 frequency bands to produce a single per-frame value.

**What it drives**: Secondary input to the section energy composite. Captures how prominent instruments are above the noise floor — a full band hitting hard produces high contrast, while a quiet ambient section has low contrast.

**Limitations**: Average range of 0.094 across songs (WEAK standalone). Useful as a 40% contributor to the energy composite, where it adds texture that pure loudness misses.

**Resolution**: Per-frame, normalized to 0-1, averaged per section.

### 3.3 Spectral Flux (Tier 2 — Character)

**What it measures**: How much the frequency spectrum changes between consecutive time frames. Computed via `librosa.onset.onset_strength()`.

**What it drives**: Rudiment envelope matching (Section 2.5). The flux *contour* over a section (32-point envelope) is compared against rudiment envelopes via cosine similarity. The flux *average* provides the target flux level for rudiment selection.

**Important**: Spectral flux is **not** used for energy calculation. Empirical testing showed it has an average range of only 0.028 across sections — too compressed to differentiate a quiet bridge from a loud chorus. It remains valuable for *pattern matching* (the shape of flux changes matters even when the magnitude doesn't vary much).

**Resolution**: Per-frame (typically 43Hz), averaged per section for target definition; 32-point contour for envelope matching.

### 3.4 Transient Sharpness (Tier 2 — Character)

**What it measures**: How percussive (fast attack) versus sustained (slow attack) the sound is. Measured via onset density (onsets per second, normalized).

**What it drives**: Rudiment type filtering via envelope categories (Section 2.5).
- High transient sharpness (percussive) → snappy rudiments: stroke, strobe, sparkle, chase
- Low transient sharpness (sustained) → flowing rudiments: wave, pulse, fade, swell

**Note**: Transient sharpness shows OK-to-GOOD differentiation (average range 0.291) and may be a candidate for inclusion in the energy composite in future iterations.

**Resolution**: Per-onset, averaged per section.

### 3.5 Vocal Presence Detection (Tier 2 — Character)

**What it measures**: Whether a lead vocalist is currently singing, using a two-stage detection pipeline:

1. **Harmonic-Percussive Source Separation (HPSS)**: `librosa.decompose.hpss()` decomposes the spectrogram into harmonic and percussive components. The harmonic component isolates tonal content (vocals, sustained instruments), removing drums and transients.

2. **MFCC Delta Variance**: MFCCs (Mel-Frequency Cepstral Coefficients) are computed on the harmonic component. The *delta* (first derivative) of MFCC coefficients captures how rapidly the spectral shape changes. The RMS of delta coefficients (excluding c0/energy) produces a per-frame vocal score. Vocals score high because phoneme transitions cause rapid spectral shape changes; sustained brass, strings, or organ score low because their spectral shape is stable.

**Why HPSS+MFCC over band-energy ratio**: The previous method (energy ratio in the 300Hz-3kHz band) was triggered equally by vocals, brass, guitar, and any mid-range-heavy instrument. The MFCC delta approach discriminates based on *spectral dynamics*, not frequency band occupancy.

**What it drives**: Spatial focus rules (Section 6) and key role weight modulation.
- Vocals present → boost key role fixtures (front-of-stage performer visibility)
- Vocals absent → key role dims (but doesn't turn off), wash/texture emphasized

**Resolution**: Continuous 0-1 score per frame, averaged per section.

### 3.6 Spectral Centroid (Tier 2 — Character)

**What it measures**: Frequency center of mass in Hz. Computed via `librosa.feature.spectral_centroid()`.

**What it drives**: Color mapping (Section 4). Higher centroid → brighter/warmer hues; lower centroid → darker/cooler hues.

**Resolution**: Per-frame in Hz, averaged per section.

### 3.7 Spectral Richness (Tier 2 — Legacy)

**What it measures**: Combination of spectral bandwidth and spectral flatness: `0.6 * normalized_bandwidth + 0.4 * spectral_flatness`.

**What it drives**: Gobo/prism activation thresholds only. When spectral richness exceeds `spectral_richness_gobo_threshold` (default 0.7) or `spectral_richness_prism_threshold` (default 0.8), gobos and prisms activate on capable fixtures.

**Important**: Spectral richness is **not** used for energy calculation or fixture group activation. Empirical testing showed it has an average range of 0.077 across sections (USELESS-WEAK). It is retained solely for gobo/prism threshold decisions, where the absolute level (not cross-section differentiation) matters.

**Resolution**: Per-frame, averaged per section.

### 3.8 Section Energy Profile

Each section receives a **relative energy** score (0.0-1.0) that drives fixture activation, intensity scaling, and movement amplitude. The composite formula:

```
relative_energy = 0.6 × percentile_rank(rms_energy) + 0.4 × spectral_contrast_avg
```

Where `percentile_rank(rms_energy)` is the section's rank among all sections' RMS values, normalized to 0-1. This percentile approach normalizes across songs with different mastering levels — a quietly mastered track and a loudly mastered track both produce a full 0-1 range.

**Empirical validation** (8 songs, 130+ sections):

| Metric | Avg Range | Verdict | Role in Energy |
|--------|-----------|---------|---------------|
| spectral_flux | 0.028 | USELESS | Not used (v2: was primary) |
| spectral_richness | 0.077 | WEAK | Not used (v2: was secondary) |
| rms_energy | 0.346 | GOOD | **Primary (60%)** |
| spectral_contrast | 0.094 | WEAK | **Secondary (40%)** |
| **energy composite** | **0.578** | **GOOD** | — |

The composite correctly ranks choruses above verses, verses above bridges, and quiet sections at the bottom across all tested songs. The previous formula (`0.6*percentile(flux) + 0.4*richness`) incorrectly scored "quiet" sections above choruses due to flux compression.

See `docs/metric_analysis_results.md` for detailed per-song data.

---

## 4. Color System

Color is determined independently from rudiments. The algorithm assigns a color palette per section based on audio mood analysis, then applies colors to blocks generated by rudiment selection.

### 4.1 Two-Axis Color Model

**Axis 1 — Pitch/Brightness**:
- Higher dominant frequencies → lighter, brighter hues
- Lower dominant frequencies → darker, warmer hues
- Measured via spectral centroid (the "center of mass" of the frequency spectrum)

**Axis 2 — Mood**:
Derived from a combination of:
- Key signature (major vs. minor) — provided by operator or detected
- Spectral centroid (bright vs. dark timbres)
- Tempo (fast vs. slow)

Mapping:
- Major key + bright spectral content + fast tempo → warm, saturated colors (reds, oranges, yellows, bright whites)
- Minor key + dark spectral content + slow tempo → cool, desaturated colors (blues, purples, deep greens, cold whites)

### 4.2 Palette Generation

For each section, the color system generates a palette of 2–4 colors that:
1. Fit the mood axis position
2. Are **complementary but not uniform** — different fixture groups can receive different colors from the palette
3. Avoid stark contrasts within a section (colors should feel cohesive)
4. Provide **contrast between sections** — verse and chorus palettes should be noticeably different

### 4.3 Color Application Rules

- Colors are applied to ColourBlocks that accompany the DimmerBlocks and MovementBlocks generated by rudiments.
- Different fixture groups may receive different colors from the section palette.
- Color transitions between sections follow the section transition type (sharp cut vs. gradual crossfade).
- Within a section, color changes are minimal — the palette holds steady for the groove, with possible intensification during fills.

---

## 5. The Algorithm

### Step 1: Song-Level Analysis

**Inputs**: Audio file + operator-provided metadata (BPM, time signature, bar count per section, section markers and types).

**Process**:
1. Parse manual inputs to establish timeline structure.
2. Run spectral analysis across the full song.
3. Detect vocal presence across the song to identify front-stage emphasis zones.
4. Calculate per-section averages for all audio parameters.

**Output**: A structured representation of the song with per-section audio profiles.

### Step 2: Section-Level Target Definition

For each section, extract target values:

| Target | Source | Used By |
|--------|--------|---------|
| Relative energy | RMS percentile rank + spectral contrast (Section 3.8) | Fixture role activation, intensity scaling, movement amplitude |
| Target flux range | Spectral flux average ± tolerance | Rudiment selection |
| Target flux envelope shape | Spectral flux contour over section | Rudiment matching |
| Transient character | Onset sharpness average | Rudiment type filtering |
| Spectral richness | Bandwidth + flatness | Gobo/prism activation only |
| Mood position | Key + centroid + tempo | Color palette |
| Vocal presence | HPSS + MFCC delta score | Key role weight, spatial rules |
| Color palette | Mood model output | ColourBlock generation |

### Step 3: Phrase Structure Definition

Each section is divided into phrases based on bar count:
- **Prepared mode**: Phrases align with the operator-defined bar structure. Default: 4-bar phrases (3 bars groove + 1 bar fill). The groove/fill split is configurable but defaults to 75%/25% (3:1 ratio in a 4-bar phrase).
- **Live mode**: No automatic phrase subdivision. The algorithm maintains a steady groove pattern and does not inject fills on its own. Fills are only triggered by explicit operator input (see Section 9.3). This keeps the output homogeneous and avoids jarring changes without operator intent.

**Live mode rolling window**: In live mode, the algorithm uses a rolling analysis window (configurable, default ~4 bars) centered around the current playback position. The window averages audio parameters over its span, smoothing out momentary spikes and preventing the lighting from reacting to every transient. When the rolling window detects a sustained shift in audio character (e.g., spectral flux rising steadily over several bars), it triggers a gradual rudiment transition rather than a hard switch.

### Step 4: Rudiment Assignment per Fixture Group

For each fixture group in each section:

1. **Filter by capability**: Only consider intensity rudiments for all groups, movement rudiments only for groups containing moving heads.
2. **Filter by transient character**: Percussive sections → prefer snappy rudiments (spike/square envelopes). Sustained → prefer flowing rudiments (sine/ramp envelopes). Use envelope shape categories for fast filtering.
3. **Generate candidates**: Select rudiments within a loose tolerance band around the target flux range. The tolerance band is intentionally wide to ensure a diverse candidate pool.
4. **Three-dimensional matching** (see Section 2.5): Score each candidate on:
   - **Envelope shape similarity**: Compare the rudiment's single-cycle (cycling) or full-duration (one-shot) envelope against the target flux character. Score via cosine similarity or DTW on normalized curves.
   - **Repetition rate fit** (cycling rudiments only): Does the cycle rate at the section's BPM and a reasonable speed multiplier match the rate of spectral flux change in the audio?
   - **Average flux level**: Does the envelope's average value, combined with the repetition rate, fall within the section's target flux range?

Multiple fixture groups can (and should) receive different rudiments to create visual depth. The constraint is that the *combined* output across all groups should approximate the section's target flux profile.

### Step 5: Groove and Fill Assignment

**Prepared mode**: For each phrase within a section:
- **Groove (bars 1–3)**: Assign the selected rudiment(s) as a repeating base pattern.
- **Fill (bar 4)**: Select a higher-flux rudiment or variation for the fill bar. Fills must have higher flux or transient sharpness than the groove they punctuate.

**Live mode**: The groove runs continuously for the entire section. No fills are inserted automatically. When the operator triggers a fill (via manual input), the algorithm selects a higher-flux rudiment for the next bar, then returns to the groove. When the rolling window detects a significant audio character change, the algorithm crossfades to a new groove selection over 1–2 bars.

### Step 6: Dual-Criteria Scoring

Score each candidate combination on two weighted criteria:

**A. Parameter Fidelity (~60%)**:
- Flux envelope shape similarity to target
- Spectral richness → active fixture group count match
- Transient character → rudiment type appropriateness
- Color palette coherence (complementary, mood-appropriate)

**B. Musical Coherence (~40%)**:
- Groove-to-fill flow: Does the fill provide a natural punctuation?
- **Cross-section contrast**: Different sections (verse vs. chorus) must have noticeably different rudiment selections, color palettes, and flux levels. Repeated identical selections across distinct section types are penalized.
- **Within-section consistency**: Within a section, the groove pattern should remain relatively stable. Variation comes from fills and subtle parameter shifts, not wholesale rudiment changes bar-to-bar.
- Fill flux > groove flux (mandatory constraint, not just scored)

### Step 7: Selection

Select the highest-scoring combination across all fixture groups for the section.

### Step 8: Iteration

If the result is unsatisfactory (score below threshold, or manual review by operator):
- Adjust tolerance bands (wider = more candidates, more variety)
- Adjust fidelity/coherence weight ratio
- Lock certain fixture groups and regenerate others
- Regenerate with a different random seed for stochastic elements

### Step 9: Transition Handling

Analyze the transition type between adjacent sections (set by operator or inferred):

| Transition Type | Lighting Behaviour |
|----------------|-------------------|
| **Sharp** (e.g., verse → chorus) | Hard cut. New section's rudiments start immediately. Optional: a transition fill in the last bar of the outgoing section that bridges both sections' characters. |
| **Gradual** (build-up, fade) | Blend rudiment parameters across the boundary. Ramp flux and density over 1–2 bars. |
| **Fade-out** | Progressive reduction in active fixture groups and intensity. Chase/wave directions converge inward. |
| **Blackout** | All fixtures to zero, then new section starts fresh. |

Transitions are applied as post-processing on the generated block sequence. Future development: a dedicated transition rudiment library for common section boundaries.

### Step 10: Spatial Application

Apply the selected rudiments to fixture groups using the lighting role model (Section 6):

1. **Role-based activation**: Each fixture group's lighting role (wash, key, texture, accent) determines its energy threshold for activation and its temporal behavior (FULL, GROOVE_ONLY, FILL_ONLY). See Section 6.3 for role definitions.
2. **Vocal rule**: Vocal presence modulates the key role weight — boosted when vocals are present, dimmed (not off) otherwise. Also affects front-zone groups via `apply_vocal_rule()`.
3. **Atmospheric rule**: When vocals are absent, shift intensity balance toward wash and texture groups.
4. **Gobo/prism activation**: When spectral richness exceeds the configured threshold, activate gobos and prisms on capable fixtures (generates SpecialBlocks).
5. **Movement attribute**: Groups with moving head capabilities receive a `MovementStrategy` based on section energy — shape selected from energy-tiered pools, amplitude scales with relative energy.

### Step 11: Block Generation

Convert the rudiment selections into concrete sublane blocks:

1. Each intensity rudiment → one or more **DimmerBlocks** with appropriate effect type, speed, and intensity parameters.
2. Each movement rudiment → one or more **MovementBlocks** with shape, speed, amplitude, and center position.
3. Color palette → **ColourBlocks** spanning the section, with per-group color assignments.
4. Gobo/prism decisions → **SpecialBlocks** when applicable.

Blocks are placed on the timeline in the existing LightLane/LightBlock structure, targeting the appropriate fixture groups. The user can then review, edit, or regenerate any part of the show.

---

## 6. Spatial Lighting Model

The system maintains a 3D stage model derived from the show creator's fixture configuration, combined with user-assigned **lighting roles** that define each fixture group's purpose.

### 6.1 Data Available

Each fixture has:
- 3D position (x, y, z) in meters, origin at center stage floor
- Orientation (mounting, yaw, pitch, roll)
- Fixture group membership
- Fixture type and capabilities (from QXF definition)
- Beam direction vector (calculated from orientation)

Each fixture group additionally has:
- **`lighting_role`** (user-assigned): one of `wash`, `key`, `texture`, `accent`, or empty for fallback behavior
- Automatic zone classification (front/mid/back/overhead) as fallback when no role is assigned

### 6.2 Design Principles

The role system follows professional lighting design practice (McCandless method, ETC training series, modern concert LD layering):

1. **Roles describe purpose, not behavior.** A role says what the fixture group IS (wash, key, accent), not how it behaves at any given moment. Behavioral variation comes from the algorithm's rudiment and movement assignment per section.

2. **Rhythm and movement are attributes, not roles.** Professional practice treats beat-synced patterns and pan/tilt movement as attributes that can be applied to ANY layer. A wash fixture doing a chase pattern is still a wash — it's a wash with rhythmic behavior. The groove/fill rudiment system handles this: a "stroke" rudiment on a wash = rhythmic wash, a "static" rudiment on the same wash = mood wash. Similarly, `MovementStrategy` is applied to any group with pan/tilt capability regardless of role.

3. **4 roles for 4-8 fixture groups.** The professional 3-4 layer model (base → key → accent → effect) maps well to small-venue setups without requiring 1:1 role-to-group mapping.

### 6.3 Lighting Roles

| Role | Description | Activation Threshold | Weight Range | Temporal Behavior |
|------|-------------|---------------------|-------------|-------------------|
| **wash** | Base illumination, broad coverage, sets color palette and mood. The visual foundation. | energy >= 0.00 (always) | 0.50 – 1.00 | FULL: plays both groove and fill blocks |
| **key** | Front-of-stage performer visibility. Vocal-aware — boosted when vocals present, dimmed otherwise. Stable patterns. | energy >= 0.00 (always) | 0.30 – 0.80 | GROOVE_ONLY: steady presence, no fill variation |
| **texture** | Gobos, prism, breakup patterns, beam effects. Adds visual complexity at medium+ energy. | energy >= 0.40 | 0.50 – 1.00 | Envelope-based: follows rudiment character |
| **accent** | Sparse, high-impact moments — strobes, blinders, bumps. Punches in at peaks only. | energy >= 0.60 | 0.70 – 1.00 | FILL_ONLY: only fires during fill blocks |

**Activation diagram:**

```
Energy:  0.0 ──────────── 0.40 ──── 0.60 ──── 1.0
         │                  │          │
         wash + key         texture    accent
         (always on)        (medium+)  (peaks only)
```

**Weight interpolation:** Within its active range, each role's weight ramps from base minimum to 1.0:

```
weight = base_weight + t × (1.0 - base_weight)
where t = (energy - threshold) / (1.0 - threshold)
```

### 6.4 Algorithmic Attributes

These are NOT user-assigned. The algorithm applies them per-section based on audio character and fixture capabilities:

| Attribute | What it does | Applied to | Driven by |
|-----------|-------------|-----------|-----------|
| **Rhythm** | Beat-synced intensity patterns (stroke, chase, ping-pong, sparkle) | Any role | Groove/fill rudiment assignment based on audio character |
| **Movement** | Pan/tilt sweeps, lissajous figures, position changes | Any group with moving heads | `MovementStrategy` based on section energy and spot targets |

A wash fixture in a high-energy chorus might receive: `wash role + stroke rudiment (rhythm) + circle movement`. The same fixture in a quiet verse: `wash role + static rudiment + linear_sweep movement`. The role stays constant; the attributes change per section.

### 6.5 Typical Fixture-to-Role Mappings

These are examples, not defaults. Roles are user-assigned per setup:

| Fixture Type | Typical Role | Rationale |
|-------------|-------------|-----------|
| LED bars, pixel strips | wash | Broad coverage, color foundation |
| Wash lights (floor/truss) | wash | Stage fill, color base |
| Front pars, face lights | key | Performer visibility |
| Moving heads (with gobos) | texture | Gobos, prism, beam effects |
| Sunstrips, blinders | accent | High-impact, sparse deployment |
| Strobes | accent | Peak moments only |

### 6.6 Zone Classification (Fallback)

When no `lighting_role` is assigned, the system falls back to automatic zone-based classification using fixture positions:

- **Front-stage**: Average Y position < stage_depth × 0.33
- **Mid-stage**: Average Y position between 0.33 and 0.66 × stage_depth
- **Back-stage**: Average Y position > stage_depth × 0.66
- **Overhead**: Average Z position > stage_height × 0.5

Zone classification uses a tiered activation model (front first, back last) that is less accurate than role-based activation but provides backward compatibility.

### 6.7 Spatial Modifiers

These rules modulate role-based activation:

| Rule | Condition | Action |
|------|-----------|--------|
| **Vocal focus** | Vocal presence detected | Boost key role weight; increase front-zone group intensity |
| **Atmospheric** | No vocal presence | Dim key role (not off); shift emphasis to wash/texture |
| **Gobo/prism threshold** | Spectral richness > threshold | Activate gobos/prisms on capable fixtures (SpecialBlocks) |
| **Movement scaling** | Section energy | Higher energy → wider movement amplitudes, faster speeds; shapes selected from energy-tiered pools |

---

## 7. Structural Analogy: Drum Theory → Light Theory

| Drum Concept | Lighting Equivalent |
|-------------|-------------------|
| Rudiment (paradiddle, flam, drag) | Light rudiment (stroke, chase, wave, ping pong) |
| Groove (repeating beat pattern) | Repeating base light pattern for a section (groove blocks) |
| Fill (transitional pattern at phrase end) | Higher-flux transitional pattern at phrase boundary (fill blocks) |
| 3 bars groove + 1 bar fill | Base rudiment blocks + fill rudiment in last bar of phrase |
| Section change fill (into chorus) | Transition handling at verse/chorus boundary |
| Which drum you play on | Color palette and fixture group assignment |
| Dynamics (ghost notes, accents) | Intensity variation within rudiment parameters |
| Orchestration (kick vs. snare vs. hi-hat) | Different rudiments on different fixture groups simultaneously |

---

## 8. Configuration & Tunables

These parameters should be exposed to the operator for tuning:

| Parameter | Default | Description |
|-----------|---------|------------|
| `groove_fill_ratio` | 0.75 (3:1) | Proportion of phrase spent on groove vs. fill (prepared mode only) |
| `phrase_length_bars` | 4 | Default phrase length in bars (prepared mode only) |
| `fidelity_weight` | 0.6 | Weight of parameter fidelity in scoring |
| `coherence_weight` | 0.4 | Weight of musical coherence in scoring |
| `tolerance_band_width` | 0.2 | How wide the candidate flux tolerance is (±fraction of target) |
| `spectral_richness_gobo_threshold` | 0.7 | Normalized richness level above which gobos activate |
| `spectral_richness_prism_threshold` | 0.8 | Normalized richness level above which prisms activate |
| `vocal_detection_debounce_ms` | 500 | Minimum vocal segment duration before triggering spatial shift |
| `cross_section_contrast_min` | 0.3 | Minimum required difference between section rudiment selections |
| `color_complementary_range` | 30–120° | Hue angle range for palette complementary colors |
| `live_rolling_window_bars` | 4 | Rolling analysis window size in bars (live mode only) |
| `live_transition_bars` | 2 | Number of bars over which to crossfade between grooves when audio character shifts (live mode only) |
| `live_fill_duration_bars` | 1 | How long a manually triggered fill lasts before returning to groove (live mode only) |
| `wash_min_energy` | 0.00 | Minimum energy for wash role activation |
| `key_min_energy` | 0.00 | Minimum energy for key role activation |
| `texture_min_energy` | 0.40 | Minimum energy for texture role activation |
| `accent_min_energy` | 0.60 | Minimum energy for accent role activation |

---

## 9. Open Questions & Future Development

### 9.0 Completed (v3.0)

- **~~Fixture group role presets~~** → Implemented as lighting roles: wash, key, texture, accent (Section 6.3). User-assignable via `lighting_role` field on FixtureGroup.
- **~~Investigation/debugging system~~** → Implemented as Generation Inspector (live dashboard with mel spectrogram, toggleable feature plots, 3D flux/transient plot, activation heatmap, rudiment score breakdown) and CLI test harness (`tests/autogen_harness.py`).
- **~~Metric validation~~** → Completed across 8 songs. Spectral flux and richness demoted; RMS energy and spectral contrast adopted. Results in `docs/metric_analysis_results.md`.
- **~~Vocal detection improvement~~** → Replaced band-energy ratio with HPSS + MFCC delta variance method.

### 9.1 Near-Term

- **Energy composite refinement**: Spectral contrast is WEAK (avg range 0.094). Transient sharpness (avg range 0.291, OK-GOOD) is a candidate for inclusion. Test formula: `0.5*rms_rank + 0.25*contrast + 0.25*transient`.
- **Key role vocal tracking**: Key is currently "always on at low weight." Should modulate more dynamically with vocal presence — boosted during singing, dimmed to minimum during instrumental passages. Integrate with HPSS+MFCC vocal detection.
- **Click track robustness**: All tested audio files contain metronome/click tracks which depress onset-based metrics. Consider HPSS percussive separation to isolate musical transients from click before computing flux and transient sharpness.
- **Musical coherence formalization**: Continued testing needed. Starting rules: fills > grooves flux; adjacent sections differ by `cross_section_contrast_min`; within-section grooves >80% consistent.
- **Weighting calibration**: 60/40 fidelity/coherence split may need per-genre tuning.
- **Color model refinement**: Two-axis model needs quantitative spectral centroid → hue mapping (HSL).
- **Tolerance band sizing**: Empirical testing needed (narrow = boring; wide = incoherent).

### 9.2 Medium-Term

- **Transition rudiment library**: Dedicated transition patterns for common section boundaries (verse→chorus, chorus→bridge, etc.).
- **Genre presets**: Pre-tuned parameter sets for common genres (rock, EDM, ballad, jazz, ambient).
- **Role energy threshold tuning UI**: Currently `_ROLE_ENERGY_CONFIG` thresholds are hardcoded in `autogen/spatial.py`. Expose via AutogenConfig for per-show tuning.
- **Rhythm attribute formalization**: Currently rhythm is an emergent property of rudiment assignment. Could be more explicit — e.g., a per-section "rhythmic intensity" score that biases rudiment selection toward beat-synced patterns (stroke, chase) vs. static ones.
- **Effect speed capping**: At high BPMs (190+), effect speeds reach 4x which is too fast. Need BPM-aware speed ceiling.

### 9.3 Long-Term

- **Live auto-show mode**: Real-time audio analysis with on-the-fly rudiment selection. Requires low-latency spectral analysis and simplified scoring. Key design elements:
  - **Rolling analysis window** (default ~4 bars): Smooths parameters, prevents chasing every transient.
  - **Operator override controls**:
    - **"Fill now"**: One-bar fill at next bar boundary, then return to groove.
    - **"Vocals active" (toggle)**: Manual vocal presence override.
    - **"Energy up/down"**: Bias energy target by configurable offset.
    - **"Blackout"**: Immediate all-off.
    - **"Next section"**: Force section-change transition.
  - Overrides take priority; algorithm resumes after override expires.
- **Machine learning refinement**: Train scoring weights on operator-approved shows.
- **Audience energy feedback**: Crowd noise/motion sensors for dynamic energy adjustment.

---

## Appendix A: Rudiment Flux Envelope Reference

Normalized envelope shapes for each intensity rudiment. Envelopes are normalized to 0.0–1.0 on both axes, sampled at 32 points per cycle.

**Cycling rudiments** — envelope describes one cycle; the cycle repeats at `BPM × speed_multiplier` rate:

| Rudiment | Shape Description | Single Cycle Profile |
|----------|------------------|---------------------|
| Ping Pong | Square wave oscillation | `█▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁` → `▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁█` |
| Chase | Rolling sawtooth (aggregate) | `▂▃▄▅▆▇█▇▅▃▂▁▁▁▁▁` |
| Wave | Sine with decay tail | `▁▂▅█▆▃▁▁▁▁▁▁▁▁▁▁` |
| Waterfall | Multi-peak with steep decay | `█▅▂▁▁█▅▂▁▁█▅▂▁▁▁` |
| Random Stroke | Irregular spikes | `▁▃▁▁█▁▂▁▁▅▁▁▃▁█▁` |
| Sparkle | Stochastic short pulses | `▂▁▃▁▁▂▁▃▁▂▁▁▃▁▂▁` |
| Pulse | Sine oscillation | `▁▃▅█▅▃▁▁▁▁▁▁▁▁▁▁` |
| Strobe | High-frequency square wave | `████████▁▁▁▁▁▁▁▁` |

**One-shot rudiments** — envelope describes the full block duration; plays once and does not repeat:

| Rudiment | Shape Description | Full Duration Profile |
|----------|------------------|--------------------|
| Static | Flat line at target intensity | `████████████████` |
| Stroke | Sharp spike, fast decay | `▁▁▁▁▁▁▁█▅▂▁▁▁▁▁▁` |
| Fill | Progressive ramp up | `▁▁▂▂▃▃▄▄▅▅▆▆▇▇██` |
| Fade In | Smooth ramp up | `▁▁▂▂▃▃▄▅▅▆▆▇▇███` |
| Fade Out | Smooth ramp down | `███▇▇▆▆▅▅▄▃▃▂▂▁▁` |
| Cascade | Build up → sharp release | `▁▂▃▄▅▆▇██▇▅▃▁▁▁▁` |

These are reference shapes. Actual envelope curves are parameterized (speed, intensity, decay rate) and computed at runtime. For cycling rudiments, the block's aggregate flux is the envelope shape repeated at the cycle rate — the shape determines *character*, the rate determines *frequency*.

---

## Appendix B: Mapping to Existing Show Creator Architecture

| Theory Concept | Show Creator Implementation |
|---------------|---------------------------|
| Intensity rudiment | `effects/dimmer_effects.py` → DIMMER_REGISTRY → DimmerBlock |
| Movement rudiment | `effects/movement_effects.py` → MOVEMENT_REGISTRY → MovementBlock |
| Rudiment definition | `rudiments/rudiment.py` → Rudiment, FluxEnvelope |
| Rudiment registry | `rudiments/registry.py` → 15 intensity + 11 movement rudiments |
| Rudiment → Block | `rudiments/block_converter.py` → rudiment_to_dimmer_block/movement_block |
| Block | Sublane blocks: DimmerBlock, ColourBlock, MovementBlock, SpecialBlock |
| Riff | `riffs/riff_library.py` — beat-based reusable block compositions |
| Fixture group | `config/models.py` → FixtureGroup, resolved via `utils/target_resolver.py` |
| Fixture capabilities | `FixtureGroupCapabilities` class in sublane system |
| Timeline placement | LightLane → LightBlock → sublane blocks |
| Section structure | `timeline/song_structure.py` → ShowPart |
| BPM-aware timing | `SongStructure.get_bpm_at_time()` |
| ArtNet output | `utils/artnet/dmx_manager.py` → real-time effect computation via DIMMER_REGISTRY |
| QLC+ export | `utils/to_xml/shows_to_xml.py` → sequence generation |
| Spatial model | Fixture positions + orientation from `config/models.py` |
| Color wheel | QXF parsing in `utils/tcp/protocol.py`, DMX handling in `dmx_manager.py` |
| Gobo/prism | SpecialBlock with gobo_index, prism fields |
| **Lighting roles** | `autogen/spatial.py` → `GroupClassification.lighting_role` (string from the config) |
| **Role-based activation** | `autogen/spatial.py` → `compute_richness_weights()`, `_ROLE_ENERGY_CONFIG` |
| **Role-based temporal behavior** | `autogen/spatial.py` → `assign_group_roles()` with `group_classifications` parameter |
| **RMS energy** | `audio/spectral_analysis.py` → `SectionAnalysis.rms_energy`, `librosa.feature.rms()` |
| **Spectral contrast** | `audio/spectral_analysis.py` → `SectionAnalysis.spectral_contrast_avg`, `librosa.feature.spectral_contrast()` |
| **Vocal detection (HPSS+MFCC)** | `audio/spectral_analysis.py` → `librosa.decompose.hpss()` + `librosa.feature.mfcc()` delta RMS |
| **Energy composite** | `autogen/generator.py` → `0.6*percentile_rank(rms) + 0.4*spectral_contrast` (line ~150) |
| **Generation Inspector** | `gui/dialogs/generation_inspector.py` → live dashboard with spectrogram, features, activation grid |
| **CLI test harness** | `tests/autogen_harness.py` → standalone pipeline runner with metric diagnostics |
| **Metric analysis results** | `docs/metric_analysis_results.md` → empirical validation across 8 songs |

---

*Framework developed March 2026. Updated April 2026 with empirical metric validation and lighting role system.*
