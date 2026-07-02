# Changelog

All notable changes to QLC+ Show Creator.

Versions are tagged in git as `v0.1.0-alpha`, `v0.9.0-beta`, `v0.9.5-beta`, and `v1.0.0`.

---

## [v1.0.0] - 2026-07-02

The first community-facing release. Focus has been on a ground-up fixture rendering rewrite, an experimental live-audio Auto Mode, automatic show generation from audio, and a UI modernization that folds the standalone visualizer into the main window - plus the show-I/O, QLC+ export, and release-pipeline work that makes it shippable.

### Fixture rewrite (capabilities-based renderer)

A multi-phase rebuild of how the visualizer interprets `.qxf` definitions. The old code mapped every fixture into a six-string enum (`PAR`, `BAR`, `WASH`, `MH`, `PIXELBAR`, `SUNSTRIP`) with hard-coded geometry. The new renderer detects capabilities (pan/tilt, gobo wheel, prism, focus, cell layout, multi-head) directly from the QLC+ definition and composes the visual from independent parts (chassis + emitter + components).

- **Phase A** - capability detection foundation parses `.qxf` heads, layout grids, channel groups, and physical envelopes.
- **Phase B** - composable renderer scaffolding (chassis library + emitter runners + component overlays).
- **Phase C** - 2D top-down stage icons follow the same chassis library.
- **Phase D** - moving-head parity components ported over; visual regression harness added; composable renderer flipped to default behind `FIXTURE_RENDERER=composable`.
- **Phase E** - three archetypes that the legacy code couldn't cover are now supported: moving wash without gobo (e.g. Martin MAC Aura), moving-cell bar (e.g. Ayrton MagicBlade-R), and pixel matrix (e.g. Stairville 5×5 LED Matrix). Legacy renderer ports retired.
- HDR + two-pass rendering so chassis stays visible under bright beams.
- Standalone visualizer re-detects capabilities locally to use the composable path.

### Auto Mode (experimental)

A sixth tab - live audio analysis drives lighting in real time without a pre-built show. Folded in from a separate window (`Ctrl+L` still focuses it).

- Real-time spectral features (RMS energy, spectral contrast, vocal HPSS+MFCC delta, transient, centroid) drive automatic rudiment selection per fixture group.
- Per-group constraints: AUTO / CURATED / LOCKED riff selection plus submaster trim.
- Manual triggers: FILL NOW, colour override wheel, BPM tap/auto-detect, energy sensitivity, plane targeting.
- Audio device picker classifies host APIs (MME, WDM-KS, WASAPI, DirectSound, ASIO) and filters junk devices.
- Embedded 3D visualizer in the right pane mirrors live DMX.
- Engine renamed `live → auto` across the codebase.

### Automatic show generation (autogen)

The "prepared" counterpart to Auto Mode: a full pipeline that produces a complete light show from an audio file and a song structure.

- Audio analysis pass extracts per-section energy, contrast, vocal presence, and spectral envelope.
- Rudiment library: 15 intensity rudiments (chase, ping-pong, wave, sparkle, pulse, strobe, heartbeat, throb, …) and 11 movement rudiments (circle, figure-8, lissajous, fan, …) with named flux-envelope shapes.
- Matcher scores rudiments per section against target envelope, repetition rate, flux level, and within-group coherence.
- Per-group spatial classification (front/mid/back, left/centre/right) drives activation and gobo/prism weighting.
- User-assignable lighting roles (wash / key / texture / accent) replace the older zone-based activation.
- Song-level colour palette generator with preset palettes or audio-derived palettes; per-section colour assignment.
- `GenerationReport` captures every decision (candidate scores, role assignments, colour choices) for the in-app Generation Inspector dialog.

### UI modernization

