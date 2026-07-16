# Changelog

All notable changes to Die Lichtmaschine (formerly QLC+ Show Creator) are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While working, add entries under **[Unreleased]**. At release time that heading
becomes the new version section - and the release workflow uses that section
verbatim as the GitHub Release notes (see [docs/releasing.md](docs/releasing.md)).

## [Unreleased]

### Added

- **Movement blocks can aim at the world, and old shows can convert.**
  Three authoring surfaces for the new world-space movement targets:
  the movement block editor's target picker now offers, besides named
  spots, the stage's bounding planes and a read-only display of an
  ad-hoc world point; the Stage tab gained an AIM toggle - click the
  stage plan to point the movement block selected in the Show timeline
  at that exact spot (Shift keeps the current target height); and
  Tools > Convert Movement to World Targets... traces where every
  legacy pan/tilt movement block's beam actually lands on the stage
  and writes that point as the block's world target, after showing a
  full per-block report (skipped blocks - e.g. beams pointing at the
  sky - and groups whose fixtures land far apart are called out).
  Pan/tilt values stay as fallback in all three paths.
- **Morph to Venue: take a show to another rig.** File > Morph to
  Venue... opens a wizard that adapts the open show to a different
  venue's rig: pick the venue project, wire the patchbay (each source
  lane stream docks onto target groups of the same capability -
  INTENSITY, COLOUR, POSITION, BEAM - with per-wire transforms like
  mirror, phase offset, intensity scale and stage-half subsets, plus
  regenerated movement for rigs that gained movers), review the
  coverage table and the full morph report from a dry run, then commit
  and save the morphed show as a new project. Patch plans save as
  reusable `*.morphplan.yaml` files per venue - reload one to re-morph
  after fixing the master show, with locked target lanes left untouched
  and any hand-edited blocks listed before they are replaced. An
  auto-suggest button prefills the wiring by lighting role; nothing
  routes without confirmation, and cancelling changes nothing. The
  review step also carries a side-by-side preview: pick a song, scrub
  to any moment, and RENDER PREVIEW shows the original show on the
  source rig next to the morphed show on the venue rig as two stills
  (rendered on demand in the background; a side without a usable GL
  context or an empty song shows a placeholder instead of failing).
- **Colour palette roles are editable.** The colour block editor gained
  a ROLE picker: tag a block with a palette role ("primary", "accent",
  or any name you type) instead of leaving it a hard-coded literal, and
  EDIT PALETTE... manages the song's role-to-colour table with swatch
  pickers. Changing a role's colour re-skins every block tagged with it
  across the song immediately - the indirection that also lets the
  venue morph route colour as intent instead of copying literal values.

## [1.4.0] - 2026-07-15

### Fixed

- **Exported movement patterns now trace the right figure on real
  rigs.** A `.qxw` export converted only the CENTRE of a moving-head
  pattern to the real fixture's yoke and layered the shape's offsets
  on top in the app's internal convention - a mix of two coordinate
  conventions that traced a distorted figure in QLC+ playback. Every
  sequence step is now computed internally first and converted whole,
  so QLC+ moves the heads exactly like the app's native output (which
  was hardware-verified). Rigs without moving heads export
  byte-identically, as before.
- **The 3D stage was a mirror image of the real stage.** The renderer
  mapped stage coordinates by swapping two axes, which is a reflection,
  not a rotation - so the whole scene was flipped. Beams still landed on
  their targets inside the mirror, which is why it went unnoticed, but
  against reality it read as "everything is backwards": aim a mover at a
  spike mark and it appeared to hit the mark's mirror image; aim at the
  audience and the beam flew toward the back of the stage. On top of
  that, the default camera sat behind the band. Both are fixed: the view
  is now a faithful copy of the stage, seen from the audience. DMX
  output is unchanged by this fix.
- **Moving heads aimed to the wrong place on real hardware.** The
  pan/tilt values sent to a physical fixture were computed in the app's
  internal yoke model, which differs from how a real moving head is
  built - so a fixture told to point straight down at a target aimed
  flat/horizontal instead. Native ArtNet output now converts each
  moving head's pan/tilt to the real fixture's yoke on the way to the
  node, so aimed positions and spot targets land where intended. The
  3D visualizer already showed the correct aim and is unchanged; the
  rig now matches it. **Verified on a real moving head** (bench
  protocol: rest/tilt/pan reference poses plus four aimed targets, all
  landing) - which also calibrated the rotation direction of the
  physical pan/tilt axes against the model. (QLC+ export still uses
  the old convention - a known follow-up.)
