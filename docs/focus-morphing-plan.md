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

- [x] **Deterministic group topology.** DONE 2026-07-16: `FixtureGroup.fixture_order`
      (explicit name list) + derived-order accessor everyone consumes
      (target resolver, rudiments, export, live). Load snapshot for
      existing groups; spatial default for new; per-group re-sort/
      hand-order control in the Fixtures tab. Byte-identical export for
      existing configs is the acceptance gate.
- [x] **Stable lane ids.** DONE 2026-07-16: `LightLane.lane_id` (uuid4 hex), assigned on
      creation and on load where missing; serialized; never surfaced in
      UI. Plans key edges by lane_id + display name for diffability.
- [x] **Colour palette roles (decision 1).** DONE 2026-07-16 (model + apply_palette; editor role picker rides the later UI phase): `ShowPalette` on
      Configuration (role -> RGB), `ColourBlock.palette_role: str = ""`;
      realization resolves role -> literal at the same places literals
      are consumed today (playback DMX, export steps, visualizer
      payload); editor affordance minimal in this phase (role picker on
      the colour block inspector). Literal fallback everywhere.
- [x] **Autogen determinism audit (design doc 5.6).** DONE 2026-07-16 - RESULT: the generation pipeline is ALREADY a pure function (no RNG in autogen/, stable sorts, hash-independent tiebreaks); nothing to seed. The only RNG lives in the EXPORT preset-scene path, untouched by morphing. Two consequences recorded: (1) the analysis cache must carry the per-section 32-float spectral_flux_envelope in addition to the SectionReport scalars (the rudiment matcher reads it: matcher.py envelope similarity + flux frequency), (2) generate_show calls ensure_default_spots(config) which MUTATES the config - the morph compile must guard config B (copy or pre-seed spots). Stale 'unseeded global RNG' claims in autogen_dialog docstring + test corrected.
      Original scope: Trace matcher /
      variant selection / colour generation for stochastic choice;
      thread an explicit seed parameter through anything found; test
      that two runs with the same seed produce identical lanes.
- [x] **Two-configs-in-process audit (design doc 4.3).** DONE 2026-07-16 - RESULT: NO must-fix blockers; config is threaded as a parameter everywhere, caches are library-keyed not config-keyed. Preview constraints recorded for phase 3: render A/B SEQUENTIALLY via OfflineRenderer (two live standalone moderngl contexts on one thread are unsafe), chassis.show_axes is a CLASS attribute (gizmo state bleeds between renderers - set once for both), avoid the TCP visualizer for the dual view (fixed port 9000, single config). Cosmetic: target_resolver._warned dedup spans configs (call reset_warnings between A/B); user_warnings intermixes A/B entries.
      Original scope: Sweep for
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
- [x] **Migration converter**: DONE 2026-07-16. utils/movement_migration.py
      (pure): solver FORWARD pass (exact inverse of calculate_pan_tilt,
      pinned by a float-precision closed-loop test) traces each
      untargeted block's centre beam onto the stage volume from
      compute_stage_planes (converted once out of spatial.py's 0..D
      depth convention); multi-fixture lanes average the per-fixture
      landings, spreads over 1 m warn; ceiling exits / upward misses =
      sky, skipped. Tools > Convert Movement to World Targets... shows
      the full per-block report (song, lane, range, point or reason)
      BEFORE anything changes; apply is in-memory (user saves manually),
      keeps pan/tilt as fallback, warns per skip (category "migration").
      Tests: test_movement_migration.py, test_movement_targets_ui.py.
- [x] **Authoring UX**: DONE 2026-07-16 (click-to-aim + spot picker; the
      pan/tilt sliders stay). Stage tab AIM toggle (action strip) arms
      StageView's aim mode: a plan click emits the stage coordinate and
      the tab writes it as target_point (z=0; Shift keeps the current
      target height) into the Shows tab's selected movement blocks -
      an explicitly clicked movement sublane block wins, else every
      movement block in the envelope multi-selection (the sanctioned
      fallback; SelectionManager stays the single source). Spot/plane
      targets are cleared so the point actually wins; tabs talk only
      through the MainWindow parent. Tests: test_movement_targets_ui.py.
- [x] **Named spots in the timeline UI**: DONE 2026-07-16. The movement
      block editor's target combo became MANUAL / POINT (read-only
      display of the stored world point) / every named spot / every
      stage plane, preselected by the resolution priority (plane > spot
      > point > manual); picking a spot or plane clears the other
      targets, MANUAL clears all. Tests: test_movement_targets_ui.py.

## Phase 2 - morph compile engine (design doc 3, 5)

- [x] **Plan model** `utils/morph/plan.py`: DONE 2026-07-16. MorphPlan / MorphEdge
      (source lane_id + sublane, target group, mode, transforms,
      priority), per-target-lane protection, seeds, source/target
      identity + hashes, YAML round-trip (`*.morphplan.yaml`).
- [x] **Compile** `utils/morph/compile.py`: DONE 2026-07-16 (v1 policies recorded in the module docstring: interval-union envelopes with NO block splits - the model cannot express phase-shifted rudiment continuation, answering design-doc open question 11.3 conservatively; fan-in clips only value-span blocks and drops cycled losers whole with a report entry; shared-channel gaps are flagged not synthesized; autogen strategy fails-clear until the analysis cache lands). routing, transforms
      (phase_offset, mirror/invert, intensity_scale, spatial_subset),
      fan-in resolution (dimmer HTP, others priority), re-enveloping
      (section-boundary + edge-union cuts, phase-preserving splits),
      shared-channel compositing rule, specials same-definition rule,
      regeneration strategies (manual, static_default,
      derive_from_intensity, autogen w/ seed).
