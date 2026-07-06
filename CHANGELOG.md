# Changelog

All notable changes to QLC+ Show Creator are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While working, add entries under **[Unreleased]**. At release time that heading
becomes the new version section - and the release workflow uses that section
verbatim as the GitHub Release notes (see [docs/releasing.md](docs/releasing.md)).

## [Unreleased]

### Added

- **GDTF fixture import (first pass).** `.gdtf` files (General Device Type
  Format, DIN SPEC 15800) are now a first-class fixture-definition source:
  drop them into `gdtf_fixtures/` and they appear in the Add Fixture
  browser (tagged `[GDTF]`), patch, export to `.qxw`, drive live ArtNet
  output, and render in the visualizer with their real photometric data
  (beam angle, pan/tilt ranges, luminous flux from the GDTF geometry tree
  instead of a wattage guess). When a fixture exists as both GDTF and
  `.qxf`, the GDTF definition wins. Implementation: `utils/gdtf_loader.py`
  transpiles the GDTF attribute system, channel functions, wheel slots
  (CIE xyY slot colors to sRGB), multi-byte channels, and geometry-
  reference cells onto the QLC channel-preset model via `pygdtf`, so every
  downstream consumer is format-agnostic. The GDTF-native data that
  exceeds what the channel model can express is extracted structurally
  onto the definition (`utils/gdtf_data.py`): the geometry tree with
  parent-relative transforms and pan/tilt axis joints, 3D model
  references with dimensions and in-archive file paths, beam
  photometrics, and full-resolution physical values - ready for mesh
  rendering (Phase 3) and stage-relative movement (v1.5a). Not yet in:
  3D model rendering itself (planned, `docs/gdtf-integration-plan.md`
  Phase 3), GDTF Share integration, and the demo-rig coverage comparison
  (needs Share downloads, which require a user account).
- **GDTF 3D models render in the visualizer.** Fixtures whose
  definition comes from a `.gdtf` now draw their embedded GLB meshes
  instead of the procedural chassis: the GDTF geometry tree becomes a
  kinematic chain (pan/tilt rotate whole subtrees at the Axis nodes),
  the beam cone emits from the Beam node, and nodes without a usable
  GLB (3DS-only or placeholder files are common in the wild) fall back
  to primitive boxes per node. GL buffers, textures, and the shader
  are shared across all instances of a fixture type, and chassis
  dimensions come from the whole geometry tree instead of the base
  plate. Any failure falls back to the procedural chassis;
  `QLC_GDTF_MESHES=0` disables the mesh path entirely.
- **Mode reconciliation on config load.** When the fixture library
  resolves a different definition than the config was authored against
  (typically a GDTF now shadowing a same-identity `.qxf`, whose mode
  names differ), fixtures no longer fall back to empty channel maps:
  the closest-footprint mode is adopted with a printed warning and the
  definition provenance is restamped.
- **GDTF persistence and QLC+ interop.** Fixtures remember where their
  definition came from (`definition_source` + the GDTF GUID in config
  YAML and the JSON rig format; old configs load unchanged). On `.qxw`
  export, GDTF fixtures QLC+ already knows pass through untouched, and
  unknown ones get a companion `.qxf` generated next to the workspace
  (`gdtf_companion_fixtures/`) to drop into QLC+'s fixture folder, so a
  GDTF-built rig still opens correctly in QLC+.
- **Fixture browser upgrade.** The Add Fixture dialog grew a details pane
  (fixture type + every mode with its channel count, parsed lazily from the
  selected `.qxf`), a `[bundled]` tag on the definitions that ship with the
  app, double-click-to-add, and a quantity field — add 8 PARs in one go,
  auto-patched at consecutive free addresses with unique names.
- **New from Template.** `File -> New from Template` (Ctrl+N) starts a
  project from one of the five bundled starter rigs (club band 9 fixtures up
  to festival mainstage 60), optionally with the ready-to-play demo show and
  audio clip. The template is copied to a location you choose and the copy
  opens — saving can never overwrite a bundled template. The starter rigs
  and demo shows now ship inside the packaged builds (they were previously
  repo-only, so release users had no templates at all).
- **Cross-config show import.** `File -> Import Shows from Config` pulls
  selected shows from another config.yaml into the current one without
  swapping the project ("get last year's set into this venue's config").
  The picker shows part counts, name conflicts (resolve by rename /
  overwrite / skip), and any fixture groups the current config lacks —
  those are reported, not silently fixed; lanes targeting them stay dormant
  until re-pointed. Audio files are copied into this config's
  `audiofiles/` bundle.
