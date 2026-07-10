# Timeline v3: visual pass against screen 06b

Reference: `design_handoff_lichtmaschine_app/screens/06b-show-timeline-v3.html`
(1920x900). The screen's own footer names the deltas versus the current
tab: block tint = muted part/group colour instead of full saturation,
sub-lane labels aligned in the lane header, compact grid bar, scenes
droppable across multiple lanes. This pass is mostly visual; the two
functional items hiding in the mock are explicitly deferred (see
"Deferred" below).

Decisions locked 2026-07-09: runs in parallel with the setlist track
(`docs/setlist-plan.md`); no Bibliothek section this pass.

## Stage T1 - one compact toolbar row

The mock collapses show combo, lane/autogen buttons, transport, grid,
snap, swing, zoom and save into a single 44px row.

- Merge the transport bar (currently `insertWidget(1, ...)`, its own row)
  into the main toolbar: play/stop compact (24px accent square in the
  mock), BAR readout inline.
- SONG selector replaces the SHOW combo label (bordered mono chip,
  "02 · MONSTERS"). Setlist numbering itself arrives with track S3;
  until then the chip shows the plain song name.
- SWING becomes a percentage dropdown ("SWING 0% ▾", 0 / 25 / 50 / 75 /
  100) instead of the on/off toggle. 0% = off; 100% = the current full
  triplet feel; intermediate values interpolate the off-beat shift.
  Small functional addition to the grid math (swing amount was
  boolean); per-lane snap unchanged.
- GRID segment styles as one bordered group (4 2 1 1/2 1/4 1/8 1/16),
  active cell accent-filled; SNAP as accent-tinted chip.
- Files: `gui/tabs/shows_tab.py`, `timeline_ui/timeline_grid.py` (swing
  amount), goldens `shows_toolbar_dark` + a swing unit test.

## Stage T2 - lane headers carry everything (260px)

- Header column widens to 260px with a 3px group-colour left edge.
- Row 1: group name in condensed caps + "N FIX" count right-aligned.
- Row 2: chip row M · S · TARGETS ▾ · + BLOCK (the targets combo becomes
  a dropdown chip; add-block becomes a chip).
- The DIM / COL / MOV / SPC sub-lane labels move INTO the header column,
  vertically aligned with their sub-rows in the canvas. The in-canvas
  painted labels (restyled + toggleable earlier) are removed; the
  Settings toggle "Show timeline sub-lane labels" now controls the
  header labels instead (kept, defaults on).
- Files: `timeline_ui/light_lane_widget.py`, `timeline_ui/timeline_widget.py`
  (remove `draw_sublane_labels` canvas path), `gui/gui.py` (setting
  passthrough unchanged), golden `timeline_lane_dark`.

## Stage T3 - block restyle

- Block body tint: the part or group colour at low alpha (the mock uses
  ~0.07-0.08 background + stronger 0.2 header strip), not the current
  full-saturation fills.
- 16px block header strip: block label left ("BASE · PULSE"), bar range
  right ("BARS 3-8").
- Sub-rows render as labelled segments in compact mono ("PULSE 1/2",
  "FADE 208", "COL #E17126 -> MAGENTA" with the gradient painted,
  "MOV · FIGURE-8"); empty sub-rows show a quiet "- · -" placeholder
  instead of an empty band.
- Selected block: accent 1.5px border + soft accent glow + check in the
  header strip.
- Files: `timeline_ui/light_block_widget.py` (paint),
  `timeline_ui/timeline_widget.py`, golden regen, unit tests on the
  label composition helpers (no styleSheet asserts).

## Stage T4 - parts band, audio row, playhead

- Parts band (26px): header cell "PARTS", regions tinted in part colour
  at 0.2 alpha with condensed part name + small BPM tag.
- Audio row compacts to 44px: header cell holds "AUDIO" + filename ·
  M · volume as one mono line (mute/volume live in a popover or stay as
  tiny chips; keep function, shrink chrome).
- Playhead: 2px accent line across all lanes.
- Files: `timeline_ui/master_timeline_widget.py`,
  `timeline_ui/audio_lane_widget.py`, goldens.

## Stage T5 - right rail: block inspector + scenes in the library

- EFFEKT-BLOCK inspector panel gets the mock's field rows: RANGE
  (bar span + snap), DIM (effect chain), COL (painted colour chips with
  an arrow), OVERLAP row (display-only until v1.6, see Deferred).
- The library rail gains a SZENEN/SCENES category rendered from the
  shared `SceneLibrary` (built for the Live tab), below the riff
  categories. Display + drag source only this pass.
- Files: `gui/tabs/shows_tab.py` (inspector panel),
  `timeline_ui/riff_browser_widget.py` (scenes section), goldens.

## Deferred (recorded, not this pass)

- **Overlap crossfade** ("OVERLAP: XFADE · 1 BAR ▾"): the roadmap's
  v1.6 "implicit crossfade on overlap" item; the chip is its UI
  surface. Until the crossfade semantics + export interpolation land,
  we do not render a fake chip.
- **Scenes dropping across multiple lanes**: needs the capability
  mapping pass (shared with morph); the scenes section lists and drags
  to a single lane only when the drop handler lands, and is inert until
  then (clearly marked).
- **Song numbering in the selector**: arrives with the setlist model
  (track S3 in `docs/setlist-plan.md`).

Each stage is one commit with tests + regenerated goldens; per-glyph
clipping check on every golden before commit (bounced once on the Live
tab pass; the check is not optional).

## Status (2026-07-10): ALL STAGES SHIPPED

T1 bbac5e7 (compact toolbar + percentage swing), T2 44cee4d (lane
headers, + lane-chip role 4a3d232), T3 bc17eba (tinted clip blocks),
T4+T5 70005b0 (parts band, compact audio row, accent playhead, block
inspector rows, scenes section in the library rail). The deferred
items above (overlap crossfade -> v1.6, cross-lane scene drop, song
numbering -> landed via setlist S3 f06bb8a) remain the open tail.
