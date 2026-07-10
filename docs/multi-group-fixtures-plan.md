# Multi-group fixtures: milestone plan

Goal: let a fixture belong to more than one group, so "a lane per group"
works without forcing a fixture into a single lane. Decided as its own
milestone because the change ripples through the model, migration, and
several consumers.

## Current model

- `Fixture.group: str` - a fixture is in exactly one group. This is the
  source of truth.
- `FixtureGroup.fixtures: List[Fixture]` - derived; rebuilt from the
  fixtures' `group` field (see `fixtures_tab._update_groups`).

## Target model

- `Fixture.groups: list[str]` becomes the source of truth (order = the
  order the user added them).
- Keep a `Fixture.group` compatibility property during the transition:
  getter returns `groups[0] if groups else ""`; setter replaces the list
  with `[value]` (or clears on ""). This lets existing callers keep
  working while they are migrated one by one.
- `FixtureGroup.fixtures` stays derived - a fixture appears in every
  group it lists.

## Migration

- **Load:** a config with the old single `group` string upgrades to a
  one-element `groups` list. A config already carrying `groups` loads as
  is. (Do this in `Configuration.load` / `Fixture` deserialization.)
- **Save:** write `groups`. For one release also write `group` (=
  `groups[0]`) so an older build can still open the file; drop the
  legacy field a release later. Autosave/backup inherit this for free.
- Add a round-trip test proving an old single-group YAML loads, gains the
  list, and re-saves without losing membership.

## Consumers to update (the ripple)

1. **Fixtures tab** - the GROUP column shows all of a fixture's groups
   (comma or chip list); the right-click "Assign to group" and the
   inspector become ADD / REMOVE membership instead of replace; group
   row counts and tints already read `FixtureGroup.fixtures`, so they
   follow once membership is a list. Multi-select assign appends the
   group rather than overwriting.
2. **Group-derived defaults precedence** - a fixture in two groups can
   get conflicting group defaults (color, orientation, lighting role,
   export intensity). Define a rule: the FIRST group in `groups` wins for
   data-color/orientation/role, or the user picks a "primary" group.
   (Open decision - see below.)
3. **Autogen** (`utils/fixture_utils`, autogen pipeline) - anything that
   reads `fixture.group` to bucket fixtures must iterate `fixture.groups`.
   Capability detection already keys off the group; make sure a fixture
   contributes to every group it is in.
4. **Export** - the QLC+ `.qxw` exporter: QLC+ channel groups may expect
   a fixture in one group; check `utils/fixture_library` / the exporter
   and decide (export to the primary group, or emit the fixture in each
   group if the schema allows). ArtNet/native playback is membership-
   agnostic (it addresses fixtures, not groups) so it is unaffected.
5. **Stage tab** - fixture data color and orientation defaults come from
   the group; apply the precedence rule from (2). The docking/layer logic
   is group-independent.
6. **Timeline** - "group-centric lanes": a lane targets one group; with
   multi-group a fixture naturally shows up in each of its groups' lanes.
   This is what makes the North Star "lane per group" honest.

## Decisions (locked 2026-07-10, build started)

- **Precedence: first group wins.** `groups[0]` is the primary group -
  data color, orientation defaults, lighting role and export intensity
  come from it; reordering the list changes precedence. No extra UI.
- **GROUP column display:** the joined group list (" · " separator),
  elided to the column with the full list in the tooltip - same
  language as the timeline lane subtitle.
- **Export** target (primary vs. per-group): decided during stage 3 by
  reading the exporter; the gate either way is byte-identical `.qxw`
  export for single-group configs (scripts/export_hash_check.py).

## Staging (each its own commit, tests + goldens)

1. Model + `groups` list + `group` compat property + load/save migration
   + round-trip tests. No UI change yet (compat property keeps callers
   working).
2. Fixtures tab: membership add/remove UI + GROUP column display.
3. Autogen + stage precedence rule + export decision.
4. Timeline group-centric lanes on top of the new model.
5. Remove the `group` compat property and the legacy save field.

Build started 2026-07-10 (stage 1 first); stage 5 (compat removal)
deliberately waits a release.
