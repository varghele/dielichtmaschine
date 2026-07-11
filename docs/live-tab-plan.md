# Live tab (3b): build-out plan

The first pass (`gui/tabs/live_tab.py`, golden `live_tab_dark`) is a
simplified shell: group SELECT tiles, one generic palette grid, a single
master, strobe, fade, blackout. The North Star
(`design_handoff_lichtmaschine_app/screens/09-live-3b-palette.html`) is a
full busking surface. This plan closes the gap; still UI-over-state (no
DMX output yet), but the state model grows to support real output later.

## What the North Star actually has

Top: a SELECT row (group tiles + ALL + ODD/EVEN + CLEAR SEL) and a FADE
row (SNAP / 0.5s / 2s / 4s / 1 BAR / 4 BARS - "touch a palette, selection
fades to it over this time").

Centre - three distinct palette POOLS in a grid, not one list:
1. **COLOUR PALETTES** - a grid of colour swatches painted in the actual
   colour with a small name (WHITE, AMBER, RED, MAGENTA, CYAN, BLUE,
   GREEN, plus split/gradient swatches RED/CYAN SPLIT, MAG/AMBER), the
   active one outlined in accent (RED with a check). Plus a SONG PALETTE
   link, a colour PICKER (conic-gradient wheel), and a "+ REC" to capture
   the current look as a palette.
2. **POSITION PALETTES** (+ MOVEMENT SHAPES) - named position presets
   (CENTRE, CROSS, FAN OUT, CEILING, DRUMS) + a P/T pad, headed "APPLIES
   TO: MOVERS"; below, a MOVEMENT SHAPES row (OFF / CIRCLE / FIG-8 /
   SWEEP / SIZE). Only movers get these.
3. **RUDIMENTS · INTENSITY FX** - STATIC / PULSE / WAVE / SPARKLE /
   STROBE / PING-PONG / WATERFALL / CASCADE, with a RATE control; cells
   that need pixel/cell fixtures grey out with "NEEDS CELLS" when the
   selection cannot run them.

A PROGRAMMER state bar spells out the current live look: "PROGRAMMER:
FRONT PARS + MOVERS · RED · AUDIENCE · CIRCLE · CHASE 1/4".

Right column (330px): an ACTIVE PLAYBACKS list (the running show cue +
any busk stacks, each with PAUSE / KILL), STROBE KILL / HOLD LOOK /
RELEASE ALL, a **GRAND**master fader and a **SUB** fader, and a big red
**DBO** (dead blackout).

Bottom (170px) - the fader bank: one **submaster** per group (FRONT PARS,
REAR WASH, MOVERS, PIXEL BAR, SUNSTRIP), each a vertical fader in the
group colour with a **FLASH** button, plus FX SPEED / FX SIZE (TAP,
RESET), STROBE RATE, WHITE WASH flash, and empty "+ ASSIGN" playback
slots.

## The gaps you flagged, mapped to the reference

- **"Colour palettes not clearly marked"** - we render generic cells.
  Needs the COLOUR PALETTES pool of real colour swatches (pool 1).
- **"No movement palettes"** - we have none. Needs the POSITION PALETTES
  + MOVEMENT SHAPES pool, scoped to movers (pool 2).
- **"No submasters"** - we have none. Needs the bottom per-group
  submaster fader bank with flash.
- **"No grandmaster for all groups"** - our single MASTER is not framed
  as a grandmaster. Needs an explicit GRAND (all groups) plus the SUB.

Also missing but part of the surface: the intensity-FX pool as its own
category, the PROGRAMMER state bar, active playbacks, RELEASE ALL / HOLD
LOOK / DBO, the colour PICKER and "+ REC".

## State model growth (`LiveState`)

Today: `selected`, `group_palettes`, `master`, `blackout`, `strobe`,
`fade_seconds`. Grow to:

- `submasters: dict[group -> 0..100]` and `grandmaster: 0..100` (output
  scale = grand * sub per group).
- Per-selection palette state split by category: `colour` (a palette id
  or an rgb), `position`, `movement_shape`, `intensity_fx` (+ its rate).
  Applied to the current selection with the fade time.
- `flash: set[group]` (momentary), `held_look` (bool).
- `playbacks: list` (the running show cue + busk stacks) - display-only
  until the engine pass; keep it a simple list of records.
- Signals stay one `state_changed`; add helpers so a future ArtNet pass
  reads a resolved per-fixture output.

## Deliberate deviations (honest, per project convention)

- **No live output this pass** - everything still mutates state; the
  ArtNet resolve is a later milestone. State is shaped so that resolve is
  a pure function of `LiveState` + the fixture patch.
- **Active playbacks stay display-only** until the show-link pass; render
  the running-show row from the Shows tab state if available, else
  "NOTHING ELSE RUNNING".
- **Palette contents are seeded, not authored** - ship a sensible default
  colour/position/movement/FX set; "+ REC" and the picker can come after
  (mark them clearly, do not fake capture).
- **Capability gating is honest** - grey a pool/cell that the current
  selection cannot run (movement only for movers; cell FX only for
  pixel/cell fixtures), matching the reference's "NEEDS CELLS" / "APPLIES
  TO: MOVERS".