- **All four wall mounting presets were swapped with their opposites.**
  Wall-back faced upstage, wall-front faced the audience, wall-left
  faced stage left (a right-wall mount) and vice versa. All corrected;
  projects saved with the old values are fixed automatically on load.
- **QLC+ export aims moving heads like the app does.** Spot targets,
  position presets and the Virtual Console XY-pad presets in exported
  workspaces now use the fixture's real pan/tilt ranges and the real
  yoke conversion, so QLC+ playback lands beams where the app and the
  rig do. Exports of rigs containing movers change accordingly;
  mover-less rigs are byte-identical as before. (Animated movement
  patterns still oscillate in the old value space around the corrected
  centre - a known refinement.)
- **`.qxf` movers aim correctly too.** Fixtures without a GDTF
  definition get the standard real-yoke treatment on the wire and in
  the export, the same convention verified on hardware - real moving
  heads are built that way regardless of definition format.
- **The universe's Target IP now drives native ArtNet output.** It was
  honoured only by the QLC+ export - the built-in output always sent to
  broadcast, which on a machine with more than one network interface
  leaves via the default one and never reaches a node wired to a
  second NIC (the classic 2.x.x.x ArtNet network). Output now unicasts
  to the configured node IP (re-read whenever output is toggled or
  playback starts), with a broadcast mirror so the local visualizer
  keeps receiving. No IP configured keeps the old broadcast behaviour.
- **Live position palettes aim with 16-bit precision.** The busk
  layer's position claims now write the pan/tilt fine channels with the
  real 16-bit remainder instead of zero. Coarse-only aim quantizes a
  540-degree pan to about 2 degrees per step - roughly 18 cm of drift
  at a 5 m throw; with the fine bytes the aim resolves to the
  fixture's true precision.
- **Aimed beams missed their targets on GDTF fixtures.** The aiming
  math and the GDTF geometry describe two different yokes: the solver
  aims with the beam perpendicular to the pan axis at tilt centre,
  while a GDTF tree (like a real moving head) has the beam along the
  pan axis at tilt centre. Feeding the solver's pan/tilt into the GDTF
  chain unchanged pointed the head - and its light cone - somewhere
  else entirely, so position presets and spot targets never landed.
  The renderer now converts between the two conventions at the GDTF
  chassis, verified closed-loop: a hanging mover aimed at a stage spot
  through the real solver, DMX and render chain hits it to within a
  few thousandths of a degree.
- **GDTF fixtures rendered upside down.** GDTF authors a fixture
  hanging from its attachment point (the geometry tree extends downward),
  while the app's own fixture bodies are authored standing - so the
  mounting flip that hangs a standing body turned GDTF meshes the wrong
  way up: a hung rig rendered standing, with its beams firing at the
  ceiling (and effectively invisible in the 3D view). GDTF geometry is
  now rotated upright on load when it is authored hanging, so hanging
  and standing read correctly and the beams point where they should.
  Floor-standing GDTF fixtures (bars authored upward) are untouched.
- **The visualizer says where the audience is.** "AUDIENCE" is written
  on the apron at the front edge of the stage, so the orientation of the
  3D view is never in doubt.

### Added

- **Silent fallbacks now speak up (Help > Warnings).** For years the
  app printed problems to a terminal nobody has open and carried on:
  a lane skipped on export, a fixture definition that would not
  parse, missing audio, a dead ArtNet socket. Those paths now report
  into a structured warnings panel - the last operation (export,
  project load) called out on top, full session history below,
  copyable for bug reports, everything mirrored into the log file.
  The export "Success" box now says when the workspace was created
  WITH warnings and opens the panel directly; a failed project load
  finally shows an error dialog instead of silently keeping the old
  project; repeated failures (a 44 Hz output error) fold into one
  counted entry instead of a storm. The headless CLI export prints
  the same warnings to stderr for scripts and CI. Exported files are
  byte-identical - only the reporting changed.
