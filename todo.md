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
