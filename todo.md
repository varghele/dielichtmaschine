# TODO: working agenda

The output + synchronisation architecture discussion happened on
2026-07-11 and was promoted to **docs/output-sync-plan.md** (arbiter
layers + masks, merge rules, exclusive playback slot, idle-floor
policy, conductor clock, phased build with tests). That file is now
the source of truth; the notes that used to live here are folded in.

2026-07-12: the Live POSITION pool was pulled forward from v1.5a/v1.8
and SHIPPED with a per-group policy (each selected group takes the
touched position, others keep theirs; second touch releases) - see
docs/position-presets-plan.md UPDATE and the ROADMAP v1.8 palette
item. In trade, GDTF Share Phase 4 (in-app login) is deferred; it
stays in ROADMAP v1.2 (unblocked since the configurable library paths
shipped later the same day). Next Live
gaps by leverage: scenes pool -> light, effects pool -> light (needs a
clock-driven riff player in the live layer).

## Pull-in candidates (roadmap items that fit the current polish phase)

Discuss before pulling any of these in - order is by leverage:

- [x] **Headless export CLI** (v1.3): done 2026-07-12 -
      `python main.py export config.yaml --out x.qxw --qlc-version
      5.2.1`, dispatched before any Qt import (utils/export_cli.py).
- [x] **Configurable fixture library paths** (v1.2): done 2026-07-12 -
      Settings > Fixture Libraries..., user-gdtf/user-qxf sources in
      fixture_search_dirs(), app-data defaults, cache invalidation on
      change. GDTF Share Phase 4 is now unblocked.
- [x] **`.lms` project extension** (v1.3): done 2026-07-12 - native
      `.lms` (app_identity PROJECT_EXT + filters + ensure_project_ext),
      Save/Save As/New-from-Template default to it, open accepts
      `.lms`+legacy `.yaml`/`.yml`, explicit `.yaml` respected, format
      is unchanged YAML (byte-identical across extensions). main.py
      opens a CLI/double-click path via open_project_on_launch. OS
      file-association registration needs an installer (noted in the
      spec) - the only follow-up. 17 unit + 3 e2e tests.
- [x] **Fixtures table delegate editing** (v1.3): dropped - obsoleted by
      the North Star rebuild of the Fixtures tab (read-only table +
      inspector editing, no cell widgets). Experiment files deleted,
      qt-gotchas #3 + ROADMAP updated 2026-07-12.