- **Import any CSV lighting table.** Real venues hand over whatever
  spreadsheet they have; the new wizard (File > Import Lighting Table
  (CSV), or the topbar import button, which now offers the choice of
  QLC+ workspace or CSV) takes it as-is. Delimiter (comma, semicolon,
  tab), text encoding (UTF-8 or Windows/Excel umlauts) and the header
  row are detected automatically, with manual overrides and a raw
  preview. Then each rig field picks the CSV column that feeds it,
  auto-guessed from the header names (manufacturer and model are
  required, everything else optional), with a live preview of the
  mapped result. The last page shows the rig resolved through the
  fixture library, exactly like Import Fixture List: known models get
  their real mode lists, models the library does not know are marked
  clearly instead of silently dropped, and bad rows are listed. A
  "position" column (FOH truss, LX1...) becomes a stage layer, so hang
  positions survive into the stage setup. Replace or add to the
  current rig, same as the fixture-list import - and nothing changes
  until IMPORT is confirmed on that last page; Cancel anywhere leaves
  the project untouched.
- **Help > Diagnostics.** One copyable markdown block for bug reports:
  app/Python/Qt versions, platform, OpenGL renderer, detected audio
  host APIs, ArtNet output state, project path and log folder. Every
  probe is guarded - on a machine where a subsystem is broken (exactly
  the machine that needs this), the report shows the error string for
  that row instead of failing to open.
- **GDTF Share, in-app.** The fixture browser grew a GDTF SHARE tab:
  log in with your own gdtf-share.com account, search the catalog
  (manufacturer uploads ranked first), and download definitions
  straight into your GDTF directory - they appear in the library list
  immediately, ready to patch. The catalog is cached for a day and
  stays browsable offline. Credentials are never written in
  plaintext: the username lives in the app settings, the password
  only in the OS credential store (Settings > GDTF Share Account,
  with a TEST LOGIN button) - without a credential store it is kept
  for the session only. Share terms hold as ever: definitions are
  fetched per user, never bundled with the app. Dropping `.gdtf`
  files into the fixtures folder manually keeps working.
- **An honest unsaved-changes asterisk.** The project name in the
  topbar (and the window title) now carries a Reaper-style ` *`
  whenever the project differs from what was last manually saved -
  regardless of where the edit happened: fixtures, stage, structure,
  timeline, dialogs. Previously the marker only tracked timeline
  block edits, so most changes never showed it. Autosave's crash
  backups deliberately do not clear it - only Ctrl+S does. Edits in a
  never-saved project read "UNTITLED *", and hovering the name says
  what the asterisk means.
- **Shows chase incoming SMPTE timecode (LTC).** Set the setlist's
  sync mode to SMPTE, give songs an SMPTE start time, pick the audio
  input carrying the timecode and press ARM CHASE in the Structure
  tab: each song fires the moment the incoming timecode reaches its
  start time, and the playhead follows the signal from then on -
  joining mid-song, following desk locates, and quietly re-syncing
  when drift builds up. A dropped timecode cable never stops the
  show: playback freewheels and re-locks when the signal returns.
  While armed the desk is the master (Play is disabled); STOP is the
  escape hatch and disarms. The Live tab's SYNC chip reads SYNC LTC
  with the lock state and the last received timecode. Frame rates
  24/25/30 and 29.97 drop-frame are detected automatically from the
  signal. No timecode hardware is needed to try it: the decoder ships
  with a generator (`utils/timecode/write_ltc_wav`) that renders a
  timecode WAV to play into the line-in from a phone or DAW.
- **Live colour swatches reach colour-wheel fixtures.** A busked swatch
  on a mover without RGB emitters (colour wheel only, like the Varytec
  Hero Spot 60) used to light the fixture white at best - the wheel
  channel was never driven. The busk layer now steers the wheel to the
  nearest matching slot, the same mapping timeline playback uses.