- [x] **Lineage + provenance**: DONE 2026-07-16 (LightBlock.provenance + Song.lineage; morphed lane ids are DERIVED from song+target+edges so re-morph is reproducible - editor hand_edited marking rides the UI phase). lineage record on the morphed setlist;
      per-block provenance tag (morphed(edge) / hand_edited / authored),
      editor sets hand_edited on touch.
- [x] **Re-morph**: DONE 2026-07-16 (pending_destruction manifest, apply_morph force gate, protected target lanes survive). same plan + seeds -> replace, destroyed hand-edits
      listed first, target-lane protection honored.
- [x] **Analysis cache** (design doc 5.7): DONE 2026-07-16 (utils/morph/analysis_cache.py: Song.analysis_cache carries every SectionAnalysis scalar + the 32-float flux envelope keyed by audio content hash; resolve() trusts a cache without audio, recomputes+refreshes on stale hash, honest None otherwise; the autogen regenerate strategy now RUNS - per-section _select_movement_strategy over cached metrics, deterministic, ensure_default_spots mutation of B is reported): per-section derived metrics in
      show YAML keyed by audio content hash; recompute fallback;
      plan validation fails autogen edges cleanly when neither exists.
      Includes the metric-sufficiency check against the matcher's real
      inputs (design doc 11.2).

## Phase 3 - validation, report, preview (design doc 6)

- [x] Completeness checker (DONE 2026-07-16, utils/morph/checker.py: per song x target group x sublane coverage, capability-aware gap rows, unrouted mirror; regenerate edges count as full coverage except manual) (per target group x capability time coverage;
      unrouted-source mirror view); saved expectations double as the
      requirements manifest.
- [ ] Morph report (every edge / transform / fan-in loss / drop /
      regeneration + seed / destroyed hand-edit), same spirit as
      GenerationReport; rendered in-app + writable as markdown.
- [x] Side-by-side preview HELPER (DONE 2026-07-16, utils/morph/preview.py: render_pair produces src/dst stills at one show time via two STRICTLY SEQUENTIAL OfflineRenderer passes per the audit constraint, either side degrading to None; real-GL test passes on the dev box). The wizard's scrub UI consumes it when the patchbay lands.

## Phase 4 - patchbay UI + CLI (design doc 8; mockup 15-morph-patch-flow-6d)

- [ ] Patchbay screen: lane-level rows expanding to sublane granularity,
      capability-gated docking (INTENSITY/COLOUR/POSITION/BEAM), edge
      chips for mode/transforms, drag-priority, lock icon per target
      lane, live completeness checker, auto-suggest prefill from
      lighting_role + capabilities (prefill only, manual-first).
- [ ] Wizard flow around it (source setlist -> target config -> patch ->
      preview -> commit), reachable from File > Morph to Venue...;
      reconcile visuals with docs/design/screens/11-morph-wizard.html.
- [x] Headless CLI DONE 2026-07-16 (`main.py morph` -> utils/morph_cli.py above the Qt imports; exit 0/1/2/3 = ok/bad-input/compile-errors/needs-force; --report writes markdown).

## Phase 5 - pre-flight (design doc 7)

- [x] Checklist generation from plan + setlist (MODEL done 2026-07-16, utils/morph/preflight.py: flash for dimmer/colour-routed groups -> spot verify + focus capture per mover group x used spot -> colour sanity -> specials -> scrub; drive_state recorded per item for the future pre-flight screen) (flash tests ->
      orientation/spot verify -> focus capture -> colour sanity ->
      busiest-section scrub).
- [ ] Verify items (app drives predicted state; incorrect -> remediation
      incl. orientation calibration -> re-test same item).
- [ ] Capture items via the Live surface; captured values land in config
      B ONLY (design doc 7.1 - never in show blocks).
- [x] Checklist persistence (DONE 2026-07-16: *.preflight.yaml next to the config, per-item done/result/timestamp, fix-and-re-test reopen; lineage attachment rides the UI wiring).
- [x] Export ordering guard PREDICATE (DONE 2026-07-16: export_guard_message covers incomplete AND completed-then-config-changed; the create_workspace hook lands with the UI integration to avoid three-way gui.py conflicts with the running agents).

## Status log

- 2026-07-15: plan written; decisions 1-3 locked by user; branch
  v1.5-focus-morphing; design doc + 6d mockup filed under docs/.
- 2026-07-16: phase 0 complete (topology + lane ids + palette roles +
  both audits; .qxw export byte-identical for demos/rigs AND
  demos/shows). Phase 1 world-space targets shipped in the same pass:
  MovementBlock.target_point everywhere, the export sampler gained the
  native renderer's world-plane path (shape chain extracted to
  _solver_shape_position, plane targets now export), native playback
  resolves points; tests in test_group_topology.py,
  test_palette_roles.py, test_world_targets.py.
- 2026-07-16 (second pass): phase 1 migration converter + authoring UX
  + timeline spot picker shipped (see the ticked items above). New
  shell surface: a Tools menu now exists in the overflow (File · View ·
  Tools · Settings · Help). Phase 1 leftover: per-fixture range-aware
  IK at export (the deliberate byte-identity break) and the world-target
  editing pass on the world-space fields themselves.