- [x] **Riff tagging + search** (v1.3): done 2026-07-13 - the model and
      library search already knew tags; added the missing UI (tags line
      on the riff card, right-click Edit Tags with parse_tags cleanup,
      #tag search scoped to tags only). Favourites pin folded into the
      Library topbar roadmap item.

Deliberately NOT pulled: Library topbar section (wants a Bibliothek
screen design first), timeline undo/redo (big), MVR/OSC (own tracks).

## Before the backend build (user)

- [ ] Tab polish pass on the individual tabs (in progress, user-led)
- [x] Discuss the output/sync logic - done 2026-07-11, decisions in
      docs/output-sync-plan.md
- [x] Promote to docs/output-sync-plan.md with phases + tests
- [x] Build phases 0-3 - done 2026-07-11/12, hashes in the plan doc;
      phase 4 (conductor, pause look, setlist runner) stays v1.7

## RESOLVED: the pan/tilt yoke model (hardware-verified 2026-07-13)

**Full write-up: `docs/coordinate-frames-and-orientation.md` (section 4).**

Closed on the bench with a real Hero Spot 60: mounting presets restored
to body-orientation values; the two-yoke translation
(solver_to_gdtf_axes) runs in the renderer AND on the wire (output
arbiter, utils/yoke); one measured correction (positive physical
pan/tilt is opposite-handed about the GDTF axes, negated in
DrawItem.compose). Three raw poses + four full-pipeline aim targets all
landed, standing and hanging. Follow-ups shipped same day: all four
wall presets unswapped (migration heals), .qxf movers get the synthetic
standard yoke (fixture_yoke), and the .qxw export aims like native
output (export_aim_dmx: real ranges + conversion in spot targets,
preset scenes, VC XY-pads). Last remaining sliver (v1.5a): animated
movement PATTERNS in the export still oscillate in solver DMX space
around the converted centre (per-step conversion), and per-fixture
DMX-direction invert flags for movers whose hardware runs opposite.

The solver and the renderer both model a mover as: beam along local
+X, PAN about local Z, TILT about local Y. In that model the beam at
tilt=0 is always PERPENDICULAR to the pan axis. With the canonical
`hanging` preset (roll -90, beam down at home) the pan axis therefore
comes out HORIZONTAL - but a real hanging moving head pans about a
VERTICAL axis, and at mid-tilt its beam points roughly horizontally,
not straight down.

Consequence if real fixtures follow the usual convention: the pan/tilt
DMX we emit aims correctly *in the app* but not on the rig. Worked
example - a hanging mover 5 m up, target 2 m to +X: we emit pan 21.8
deg, tilt 0. A real mover at tilt 0 (straight down) would ignore pan
entirely and stay pointing down.

Deeper cause: the beam's local direction is hard-coded to +X for every
fixture, but a PAR's emission is fixed to its body while a mover's is
articulated off its base axis. One (yaw, pitch, roll) cannot make a
hanging PAR point down AND give a hanging mover a vertical pan axis.
The beam/base axes likely need to come from the fixture definition
(GDTF carries the geometry tree for exactly this).

- [ ] Settle with hardware: patch one mover, aim it at a spike mark,
      compare the rig against the visualizer. If they disagree, model
      the yoke properly (pan about the mount's base axis; per-fixture
      tilt-centre convention) rather than patching signs.

## Pending manual verification (user, needs hardware/desktop)

- [ ] QLC+ export aim check: export tester.lms (or any mover project)
      to .qxw, open in QLC+, fire a position preset from the Virtual
      Console at the hung head - the beam should land where
      Lichtmaschine lands it (the export now goes through
      utils/yoke.export_aim_dmx: real ranges + the hardware-verified
      yoke conversion; this check closes the last interop link)

- [ ] Busk a colour over a playing show against a real ArtNet node or
      the standalone visualizer (merge is unit-tested, never touched
      hardware)
- [x] Live swatch on the wheel head - CONFIRMED on the bench
      2026-07-13 ("working well"); the follow-up (swatches would not
      release / blocked the scene) shipped same day: second touch
      releases, toggle contract like positions.
- [x] Busk a SCENE - exercised on the bench 2026-07-13 (the user saw
      the scene light the rig while diagnosing swatch release).
- [x] Fire a RIFF at the bench rig - CONFIRMED on the bench
      2026-07-13 ("the riffs work on the bench").
- [ ] Run CIRCLE on the hung mover (live-output-plan phase 4
      checkpoint): select the mover group, hold a POSITION (or none -
      CENTRE is the fallback anchor), touch CIRCLE in MOVEMENT
      SHAPES, open the fixture with FLASH or a swatch - the beam
      should orbit the held target at the live tempo (16 beats per
      lap); TAP rescales it; touching the position palette again
      moves the anchor; second touch on the shape releases pan/tilt
      to the show.
- [x] Aim a POSITION palette at real movers - CLOSED on the bench
      2026-07-13 with the yoke protocol: raw poses + four aimed
      targets landed standing AND hanging (the wire carries the
      solver->GDTF yoke conversion; docs/coordinate-frames-and-
      orientation.md section 4).
- [ ] Topbar VISUALIZER OPEN end to end: one press = feed up + viewer
      launched + client count ticks to 1 (process launch is stubbed
      in tests)
- [ ] Eyeball the rebranded visualizer frame under a live GL context
      (header spacing, statusbar colors)