- **The Live INTENSITY FX pool plays bundled dimmer patterns.** Every
  dimmer rudiment the timeline knows ships as a bundled riff - Pulse,
  Wave, Chase, Sparkle, Heartbeat, Strobe Burst, Stroke, Throb,
  Ping-Pong, Waterfall, Fill, Random Stroke, Fade and Cascade - and
  loops on the selected groups at the live tempo, on its own playback
  slot, so a dimmer pattern runs underneath a colour effect from the
  EFFECTS pool at the same time. Same contract as effects: second
  touch releases, PAUSE freezes, KILL clears. A held colour swatch no
  longer flattens the pattern: the swatch keeps the colour while the
  pattern drives the dimmer (FLASH still forces full), and fixtures
  running a pattern get their shutter opened even with nothing else
  busked - both found on the bench.
- **A STAGGER fader for movement shapes.** Next to the S/M/L size
  chips: at 0 the selected heads trace the shape in unison, raising
  the fader fans them around the cycle (100 spreads them evenly), for
  wave-like sweeps instead of lockstep movement. Changing it restages
  the running shape live.
- **The Live MOVEMENT SHAPES pool moves real movers.** The placeholder
  cells became the ten movement rudiments (circle, figure-8, diamond,
  square, triangle, lissajous, sweep, bounce, random, fan). Touching
  one loops the shape on every selected mover group at the live tempo,
  anchored at the group's held position palette (stage CENTRE when
  none is held) - hold a position to place the orbit, touch the shape
  to spin it, touch again to release. Shapes claim only pan/tilt, so
  they run dark until something opens the fixture. The orbit is
  measured in real meters on the stage, not in DMX travel: S/M/L SIZE
  chips choose a 0.4 / 0.75 / 1.5 m radius around the anchor, and the
  beam stays that close to the target at any throw distance (the
  first cut orbited a fraction of the fixture's full pan range, which
  dwarfed nearby targets - found on the bench).
- **The tempo RESET button resets the tempo.** It used to clear only
  the invisible tap history, which read as a dead button; it now snaps
  the BPM back to 120 as well.
- **The Live EFFECTS pool plays riffs for real.** Touching an effect
  loops its riff on every selected group at the live tempo: TAP
  changes the speed mid-play without a phase jump, re-selecting
  groups moves the effect to them, the queue's GO fires the next
  staged effect, PAUSE freezes the pattern mid-pose (and keeps
  streaming that pose), KILL and a second touch release everything to
  the show underneath. Explicit palette touches still win on top: a
  held swatch overrides the running riff's colour on that group.
- **Colour swatches release on second touch.** A busked colour could
  only be replaced or panic-cleared with RELEASE ALL - touching the
  held swatch again did nothing, and since an explicit swatch
  deliberately outranks a scene, a stuck colour also blocked the scene
  on that group. Swatches now follow the same toggle contract as
  position palettes: touching the swatch every selected group already
  holds releases it, and the group falls through to the active scene
  or the show underneath.
- **The Live SCENES pool makes real light.** Touching a scene applies
  its colour to the groups it lists - whole-rig, independent of the
  current selection, under the same submaster/strobe treatment as
  swatches. An explicitly touched swatch still wins on its group, and
  a second touch releases the scene to whatever plays underneath.
- **Touching a palette with nothing selected now says so.** Colour and
  position palettes are selection-scoped; touching one with no group
  selected used to be pure silence. The programmer bar now flashes
  "NO GROUP SELECTED" for a moment instead.
- **OUTPUT turns on with one press.** The topbar's OUTPUT switch needed
  two clicks when nothing was running yet, because it flipped a stored
  flag that started out claiming output was already on. It now derives
  the toggle from the actual output state (the same cure the
  VISUALIZER button received earlier).
- **The local visualizer always receives output.** Every merged frame
  is now also sent to the local machine (loopback), regardless of what
  the universes' Target IPs say - previously, output aimed at a
  hardware node could leave the 3D viewer dark, since broadcast is not
  reliably heard locally on machines with several network interfaces.
- **FLOOR position preset.** The Live tab's POSITION pool gained a
  Floor preset - every selected mover aims straight down at the deck
  beneath it, the natural rest for a hanging rig (Ceiling remains its
  standing counterpart).
- **The visualizer respects a mover's real tilt travel.** A hanging
  moving head cannot point at the ceiling, but the 3D view pretended it
  could; rendered pan/tilt now clamps to the fixture's physical ranges
  exactly like the values sent to the rig, so an out-of-reach target
  pins at the travel limit in both places identically.
