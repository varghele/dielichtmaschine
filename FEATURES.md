# Features

A walkthrough of what Die Lichtmaschine does today, in the order you'd actually use it for a real show.

Die Lichtmaschine is the authoring environment, the preview window, a native ArtNet playback engine, and an optional live audio-reactive engine. For interop it also exports QLC+ workspace files (`.qxw`), so a show authored here can run in QLC+ with the same fixture profiles you already use.

---

## 1. Configuration tab - universes and DMX output

Set up where DMX goes. Three output types are supported:

- **E1.31 / sACN** - multicast on your network, one universe per multicast group.
- **ArtNet** - unicast or broadcast UDP, universe numbering is 0-based to match the wire protocol.
- **DMX USB** - auto-detected via `pyserial` (Enttec Open DMX, FTDI-based interfaces).

You can map several universes at once. The universe table is theme-neutral and keeps consistent header alignment with the rest of the app.

---

## 2. Fixtures tab - QLC+ definition import and groups

- **Import any `.qxf`** from the QLC+ fixture library or your own `custom_fixtures/` folder. Modes and channels are parsed straight from the QLC+ definition - no separate database to maintain.
- **Fixture types** are detected from the channel signature: PARs, washes, LED bars (single source), pixel bars (per-cell RGBW), sunstrips (per-cell dimmer), moving heads (single or multi-head), pixel matrices.
- **Groups** organise fixtures by role (front PARs, rear washes, moving heads, etc.) and are the unit of addressing on the timeline. Each group can be restricted to specific fixture types.
- **Per-row tinting** colours each fixture row by group so the assignment is visible at a glance, with luminance-aware text colour in both light and dark themes.

Auto-creation: dropping a fixture in automatically allocates a universe + address range if one isn't set.

---

## 3. Stage tab - visual placement

A top-down 2D plot of your stage. Drag fixtures into position. Each fixture carries:

- **Position** - X, Y, Z in metres.
- **Mounting + orientation** - yaw / pitch / roll, with a separate 3D dialog for tricky angles (overhead truss, side wash, floor uplight). See `docs/orientation.md`.
- **Stage geometry** - width / depth / height / grid size, persisted with the configuration.

The 2D plot supports zoom and pan and follows the active theme via QSS.

**Embedded 3D visualizer** lives in the right pane of this tab. While no show is playing, fixtures render with all DMX channels at full so you can see exactly what you're positioning before you wire any effects.

---

## 4. Structure tab - song parts and timing

Define the structure of the song before you light it.

- **Song parts** - intro, verse, chorus, bridge, drop, outro, anything you name.
- **Per-part BPM, time signature, bar count.**
- **Transitions** between parts (instant, crossfade, fill).
- **Master timeline grid** showing the full song with bar-accurate boundaries; half-beat and quarter-beat subdivisions are available with a master snap toggle.

This drives every downstream feature - block snapping on the timeline, riff trimming, automatic show generation.

---

## 5. Shows tab - timeline authoring

The main authoring surface. One horizontal scrollbar runs across the master ruler, the audio waveform, and every light lane - they're aligned by construction, not by signal-synced scroll bars.

### Sublanes (four effect layers per lane)

Each light lane targets one or more fixture groups (or individual fixtures) and contains four sublanes:

| Sublane    | What it controls                                     |
|------------|------------------------------------------------------|
| Dimmer     | Intensity, strobe, iris, dimmer effect + speed       |
| Colour     | RGB / CMY / HSV, colour wheel position               |
| Movement   | Pan / tilt + shape (circle, figure-8, lissajous, sweep, diamond, square, triangle, fan, bounce, random) |
| Special    | Gobo index, prism, focus, zoom                       |

15 intensity effects ship (static, stroke, ping-pong, chase, wave, waterfall, fill / infill, random stroke, sparkle, pulse, strobe, fade, cascade, heartbeat, throb). 11 movement shapes.

### Multi-target lanes

One lane can address several groups at once - useful when "all front fixtures pulse on the kick" is one decision, not five lane copies.

### Riff library

A reusable effect library docked under the Shows-tab visualizer. Drag a riff onto the timeline and it expands into the right number of sublane blocks for the bar length you drop it across.

- Five built-in folders: `builds/`, `drops/`, `fills/`, `loops/`, `movement/`.
- A `custom/` folder for your own patterns.

### Embedded 3D visualizer

The same `RenderEngine` widget as Stage tab, driven by playback. No separate window to manage. The standalone visualizer remains for cross-machine use (TCP + ArtNet over the network).

### Audio waveform + playback

- pygame-based playback with a waveform display.
- Peaks pre-computed so scrubbing is responsive on large files.

### Undo / redo, copy / paste, snap

All effect-block operations go through an undo command stack. Multi-selection is supported. Copy / paste works across lanes.

### Export

`File → Export QLC+ Workspace` produces a `.qxw` containing:

- Fixture definitions and universe mappings.
- Scenes with the exported DMX values.
- Sequences built from sublane blocks with adaptive step density (capped at 24 steps/sec so QLC+ stays responsive).
- A virtual console with master presets + auto-generated show buttons.
- The full show timeline.

A progress log surfaces what's being exported as it runs.

---

## 6. Auto Mode tab (experimental) - live audio-reactive lighting

The "sixth tab." Reach it from the tab bar or with `Ctrl+L`.

Auto Mode is for unscripted situations - rehearsal jams, busking, parts of the set you haven't authored yet. Pick a host API, pick an input device, hit **START**, and the engine picks rudiments per fixture group from a rolling window of live audio.

### Live audio analysis

Real-time spectral features computed in a background thread:

