# Live tab: full working order - implementation plan

Signed off 2026-07-13. Goal: every surface on the Live busking tab
produces real light through the busk layer / output arbiter, or is
consciously deferred. Out of scope by decision: MIDI mapping (v1.8),
OSC (v1.8), timecode/show-clock sync (LTC v1.5a, MTC v1.7), setlist
runner (v1.7).

Already live (pre-plan): grandmaster/submasters/FLASH/DBO, colour
swatches (bug pending, phase 0), strobe, position palettes
(hardware-verified 2026-07-13).

## Architecture decision: one synthetic-lane engine for everything

The playback stack already evaluates every block type we need:
`DMXManager.update_dmx(t)` renders lanes (dimmer / colour / movement /
special blocks, including all 11 movement rudiments in
`effects/movement_effects.MOVEMENT_REGISTRY`: static, circle, diamond,
square, triangle, figure_8, lissajous, random, bounce, linear_sweep,
fan) into per-universe `(values, mask)` frames via `get_frame`.

The live engine therefore does NOT reimplement effects. It owns a
PRIVATE DMXManager fed with SYNTHETIC lanes built from the staged
library items, driven by a looping beat clock:

- virtual time `t = ((now - staged_at) * bpm / 60) mod loop_beats`,
  converted back to seconds for `update_dmx` through a synthetic
  one-part SongStructure at `LiveState.bpm` (rebuilt when TAP changes
  the tempo).
- the resulting frames merge INTO the busk layer's own frame BELOW the
  explicit busk writes (a touched colour swatch beats a running riff's
  colour for that group), and the whole layer stays busk-on-top in the
  arbiter as today.
- the private manager must NOT emit its safe-idle floor (it claims
  wheel/shutter channels for every fixture): add an opt-out flag to
  DMXManager (`emit_safe_idle=False`) - the arbiter's real floor
  already covers idle policy.

This one engine powers phases 3, 4 and 5.

## Phases

### Phase 0 - colour swatch bug (diagnose first, on the wire)

User report: swatches currently produce no light. Suspects, in order:
(a) colours are selection-scoped - no selected group means a silent
no-op (a UX bug of its own); (b) a regression from the 2026-07-13
arbiter work (fixture-map registration, loopback mirror, hardware yoke
pass). Diagnose live against the bench rig; fix what falls out. Either
way: touching a palette with nothing selected must give visible
feedback (statusbar hint or a brief pool flash), not silence.
Tests: regression pin for the root cause; unit test for the
no-selection feedback path.
**Hardware checkpoint: user confirms swatches light the rig.**

### Phase 1 - scenes pool makes light

`Scene` = colour + group list. The busk layer renders the active scene
(`LiveState.scene`) by applying `scene.color` (hex -> RGB) to
`scene.groups`, selection-independent, under the same
grandmaster/submaster/strobe treatment as swatch colours - and BELOW
them in priority (an explicit swatch on a group overrides the scene on
that group). Second touch releases (already the state contract).
Remove the "actual output arrives later" markers.
Tests: extend `test_live_busk_layer.py` (scene claims per group,
priority vs swatch, release = fall-through, hex parsing).
**Hardware checkpoint: user busks a scene.**

### Phase 2 - the live engine (infrastructure, no UI change)

`utils/artnet/live_engine.py`: the private-DMXManager wrapper above.
API sketch:

    engine = LiveEngine(config_provider, fixture_maps_provider)
    engine.stage(slot, lanes, loop_beats, bpm)   # slot: "effect" | "intensity" | "movement"
    engine.set_bpm(bpm); engine.pause(slot); engine.kill(slot)
    engine.render(now) -> Frame                  # merged sub-frame per slot

Slots run concurrently (one riff + one intensity FX + one movement
shape). DMXManager grows the `emit_safe_idle=False` flag (default True,
playback unchanged - byte-identical export untouched since export never
constructs DMXManager).
Tests: pure - stage a synthetic dimmer-pulse lane, tick at known times,
assert values/mask loop at the right beat rate; bpm change rescales;
pause freezes the frame; kill drops the claims; safe-idle suppressed.

### Phase 3 - effects pool plays riffs

Staging a riff (`LiveState.effect`) builds synthetic lanes via
`Riff.to_light_block(0, synthetic_structure)` - one lane per SELECTED
group (riff scoping rule) - and stages them in the engine's "effect"
slot, looping every `riff.length_beats`. Restage on selection change;
release on second touch (state contract already). Queue: GO promotes a
next-up record into the slot; pause row freezes the slot's clock; kill
clears it (state machinery exists, gains real consequences).
Tests: busk-layer frames show the riff's dimmer/colour pattern moving
over ticks on exactly the selected groups' channels; queue GO/pause/
kill against the engine; selection rescope.
**Hardware checkpoint: user fires a riff at the bench rig on TAP tempo.**

### Phase 4 - movement shapes pool aims real shapes

The placeholder MOVEMENT SHAPES cells become the 11 registry rudiments
(minus `static`, which the position palettes already cover - 10 cells).
Staging a shape builds, per selected mover group, a synthetic lane with
one MovementBlock (`effect_type` = the rudiment) anchored at the
group's HELD POSITION target (falling back to the CENTRE preset), via a
transient spot injected into the private manager's config view - the
spot-targeting path then resolves per-fixture pan/tilt through the
verified solver + output yoke conversion. Amplitude/speed defaults from
the block's own defaults; speed follows LiveState.bpm.
Claims pan/tilt(+fines) only, like the position palettes - shapes can
run dark. Held positions and shapes compose: position sets the anchor,
shape orbits it.
Tests: engine frame pan/tilt values trace the expected shape over a
cycle (reuse the movement-effects math as oracle); anchor follows the
held position; release restores fall-through.
**Hardware checkpoint: user runs CIRCLE on the hung mover.**