- Maximized startup, single shared timeline grid in the Shows tab (one horizontal scrollbar across master ruler + audio waveform + light lanes).
- Selectable light and dark themes, persisted across sessions, applied once via `app.setStyleSheet`.
- Embedded 3D visualizer in the Stage tab (fixtures render full-on so you can see what you're positioning) and Shows tab (mirrors playback).
- 2D stage plot: zoom + pan, theme-aware QSS.
- Riff library docked under the Shows-tab visualizer.
- Per-row group tinting in the fixtures table, luminance-aware text colour.
- Theme-neutral universe-mapping table; unified toolbar icon-button styling across Configuration and Fixtures.
- Half-beat and quarter-beat grid subdivisions, master snap toggle.
- Persistent stage geometry (width / depth / height / grid size) saved with the configuration.

### Audio

- Per-device classification (host API, channel count, exclusive-mode capability) with a UI status pill that surfaces ASIO availability.
- Live audio capture path separate from playback path.
- Empirically tuned spectral metrics: RMS energy replaced spectral flux as the primary energy driver; spectral contrast replaced spectral richness as the secondary signal; vocal detection moved to HPSS + MFCC delta. See `docs/metric_analysis_results.md` for the validation against 8 hand-made shows.

### Show I/O and QLC+ export

- **Config YAML is the single source of truth.** Loading a config no longer auto-creates a `shows/` directory or keeps a parallel set of `shows/*.csv` structure files alongside the YAML timeline data. `_auto_save` stops writing CSV; audio bundles to `<config_dir>/audiofiles/` via `Configuration.audio_bundle_dir`. Explicit `File -> Import / Export Show Structure` actions cover `.csv` (structure-only) and `.yaml` (full show via `Show.to_dict` / `from_dict`). A one-shot legacy-CSV merge prompt fires on config load if stray CSVs are found.
- **Sequence-step compaction in the QLC+ exporter.** Zero-valued `(fixture, channel, value)` triples - 44% of the total on a representative export - are no longer emitted unconditionally. Zero-skip lives in `utils/to_xml/step_compaction.py`, wired into `unified_sequence` + `shows_to_xml`, matching QLC+'s own saver convention. Compacted output is semantically identical to the uncompacted export.
- **QLC+ target-version stamp.** The Workspace Options dialog now offers a target-version dropdown (4.14.4 default, 5.2.1), threaded through to the exported `<Creator><Version>` stamp. The XML schema is identical between the two QLC+ versions; only the stamp differs.

### Release pipeline

- **CI / release on tag push.** `.github/workflows/release.yml` builds via PyInstaller on a `windows-latest` + `ubuntu-22.04` matrix (22.04 pinned for glibc forward compatibility) on `push: tags: ['v*']` or manual `workflow_dispatch`, uploads the archives as artifacts, and drafts a GitHub Release on tag pushes.
- **QLC+ runtime verification.** An exported demo `.qxw` was smoke-tested against the real QLC+ 4.14.4 and 5.2.1 binaries: it loads cleanly, all fixtures patch to the right universe/addresses, functions populate (Chaser / EFX / Scene / Sequence / Show), and the Virtual Console renders with no overlapping widgets.

### Demo content

- **Bundled demo rigs** - five reproducible archetypes in `demos/rigs/` (club band, mid-size band, festival mainstage, DJ/EDM, static theatre), built deterministically from the bundled `custom_fixtures/` by `demos/generate_rigs.py`.
- **Bundled demo shows** - one autogenerated show per rig in `demos/shows/`, structured from a real hand-made show and driven by a short royalty-free clip; `demos/generate_shows.py` with `--structure-from` / `--structure-slice` / `--calm-movement`.
- **Automated README media** - `demos/generate_media.py` renders clean stills + repo-friendly GIFs (and optional MP4) from any demo show, headlessly, via `utils/render/offline_renderer.py`. Hero GIF + stills are embedded in the README and `demos/README.md`.
- **Legacy show converter** - `utils/legacy_show_converter.py` upgrades old effects-format shows to modern timeline blocks, used to recover a real touring config under `demos/reference/`.

### Fixes and polish (selection)

- `fix(vc-export)` group-control frames no longer overlap the Master frame / SpeedDial in the exported Virtual Console.
- `fix(movement)` default movement rate slowed 4x (one shape cycle per 4 bars at speed 1), consistent across preview and QLC+ export.
- `fix(shows)` the emptied lane-widget shell is hidden so it no longer lingers as a stray panel over the timeline.
- `fix(autogen)` zone classification handles centred-Y stage coordinates.
- `fix(visualizer)` chassis stays visible under beams (real `glDepthMask` write rather than blend trickery).
- `fix(structure)` master timeline scrollbar hidden; grid renders inside `TimelineGrid`.
- `fix(gui)` stage dimensions reload correctly; submasters panel scrollable.
- `fix(live)` engine config rebinds on YAML load / workspace import.
- `fix(auto)` universe table repopulates on config load.
- `fix(visualizer)` `RenderEngine` state buffered before `initializeGL`.
- ArtNet config switched from 1-based to 0-based universe numbering to match the wire protocol.

### Docs

- `docs/architecture.md` - directory structure, data models, communication.
- `docs/fixture_taxonomy.md` - QLC+ fixture-type survey + the rewrite design.
- `docs/artnet.md`, `docs/tcp-protocol.md`, `docs/visualizer.md`, `docs/orientation.md`, `docs/riffs.md` - subsystem pages.
- `docs/qt-gotchas.md`, `docs/gl-gotchas.md` - pitfalls hit during the UI and renderer work, pinned for future contributors.
- `docs/metric_analysis_results.md` - empirical audio-metric analysis backing autogen v3.

---

## [v0.9.5-beta] - 2025

Polish pass over the v0.9.0 beta. 12 commits.

- ArtNet universe numbering switched to 0-based (first universe is ArtNet `0`).
- "Help" window in the visualizer surfaces the ArtNet listen address.
- Visualizer camera moved closer; minor cleanup and font-colour fix.
- `noHead` render path (fixtures without yokes).
- MIDI device + port can be set so show buttons auto-assign.
- Export log surfaces state to the user during workspace export.
- Virtual-console export positioning improvements (still not bug-free; see roadmap).
- Bugfix: Shows tab now auto-updates after structure changes.

## [v0.9.0-beta] - 2025

The first beta. ~137 commits since the alpha.

- Show creator core: Configuration, Fixtures, Stage, Structure, Shows tabs.
- Timeline editor with four sublane types (Dimmer / Colour / Movement / Special) and per-lane multi-target support.
- Riff system: reusable beat-based effect patterns with drag-and-drop, custom riff folder.
- Effect plug-ins (15 intensity + 11 movement) extracted into the `effects/` module.
- 3D visualizer (separate window) - TCP for scene config, ArtNet for live DMX.
- Fixture orientation system (yaw / pitch / roll + mounting) with 3D preview dialog.
- ArtNet output at 44 Hz with BPM-aware movement shapes (Phase 12).
- QLC+ workspace export (`.qxw`) with adaptive sequence step density.
- Automatic spot generation for moving heads.
- Automatic virtual-console creation.
- Master presets auto-generated per show.
- Undo / redo with unit-tested commands.
- Copy / paste of effect blocks.
- Lazy loading so large fixture configurations don't block startup.
- Multiple blocks per sublane with visual feedback (Phase 5).
- Compact YAML serialization with two-level template deduplication.

## [v0.1.0-alpha] - 2024

Initial public alpha - proof-of-concept timeline + export pipeline.
