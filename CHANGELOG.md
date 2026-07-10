# Changelog

All notable changes to QLC+ Show Creator are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While working, add entries under **[Unreleased]**. At release time that heading
becomes the new version section - and the release workflow uses that section
verbatim as the GitHub Release notes (see [docs/releasing.md](docs/releasing.md)).

## [Unreleased]

### Added

- **A Settings toggle for the timeline sub-lane labels.** The faint
  dimmer/colour/movement/special labels drawn on each sub-lane were
  restyled to the brand, and Settings now has a "Show timeline sub-lane
  labels" switch to hide them (they stay in the code, off is one click).
- **A Live tab.** The touch-palette busking surface (North Star layout
  3b): pick fixture groups, apply colour palettes painted in their real
  colour (with a fade time), per-group submaster faders with flash, a
  grandmaster, strobe and a dead blackout. A tempo cluster (a BPM readout
  with TAP and RESET) sets the rate reference, and a SHOW / LIVE mode
  toggle marks whether a predefined show runs underneath the busk (the
  surface stays live either way; the show engine is a later pass).
  The centre is a five-pool grid: colour, position, intensity FX, plus an
  EFFECTS pool listing the riff library (selection-scoped, greyed with no
  selection) and a SCENES pool backed by a new scene library (whole-rig
  looks spanning multiple groups, always live; predefined scenes arrive
  later). The right column carries a dual queue: fired effects and scenes
  stack up as ACTIVE PLAYBACKS rows (pause and kill per row, the running
  show pinned on top in SHOW mode), and a QUEUE latch reroutes palette
  touches into a NEXT UP list that a GO button fires in order; RELEASE ALL
  is the panic release. Position/movement and intensity-FX pools are laid
  in and marked as arriving next. Drives an in-memory live state (with a
  grand x sub output resolve); live DMX output is a later pass.
- **A fuller timeline grid and a swing toggle.** The grid snap now ranges
  from coarse to fine: 4, 2, 1, 1/2, 1/4, 1/8, 1/16 (4 and 2 place a line
  every 4 and every 2 beats; the fractions subdivide the beat). A new
  SWING toggle shifts the off-beat grid lines to a triplet feel, so blocks
  snap to swung positions; beat and bar lines are unaffected.
- **Drag to reorder show parts.** In the Show Structure tab, drag a part
  card onto another to move it there, in addition to the Move buttons.
- **Autosave with crash recovery.** While you work, unsaved changes are
  written every few seconds to a backup file next to the project (Reaper
  style). Ctrl+S writes the project and clears the backup. If the app
  stops before a save, the unsaved work is offered back to you: at the
  next launch (for the session you were in, saved or brand-new) and again
  whenever you reopen that specific project. The manual "UPDATE CONFIG"
  button on the Universes tab is gone: edits apply live and are
  autosaved, so there is nothing to push by hand.
- **F7 opens the pause screen** (screensaver). F11 stays fullscreen; F
  and L remain the Stage tab's own zoom/layer keys.

### Changed

- **Live and Auto share one LIVE section.** The topbar nav is SETUP ·
  SHOW · LIVE; the LIVE section hosts the Live busking surface and the
  Auto pilot as sibling sub-tabs (like Setup and Show), remembering
  which of the two you last used. Ctrl+L still jumps straight to Auto.
- **Timeline snap is per-lane again.** The master timeline no longer has
  its own Snap and Grid controls (they overrode the individual lane
  snaps); the per-lane snap checkboxes plus the toolbar's global
  GRID/SNAP/SWING are the controls now.
- **The timeline buttons are consistent.** Across the toolbar, transport
  and lanes they follow one scheme: Add actions green, Auto-Generate the
  single accent CTA, other text buttons bordered caps, toggles as chips,
  Play/Stop in the function colors.
- **The timeline transport moved to the top.** The play / stop / scrubber
  bar now sits under the toolbar instead of at the bottom, matching the
  North Star. (One self-contained change, easy to revert.)