- **Undo / redo on the timeline.** Ctrl+Z / Ctrl+Y now cover the Shows
  tab: adding, moving, resizing, deleting and pasting effect blocks, and
  adding or removing whole lanes. A multi-block delete undoes in one
  step, and a moved or resized block is now saved (that edit previously
  slipped past auto-save). Switching songs starts a fresh history.
- **Untangle and Compact for DMX addresses.** Right-click the patch
  table for two one-shot repairs: **Untangle addresses** fixes address
  conflicts by moving only the offending fixtures to the nearest free
  ranges (fixtures that can stay put do - including the lower-addressed
  half of an overlapping pair), and **Compact addresses** repacks each
  universe to consecutive addresses with no gaps, keeping the order.
  Fixtures that genuinely cannot fit are left alone and named.
- **Riff tags.** Riffs can carry tags: right-click a riff in the
  library rail for Edit Tags (comma-separated), the tags show on the
  riff card, and the rail search matches them - a query starting with
  `#` (like `#chorus`) searches tags only.
- **BUILD look in the standalone visualizer.** A BUILD chip in the
  viewer's header lights the whole received rig with a synthetic look
  (dimmer up, shutter open, pan/tilt centred - the same look the
  in-app 3D preview uses while building) so mounting orientation and
  beam direction can be checked without playing a show. Live DMX is
  ignored while the chip is on; switching it off returns the view to
  the real output (dark until data arrives).
- **Native `.lms` project files.** Projects now save with the `.lms`
  extension (Die Lichtmaschine project); Save and Save As default to it,
  and a bare typed name gets `.lms` automatically. The file is still
  plain YAML inside, so nothing about the format changed - your existing
  `.yaml` projects open exactly as before and can be re-saved as either.
  Passing a project path on the command line (or double-clicking a
  `.lms` file once it is associated with the app) opens it on launch;
  registering that association still needs a manual step until an
  installer ships.
- **Your own fixture library folders.** Settings > Fixture Libraries...
  points the app at a personal GDTF directory and a personal .qxf
  directory. Definitions found there are picked up by the fixture
  browser (tagged [GDTF] / [user]) and take priority over the shipped
  ones - your corrected file wins over the bundled copy of the same
  fixture. The defaults live in the per-user app data folder, so a
  packaged install never needs write access to its own directory.
- **Headless QLC+ export.** `python main.py export show.yaml --out
  venue_a.qxw --qlc-version 5.2.1` writes the workspace without opening
  the app (no display needed) - for scripted setups and exporting many
  venue variants in one go. `--no-vc` skips the Virtual Console,
  `--dark-mode` flips its background, and with no `--out` the workspace
  lands next to the config.

- **The Live tab's POSITION pool aims real light, per group.** Select
  fixture groups and touch a position palette - a computed preset
  (CENTRE, AUDIENCE, CROSS, FAN OUT, CEILING, one per placed drum
  riser / keys / FOH / mic stand) or a spike mark from the Stage tab -
  and the selected groups' moving heads aim at that stage-space target.
  Each group holds its own position (aim one group at the drums while
  another washes the audience); touching the same palette again releases
  that group's pan/tilt back to the running show. Positions claim only
  pan/tilt, so movers can be pre-aimed while dark, and the aim respects
  each fixture's mounting, orientation and its definition's physical
  pan/tilt ranges (from GDTF or .qxf data, with 540°/270° assumed when
  the definition declares none). Native ArtNet playback aiming at spike
  marks and stage planes now honours those true ranges too.

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
- **A fuller timeline grid and percentage swing.** The grid snap now
  ranges from coarse to fine: 4, 2, 1, 1/2, 1/4, 1/8, 1/16 (4 and 2 place
  a line every 4 and every 2 beats; the fractions subdivide the beat). A
  SWING dropdown (0/25/50/75/100%) shifts the off-beat grid lines toward
  a triplet feel by that amount, so blocks snap to swung positions; 100%
  is the full triplet, beat and bar lines are unaffected.
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
- **The standalone visualizer wears the brand.** The viewer window
  boots with the app's fonts, dark theme and icon; the stock grey
  toolbar became the brand header (rotor glyph, wordmark, VISUALIZER
  tag, CONNECT / RESET VIEW / HELP as chips) and the status bar reads
  in mono caps with the theme's own state colors and the brand
  separator. The 3D scene itself is untouched.
