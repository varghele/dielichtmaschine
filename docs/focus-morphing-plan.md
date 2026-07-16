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
- [x] **Colour palette roles (decision 1).** DONE 2026-07-16 (model + apply_palette; the editor role picker landed with the wizard-preview pass the same day: ROLE combo + free-text new role on the colour block dialog writing ColourBlock.palette_role, EDIT PALETTE... dialog writing Song.palette and calling apply_palette so tagged blocks re-skin immediately; the block dialog reaches its Song by block identity over config.songs - no tab plumbing; tests in test_colour_role_picker.py): `ShowPalette` on
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
- [x] **Per-fixture IK resolution at export** - CLOSED BY VERIFICATION
      2026-07-16: every export aim already flows through utils/yoke.py
      at the definition's real Focus ranges (the 2026-07-13/14 yoke
      work closed this; the 540/270 claim in older notes was stale).
      Pinned by TestRangeAwareExportPin in tests/unit/test_dmx_invert.py -
      no code change, NO byte-identity break needed (demo-show hashes
      unchanged). The same commit shipped the LAST v1.5a sliver:
      per-fixture DMX invert flags (Fixture.invert_pan/invert_tilt,
      applied at the wire in the arbiter hardware pass - including
      invert-only fixtures without a yoke chain - and at export in
      convert_solver_dmx/export_aim_dmx; UI placement decided: the
      orientation panel's Group Defaults box, initialized from the
      fixture, written by the stage tab apply; solver/visualizer
      deliberately untouched).
      Original scope: range-aware (the
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
- [x] **Lineage + provenance**: DONE 2026-07-16 (LightBlock.provenance + Song.lineage; morphed lane ids are DERIVED from song+target+edges so re-morph is reproducible). Editor hand_edited marking landed with the phase-4 UI (2026-07-16 evening): every sublane content edit in timeline_ui/light_block_widget.py funnels through _mark_hand_edit (the single block.modified assignment left in the file, pinned by test) and envelope move/resize finalizes through _flip_morph_provenance - morphed blocks flip to hand_edited on first touch, authored blocks never tagged; tests in test_morph_patchbay.py TestHandEditHook. lineage record on the morphed setlist;
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
- [x] Side-by-side preview HELPER (DONE 2026-07-16, utils/morph/preview.py: render_pair produces src/dst stills at one show time via two STRICTLY SEQUENTIAL OfflineRenderer passes per the audit constraint, either side degrading to None; real-GL test passes on the dev box). CONSUMED 2026-07-16: the wizard's REVIEW page grew the scrub (song selector over the dry-run songs, time slider bounded by _song_duration, RENDER PREVIEW button only - never per slider tick, a QThread worker keeps the dialog live, the morphed side renders against the dry-run DEEP COPY, None sides show PREVIEW UNAVAILABLE); tests in test_morph_preview_ui.py, render_pair stubbed - construction never renders.

## Phase 4 - patchbay UI + CLI (design doc 8; mockup 15-morph-patch-flow-6d)

- [x] Patchbay screen: DONE 2026-07-16 (gui/dialogs/morph_patchbay.py per
      mockup 6d): lane-level rows expanding to the four sublane streams,
      capability-gated docking (chip-to-chip wiring, incompatible target
      chips disabled while a wire is pending; solid = 1:1, dashed =
      lane patch fan-out, coloured cubic curves per source lane), edge
      context menu for mode (copy / copy+transform / regenerate +
      strategy) and transforms (phase_offset, mirror, intensity_scale,
      spatial_subset) with the filter marker on transformed edges,
      priority via the menu's +/- pair instead of drag-order (flow-
      wrapped chips make a drag order ambiguous; +/- maps 1:1 onto
      MorphEdge.priority), LOCK per target row round-tripping
      plan.protected_target_lanes, live checker strip (worst coverage
      across songs, red GAP at 0% on a capability the group has),
      auto-suggest prefill (same lighting_role first, then capability
      overlap; add-only, manual-first). Ghost POSITION chip on lanes
      without movement wires a regenerate edge. All mutations are plain
      widget methods; tests/unit/test_morph_patchbay.py drives them
      without mouse events.