- **The timeline body now matches the brand.** The lanes, blocks, riff
  browser and the block-edit dialogs were still in pre-rebrand
  Material/Windows colors while the toolbar around them was rebranded.
  Lane headers now use the group color, the Barlow name, a fixture count
  and the sub-lane labels; blocks tint from the group's own color instead
  of a fixed palette (colour rows show the real gradient); the riff
  browser and the colour/movement/dimmer/special/target/save dialogs
  moved onto the theme's roles and accent. Custom-painted widgets read the
  theme tokens directly (see docs/timeline-styling-review.md).
- **The Add button stays put between the Universes and Fixtures tabs.**
  The Universes tab now uses the same top action strip as Fixtures, so
  "+ ADD UNIVERSE" and "+ ADD FIXTURE" sit in the identical spot and the
  button no longer jumps when you switch tabs. The redundant "auto-patch"
  hint line under the fixtures table was removed (the behavior stays).
- **The stage plan puts the audience at the bottom.** Front (the audience
  side) now renders along the bottom edge, matching how stage plots are
  conventionally drawn; the AUDIENCE marker moved there, fixture beams now
  point the right way for the flipped layout, and the horizontal position
  numbers moved to the top edge. This applies to both the interactive 2D
  plan and the printable stage-plot export, so the two agree. Display
  change only: stored coordinates and the 3D view are unchanged.
- **Stage tab side sections are flatter and the footer buttons match.**
  The Marks and Layers sections dropped their redundant inner card and
  repeated caption (the collapsible header already names them), and the
  footer's Fit View / Launch Visualizer / Plot Stage buttons now share one
  size, weight and casing instead of three different looks.
- **Stage marks are managed like layers.** The Marks section is now a
  list with add, delete (the button, the Delete key, or right-click) and
  rename, in place of the old two bare buttons.
- **Fit View moved into the Stage tab's action footer**, above the
  exports, and the footer order is now Fit View, Launch Visualizer, Plot
  Stage. Fit View is one click away with every section collapsed; the F
  shortcut is unchanged.
- **Stage tab left panel regrouped for use, not for the mockup.** Under
  STAGE SETTINGS the stage dimensions, grid and view controls are now one
  "Stage" section instead of three; Marks and Layers are their own
  collapsible sections; and the Stage Planes picker (a display-only face
  selector) was removed. Fewer sections to expand to reach what you set
  first.

### Added

- **Right-click to add a fixture or a group.** The Fixtures table's
  right-click menu now leads with "Add fixture..." (works on empty space
  too), and right-clicking the groups panel offers "Add group...".
- **Right-click a fixture row to Duplicate or Remove it** in the Fixtures
  tab, alongside the existing buttons.
- **Assign several fixtures to a group at once**: select multiple rows and
  use the right-click "Assign to group" menu (existing group, a new one,
  or Ungroup).
- **Duplicate a group** by right-clicking it in the groups panel; the copy
  keeps the lighting role and starts empty, ready for its own fixtures.

### Fixed

- **The Fixtures table no longer leaves a dotted focus rectangle** on the
  cell after you select a row; only the row outline shows.
- **"Apply to group default" now works in the Stage tab.** The inline
  orientation editor's checkbox was wired to nothing, so ticking it did
  nothing until some other value changed. It now re-applies to the group
  the moment you click it (and stays silent on the programmatic toggles
  that happen while switching selection).
- **Stage tab polish.** The nested Stage / Marks / Layers sections are now
  indented under STAGE SETTINGS so the hierarchy reads at a glance; the
  orientation editor's 3D preview no longer touches its frame (a few
  pixels of inset); and the "only elements on the active layer are
  selectable" hint is hidden until you hover the LAYER field, reclaiming
  that space the rest of the time.
- **The orientation editor no longer needs sideways scrolling.** In the
  Stage tab the editor packed three group boxes side by side, wider than
  the inspector column, so the preset buttons ran off the edge behind a
  horizontal scrollbar. It now shows Presets and Fine Adjustment as two
  columns with the apply-to-group control on a full-width row below, and
  the right column is a little wider to fit them. The single-fixture 3D
  preview stays above the two panels (height-capped so the controls below
  stay reachable) so the fixture's orientation is always in view. The
  pop-out dialog shows the preview full size.