- **One press opens the visualizer.** The VISUALIZER button used to
  need two presses: a stale "enabled" flag from startup made the
  first press a silent no-op. The toggle now derives from whether the
  feed is actually running, so the first press starts it and launches
  the viewer.
- **The topbar chips say what they do: OUTPUT and VISUALIZER.** The
  ArtNet chip is now the OUTPUT master switch and reads streaming
  truth (it shows ON whenever anything is on the wire, Auto included),
  and enabling it no longer locks Auto mode out - the timeline claims
  the exclusive output slot only while it actually plays, so you can
  switch output on, busk on the Live tab, then start Auto without
  being refused. Pressing play while Auto holds the output explains
  itself and keeps the audio running. The cryptic "Vis" dot became a
  VISUALIZER chip with a labelled OPEN/STOP button: OPEN launches the
  standalone visualizer and starts its feed in one click (no more
  "would you like to launch it?" dialog), the status readout shows
  the connected-viewer count, STOP ends the feed.
- **OUT and SYNC readouts in the Live tab.** Two status chips sit next
  to the tempo cluster in the LED-readout voice: OUT shows what is
  actually on the wire - protocol, universe count and a live activity
  dot fed by the output loop's frame counter - with a per-universe
  wire-mapping tooltip, and flags universes configured for E1.31/DMX
  USB (native output is ArtNet-only for now; those settings are
  honoured in the QLC+ export). SYNC names the clock reference -
  internal TAP today, external sources when the v1.7 engine slaves
  the clock. The DBO kill switch now reads its state (quiet red
  outline idle, filled red while armed) and FLASH - like every chip
  of its kind - fills in the accent while held.