- [x] Wizard flow around it: DONE 2026-07-16, REHOSTED same day as the
      full-window MORPH SCREEN (gui/screens/morph_screen.py, Tools >
      Morph to Venue... - the 2026-07-16 desktop check found the modal
      dialog starved the patchbay and fought the consult-other-tabs
      workflow; see the status log): target picker (.lms/legacy .yaml)
      -> patchbay -> review (coverage table with highlighted gap rows,
      dry-run morph report compiled into a DEEP COPY of the target,
      destroyed-hand-edits manifest on re-morph) -> commit (apply_morph
      force flow with explicit manifest confirm) + Save Target As /
      Save Plan As (*.morphplan.yaml, source/target config_hash + date
      stamped on save). Load Plan... adopts an existing plan for
      re-morph; a hash mismatch shows a non-blocking rig-changed
      banner. Discarding the screen changes nothing - only the commit
      button mutates the screen-held target object, and only the save
      buttons write disk. Tests in tests/unit/test_morph_screen.py
      (isolation, force flow, plan round-trip, banner, exit gate) +
      tests/e2e/test_morph_screen_shell.py (page_stack hosting, resume,
      stale-config discard).
- [x] Headless CLI DONE 2026-07-16 (`main.py morph` -> utils/morph_cli.py above the Qt imports; exit 0/1/2/3 = ok/bad-input/compile-errors/needs-force; --report writes markdown).

## Phase 5 - pre-flight (design doc 7)

- [x] Checklist generation from plan + setlist (MODEL done 2026-07-16, utils/morph/preflight.py: flash for dimmer/colour-routed groups -> spot verify + focus capture per mover group x used spot -> colour sanity -> specials -> scrub; drive_state recorded per item for the future pre-flight screen) (flash tests ->
      orientation/spot verify -> focus capture -> colour sanity ->
      busiest-section scrub).
- [x] Verify items (DONE 2026-07-16, the pre-flight SCREEN:
      gui/dialogs/preflight_dialog.py, opened from Tools > Venue
      Pre-Flight... (plan derived from the config's own lanes via
      preflight.derive_plan_from_config) and from the morph wizard's
      commit page (the real plan against config B). DRIVE arms
      utils/artnet/preflight_layer.py on the shared arbiter's
      EXCLUSIVE playback slot (owner "preflight": a playing show
      refuses the attach; detach never stops a loop another producer
      streams through). Drive states: flash_full = group at full
      white, aim_spot = movers on the named spot (busk-layer aim
      math, definition ranges, 16-bit + fines) plus full white,
      rgb_steps = stepped pure R/G/B with claim-to-zero on unused
      colour channels, special_steps = gobo wheel positions at index
      steps (v1: evenly spaced DMX values). CORRECT auto-advances
      with the drive state following; INCORRECT opens the orientation
      dialog for aim items (values written to the CONFIG fixtures) or
      a guidance box naming the fixing tab, then re-arms the SAME
      item. Tests: test_preflight_layer.py, test_preflight_dialog.py).
- [x] Capture items (DONE 2026-07-16: hold_aim_for_capture holds the
      aim + full while focus/zoom sliders trim live - driven on the
      wire only where the definition maps BeamFocusNearFar /
      BeamZoomSmallBig channels, otherwise the sliders drive nothing
      extra; CAPTURE writes {'focus': v, 'zoom': v} into each group
      fixture's Fixture.calibration in the CONFIG and marks the item
      done(result='fixed') - never into show blocks (7.1, pinned by
      test). Playback/export CONSUMPTION of the captured focus/zoom
      values is deliberately future work: today they are recorded
      venue truth, nothing reads them back yet).
- [x] Checklist persistence (DONE 2026-07-16: *.preflight.yaml next to the config, per-item done/result/timestamp, fix-and-re-test reopen; lineage attachment rides the UI wiring).
      Screen wiring same day: the dialog saves on every completion,
      resumes when plan_fingerprint + config_hash still match, offers
      regenerate on a mismatch, and stamps completed_at +
      completed_target_hash (the config hashed AS COMPLETED, captures
      included) when the last item lands.
- [x] Export ordering guard PREDICATE (DONE 2026-07-16: export_guard_message covers incomplete AND completed-then-config-changed; the create_workspace hook lands with the UI integration to avoid three-way gui.py conflicts with the running agents).
      Hooks DONE 2026-07-16: gui.py create_workspace shows the hard
      warning (Continue Anyway / Cancel) BEFORE the options dialog;
      utils/export_cli.py prints it as "warning:" on stderr without
      blocking (scripts decide); both guarded so a missing or corrupt
      checklist file never breaks an export.

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
- 2026-07-16 (evening): phase 4 patchbay + wizard shipped (see the
  ticked items above) plus the phase-2 editor hand_edited hook. The
  wizard's review page renders the morph report in-app (dry run).
  Still open in phase 3: wiring utils/morph/preview.render_pair into a
  scrubbable side-by-side view inside the wizard.
