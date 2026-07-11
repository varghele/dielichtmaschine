# Computed position presets: plan + handoff

Decided 2026-07-11 in discussion. SHIPPED 2026-07-11 (the background
agent from the earlier session never landed its work; a fresh session
re-implemented from this spec). Files: utils/position_presets.py,
gui/tabs/live_tab.py, tests/unit/test_position_presets.py,
tests/unit/test_live_tab.py, tests/visual/test_live_tab_golden.py +
win32 golden. One interpretation call: CROSS's near-centre rule reads
"x_target = 1.5"; implemented as a 1.5 m throw to the OPPOSITE side
(sign(0) = +1 counts as stage right, so x = 0 targets -1.5) because
the stated intent is "so the beam still crosses".

## The idea

The Live tab's POSITION pool lists the stage's spike marks
(config.spots) as selectable palettes (committed 31b4980). The old
placeholder presets (CENTRE, AUDIENCE, CROSS, FAN OUT, CEILING, DRUMS)
were removed as fakes - but the CONCEPTS are good and the program can
compute most of them from the stage setup it already knows (stage
dims, mover positions/orientations, layers, placed stage elements).

## Classification (what is computable, and how)

Point targets (all beams converge on one derived point):

| Preset | Rule (stage space: X centered, Y depth centered with negative = front/audience, Z height, meters) |
|---|---|
| CENTRE | (0, 0, 1.5) - centre stage at focus height |
| AUDIENCE | (0, -(D/2 + 3.0), 2.0) - past the downstage edge, head height |
| DRUMS / KEYS / FOH / MIC | centre of a PLACED stage element of that kind (utils/stage_element_catalog.py kinds: drum-riser, keys, foh, mic-stand), z = element layer height + 1.2 else 1.2; one preset per matching element, duplicate kinds suffixed ("DRUMS 2") |

Per-fixture patterns (each mover derives its own target from its own
position):

| Preset | Rule |
|---|---|
| CROSS | target = (-fixture.x, min(fixture.y, 0), 0.5) - beams scissor across the centreline; near-centre fixtures (abs x < 0.3) use x_target = 1.5 so the beam still crosses |
| FAN OUT | (sign(x) * (W/2 + 2.0), fixture.y, 4.0), sign(0) = +1 - outward past the edges, raised |
| CEILING | (fixture.x, fixture.y, fixture.z + 10.0) - straight up |

## Locked decisions

- All five geometry presets + element-derived targets (user choice).
- Pool layout: TWO SUBSECTIONS - "PRESETS" caption + grid on top,
  "MARKS" caption + the spike-mark grid below; movers-only gating
  covers both; the marks empty-state stays under MARKS.
- Position state gets NAMESPACED ids now ("preset:centre",
  "preset:element:<id>", "mark:<spot name>") - the mark-only ids from
  31b4980 are one day old, so migrate rather than accrete. Programmer
  bar shows the LABEL ("POS: CROSS").
- Pruning: marks pruned when their spot disappears (as shipped),
  element presets pruned when their element disappears, geometry
  presets never pruned.
- Honest scoping: presets carry COMPUTED TARGET DATA from day one
  (utils/position_presets.py, pure + testable), but no pan/tilt math -
  converting a target into per-fixture pan/tilt is the v1.5a
  focus-geometry milestone, and making light move is the output
  arbiter (todo.md). Same in-memory honesty as the whole Live surface.

## Architecture

- NEW utils/position_presets.py: PositionPreset dataclass (preset_id,
  label, kind point|pattern, tag, target_for(fixture) -> (x,y,z)),
  compute_presets(config) in deterministic order (five geometry, then
  element presets in config.stage_elements order). All magic numbers
  are named constants. COORDINATE FRAME WARNING: use the config/stage
  frame (Y centered, negative = front); do NOT mix in
  autogen/spatial.py's 0..D depth convention (CLAUDE.md gotcha).
- gui/tabs/live_tab.py: pool rebuild renders presets + marks with the
  two captions; rebuild fingerprint includes spots AND relevant
  element ids/kinds; LiveState pruning per the rules above.

## Session handoff state (2026-07-11)

A background agent was implementing exactly the above when the session
stopped. Expected working-tree footprint (unstaged if it finished
after the session ended): utils/position_presets.py (new),
gui/tabs/live_tab.py, tests/unit/test_position_presets.py (new),
tests/unit/test_live_tab.py, tests/visual/test_live_tab_golden.py,
tests/visual/goldens/win32/live_tab_dark.png.

To resume:
1. `git status` - if those files are modified/present, the agent
   likely finished; if the tree is clean apart from the untracked
   screenshots/ dir (user files - never delete), it did not, and this
   plan is the spec to re-run.
2. Verify before committing (the standing gauntlet): run
   `QT_QPA_PLATFORM=offscreen python -m pytest tests/unit/test_position_presets.py tests/unit/test_live_tab.py tests/visual/test_live_tab_golden.py -q`,
   then full `pytest tests/unit -n auto -q` (suite was FULLY GREEN at
   HEAD ec35dab..31b4980 era - any failure belongs to this change),
   visual + e2e serial, and READ the regenerated live_tab_dark golden
   at magnification: PRESETS caption + CENTRE/AUDIENCE/CROSS(active)/
   FAN OUT/CEILING/DRUMS cells with tags, MARKS caption + DS CENTRE/
   DRUM RISER/SL SOLO, programmer bar "... · POS: CROSS", nothing
   clipped in the fifth column.
3. Commit (as varghele, one-line conventional, explicit paths) with a
   CHANGELOG entry under [Unreleased] Added/Changed, e.g. "Computed
   position presets return to the Live pool: CENTRE/AUDIENCE/CROSS/
   FAN OUT/CEILING from stage geometry plus targets for placed stage
   elements (drum riser and friends), above the spike marks."
4. Related follow-ups already tracked elsewhere: v1.5a consumes the
   targets (focus geometry), the output arbiter makes them move
   (todo.md), Live plan stages for picker/REC remain open
   (docs/live-tab-plan.md).