- **The Live tab makes real light.** With ArtNet output enabled, the
  busk surface now drives the rig: applied colour palettes (split
  swatches alternate across a group's fixtures), submaster levels,
  FLASH and the strobe reach DMX through the output arbiter's LIVE
  layer, riding on top of whatever plays underneath - a group you
  touch overrides the show for exactly its channels, RELEASE ALL hands
  them back seamlessly, and untouched groups keep playing the show.
  The Live GRAND fader and DBO cap all output, timeline and Auto
  included. The idle floor follows the shell: SETUP/SHOW keep the rig
  visible for authoring, the LIVE section idles to blackout. Still
  data-only until their own milestones: position presets (pan/tilt
  math is v1.5a) and the effects/scenes pools (the v1.7 engine).
- **Computed position presets return to the Live pool.** The POSITION
  pool's new PRESETS subsection lists CENTRE, AUDIENCE, CROSS, FAN OUT
  and CEILING - not canned looks but targets computed from the stage
  setup (stage size, each mover's own position) - plus one preset per
  placed stage element the plot knows a focus for (drum riser, keys,
  FOH desk, mic stand; the element's layer height folds into the
  target). The spike marks keep their own MARKS subsection below.
  Presets carry real target coordinates from day one; pan/tilt math
  and actual movement arrive with the focus-geometry and output-engine
  milestones.

### Fixed

- **Spike marks are position palettes in the Live tab.** The POSITION
  pool lists the stage's spike marks (name + x/y tag) as selectable
  cells - movers-only, the staged mark accent-outlined and shown in the
  programmer bar; a mark removed or renamed on the Stage tab clears
  from the staged position. The fake position presets are gone; with no
  marks the pool says so and points at the Stage tab. Staging is still
  in-memory only until the output engine lands.
- **Stage spots are spike marks in the brand voice.** The stage marker
  renders the spike-mark symbol (X through a circle, the screen 04
  asset) on the stage canvas and the printed plot, replacing the plain
  black X; the marker labels left Arial for the brand mono, centered
  under the mark, and the selected mark reads in the accent. The whole
  printed stage plot now sets its text in Barlow, and its title uses
  the brand separator.
- **Lane names no longer clip, and lanes show their fixture group.**
  The lane-name field sizes from its font instead of a hardcoded
  height, and a quiet subtitle under the name lists the targeted
  fixture group(s), eliding when long and disappearing when the lane
  has no targets.
- **The block header strip no longer covers the dimmer bar.** The
  "BASE · ..." strip on every timeline block now has its own 16px zone
  at the top of the lane; the dimmer band and its drag handle sit fully
  below it, visible and clickable along their whole height. One shared
  band-geometry helper drives the canvas stripes, the block rows and
  the header labels so they can no longer drift apart. The DIM / COL /
  MOV / SPC labels are each aligned with their own sublane row in the
  lane header, and + BLOCK is an accent chip.
- **The fixture-loading dialog no longer runs a modal event loop.** On a
  cold fixture-capabilities cache, adding fixtures from a definition
  showed its progress dialog via a blocking exec; it now waits on the
  background cache worker with a plain event loop while the dialog
  animates. Same behaviour, no modal loop, and the multi-add test runs
  clean on a cold cache.

### Changed

- **One output arbiter drives ArtNet.** All DMX now flows through a
  single merge stage and one 44 Hz send loop (the old per-feature
  senders looped at 30 Hz), per docs/output-sync-plan.md: producers
  render frames with per-channel claims, the arbiter layers them
  (strict priority, dimmer-only HTP), and a grandmaster/dead-blackout
  stage caps everything post-merge. Pausing a show now holds its last
  look on the rig instead of going dark between refreshes, stopping
  returns to a continuously refreshed idle state, and the embedded
  visualizer mirrors exactly what goes on the wire, merge included.
  Timeline playback and Auto mode share one exclusive output slot:
  starting one while the other holds DMX is refused with a clear
  message instead of both blasting the rig from separate sockets, and
  Auto's universe remapping and broadcast mirror now work for every
  producer.
- **The show-directory button is gone; legacy CSV import is a File
  action.** The Structure tab's "SHOW DIRECTORY..." chip only existed
  to point at a pre-v1.0 folder of CSV songs; that is now the explicit
  File > Import Legacy CSV Songs action (pick a folder, it merges and
  reports). The directory hint still self-maintains for import/export
  dialogs and the legacy audiofiles fallback, and old configs load
  unchanged. The dead CSV auto-save/auto-load code went with it.
- **Multi-group rows wear candy stripes.** A fixture in several groups
  gets a row background of gently slanted stripes cycling through its
  groups' colours (primary first, same muted tint as the solid rows, so
  nothing gets harder to read); single-group rows keep the solid tint.
- **Multi-group fixtures work end to end.** A fixture in several groups
  shows up in each group's timeline lane, contributes its capabilities
  to every lane, appears in each group's exported channel groups and
  preset scenes, and answers every group's Live submaster. Indexed lane
  targets (Group:2) count positions within that group's own fixture
  order. The lane header's FIX count now counts distinct fixtures (a
  lane targeting two overlapping groups counted shared fixtures twice).
- **Fixtures can belong to multiple groups.** A fixture carries an
  ordered list of group memberships; the first is its primary (drives
  data colour, orientation defaults and role). Assigning a group from
  the right-click menu now ADDS the membership instead of replacing it
  (entries are checkable; clicking a checked one removes it), "Make
  primary" reorders, the inspector's combo edits the primary slot only,
  Duplicate keeps the full membership, and a new "Delete group" removes
  the membership from its fixtures without deleting them. The GROUP
  column lists all memberships (elided, full list in the tooltip). Old
  configs with the single `group` field load unchanged and re-save in
  both formats for one release; workspace export is byte-identical.
- **Shows became songs in a setlist.** What the app called a show (parts,
  BPM, audio) is now a song, and the show is the whole evening: an
  ordered setlist of songs, each entry carrying a start trigger (manual,
  MIDI PC/note, MTC or SMPTE time, or "follows automatically") and a
  pause look for after the song (blackout, warm white, hold last look,
  ambient loop). Config files write `songs` and `setlist`; older files
  with `shows` load forever and get a setlist synthesized. Editing UI
  and the trigger engine follow in later passes; workspace export is
  byte-identical.