- 2026-07-16 (late): two small closures - the wizard REVIEW page's
  side-by-side preview scrub (phase 3 consumption of render_pair;
  renders on click only, worker-threaded, headless-safe) and the
  colour-role picker (phase 0 leftover: ROLE combo + EDIT PALETTE
  dialog on the colour block editor; song reached by block identity).
  Tests: test_morph_preview_ui.py, test_colour_role_picker.py.
- 2026-07-16 (late): phase 5 complete - the pre-flight screen +
  rig-driving layer + both export guard hooks shipped (see the ticked
  items above for the full shape). New surfaces: Tools > Venue
  Pre-Flight..., the wizard commit page's Run Pre-Flight Now..., and
  the hard export warning in create_workspace / the headless export's
  stderr warning. Deliberate leftovers: focus/zoom calibration values
  are recorded, not yet consumed by playback/export; special_steps
  uses evenly spaced gobo DMX values until routed capability values
  ride the GDTF work; the scrub item is operator-driven (no transport
  automation from the dialog).
- 2026-07-16 (later): EVERY plan item is closed. Inline: DMX invert
  flags (wire + export, orientation panel UI) and the range-aware
  export closed by verification (already real since the yoke work -
  pinned, no byte break). Agents: the pre-flight SCREEN (preflight
  layer on the arbiter's exclusive slot, Tools > Venue Pre-Flight +
  wizard hook, capture -> Fixture.calibration, export guard in
  create_workspace + CLI) and the wizard preview scrub + colour
  palette-role picker. Final: 2861 unit + 111 e2e/visual green; stage
  inspector golden regenerated (invert checkboxes, reviewed). v1.5
  code scope is COMPLETE pending the user's desktop/bench checks and
  the v1.5.0 release ritual (not tagged - user said no release).
- 2026-07-16 (desktop check round): the user's first real-screen pass
  rejected the morph wizard's ergonomics - clipped group names, elided
  capability chips ("I..Y"), an anonymous blank expand button, no drag
  wiring (the 6d mockup says ZIEHEN: QUELLE -> ZIEL), and the modal
  dialog fighting the consult-the-stage-tab workflow. Rework shipped
  the same day: the flow is now a page-stack SCREEN
  (gui/screens/morph_screen.py, Tools > Morph to Venue - moved from
  File by user call, it is a venue workflow like Pre-Flight; leaving
  keeps the in-progress plan, the menu resumes it, a project load
  discards stale screens; keep/discard exit gate) and the patchbay
  got its layout pass (names lead rows, chips size to their text,
  arrow-glyph expanders, visible LOCK, edge chips in a wrapping
  FlowLayout - promoted to gui/widgets/flow_layout.py - proportional
  columns) plus DRAG-AND-DROP wiring through the same can_dock gate as
  click-click (encode/decode_wire_mime + handle_wire_drop, tests drive
  drops without mouse events). gui/dialogs/morph_wizard.py is GONE
  (tests moved to test_morph_screen.py). New golden pins the PATCH
  page (test_morph_screen_golden.py). Two harness lessons pinned in
  that golden's docstring: grab the themed WINDOW (a bare QWidget
  composites no styled background) and flush DeferredDelete before
  grabbing (_rebuild_rows ghost-stacks row generations otherwise).
- 2026-07-16 (SBD recovery round): the user's real Shoo Bee Doom
  project (archive/conf_v7.yaml, the latest full-rig save - v8 only
  trims the rig and adds empty conflict stubs) was converted to
  shoo_bee_doom/shoo_bee_doom.lms (untracked, gitignored; archive
  audio bundled beside it, 7 of 10 audio refs rewritten to the bundled
  mp3s, 3 left absolute for the desk PC). Its first trip through the
  morph pipeline exposed two real bugs the single-song demos never
  could: (1) group_capabilities assumed all four sublanes for every
  loaded config (nothing persists FixtureGroupCapabilities), so
  patchbay gating was a no-op on real projects - now detected from
  fixture definitions with assume-everything kept only for unknown
  models; (2) the compile errored on every edge x song where the
  edge's lane lived in ANOTHER song - per-song lanes are the norm in
  multi-song projects, so a 12-song morph produced 1452 bogus errors
  and commit stayed disabled - cross-song edges now skip silently,
  dangling lane ids still fail plan validation. Also this round: the
  bundled demos converted to .lms (generators + templates + tests
  swept; legacy-load fixture preserved as
  tests/fixtures/legacy_band_midsize.yaml; export hashes verified
  byte-identical before/after).
