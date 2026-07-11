# TODO: working agenda

The output + synchronisation architecture discussion happened on
2026-07-11 and was promoted to **docs/output-sync-plan.md** (arbiter
layers + masks, merge rules, exclusive playback slot, idle-floor
policy, conductor clock, phased build with tests). That file is now
the source of truth; the notes that used to live here are folded in.

## Pull-in candidates (roadmap items that fit the current polish phase)

Discuss before pulling any of these in - order is by leverage:

- [ ] **Headless export CLI** (v1.3): nearly free since
      `create_qlc_workspace` gained `output_path`; just an argparse
      shell + console-script entry.
- [ ] **Configurable fixture library paths** (v1.2): user GDTF dir +
      user `.qxf` dir in Settings, folded into `fixture_search_dirs()`;
      prerequisite for GDTF Share Phase 4, and the packaged app needs
      writable per-user defaults anyway.
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
- [ ] Topbar VISUALIZER OPEN end to end: one press = feed up + viewer
      launched + client count ticks to 1 (process launch is stubbed
      in tests)
- [ ] Eyeball the rebranded visualizer frame under a live GL context
      (header spacing, statusbar colors)