- **Stage plot export.** The Stage tab's "Plot Stage" button (non-functional
  since v0.9.5) now exports the rig as a printable stage plot: vector PDF or
  PNG, A4/A3/A2 landscape. Includes a title block (config name, stage
  dimensions, scale, fixture count, date), the stage with grid and meter
  labels, an AUDIENCE edge marker, every fixture as its chassis symbol in
  group color with an orientation tick and a name + universe.address label
  (greedy collision avoidance keeps labels readable on dense rigs), stage
  marks, and a legend listing groups, stage layers, and a scale bar.
- **Stage plane visualization.** The Stage tab gets a plane picker for the 6
  faces of the stage bounding cuboid (Floor / Ceiling / Front / Back / Left /
  Right). Hovering an entry previews the face as a translucent highlight in
  the embedded 3D view; clicking keeps it highlighted, clicking again clears.
  The cuboid's ceiling follows the tallest fixture (min 3 m), matching the
  planes Auto Mode targets. Display-only for now: plane *targeting* from
  movement blocks lands with the v1.5a focus-geometry work.
- **Stage layers (vertical stacking).** The Stage tab gets named Z-planes
  (ground stack, mid-truss, top-truss, ...) with a per-layer visibility
  toggle. Assign fixtures via right-click on the stage; assignment snaps the
  fixture to the layer's height, and editing a layer's height moves
  everything on it. Hidden layers disappear from the 2D plot and every 3D
  preview (embedded and standalone) but still patch, output DMX, and export.
  Layers round-trip through the config YAML and the fixture-list CSV/JSON.
- **Active-layer editing.** Double-click a stage layer (or press L to cycle)
  to edit only that layer: its fixtures stay fully interactive while every
  other fixture ghosts to a faint, locked reference — visible enough to
  place against, impossible to select or drag by accident. Activating a
  hidden layer shows it; hiding or removing the active layer ends the
  editing session.
- **Fixture list import/export.** `File -> Import / Export Fixture List`
  round-trips the rig (patch, grouping, position, orientation) without the
  rest of the project, as `.csv` (flat spec sheet, effective values; a
  hand-written sheet with just manufacturer/model/universe/address imports
  fine) or `.json` (full fidelity: deduplicated fixture definitions, group
  metadata, mode lists). Imports resolve modes against the QLC+ fixture
  library where a `.qxf` is found, and offer Replace / Add when the config
  already has fixtures.
- **DMX address conflict checker.** The Fixtures tab now flags fixtures whose
  channel footprints overlap on the same universe, and fixtures that run past
  DMX address 512: the Universe/Address cells turn red with a tooltip naming
  the clashing fixture and the overlapping channel range, and an issue count
  appears next to the table header. Re-lints live as addresses, universes, or
  modes change.

### Changed

- **Fixture-definition layer unified** (Phase 0 of the GDTF integration
  plan, `docs/gdtf-integration-plan.md`). QXF discovery, parsing, and
  caching now live in one place, `utils/fixture_library.py`, producing a
  canonical `FixtureDefinition`; the five previously independent parsers
  (export/DMX loader, workspace-import scanner, renderer capability
  detection, visualizer payload parse, fixture-browser summary) and the
  five duplicated QLC+ directory-search implementations all delegate to
  it. Search paths are the union of the old variants (some scanners
  missed the `C:\QLC+5` directory or used different casing on Linux) and
  duplicate fixture identities now resolve consistently: first match in
  priority order, bundled `custom_fixtures/` first. Byte-identical `.qxw`
  export for all five demo rigs verified before vs after
  (`scripts/export_hash_check.py`); no behaviour change intended. New onset front end: a
  dedicated undecimated 86 Hz beat-flux path (multi-band log flux, per
  band saturated against its recent peak and reduced to its rising edge,
  hats down-weighted) so a kick/snare backbeat reads at the beat rate
  and subdivision doesn't read as double time. New estimator: harmonic
  comb scoring on a fractional 0.25 BPM grid, a temporal belief filter,
  an octave-raise walk with hysteresis, and a 3-analysis median. Also
  new: beat *phase* - `AutoBPMDetector.get_next_beat()` predicts the
  next beat to 0-12 ms mean error on click benchmarks (not yet consumed
  by the UI). Measured ladder in `docs/beat-tracking.md`: the real-album
  benchmark went from 5% of time correct (pre-fix wiring) to **65%,
  ahead of both QLC+ beat trackers** (63% / 4%), with a perfect 64/64 on
  the synthetic audio suite and 139/140 on the flux-level sweep.

### Fixed

