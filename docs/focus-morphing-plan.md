# v1.5 implementation plan: focus geometry (v1.5a) + show morphing (v1.5b)

Task derivation from `docs/design-show-morphing.md` (the design authority;
this file only sequences it) plus the ROADMAP v1.5a section. Branch:
`v1.5-focus-morphing`. Both halves make the v1.5.0 tag; no release until
the user calls it.

**Decisions locked 2026-07-15 (user):**

1. **Colour palette roles land in-milestone, with literal fallback.**
   `ColourBlock` gains an optional `palette_role`; a show-level palette
   resolves roles at realization time. Literal RGB blocks keep working
   forever; the morph routes roles where present and copies literals
   where not (design doc section 4.4).
2. **Group ordering: snapshot old, spatial for new.** Config load writes
   each existing group's current insertion order into an explicit order
   (zero behavior change - `Group:N` targets and chase direction are
   pinned); newly created groups default to spatial sort (stage X, then
   Y); a per-group control re-sorts or hand-orders (design doc 4.1).
3. **Capability vocabulary maps 1:1.** UI INTENSITY / COLOUR / POSITION /
   BEAM == sublanes dimmer / colour / movement / special. No sublane
   split.

**Resolved without user input** (code-informed, 2026-07-15): lane
identity gets stable ids (names are user-editable, plans must survive
renames); seeds are plan-global with per-edge override; envelope cuts
start at section boundary + contributing-edge union, coarsening only if
fixtures prove it necessary; headless CLI is
`python main.py morph <source.lms> --plan <p.morphplan.yaml> --target
<venue.lms> --out <morphed.lms> [--report <path>]`, dispatched before Qt
imports like `export`.

**Code facts the plan builds on** (verified 2026-07-15): ColourBlock is
literal RGB/CMY/wheel today; group order is list insertion order and
`Group:N` + chases consume it; `MovementBlock` already carries
`target_spot_name` and native playback resolves spots through real Focus
ranges (the export pipeline does not - it still assumes 540/270);
`autogen/` shows no unseeded randomness at first pass (the known RNG
hole is export preset-scene sampling, untouched by morphing);
`SectionReport` already carries the per-section metrics the analysis
cache wants; no config singleton exists, but MainWindow + visualizer TCP
assume one active config.

---

## Phase 0 - prerequisites (design doc section 4)

- [ ] **Deterministic group topology.** `FixtureGroup.fixture_order`
      (explicit name list) + derived-order accessor everyone consumes
      (target resolver, rudiments, export, live). Load snapshot for
      existing groups; spatial default for new; per-group re-sort/
      hand-order control in the Fixtures tab. Byte-identical export for
      existing configs is the acceptance gate.
- [ ] **Stable lane ids.** `LightLane.lane_id` (uuid4 hex), assigned on
      creation and on load where missing; serialized; never surfaced in
      UI. Plans key edges by lane_id + display name for diffability.
- [ ] **Colour palette roles (decision 1).** `ShowPalette` on
      Configuration (role -> RGB), `ColourBlock.palette_role: str = ""`;
      realization resolves role -> literal at the same places literals
      are consumed today (playback DMX, export steps, visualizer
      payload); editor affordance minimal in this phase (role picker on
      the colour block inspector). Literal fallback everywhere.
- [ ] **Autogen determinism audit (design doc 5.6).** Trace matcher /
      variant selection / colour generation for stochastic choice;
      thread an explicit seed parameter through anything found; test
      that two runs with the same seed produce identical lanes.
- [ ] **Two-configs-in-process audit (design doc 4.3).** Sweep for
      single-active-config assumptions (globals, TCP sync, spot
      resolution, fixture-map builders); fix what morphing + preview
      need; document what stays single-config on purpose (the shell).

## Phase 1 - v1.5a focus geometry

- [ ] **World-space targets on MovementBlock**: `target_kind`
      ("none" | "spot" | "point" | "plane"), `target_point` (x, y, z m),
      `target_plane` (StagePlane ref), keeping `target_spot_name` as the
      spot key. Pan/tilt fields remain as authored-fallback + migration
      source. YAML schema bump, old configs load unchanged.
