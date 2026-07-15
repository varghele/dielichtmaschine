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
- **Export: per-group emission (decided 2026-07-10, stage 3).** The
  exporter never writes QLC+ `<FixtureGroup>` elements; groups reach the
  `.qxw` as per-capability `<ChannelsGroup>` lists, VC group controls and
  per-group preset scenes, all built from the derived
  `FixtureGroup.fixtures`. QLC+ accepts the same fixture channel in any
  number of ChannelsGroups, so a multi-group fixture simply appears in
  each of its groups' structures while `<Fixture>` patch elements keep
  coming from `config.fixtures` (patched exactly once). Show tracks keep
  deduplicating a fixture per lane (`resolve_targets_unique`) and bucket
  the deduped fixture under its PRIMARY group: that bucket is what
  applies the group export intensity, so it implements the locked
  first-group-wins precedence (the track name follows the bucket).
  Gate held: byte-identical single-group export for all five demo rigs
  (scripts/export_hash_check.py vs a pristine `git archive HEAD`
  baseline); parse-back test in tests/unit/test_multi_group_fixtures.py.

### Stage 3 audit findings (2026-07-10)

- Every bucketing consumer already flows through the derived
  `FixtureGroup.fixtures` (stage 1): autogen classification/lanes
  (`autogen/spatial.py`, `autogen/generator.py`), capability detection
  buckets (`utils/create_workspace.py`), lane target resolution
  (`utils/target_resolver.py`), live/auto tab group rebuilds, TCP
  groups message, stage plot legend counts, pause show generator, VC
  and preset-scene generation. No production change was needed.
- Defaults reads (data color, orientation, Z, lighting role, export
  intensity) stay on the compat `fixture.group` primary per the locked
  rule: `autogen/spatial.py` max-Z, `utils/artnet/dmx_manager.py` and
  `utils/to_xml/unified_sequence.py` spot targeting,
  `utils/tcp/protocol.py` fixture payload, `gui/stage_plot.py` symbol
  color, `gui/StageView.py`, the stage tab selection inspector, and the
  apply-to-group-default propagation (`config_fixture.group ==` in
  `gui/tabs/stage_tab.py` is correct: only fixtures whose PRIMARY group
  changed resolve new defaults).
- Known lossy spot: the CSV rig sheet (`utils/fixture_io.py`) writes a
  single `group` column (the primary); secondary memberships do not
  survive a CSV round-trip. Deliberate for now: the sheet is documented
  as flat/resolved (it flattens orientation overrides too) and JSON is
  the lossless interchange. Revisit if users hit it.
- Layering question (deferred to the output arbiter, todo.md): a
  fixture in two groups gets blocks from BOTH groups' lanes; at export
  that is two QLC+ tracks writing the same channels, natively two
  registered lanes in the DMX manager. Conflict resolution between
  simultaneous blocks is pre-existing semantics owned by the arbiter;
  stage 3 only guarantees membership completeness.

### Stage 4 findings (2026-07-10)

- Verification pass, not a rebuild: lane target resolution
  (`utils/target_resolver.py`) already reads the derived
  `FixtureGroup.fixtures`, so a fixture in groups A and B resolves into
  both lanes, both lanes' capability detection
  (`detect_targets_capabilities`) includes it, and a single lane
  targeting both groups addresses it once via `resolve_targets_unique`
  (the export/ArtNet/offline-render path). All pinned in
  `tests/unit/test_multi_group_fixtures.py` (stage 4 section).
- **Indexed-target semantics pinned:** `Group:N` means position N in
  that group's DERIVED fixture list, which is `config.fixtures` (patch)
  order filtered by membership. A shared fixture's index therefore
  differs per group (`Front:1` and `Warm:0` can be the same fixture);
  parse/resolve/validate/display-name all honor the per-group index.
  Derivation order is deterministic in every path
  (`Configuration.load`, `Configuration.from_workspace`,
  `fixtures_tab._update_groups`, `fixture_io.apply_fixture_list` - all
  iterate `config.fixtures` in order); the load and tab paths are
  asserted to agree.
- **One real bug found and fixed:** the lane header's N FIX count
  (`timeline_ui/light_lane_widget.py _fixture_count`) deduped per
  GROUP, so a lane targeting two groups that share a fixture counted it
  twice, and an out-of-range indexed target counted as a fixture. Now
  counts `len(resolve_targets_unique(...))` - distinct fixtures, the
  same set the lane addresses at export/playback.
- Other timeline touch-points verified clean: the lane group subtitle
  lists lane TARGETS (membership-agnostic), the group border color uses
  the first target's group, riff-drop compatibility and color-wheel
  options read the derived `group.fixtures` (shared fixture included).
- Generator lane flow: `generate_show` (audio analysis stubbed) builds
  one lane per classified group and the shared fixture is in both
  lanes' resolved targets. Layering/conflicts between the two lanes'
  blocks stay with the output arbiter (todo.md), per stage 3.
- Left for stage 5: remove the `group` compat property + legacy save
  field (waits a release, unchanged).

## Staging (each its own commit, tests + goldens)

1. Model + `groups` list + `group` compat property + load/save migration
   + round-trip tests. No UI change yet (compat property keeps callers
   working).
2. Fixtures tab: membership add/remove UI + GROUP column display.
3. Autogen + stage precedence rule + export decision.
4. Timeline group-centric lanes on top of the new model. Done: shipped
   as a verification + gap-closing pass (see "Stage 4 findings") - lane
   resolution/capabilities/generator lanes proven membership-complete,
   indexed-target semantics pinned (index = position in the group's
   derived, patch-ordered list), and the one proven bug fixed (N FIX
   count now dedupes by fixture identity). Tests in
   tests/unit/test_multi_group_fixtures.py, stage 4 section.
5. Remove the `group` compat property and the legacy save field.

Build started 2026-07-10 (stage 1 first); stage 5 (compat removal)
deliberately waits a release.