- **RMS energy** drives overall intensity targets.
- **Spectral contrast** drives texture choices (when the mix is "rich" the algorithm reaches for sparkle / texture, when it's "flat" it stays on washes).
- **HPSS + MFCC delta** detects vocal presence, which flips a per-group bias toward front lighting.
- **Transient and centroid** drive movement speed and colour temperature hints.

Empirically tuned against 8 hand-made shows - see `docs/metric_analysis_results.md`.

### Per-group constraints

Each fixture group has a row with:

- **AUTO** - engine picks the rudiment each cycle.
- **CURATED** - engine picks from a user-restricted subset.
- **LOCKED** - fixed rudiment until the operator releases it.
- **Submaster trim** - per-group output level.

### Manual overrides

- **FILL NOW** button to inject a fill bar without waiting for the phrase boundary.
- **Colour override wheel** - pin the palette while the engine still handles intensity / movement.
- **BPM** - tap, auto-detect, or set manually. Detection uses librosa's onset / tempogram path.
- **Energy sensitivity** slider.
- **Plane targeting** - bias which spatial plane (front / mid / back) the engine prefers this section.

### Embedded visualizer

The same composable renderer mirrors the live DMX in the right pane. No second window.

### Audio device handling

Host APIs are classified and labelled (MME, WDM-KS, WASAPI, DirectSound, ASIO). Junk / loopback devices are filtered. An ASIO status pill surfaces when an ASIO driver is available.

---

## 7. Automatic show generation (autogen)

Available from `Tools → Autogenerate Show` (the `AutogenDialog`). The prepared-mode counterpart to Auto Mode: it produces a complete light show from an audio file and a song structure.

### How it works

1. **Audio analysis** - per-section energy, contrast, vocal presence, spectral envelope.
2. **Section targets** - each section gets a flux envelope (flat / pulse / build / drop / texture / …).
3. **Phrase structure** - bars within a section are grouped into phrases, with the last bar of each phrase tagged as the fill bar.
4. **Rudiment matching** - every rudiment in the library is scored per section against envelope similarity, repetition-rate fit, flux-level fit, and within-group coherence.
5. **Spatial activation** - fixture groups are classified by stage zone (front / mid / back × left / centre / right) and roles are assigned (wash / key / texture / accent).
6. **Colour palette** - either a preset palette or one derived from the audio is assigned per section.
7. **Block generation** - rudiments expand into `DimmerBlock` / `MovementBlock` / `ColourBlock` / `SpecialBlock` instances on the timeline.

The output is regular timeline blocks. You can edit, replace, or delete anything the algorithm produced.

### Generation Inspector

Every autogen run produces a `GenerationReport` capturing the candidate scores, the picks, the role assignments, and the colour choices. The Generation Inspector dialog visualises it so you can see *why* the algorithm picked a chase over a sparkle in chorus 2.

### Status

The pipeline runs end-to-end. The matcher heuristics are still being tuned - see roadmap for the decision-logging and inspector improvements planned for v1.1.

---

## 8. 3D Visualizer - standalone

The visualizer is also a separate ModernGL application (launched from the Stage tab toolbar or `python -m visualizer.main`).

### Composable renderer (default in v1)

`FIXTURE_RENDERER=composable` is now the default. The renderer reads capabilities directly from the `.qxf` and composes the visual:

- **Chassis** - the physical body. PAR can, par-stick, yoke, moving-head body, bar, pixel matrix, sunstrip, panel.
- **Emitter** - single-source RGB(W), cell array, multi-head.
- **Components** - gobo wheel, prism (3-facet beam split), focus / zoom, colour wheel - instantiated only when the fixture declares the capability.

This means fixtures with unusual mode combinations (e.g. a moving wash without gobos) render correctly instead of being shoehorned into a fictional gobo+prism subsystem. Validated by the visual-regression harness in `tests/visual/`.

### What's supported today

- PAR, LED bar (beam), pixel bar, sunstrip, wash, moving head (single-head, multi-head, cell-array bars), pixel matrix.
- Volumetric beam cones with floor-projection spotlights.
- Prism (3-facet split), gobo patterns, focus simulation.
- HDR pipeline so bright beams don't blow out the chassis.

### What's not (yet)

Hazers, smoke, lasers (vector), scanners, effect lights (centipede / derby / sweeper), flowers. They currently fall back to a generic point. See roadmap §3.

### Dual input

- **TCP (port 9000)** - Die Lichtmaschine pushes the stage config (fixtures, positions, orientations, groups) once and on change.
- **ArtNet (UDP 6454)** - live DMX values at 44 Hz.

The visualizer can also receive ArtNet from QLC+ directly, so you can use it as a live preview when the show is running off the QLC+ Console.

---

## 9. Themes, UX, and platform

- **Light and dark themes** - selectable and persisted. Applied once via `app.setStyleSheet`.
- **Maximized startup** with an F11 fullscreen toggle.
- **`MainWindow` + tab system** - every tab extends a `BaseTab` lifecycle.
- **Compact YAML serialization** with two-level template deduplication (identical sublane blocks → shared template; identical light blocks → shared definition with position offsets). Keeps show files small even when the same chase repeats across the song.

---

## What this app is *not*

- Not a QLC+ plugin or frontend - it drives DMX natively over ArtNet; the `.qxw` export is an interop path for rigs that run on QLC+.
- Not a live-mixing console - Auto Mode is for unscripted moments inside a structured set, not "click and DJ a whole gig" (though see roadmap §2).
- Not a fixture-library editor - write `.qxf` files in QLC+ itself; this app consumes them.