- **The timeline knows the setlist.** Its song selector lists songs in
  setlist order as "01 · Name", with songs outside the setlist after a
  divider; reordering the setlist renumbers it. Autogen wording says
  song instead of show throughout (button, dialog, hints), with the
  German catalog updated.
- **Timeline chrome finished the v3 pass.** The parts band is a slim
  tinted region row with part names and BPM tags behind a shared PARTS
  header cell; the audio track compacts to one 44px row (filename,
  mute, volume, load beside the waveform); the playhead is one accent
  line across every track. The effect-block inspector spells out the
  selected block (bar range with the active snap, the dimmer chain,
  the actual colours as swatches with transition arrows), and the riff
  library rail gained a Scenes section from the shared scene library
  (drag arrives with the cross-lane drop pass).
- **Timeline blocks read like clips, not debug output.** Blocks are
  tinted in their part's colour (group colour when they cross parts) at
  a muted alpha, carry a header strip with the block name and its bar
  range (BARS 3-5), and render each sub-lane as a labelled segment:
  effect + rate (PULSE 1/2), colour with the real gradient painted
  (COL #E17126 -> MAGENTA), movement shapes, honest specials; empty
  rows show a quiet placeholder. The selected block gets an accent
  border, glow and a check; labels elide instead of painting outside
  narrow blocks.
- **The Structure tab inspector edits triggers and pause looks.** For
  the open song's setlist entry: a start-trigger selector across all
  six modes (manual, MIDI PC, MIDI note with note names, MTC, SMPTE,
  follow) with per-mode value editors and timecode validation, a
  disabled LEARN chip until the v1.7 sync engine, and an after-the-song
  pause-look editor (mode, warm-white level, until trigger or a
  duration). Edits update the setlist rail live. The audio-analysis
  rows became real bars fed by the autogen report (session-only), with
  an honest empty state before a run.
- **The Structure tab centre is a song editor.** The open song's name
  heads the page with a BPM · signature · bars · duration line and
  rename/delete chips; part cards are tinted in their part colour with
  the selected card checked; the transition between parts is an inline
  chip menu; the master grid gained a header column (MASTER · N BARS,
  AUDIO + file + load) and a compact transport beneath. The legacy
  show/trigger/pause-show rows are gone - song creation lives in the
  setlist rail, triggers and pause looks on the setlist entries.
- **The Structure tab grew a setlist rail.** A left rail lists the
  setlist: numbered song cards with duration, colour edge and the
  song's start trigger (MIDI PC/note with channel, timecode, "Follows
  automatically" or manual), the open song marked, pause looks shown
  between songs, drag to reorder, a + SONG tile that also adds the
  setlist entry, and a sync-mode selector (MIDI · MTC · SMPTE ·
  MANUAL). Songs outside the setlist list separately as unlisted.
  Trigger and pause-look editing arrives with the inspector pass; the
  engine that obeys them is the v1.7 sync work.
- **One compact timeline toolbar.** Song selector, lane/autogen/inspector
  actions, the transport with a bar-based readout (BAR n.m · mm:ss.s),
  the grid segment, snap, swing and save all live in a single row, with
  the position and zoom sliders on a slim strip directly beneath. The
  separate transport bar row is gone.
- **Timeline lane headers carry everything.** Each light lane's header
  column (now 260px, shared across all track types so the canvases stay
  aligned) shows the group-coloured edge, the lane name with a fixture
  count, a compact chip row (M · S · TARGETS · + BLOCK) and the
  dimmer/colour/movement/special sub-lane labels aligned to their rows.
  The labels are no longer painted on the canvas; the Settings toggle
  now shows/hides them in the header.
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

[Unreleased]: https://github.com/varghele/dielichtmaschine/compare/v1.4.0...HEAD
[1.4.0]: https://github.com/varghele/dielichtmaschine/releases/tag/v1.4.0
[1.0.0]: https://github.com/varghele/dielichtmaschine/releases/tag/v1.0.0
[0.9.5-beta]: https://github.com/varghele/dielichtmaschine/releases/tag/v0.9.5-beta
[0.9.0-beta]: https://github.com/varghele/dielichtmaschine/releases/tag/v0.9.0-beta
[0.1.0-alpha]: https://github.com/varghele/dielichtmaschine/releases/tag/v0.1.0-alpha