- **"+ New" did nothing on the Show Structure tab.** Creating a show was
  gated on a shows directory, which v1.0 demoted to an optional
  import/export hint, so the handler silently returned on every config
  that never set one. Shows are created straight into the config again.
- **A truss had no adjustable length.** Stage elements can now be
  resized from their context menu: trusses ask for a length, other
  elements for width and depth. The footprint is stored in the config
  and survives a save/load round trip.
- **Fixture orientation was unreachable.** "Set Orientation..." in the
  stage plan's context menu only filled the inline panel under the 3D
  preview; it now opens the orientation dialog as well, so yaw, pitch
  and mounting can be set from the plan.
- **Buttons mixed three typefaces in one toolbar.** The accent-button
  style pinned the display family (Barlow Condensed) onto sentence-case
  buttons, so Structure and Timeline showed condensed, bold and regular
  labels side by side. Accent fill and display caps are now separate
  roles: uppercase CTAs use the display family, every other button uses
  the UI family at one weight.
- **Pop Out was offered twice** on every tab with a 3D preview: once in
  the pane header and once inside the visualizer widget.
- **Fixtures could be placed with a stale stage size.** Loading a
  config applied the fixture positions before the stage view knew the
  new stage dimensions, so fixtures on a non-default stage landed at
  the wrong metre coordinates (and could be written back that way).
- **Theme choice no longer resets to light.** Running the test suite
  (or anything else calling the theme engine) could overwrite the
  saved theme, so the app kept opening in light mode regardless of
  the View > Theme choice. Applying a theme and persisting it are now
  separate; only the View > Theme action saves, and the test suite is
  fully isolated from the real settings store.
- **Tab pages are actually dark.** Tab contents sat on the platform's
  default light-gray background because the stylesheet never painted
  bare page widgets; every tab page now uses the theme's window color.

### Added

- **Screensaver matched to the original design reference.** The
  fullscreen brand screen gained the faint engineering grid, corner
  registration marks, and a state kicker above the clock; the rotor's
  rotation periods now match the design (16 s inner, 40 s
  counter-rotating outer). Its status bar no longer claims things the
  widget cannot know: the rig and ArtNet readouts are optional and
  injectable rather than hardcoded text, and the activation hint names
  the real trigger (View > Screensaver).
- **Autogenerate dialog rebuilt against the original design
  reference.** A 420px setup column (audio file with LOADED / MISSING
  chip, structure summary, song key, colour-palette source chips with
  swatches, accent GENERATE) beside a generation panel showing the
  real parameter knobs and a GENERATION INSPECTOR table of the last
  run: one row per section with its envelope, the rudiment picked per
  fixture group, and why (energy, flux, vocals), with the peak-energy
  section highlighted. Reference controls with no backing in the
  generator (intensity ceiling, overwrite toggle, seed and rerun) are
  deliberately absent rather than faked, and in "from audio" mode the
  palette swatches stay hidden until the analysis produces colours.
- **Universes screen matched to the original design reference.** The
  tab title row is gone (the subnav names the screen), the inspector
  now leads with a "U1 · MAIN RIG" heading, labels its ArtNet fields
  Target IP / Net / Universe, shows the fixed 44 Hz output rate as a
  readout, offers a Broadcast toggle (which is simply the
  255.255.255.255 target convention, kept in sync when the IP is typed
  by hand), and carries an info explainer about ArtNet's 0-based
  numbering. A mono status strip reads "3 UNIVERSES · 2 CONFIGURED".
