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
- [ ] **`.lms` project extension** (v1.3): file filters, recents,
      packaging association; `.yaml` stays loadable.
- [ ] **Fixtures table delegate editing** (v1.3): the last old-styling
      holdout, fits the tab-polish pass.
- [ ] **Riff tagging + search** (v1.3): rail search exists; tags are a
      small model addition.

Deliberately NOT pulled: Library topbar section (wants a Bibliothek
screen design first), timeline undo/redo (big), MVR/OSC (own tracks).

## Before the backend build (user)

- [ ] Tab polish pass on the individual tabs (in progress, user-led)
- [x] Discuss the output/sync logic - done 2026-07-11, decisions in
      docs/output-sync-plan.md
- [x] Promote to docs/output-sync-plan.md with phases + tests
- [x] Build phases 0-3 - done 2026-07-11/12, hashes in the plan doc;
      phase 4 (conductor, pause look, setlist runner) stays v1.7

## Open finding: the pan/tilt yoke model may not match real movers

**Full write-up, with the hardware verification protocol (tests A-D and
the data to collect): `docs/coordinate-frames-and-orientation.md`.**
The user has two real moving heads to test with. Read that doc first.

Found 2026-07-12 while fixing the mirrored stage and the mounting
presets. NOT yet fixed - it needs a real fixture to settle, and it
does not affect the visualizer (which is self-consistent).

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

- [ ] Busk a colour over a playing show against a real ArtNet node or
      the standalone visualizer (merge is unit-tested, never touched
      hardware)
- [ ] Aim a POSITION palette at real movers (or the visualizer): select
      a mover group, touch CENTRE and a spike mark, watch the heads
      converge; touch again and confirm pan/tilt falls back to the
      show (aim math is unit-tested against the playback spot path,
      never touched hardware)
- [ ] Topbar VISUALIZER OPEN end to end: one press = feed up + viewer
      launched + client count ticks to 1 (process launch is stubbed
      in tests)
- [ ] Eyeball the rebranded visualizer frame under a live GL context
      (header spacing, statusbar colors)