- Auto tab: the "Auto" BPM detection was wrong twice over - the detector
  assumed feature frames arrive at 86 Hz while the analyzer delivers
  ~43 Hz (every estimate came out doubled), and it read the smoothed
  display flux, which degenerates to a bogus 240 BPM on real music. The
  analyzer now exposes the raw onset flux (`LiveFeatureFrame.flux_raw`)
  and its true `frame_rate_hz`, and the detector consumes both. On a real
  track the estimate now matches librosa's reference exactly.
- Stage tab: the layer panel's +/- buttons rendered their glyph as a
  cut-off sliver (32px fixed width vs the theme's 14px button padding);
  they now use the shared 40px toolbar-button width.

### Testing

- **Visual regression harness.** A glyph-clipping sweep grabs every
  fixed-width icon button (both themes) and fails when the rendered ink is
  clipped by the widget bounds or the QSS-padding content rect — the exact
  class of the layer-button bug. Golden-screenshot tests compare
  deterministic renders (stage plot, Fixtures table with conflict cells,
  Stage Layers panel) against per-platform reference images with pixel
  tolerance; regenerate intended changes with `QLC_REGEN_GOLDENS=1`.
  `tests/README.md` rewritten to match reality.
- **Beat tracker test suite + evaluator.** The Auto Mode BPM detectors (tap
  tempo and the autocorrelation auto-detector) got 22 deterministic unit
  tests (fake clock, synthetic click trains) and a benchmark script
  (`scripts/evaluate_bpm_detector.py`) that sweeps 7 scenario types
  (noise, subdivision, swing, drift, dropout, tempo step) across 50-240
  BPM with ground truth, classifies octave errors, and measures estimate
  error, time-to-lock, confidence, and throughput. It can also run any
  audio file through the live onset-flux path against a librosa
  reference (`--audio song.ogg --bpm 128`).
- **BPM comparison vs QLC+ upstream.** `scripts/compare_bpm_qlcplus.py`
  benchmarks our detector head-to-head against faithful Python ports of
  both QLC+ beat trackers (the ACF tempo-induction `BeatTracking` and the
  onset-reactive `BeatTracker`) on synthesized percussion audio and real
  tracks; results and analysis in `docs/bpm-comparison-qlcplus.md`. Our
  core wins (92% vs 75%/84%), and the run exposed two Auto tab wiring
  defects (frame-rate assumption 2x off; detector fed the smoothed
  display flux instead of raw flux) that make in-app estimates unreliable
  on real music - fix planned, tracked in the v1.1 roadmap item.

### Removed

- The root-level `merge_configs.py` script. It merged raw YAML and predated
  the v1.0 compact serializer: shows copied between files kept references
  into the wrong file's `block_defs` template table, silently corrupting
  the merged config. `File -> Import Shows from Config` replaces it and
  goes through the object model instead.

## [1.0.0] - 2026-07-02

The first community-facing release: a ground-up fixture-rendering rewrite, live
and prepared audio-reactive show generation, a modernized UI with an embedded 3D
visualizer, and the show-I/O, QLC+ export, and release plumbing that makes it
shippable.

### Added

- **Capabilities-based 3D renderer.** The visualizer detects each fixture's real
  capabilities (pan/tilt, gobo wheel, prism, focus, cell layout, multi-head)
  straight from its `.qxf` and composes the visual from independent parts
  (chassis + emitter + components), instead of the old six-type hard-coded
  geometry. Adds support for moving wash without gobo (e.g. Martin MAC Aura),
  moving-cell bar (e.g. Ayrton MagicBlade-R), and pixel matrix (e.g. Stairville
  5x5). HDR two-pass rendering keeps fixtures visible under bright beams.
- **Auto Mode (experimental).** A live audio-reactive tab that drives lighting in
  real time with no pre-built show - spectral features (energy, contrast, vocal
  presence, transient, centroid) pick rudiments per fixture group; per-group
  AUTO / CURATED / LOCKED control, FILL NOW, colour override, and BPM tap.
- **Automatic show generation.** Point it at an audio file + song structure and
  it produces an editable timeline: a library of 15 intensity + 11 movement
  rudiments, a matcher that scores them per section, lighting roles
  (wash / key / texture / accent), a colour-palette generator, and a Generation
  Inspector that explains every decision.
- **Modernized UI.** Embedded 3D visualizer in the Stage and Shows tabs,
  selectable light/dark themes (persisted), a single shared timeline grid, a
  docked riff library, zoom/pan 2D stage plot, and finer grid subdivisions.
- **Explicit show import/export.** `File -> Import / Export Show Structure`
  round-trips `.csv` (structure only) and `.yaml` (full show).
- **QLC+ target-version stamp.** Workspace Options dialog picks the exported
  `<Creator><Version>` (4.14.4 or 5.2.1).
- **CI / release pipeline.** `.github/workflows/release.yml` builds Windows +
  Linux via PyInstaller on tag push and drafts a GitHub Release with the
  archives attached.
- **Bundled demos.** Five reproducible demo rigs (`demos/rigs/`) and an
  autogenerated demo show per rig (`demos/shows/`), plus a headless media
  renderer (`demos/generate_media.py`) for the README stills/GIFs and a
  legacy->timeline show converter (`utils/legacy_show_converter.py`).

### Changed

- **Config YAML is the single source of truth.** Loading a config no longer
  auto-creates a `shows/` directory or keeps parallel `shows/*.csv` structure
  files; audio bundles to `<config_dir>/audiofiles/`.
- **Smaller QLC+ exports.** The exporter skips zero-valued `(fixture, channel,
  value)` triples (~44% of a representative export), matching QLC+'s own saver
  convention; output stays semantically identical.
- **Retuned audio metrics.** RMS energy drives intensity (was spectral flux),
  spectral contrast is the secondary signal, and vocal detection uses HPSS +
  MFCC delta - validated against hand-made shows (`docs/metric_analysis_results.md`).
- **Calmer default movement.** Movement runs one shape cycle per 4 bars at speed
  1 (4x slower than before), consistently in both preview and QLC+ export.
- Live audio-reactive engine renamed `live -> auto` across the codebase.

### Fixed

- Virtual Console export: group-control frames no longer overlap the Master
  frame / SpeedDial.
- Shows tab: the emptied lane-widget shell is hidden so it no longer lingers as
  a stray panel over the timeline.
- Visualizer: chassis stays visible under beams (real `glDepthMask` write);
  `RenderEngine` state is buffered before `initializeGL`.
- Autogen zone classification handles centred-Y stage coordinates.
- Stage dimensions reload correctly; submasters panel scrolls; the master
  timeline scrollbar no longer double-renders.

### Removed

- The legacy six-type hard-coded renderer, replaced by the composable one.
- The parallel `shows/*.csv` filesystem that shadowed the config YAML.

### Verified

- The exported `.qxw` was smoke-tested against the real QLC+ **4.14.4** and
  **5.2.1** binaries: it loads cleanly, all fixtures patch to the right
  universe/addresses, functions populate (Chaser / EFX / Scene / Sequence /
  Show), and the Virtual Console renders with no overlapping widgets.

## [0.9.5-beta] - 2025

Polish pass over the v0.9.0 beta.

### Changed

- ArtNet universe numbering is now 0-based (first universe is ArtNet `0`), to
  match the wire protocol.
- Visualizer camera moved closer; the Help window surfaces the ArtNet listen
  address; export log surfaces state during workspace export.

### Added

- `noHead` render path for fixtures without yokes.
- MIDI device + port assignment so show buttons auto-assign.

### Fixed

- Shows tab auto-updates after structure changes.

## [0.9.0-beta] - 2025

The first beta (~137 commits since the alpha).

### Added

- Show-creator core: Configuration, Fixtures, Stage, Structure, Shows tabs.
- Timeline editor with four sublane types (Dimmer / Colour / Movement / Special)
  and per-lane multi-target support.
- Riff system: reusable beat-based effect patterns with drag-and-drop.
- Effect plug-ins (15 intensity + 11 movement) in the `effects/` module.
- 3D visualizer (separate window) - TCP for scene config, ArtNet for live DMX.
- Fixture orientation (yaw / pitch / roll + mounting) with a 3D preview dialog.
- ArtNet output at 44 Hz with BPM-aware movement shapes.
- QLC+ workspace export (`.qxw`), automatic spot/virtual-console/master-preset
  generation, undo/redo, and copy/paste of effect blocks.
- Compact YAML serialization with two-level template deduplication.

## [0.1.0-alpha] - 2024

Initial public alpha - proof-of-concept timeline + export pipeline.

[Unreleased]: https://github.com/varghele/QLCplusShowCreator/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/varghele/QLCplusShowCreator/releases/tag/v1.0.0
[0.9.5-beta]: https://github.com/varghele/QLCplusShowCreator/releases/tag/v0.9.5-beta
[0.9.0-beta]: https://github.com/varghele/QLCplusShowCreator/releases/tag/v0.9.0-beta
[0.1.0-alpha]: https://github.com/varghele/QLCplusShowCreator/releases/tag/v0.1.0-alpha