- **Timeline chrome rebuilt against the original design reference.**
  The transport readout now shows the real musical position ("BAR
  19.4 · 00:52.6"), derived from the song structure's parts, bars and
  time signatures. A SNAP chip joins the grid-subdivision chips (both
  synced with the master timeline), the 3D pane gained a proper
  header (POP-OUT, collapse chevron) and the riff browser a caption,
  and a new read-only EFFECT BLOCK inspector shows the selected
  block's lane (in its group color), bar range, duration, and its
  DIM / COL / MOV / SPC sub-lane block counts. A mono status footer
  reads "4 LANES · 28 BLOCKS · GRID 1 · ZOOM 1.0X". Per-block overlap
  functions (XFADE / HTP / LTP) remain future work, so they are not
  shown.
- **Stage, Structure, and Auto screens rebuilt against the original
  design references.** Stage: the layer picker moved into the action
  strip as accent-filled segmented chips beside EXPORT RIDER PDF, the
  left rail became a library (fixture-group rows, click-to-place stage
  element and truss tiles) with every previous control preserved in a
  collapsible STAGE SETTINGS section, the plan gained its draughting
  overlays (top-view caption, active-layer badge, legend, title
  block), and the right pane became a SELECTION inspector with X/Y/Z
  stat tiles and a layer field. Structure: song parts render as cards
  with color top bars, tints, and transition chips, over the master
  grid, with a 2x2 stat-tile inspector (BPM / time signature / bars /
  duration). Auto: per-group AUTO / CURATED / LOCKED segmented chips
  with group-colored intensity bars, a centered engine stage (large
  live BPM readout, tap tempo, RMS / contrast / vocals meters, FILL
  NOW), colour override, and a 3D preview pane with an engine log.
- **Fixtures screen rebuilt against the original design reference.**
  The patch table is now calm, read-only display (row number, fixture
  name, type, "8 CH" mode, "U1", zero-padded address ranges, group
  name in its group color, low-alpha group tints, accent outline on
  the selected row) - all editing happens in the inspector, which
  gained the reference's CAPABILITIES chips and the full CHANNEL MAP
  resolved from the fixture definition, plus Duplicate/Remove
  actions. New GROUPS side panel: color-bar rows with fixture counts
  and role summaries, click to select a group's fixtures, "+" to
  create a group. Status strip shows counts and per-universe channel
  usage (U1 226/512). DMX-conflict red cells, tooltips, and the
  warning chip carry over unchanged.
- **Home screen rebuilt against the original design reference.** The
  starting window now matches screen 01 of the design handoff: the
  brand lockup (rotor beside the two-line wordmark) with the accent
  rule and slogan, NEW PROJECT / OPEN actions, recent projects as
  bordered rows with relative age (today / yesterday / N days ago),
  and the new FROM ZERO TO SHOW checklist - five onboarding steps
  whose done-state is computed live from the project (universes
  patched, fixtures imported, placed on stage, structure defined,
  timeline filled), with the current step highlighted and every row
  jumping straight to its screen. The topbar reads "no project
  loaded" until a project exists, and the status bar carries
  dielichtmaschine.de.
- **Truss docking: a truss is its own layer.** Placing a truss on the
  stage plan now auto-creates a stage layer for it (Truss 1, Truss 2,
  ... at a 4 m default hang height). Drop a fixture onto the truss to
  dock it: it joins the truss's layer, its Z snaps to the hang height,
  and on straight trusses it snaps onto the truss axis (clamped to the
  span, rotation respected). Docked fixtures ride along when the truss
  is dragged; dragging a fixture off the truss undocks it (position
  and height stay). Right-click the truss for "Truss Height...", which
  moves the layer and every fixture on it. Removing a truss undocks
  its fixtures but keeps the layer. Docking round-trips through the
  config YAML; older configs load unchanged.
- **Static stage elements on the stage plan.** The Stage tab's left
  rail grew an element palette (drum riser, risers, wedges, amps,
  4x12, mic stands, keys, DI, distro, FOH, backdrop, stairs, hazer,
  plus the four truss shapes as static outlines): click to place at
  stage center, drag with grid snap, right-click to rotate in 45
  degree steps, set a label, assign to a stage layer, or remove.
  Elements follow the layer rules (hidden layers hide them, active-
  layer editing ghosts non-members), draw under fixtures as steel
  line symbols at their real footprint, persist in the config YAML
  (old configs load unchanged), and appear on the printable stage
  plot. Truss docking (fixtures attached to trusses) is a separate
  future step and needs a design decision on trusses vs layers.

### Changed

- **Fixtures, Structure, Timeline, and Stage screens rebuilt to the
  North Star designs.** Fixtures (card 1c): brand toolbar with the
  DMX-conflict chip and an accent ADD FIXTURE button, tracked-mono
  table headers, a counts + auto-patch status footer, and a right
  inspector editing the selected fixture (name, manufacturer/model
  with GDTF/QXF provenance, patch, group, position) in sync with the
  table. Structure (1e): song parts as color-tinted cards with a 3px
  part-color top bar, transition chips between parts, a dashed add
  tile, a MASTER GRID caption over the region-band timeline, and a
  part inspector (BPM, signature, bars, duration, transition, color,
  reorder, delete). Timeline (4a): grid subdivision as a chip row,
  icon transport with play/pause swap, mono readouts, a 3D PREVIEW
  caption with a collapsible pane toggle. Stage (5a): an active-layer
  chip row above the plan (ALL, per-layer chips with show/hide/edit/
  remove, + LAYER, an "others 25% · locked" hint), a restructured
  left rail with micro captions and a PLOT STAGE accent button, and a
  SELECTION inspector with direct layer assignment. All behavior,
  file formats, and shortcuts unchanged; stage-element/truss
  placement and SWING remain future feature work.
- **Universes tab rebuilt to the North Star design.** Universes render
  as row cards (UNI · name · output chip · destination · channels-used
  meter · status dot) with an inspector on the right editing the
  selected universe: name, output type as selectable chips, and only
  the fields the chosen protocol actually uses (the old table's
  confusing protocol-disabled dead cells are gone structurally).
  Channels-used is computed live from the patched fixtures. Data
  format and behavior (E1.31 multicast auto-IP, device refresh,
  add/remove) unchanged.
- **Stage plan matches the design language.** The 2D stage view keeps
  its 3D-matching axis hues but as quiet dashed hairlines, gains the
  AUDIENCE marker at the front edge, and fixture labels moved to the
  mono readout style with the Z/layer line one step quieter.
- **The app is now Die Lichtmaschine** (dielichtmaschine.de). The
  QLC+ Show Creator name described a companion tool; since the
  standalone pivot the product authors and plays shows on its own, so
  the identity follows. This first slice covers the runtime identity:
  window title, application/organisation names, About dialog,
  `--version` output, the new rotor app icon, and the visualizer
  window title. Persisted settings (theme, splitter layouts) migrate
  automatically from the old QLCShowCreator store on first launch.
  The three brand font families (Barlow, Barlow Condensed, IBM Plex
  Mono; all SIL OFL) now ship with the app. File formats, config
  compatibility, and the QLC+ workspace export are unchanged.
- **New brand themes.** Both themes now carry the Lichtmaschine design
  tokens: Glutorange `#F0562E` accent (selections, hovers, checked
  states), near-black `#141416` surfaces with warm off-white `#F4F1EA`
  text in dark, warm paper tones in light, hard edges everywhere
  (border radius 0), Barlow as the UI font and IBM Plex Mono for time
  readouts. Under the hood the two hand-maintained `.qss` files became
  one QSS template rendered from per-theme token dictionaries
  (`gui/theme_tokens.py`), so palette changes are one dict edit.
  Function colors (green/blue/orange/red status and destructive
  states) keep their roles.
- **Packaging and docs renamed.** The PyInstaller spec is now
  `lichtmaschine.spec` building a `Lichtmaschine` app with the rotor
  icon; release artifacts are named `Lichtmaschine-<os>-<version>`;
  README (with the new banner), FEATURES, and docs present the app as
  Die Lichtmaschine with QLC+ export as one interop path. Fixture-list
  JSON exports are stamped `lichtmaschine-fixture-list`; files with
  the old `qlcshowcreator-fixture-list` stamp import unchanged.
  Companion `.qxf` files are stamped `Die Lichtmaschine GDTF import`.

### Added

- **North Star shell.** The menubar and tab row were replaced by the
  Lichtmaschine shell chrome: a 48px topbar with the rotor glyph and
  wordmark, SETUP · SHOW · AUTO section tabs (Barlow Condensed caps,
  Glutorange underline on the active one), save/load/export icon
  buttons, a MENU overflow button hosting the old File/Edit/View/
  Settings/Render/Help menus (all keyboard shortcuts still work), the
  current config filename with dirty marker, and the ArtNet /
  Visualizer status chips (still click-to-toggle). A subnav row lists
  the active section's screens (Setup: Universes · Fixtures · Stage;
  Show: Structure · Timeline), remembering the last visited screen
  per section; Ctrl+L still jumps to Auto. The status bar is now the
  26px mono strip with the app version on the right. Typography
  helpers (`gui/typography.py`) provide the condensed-caps display
  and tracked mono micro-label voices; golden screenshots pin the
  topbar and subnav in both themes.