- [ ] **Per-fixture IK resolution at export**, range-aware (the
      definition's real pan/tilt ranges instead of 540/270), through the
      yoke conversion that playback already uses. THIS INTENTIONALLY
      BREAKS byte-identical export for mover rigs: hash demos/shows/
      before/after and review that ONLY the aim values move
      (scripts/export_hash_check.py covers only movement-less
      demos/rigs/ - do not trust it alone here).
- [ ] **Migration converter**: per show, snapshot the current rig, trace
      where each movement block's beam lands (solver forward pass),
      rewrite the block to the world-space equivalent; report per block;
      user-invoked (Tools menu), never automatic.
- [ ] **Authoring UX**: click-to-aim in the Stage tab (click stage ->
      world point on the active movement block), spot picker on the
      movement inspector; sliders stay.
- [ ] **Named spots in the timeline UI**: spot markers usable as
      first-class targets (they already exist on Configuration).

## Phase 2 - morph compile engine (design doc 3, 5)

- [ ] **Plan model** `utils/morph/plan.py`: MorphPlan / MorphEdge
      (source lane_id + sublane, target group, mode, transforms,
      priority), per-target-lane protection, seeds, source/target
      identity + hashes, YAML round-trip (`*.morphplan.yaml`).
- [ ] **Compile** `utils/morph/compile.py`: routing, transforms
      (phase_offset, mirror/invert, intensity_scale, spatial_subset),
      fan-in resolution (dimmer HTP, others priority), re-enveloping
      (section-boundary + edge-union cuts, phase-preserving splits),
      shared-channel compositing rule, specials same-definition rule,
      regeneration strategies (manual, static_default,
      derive_from_intensity, autogen w/ seed).
- [ ] **Lineage + provenance**: lineage record on the morphed setlist;
      per-block provenance tag (morphed(edge) / hand_edited / authored),
      editor sets hand_edited on touch.
- [ ] **Re-morph**: same plan + seeds -> replace, destroyed hand-edits
      listed first, target-lane protection honored.
- [ ] **Analysis cache** (design doc 5.7): per-section derived metrics in
      show YAML keyed by audio content hash; recompute fallback;
      plan validation fails autogen edges cleanly when neither exists.
      Includes the metric-sufficiency check against the matcher's real
      inputs (design doc 11.2).

## Phase 3 - validation, report, preview (design doc 6)

- [ ] Completeness checker (per target group x capability time coverage;
      unrouted-source mirror view); saved expectations double as the
      requirements manifest.
- [ ] Morph report (every edge / transform / fan-in loss / drop /
      regeneration + seed / destroyed hand-edit), same spirit as
      GenerationReport; rendered in-app + writable as markdown.
- [ ] Side-by-side preview: source show on config A vs morphed on config
      B in the embedded visualizer, scrubbable (two-config work from
      Phase 0 pays off here).

## Phase 4 - patchbay UI + CLI (design doc 8; mockup 15-morph-patch-flow-6d)

- [ ] Patchbay screen: lane-level rows expanding to sublane granularity,
      capability-gated docking (INTENSITY/COLOUR/POSITION/BEAM), edge
      chips for mode/transforms, drag-priority, lock icon per target
      lane, live completeness checker, auto-suggest prefill from
      lighting_role + capabilities (prefill only, manual-first).
- [ ] Wizard flow around it (source setlist -> target config -> patch ->
      preview -> commit), reachable from File > Morph to Venue...;
      reconcile visuals with docs/design/screens/11-morph-wizard.html.
- [ ] Headless CLI (`main.py morph ...`) above the Qt imports.

## Phase 5 - pre-flight (design doc 7)

- [ ] Checklist generation from plan + setlist (flash tests ->
      orientation/spot verify -> focus capture -> colour sanity ->
      busiest-section scrub).
- [ ] Verify items (app drives predicted state; incorrect -> remediation
      incl. orientation calibration -> re-test same item).
- [ ] Capture items via the Live surface; captured values land in config
      B ONLY (design doc 7.1 - never in show blocks).
- [ ] Checklist persistence + completion attached to lineage.
- [ ] Export ordering guard (hard warning on exporting with an
      incomplete/stale checklist).

## Status log

- 2026-07-15: plan written; decisions 1-3 locked by user; branch
  v1.5-focus-morphing; design doc + 6d mockup filed under docs/.