## Suggested staging (each its own commit + golden)

1. **Layout skeleton** - restructure into top rows + 3-pool centre grid +
   right master column + bottom submaster bank. Regenerate `live_tab_dark`.
2. **Colour palettes pool** - real colour swatches, selection outline,
   apply-to-selection with fade; PROGRAMMER bar shows the colour.
3. **Submaster bank + GRAND/SUB** - per-group vertical faders with flash,
   grandmaster + sub, output scale = grand * sub in state; DBO.
4. **Position + movement pool** - movers-only, capability-gated.
5. **Intensity-FX pool** - with rate + cell-fixture gating.
6. **Right column extras** - RELEASE ALL / HOLD LOOK / STROBE KILL, and
   the active-playbacks list (display-only).
7. **Picker + REC** - colour picker and palette capture (optional, later).

Stages 1-3 cover everything you called out (colour marking, submasters,
grandmaster); 4-5 add the movement and FX pools; 6-7 finish the surface.

Stages 1-3 are DONE (commits through c3a732a): colour swatches, per-group
submasters, grandmaster-as-first-bank-fader + DBO.

## Requested additions (round 2, decisions locked)

New asks and their decided shape:

- **BPM + TAP** - reuse `auto/bpm_detector.py::TapBPM` (`tap()` returns the
  running estimate, `reset()` clears). A tempo cluster: a BPM readout + a
  TAP button (and a reset). This tempo is the reference for rate-based
  controls (strobe rate, the rudiment "1/4" etc.). When a show is running
  underneath (see mode), sync to the show BPM; free-busk uses the tap.
- **Effect palette = the Riff library.** A `Riff` already is "a reusable
  pattern of sublane blocks", so the EFFECTS pool lists riffs from the
  shared `RiffLibrary` (the same catalog the riff browser shows). "Customize
  from the library" is exactly this.
- **Scenes palette = a new scene library** (parallel to riffs), predefined
  and populated later. A `Scene` is a static look; the palette lists scenes
  from a `SceneLibrary`. For now the pool renders from the (possibly empty /
  seeded) library and is clearly marked when empty - no live capture yet.
- **Queue = both** a running-playbacks stack AND a preloaded next-up list.
  The right column's ACTIVE PLAYBACKS is the running stack (each pausable /
  killable); a NEXT-UP list holds items you staged with "add to queue";
  firing moves an item next-up -> running. Scenes/effects/palettes can be
  fired live or added to next-up.
- **Show-vs-live selector = busk-on-top.** The surface is ALWAYS live; a
  SHOW / LIVE toggle says whether a predefined show also runs underneath.
  In SHOW mode the running-show cue appears in ACTIVE PLAYBACKS and the
  live controls layer over it (merge). In LIVE mode there is no show
  underneath. (The actual merge is the engine pass; here it is state +
  the playbacks display.)

### Layout placement (proposed)

- Top strip: the SHOW / LIVE mode toggle (segment) on the left near SELECT;
  the BPM readout + TAP on the right of the FADE row.
- Centre pools: FIVE narrower columns side by side (decided) - COLOUR ·
  POSITION · INTENSITY-FX · EFFECTS · SCENES - each column thinner so all
  are visible at once.
- **Effects vs scenes scope (decided):** an EFFECT is a riff, applied to
  the current selection / group (per-group pattern). A SCENE is a look
  that spans MULTIPLE fixture groups - a full-rig snapshot across groups,
  not tied to the current selection. So the effects pool respects the
  SELECT state; the scenes pool fires a whole-rig look regardless of
  selection.
- Right column: ACTIVE PLAYBACKS becomes the running stack; a NEXT-UP
  section below it for the queued items, with the GO / add-to-queue wiring.

### Revised staging for the additions (each its own commit + golden)

A. BPM + TAP cluster + the SHOW/LIVE mode toggle (state + display; reuse
   TapBPM). No centre-layout change.
B. Effects pool wired to the shared RiffLibrary (+ the pool-selector if we
   go that route).
C. Scenes pool + a `SceneLibrary` model (empty/seeded, predefined later).
D. Queue: running stack + next-up list + add-to-queue / GO wiring in state.
E. (later) engine resolve so busk-on-top actually merges over the show.

`LiveState` grows: `bpm`, `mode` ("show"/"live"), `running` (list),
`next_up` (list), `effect`/`scene` per selection. Still one
`state_changed`; still no DMX this round.

Stages 1-3 done. Round 2: A done (e3487e4, tempo cluster + SHOW/LIVE
toggle), B+C done (8411222, five-column centre with the effects pool on
RiffLibrary and the scenes pool on the new SceneLibrary), D done
(07ceb13, running stack + QUEUE latch + NEXT UP + GO). E done for the
programmer surface (f10cceb, output-sync plan phase 3: colours,
submasters, flash, strobe and GM/DBO render through the arbiter's
LIVE layer, busk-on-top over the running playback with RELEASE ALL
fall-through; utils/artnet/live_layer.py + tests/unit/
test_live_busk_layer.py). Still open: playing the staged
effects/scenes needs the v1.7 engine, plus original stages 4-7
(position + intensity wiring, picker, REC) and predefined scene
content for the library.