- **North Star component styling.** The topbar now uses the design
  system's 16px line icons (extracted from the design boards,
  currentColor SVGs rasterized in the active theme's color, crisp on
  HiDPI) instead of Qt's standard icons; the overflow button gets the
  proper hamburger icon. New reusable Chip element (bordered mono-caps
  tag with neutral/warning/error/accent variants): the Fixtures tab's
  DMX addressing issue count is now a warning chip. Timeline lane
  headers carry a 3px left border in their fixture group's color, so
  lanes read by group at a glance (mockup lane anatomy); the border
  follows target changes.
- **Home screen.** The app now opens on a landing page: rotor hero,
  wordmark, slogan, New from Template / Open Configuration quick
  actions, and a recent-configurations list (tracked automatically on
  load and save). Clicking the wordmark in the topbar returns Home;
  any navigation, shortcut, or file open leaves it. Tab behavior and
  shortcuts are unchanged underneath.
- **Screensaver.** View > Screensaver starts the fullscreen brand
  screensaver: the rotor glyph animating (counter-rotating rings,
  pulsing Glutorange center), a large mono clock, and a status line;
  any key or mouse input exits. Automatic idle / live-pause activation
  arrives with the Live milestones.
- **Stage plot symbols.** The stage view and the printable stage plot
  now draw fixtures as the design system's line symbols (PAR, moving
  head, wash, LED bar, pixel bar, sunstrip) in their group color, with
  the beam tick showing orientation; unknown types keep the old
  primitive shapes. The full 30-symbol set (stage elements + trusses)
  ships in resources/stageplot/ for the upcoming stage work.