### Phase 5 - intensity FX pool subsumed as curated dimmer riffs

Ship a small bundled set of dimmer-only riffs (`riffs/intensity/`:
pulse, wave, strobe-burst, heartbeat, chase, sparkle - straight from
the existing dimmer effect types). The INTENSITY FX pool lists that
category and stages into the engine's "intensity" slot (concurrent
with the effect slot, dimmer sublanes only by construction).
Tests: pool population from the category; concurrent effect+intensity
slots merge (intensity dimmer + effect colour coexist).

## Sequencing and checkpoints

0 -> 1 ship together (small); 2 is pure infrastructure; 3, 4, 5 ride on
2 and can land in any order (3 first - it makes the queue real).
Hardware checkpoints after 0/1, 3, and 4 - the bench rig is set up.

## Status

- [x] Phase 0 - swatch bug + no-selection feedback. Root cause found in
  code review before the bench even fired: the busk layer only wrote
  RGB/CMY emitter channels, and the bench rig's Hero Spot 60 has NONE -
  it is a colour-wheel fixture, so a swatch opened dimmer + shutter
  (white at best) and could never show a colour. The layer now steers
  color_wheel_channels via the shared rgb_to_color_wheel mapping
  (extracted to module level in utils/artnet/dmx_manager.py; playback
  behaviour unchanged), guarded on RGB-channel absence - the guard
  matters because group "Colour" RGB channels also bucket into
  color_wheel_channels (the get_channels_by_property quirk). Palettes
  touched with no selection flash NO GROUP SELECTED in the programmer
  bar (stage_colour/stage_position now return the applied count).
  Tests: TestWheelOnlyFixtures in test_live_busk_layer.py,
  TestNoSelectionFeedback in test_live_tab.py. Hardware checkpoint
  pending: user confirms swatches light the rig in colour.
- [x] Phase 1 - scenes -> light. LiveBuskLayer gained a scene_provider
  (gui.py injects LiveTab.scene_for_key); the active scene claims its
  listed groups like an applied colour, selection-independent, below
  explicit swatches, same level/strobe resolve. Stale "no output
  engine" markers removed from tooltips and docstrings. Tests:
  TestScenePool in test_live_busk_layer.py. Hardware checkpoint
  pending: user busks a scene (needs an authored scene JSON - the
  bundled library ships empty). Bench follow-up 2026-07-13: swatches
  now RELEASE on second touch (same toggle contract as positions) -
  the user could not un-busk a colour, and a stuck swatch permanently
  outranked the scene on its group. stage_colour toggles; the
  swatch-beats-scene priority itself is unchanged.
- [x] Phase 2 - LiveEngine infrastructure (2026-07-13).
  utils/artnet/live_engine.py: LiveEngine(manager_factory) with the
  three SLOTS, per-slot private DMXManager (factory must pass the new
  emit_safe_idle=False - the flag landed on DMXManager.__init__ with
  True as the unchanged playback default), OnePartStructure for the
  constant-tempo structure, stateless per-render block scheduling
  (active sublane block per type at the looped virtual time, latest
  start wins), incremental beat clock (set_bpm rescales phase-
  continuously without restaging - blocks keep their build_bpm
  timescale), pause freezes the exact frame, kill drops claims,
  restage replaces, slot frames merge in SLOTS order (later overrides
  earlier per claimed channel). Not yet wired to any UI - phase 3
  consumes it. Tests: tests/unit/test_live_engine.py (loop rate, bpm
  rescale, claim width, pause/resume without time jump, kill, restage,
  concurrent slots, safe-idle suppression + playback default pinned).
- [x] Phase 3 - effects pool riff player + queue (2026-07-13).
  LiveEffectsBinder (utils/artnet/live_engine.py) connects
  LiveState.state_changed to the engine's "effect" slot: staging
  builds one lane per selected group via Riff.to_light_block at the
  current bpm (loop = riff.length_beats), restages on key or
  selection-scope change (loop restarts at beat 0), follows TAP bpm
  phase-continuously without restaging, maps the running record's
  paused flag onto the slot clock (engine.pause is idempotent so
  unrelated state churn cannot re-anchor the clock), and kills the
  slot on second touch / KILL row / RELEASE ALL / empty scope. GO
  (fire_next) works unchanged because it flows through set_effect.
  The busk layer takes the engine frame as its BASE and overlays its
  explicit writes (swatch beats riff per channel); with no busk
  claims the engine frame passes through. gui.py builds the engine
  with a manager factory (config + load_fixture_definitions_from_qlc,
  emit_safe_idle=False). Effects touched with no selection flash the
  programmer-bar warning and start when groups get selected. Known
  scope cuts: the soft LIVE blackout and group submasters do not
  scale a running riff (grand/DBO cap it post-merge as always) - a
  submaster-scaled engine frame needs per-group channel attribution
  and can ride a later polish pass. Tests: TestEffectsBinder +
  TestEngineUnderBuskLayer in test_live_engine.py.
  **Hardware checkpoint pending: user fires a riff at the bench rig
  on TAP tempo.**
- [ ] Phase 4 - movement shapes pool
- [ ] Phase 5 - intensity FX as bundled riffs