- **Timeline anatomy.** Lane headers list their sub-lanes (DIM / COL /
  MOV / SPC) as micro-labels; the master timeline's song parts render
  as North Star region bands (3px part-color bar + tint, condensed
  caps names, mono BPM readouts).
- **North Star detailing.** The statusbar now shows a contextual hint
  per screen (verified shortcuts only, e.g. "L cycles the active
  layer · hold Space to pan" on Stage). Timeline effect blocks carry
  the mockup's block anatomy: envelope framed and tinted (~0.18
  alpha) in the lane's group color, hard corners across all block
  painting, and selection marks in Glutorange; colour blocks keep
  rendering their actual color as the swatch. A faint 48px
  engineering grid (steel at 0.04-0.07 alpha) tiles the main-window
  background in both themes.
- **UI translation scaffolding.** Shell strings go through Qt's
  translation system with a started German catalog
  (`translations/lichtmaschine_de.ts`); set the `ui/language` setting
  to `de` and compile the catalog (`scripts/update_translations.py`,
  needs a Qt lrelease) to switch. Default stays English; no
  language-switcher UI yet.
- **Structured local logging.** The app now writes a daily-rotated log
  file (14 days kept) to the per-OS app-data directory (Windows:
  `%LOCALAPPDATA%\dielichtmaschine\Lichtmaschine\logs`), capturing a
  startup banner (version, Python/Qt, platform), warnings, Qt
  messages, and every uncaught exception including background threads.
  Help > Open Log Folder reveals it. Override the location with the
  `QLC_LOG_DIR` environment variable.
- **Crash reporter dialog.** Uncaught exceptions now surface a dialog
  with the full traceback and app version, with copy-to-clipboard,
  save-as-file, and open-log-folder actions for attaching to a GitHub
  issue. Nothing is uploaded automatically.
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
