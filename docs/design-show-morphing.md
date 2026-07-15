# Design: Show Morphing (venue adaptation)

**Status:** draft for review
**Target milestone:** v1.5b (depends on v1.5a stage-relative movement; authored against the v1.4 branch)
**Audience:** implementation (Claude Code) and future contributors. This is a design-approach document: it fixes the north star and the load-bearing decisions, states their rationale, and lists what is deliberately out of scope. It is not a task breakdown — derive tasks from the Decisions section.

---

## 1. Problem

A show is authored against one rig (config A) and must play on another (config B): different fixture counts, different fixture types, fixtures the show has never seen. Today that means re-authoring. Consoles solve adjacent problems (palette indirection, per-fixture type exchange à la MagicQ "Morph Head" / MA "Clone") but nothing solves lane-level retargeting across arbitrary rigs — because consoles store values, and we store *intent*: rudiments parameterized over group topology, colour resolved from palettes, focus expressed in stage coordinates (v1.5a). That intent is count-free and rig-free by construction. Morphing exploits it.

## 2. North star

**Morphing is a compile step, never a runtime layer.**

```
(config A, show or setlist, patch plan, config B)  →  new show(s) inside config B
```

The morph runs once, up front. Its output is an ordinary show in an ordinary config: the timeline editor, playback engine, ArtNet output, offline renderer, and QLC+ exporter remain completely ignorant that morphing exists. No consumer of show data grows a "resolve through morph table" indirection.

Venue adaptation is a **two-phase process**: Phase 1, the morph compile, reconciles the show with config B and can happen anywhere (on the bus to the venue). Phase 2, the on-site pre-flight (§7), reconciles config B with physical reality through a generated, operator-driven checklist. The morph trusts the config; the pre-flight makes the config trustworthy.

Rationale: (1) the `.qxw` export forces materialization anyway — a runtime layer would be a second implementation of the same logic that must agree with the first; (2) WYSIWYG — the morphed show opens in the normal editor and the operator tweaks the two lanes that came out wrong; (3) every downstream subsystem stays simple forever.

The corollary: **copies diverge.** All of Section 5 (plans, lineage, provenance, re-morph) exists to manage that consequence.

### What a show is (the portability contract)

The portable content of a show is its intent layer: rudiment choices and their parameters, flux/energy envelopes, section structure and timing, colour expressed as palette roles, focus expressed as world-space targets / named spots / stage planes (v1.5a). Everything rig-specific — which fixtures, how many, their channels — lives in group definitions and in the realization of blocks against them. Morphing succeeds to exactly the degree that nothing rig-specific leaks into blocks. Any feature that stores raw per-fixture values in a block is a morphing bug waiting to happen; v1.5a's migration of pan/tilt to stage coordinates is the template for fixing such leaks.

### The intended arrival workflow

Venue day: import the venue's rig list via the v1.4 CSV wizard (or open an existing config) → config B exists → open the morph patchbay against the setlist → wire / adjust the plan → preview → commit (all doable on the bus) → **on-site pre-flight checklist** (§7) → play natively or export `.qxw`. Exporting before pre-flight completion gets a hard warning (§7.5). The v1.4 headless export ("N variants for N venues") extends naturally: morphing gets a headless mode (`python main.py morph setlist.lms --plan venue_a.morphplan.yaml --target venue_a.lms --out ...`).

---

## 3. Core model: the morph patchbay

The morph is described by a **patch plan**: a user-authored routing document, visualized as a patchbay. Left side: the source show's lanes, decomposed into their sublane streams (dimmer / colour / movement / special). Right side: the target config's groups. The user wires edges from `(source lane, sublane)` to `(target group)`.

Properties of the routing graph:

- **Fan-out** is allowed: one source stream feeds many target groups (a dimmer lane drives both the house PARs and the movers' intensity).
- **Fan-in** is allowed: one target group receives streams from several source lanes (colour from lane A, dimmer from lane B). Resolution rules in §3.3.
- **Incomplete patching** is allowed and explicit: unrouted source streams are deliberate drops; unrouted target capabilities are deliberate darkness. Both are surfaced (§6), never silent.
- **Manual-first**: nothing routes without the user's say-so. Auto-suggestion (§8) only *prefills* the matrix; the user always confirms.

This is the design's legibility advantage over console-style morphing: the morph report is not a log of what an algorithm did — it is a document the user authored.

### 3.1 Edge semantics

An edge is not just a wire. Each edge carries:

**A mode** — one of:

- `copy` — the stream lands verbatim (retimed only by re-enveloping). The default.
- `copy+transform` — verbatim plus one or more transforms (below).
- `regenerate(strategy)` — the stream's content is synthesized for the target group. Primarily for movement onto groups that had none; strategies in §3.2.

**Optional transforms** (composable, order-defined):

- `phase_offset(beats | fraction-of-cycle)` — offsets the rudiment's cycle.
- `mirror` / `invert_direction` — flips spatial direction of directional rudiments.
- `intensity_scale(factor)` — scales dimmer output.
- `spatial_subset(selector)` — restricts to a spatial subset of the target group (e.g. stage-left half).

This unifies the one-to-many question: "one dimmer lane splits into two mover lanes" is simply two edges from the same source, one carrying `phase_offset(1/2)` or `mirror`. Fan-out with no transforms = lockstep, which is the correct boring default. There is no separate split-policy machinery.

### 3.2 Regeneration strategies (movement first, generalizable)

When a target group has movement capability but the routed source had no movement stream, the movement edge uses `regenerate` with one of four strategies, chosen per edge at morph time:

1. **`manual`** *(default)* — the morph emits no movement blocks; the lane is flagged in the report as "movement: intentionally empty — author by hand." Safe, honest, default.
2. **`static_default`** — a per-role default policy: slow ambient motion at a default target (named spot or stage plane). Boring but never wrong.
3. **`derive_from_intensity`** — a complement mapping `intensity_rudiment → movement_rudiment` in the rudiment registry (high-flux chase → sweep; slow pulse → drift). Deterministic, no audio needed.
4. **`autogen`** — run the autogen movement-strategy pass for just these lanes against the song's audio analysis (§5.4). Highest quality, requires analysis or audio.

The same `regenerate` shape covers future cases (e.g. synthesizing a per-cell chase for a pixel bar from a plain dimmer stream) without new machinery.

### 3.3 Fan-in resolution

When multiple streams of the same sublane type land on one target group and overlap in time:

- **Dimmer: HTP** (highest takes precedence) — a century of industry precedent; predictable; never darker than either source.
- **Colour, movement, special: priority order** — each edge in the plan has an explicit priority; highest priority wins for the overlapping span (LTP-style, but statically resolvable at compile time). No blending: blending two unrelated streams produces mud; a deliberate composite is an editor job post-morph.
- Every fan-in overlap that actually resolved (i.e. something lost) produces a report entry (§6).

### 3.4 Shared-channel compositing

The patchbay assumes sublane independence, which holds for fixtures with a real dimmer channel but not for RGB-only fixtures, where intensity is driven through the colour channels (the timeline UI already models this: dimmer blocks render orange on colour-only lanes). Rule:

> When dimmer and colour streams both target a group whose fixtures lack a dedicated dimmer channel, the rendered output is **multiplicative**: `channel = colour × normalized_dimmer`.

Gaps: dimmer routed but no colour → scaled white (or the group's configured default colour); colour routed but no dimmer → colour at full, flagged by the completeness checker (§6) since it likely means an unintended always-on. This rule lives in the morph's realization pass, not in playback — playback sees ordinary blocks.

### 3.5 Re-enveloping

Sublane streams from different source lanes arrive with different `LightBlock` envelope boundaries. The morphed lane must contain well-formed, *editable* `LightBlock`s — a morphed show that can't be edited defeats the WYSIWYG rationale. Policy:

- Envelope boundaries for a morphed lane are cut at **section boundaries** first, then at the union of contributing sublane-block edges within each section.
- Sublane blocks are split (never stretched) to fit envelopes; splitting a rudiment-backed block at time *t* must preserve phase (the second half continues the cycle, not restarts it).
- Envelope `name`/`effect_name` carry provenance: `morph:<source-lane>/<sublane>` (§5.3).

This is a pure compile-time transformation; get it wrong and the editor shows garbage, so it warrants its own unit-test suite with hand-checkable fixtures.

### 3.6 Specials policy (v1)

Gobo indices and colour-wheel positions are fixture-specific; routing them across types is semantically meaningless in general. v1 rule: **special streams route only between groups of the same fixture definition** (same GDTF/qxf identity). Everything else drops with a report entry. GDTF wheel definitions carry per-slot media metadata, so a semantic layer (gobo *category*: breakup / dots / linear) is partially reachable later — explicitly deferred (§10), but the edge `mode` field leaves room for a future `map_semantic` mode.

---

## 4. Prerequisites this design imposes

These are not morph code, but morphing is broken without them:

1. **Deterministic group topology.** Rudiments are count-free but not *order*-free: a chase needs "which fixture is first." Group ordering must be defined and stable: default = spatial sort by stage X (then Y), with an optional explicit per-group order the user can set. Without this, a morphed chase runs backwards or zigzags in patch-address order. This is a group-model fix; land it before the morph engine.
2. **v1.5a complete.** Movement routing across rigs is meaningless while blocks store pan/tilt. World-space targets, named spots, and per-fixture IK resolution are hard prerequisites.
3. **Two configs in one process.** The morph tool holds config A and config B simultaneously (and the side-by-side preview renders both). Audit for single-active-config assumptions: globals, visualizer TCP sync, spot resolution, anything reading "the" configuration. Make this an explicit early implementation task, not a mid-implementation discovery.
4. **Colour as palette roles.** To the extent shows still carry literal RGB `ColourBlock`s, morphed colour is copy-only. The palette-role indirection (lane stores a role; a show-level palette resolves it) makes colour morph trivially and should be treated as part of the intent-layer contract. Migration mirrors v1.5a's pan/tilt migration. If it slips, morphing still works — colour just routes as literal values.

Explicitly *demoted*: the fixture role-taxonomy rethink. Manual-first patching means taxonomy is only needed to prefill suggestions (§8), not to morph. It is off this milestone's critical path.

---

## 5. The patch plan as a first-class artifact

### 5.1 Persistence

The plan is a YAML document (`*.morphplan.yaml`) containing: source config identity + hash, target config identity + hash, the edge list (source stream, target group, mode, transforms, priority), per-target-lane protection flags (§5.5), regeneration seeds (§5.6), and plan metadata (author, date, notes). Plans are diffable, reviewable, and reusable: a band that rotates through five venues accumulates five plans and re-applies them every tour. The plan is what turns morphing from a one-shot wizard into a workflow.

### 5.2 Setlist scope

The unit of morphing is the **setlist**, not the show. A gig is one `.lms` with N songs on one rig; one plan applies across all of them (lanes are keyed by group targets, which are consistent across songs in a config). Per-song edge overrides are allowed in the plan (a song whose lane layout differs), but the default is one plan → whole gig. This is the single biggest workflow multiplier in the design.

### 5.3 Lineage and provenance

- The morphed show/setlist stores a lineage record: `(source show hash, plan hash, source config hash, target config hash, app version, timestamp)`. Six months later, this is the difference between a managed workflow and a diaspora of diverged `show_final_v3_kufa` files.
- Every morphed block carries a provenance tag: `morphed(edge-id)` vs. `hand_edited` (set when the editor touches a morphed block) vs. `authored` (created in the editor from scratch). Cheap now, load-bearing for §5.4.

### 5.4 Re-morph

Fixing the master show and re-applying the plan must be one click. Re-morph = re-run the compile with the same plan (and seeds). Divergence policy for v1, deliberately blunt:

> Re-morph **replaces** the target show. Before it does, the report lists exactly which `hand_edited` blocks will be destroyed, per lane, and the operator confirms.

No three-way merge in v1 (§10). Provenance tags make the blunt policy honest; protection flags (next) make it survivable.

### 5.5 Selective re-morph: the unit is the *target lane*

With fan-in, "re-morph everything except my hand-edited movement lane" must be expressed as protecting a **target** lane, which skips *all* edges feeding it. Protecting source lanes does not compose. The plan carries a `protected: true` flag per target lane; protected lanes are left untouched by re-morph and listed as frozen in the report.

### 5.6 Determinism

Re-morph is only trustworthy if `(source show, plan, analysis, seed) → output` is a pure function. Otherwise fixing one bar and re-morphing reshuffles every regenerated lane and the operator must re-review the whole show. Requirements:

- Any `regenerate` strategy with stochastic choice (rudiment/variant selection in autogen) takes an explicit seed, stored per-edge or plan-global in the plan.
- **Pre-work:** audit the autogen pipeline (matcher, variant selection, colour generator) for unseeded randomness and thread a seed through. Small change now, painful retrofit later.
- Analysis inputs are pinned by hash (§5.7), so a changed audio file visibly invalidates rather than silently altering output.

### 5.7 Audio analysis: cache derived metrics, recompute as fallback

The `autogen` regeneration strategy needs the song's analysis at morph time. Policy:

- Cache the **per-section derived metrics** the matcher actually consumes (energy, vocal presence, spectral contrast, etc.) in the show YAML, keyed by an audio-file content hash. These are kilobytes; raw feature frames (megabytes) are not cached.
- If the cache is missing/stale and the bundled audio (`<config_dir>/audiofiles/`) is present, recompute on demand — seconds to tens of seconds for a typical track, acceptable on venue day.
- If neither cache nor audio is available, `autogen`-mode edges fail plan validation with a clear message; the operator downgrades those edges to `derive_from_intensity` or `static_default`.
- Open validation question: confirm the per-section metrics are *sufficient* for the movement-strategy pass, or whether any consumer needs finer-grained frames. If insufficient, cache the minimal additional aggregate rather than frames.

---

## 6. Validation, report, and preview

**Completeness checker** (live in the patchbay, blocking-warning at commit): per `(target group, capability)`, the time-coverage of routed streams over the show — e.g. `movers-L: dimmer 100 %, colour 100 %, movement 0 % ⚠`. Mirror view: source streams that feed nothing (deliberate drops, visible). The checker's output doubles as the old roadmap's "show requirements manifest" idea: a show's minimum-rig declaration is just saved checker expectations, nearly free.

**Morph report** (same spirit as autogen's `GenerationReport`): every edge applied, every transform, every fan-in resolution that lost data, every dropped special stream, every regeneration with its strategy and seed, every hand-edited block a re-morph destroyed. The report is the plan's execution trace; because the plan is user-authored, the report reads as confirmation, not surprise. Consoles' clone/exchange operations are notorious for silent data loss — this is the differentiator.

**Side-by-side preview:** original show on config A vs. morphed show on config B in the embedded visualizer, scrubbable, before commit. Requires the two-configs-in-process work (§4.3).

---

## 7. Phase 2: on-site pre-flight

The morph reconciles the show with config B; nothing in Phase 1 reconciles config B with the physical rig — and venue rig lists lie constantly (heights off by a metre, a mover hung inverted, an address typo, a fixture in a different DMX mode than the CSV claimed). The pre-flight is that reconciliation, made procedural: a generated checklist the operator clicks through onsite, with the app driving the rig into testable states. It is the formalization of the industry's focus session, and it **absorbs the v1.5a calibration helper** — "point each head at a known reference, derive orientation" is one checklist item type, not a separate feature.

### 7.1 The capture rule (load-bearing)

**Captured values land in config B (fixture calibration and geometry), never in the morphed show.** Focus captures become per-fixture calibration data (focus-at-distance or per-spot focus overrides); orientation corrections update the fixture's yaw/pitch/roll/mounting; position corrections update stage coordinates. The show keeps referencing spots and world-space targets untouched. Because v1.5a resolves pan/tilt from geometry at playback/export time, fixing the geometry fixes every cue without touching the morph — and re-morphing after a master fix does not destroy the focus session. Show = intent, config = physical truth, pre-flight edits only the truth. Writing captured values into show blocks is a design violation, not a shortcut.

### 7.2 Item types

- **Verify** — the app drives a predicted state ("all four movers at SPOT_CENTER, full, white"); the operator answers correct / incorrect. *Incorrect* branches into a remediation flow (re-run orientation calibration, adjust height in the Stage tab, fix address/mode) and then **re-tests the same item**. The fix-and-re-test loop is mandatory: a checklist that cannot be re-run after a fix is a list of regrets.
- **Capture** — the app holds a state; the operator adjusts a live value (focus, zoom, position trim) and presses capture; the value is written to config per §7.1. The v1.4 Live tab is the control surface for the adjustment step — its controls already merge into the same ArtNet output, so capture is wiring, not new infrastructure.

Every item is operator-confirmed. The automation is in *generating* items and *driving the rig into testable states*, never in judging correctness — the same manual-first principle as the patchbay. No auto-pass, no camera-assisted verification (§10).

### 7.3 Checklist generation

The checklist is generated from the plan + setlist, not authored. The morph already knows what to test: which spots the setlist uses (→ one verify item per mover-group × key spot), which groups received dimmer streams (→ per-group flash test, doubling as the patch/address check), which received colour (→ RGB sanity swatch, catching channel-order and mode mismatches), which received specials (→ gobo/prism verify). Generated order: patch flash tests first (cheapest, catches the grossest errors) → orientation/spot verification → focus capture → colour sanity → optional scrub-through of the busiest section as a final eyeball.

### 7.4 Persistence

The checklist persists with per-item completion state and timestamps. Venue setup gets interrupted; the checklist resumes. A completed checklist ("all items verified at 16:42") attaches to the lineage record (§5.3) as the venue-readiness record for that gig.

### 7.5 Export ordering guard

Native ArtNet playback resolves pan/tilt at runtime, so calibration changes apply instantly. A `.qxw` export **materializes** pan/tilt — a workspace exported before pre-flight completion bakes in uncalibrated geometry. The exporter warns hard (not a footnote) when the active config's checklist exists and is incomplete or was completed before the last calibration change.

---

## 8. UI approach (sketch, not spec)

The raw matrix (lanes × sublanes × target groups) explodes fast — a 10-lane show onto a 12-group rig is hundreds of potential edges. Mitigations:

- Left side defaults to **lane-level rows** ("whole lane → group", the common case) that expand to sublane granularity only when the user wants split routing.
- **Auto-suggest prefill:** a role/capability-based pass proposes an initial wiring the user edits. This is where the (demoted) taxonomy earns its keep later; v1 can prefill on the existing `lighting_role` + fixture capabilities and be useful. Prefill never commits — manual-first stands.
- Edge affordances: transforms and mode as per-edge chips; priorities as drag-order within a target lane; protection as a lock icon per target lane.

---

## 9. Interaction with the roadmap

- **v1.5a** is a hard prerequisite (movement portability) — unchanged. Its calibration helper is absorbed into the pre-flight as a remediation/verify item type (§7); implement it as such rather than as a standalone dialog.
- **Live tab (v1.4)** is the control surface for pre-flight capture items (§7.2); no new live-control infrastructure.
- **CSV rig import (v1.4)** is the arrival path for config B — reference it in the morph docs/UX.
- **GDTF (v1.4)** supplies the canonical attribute vocabulary the routing layer maps over, and (later) wheel metadata for semantic specials.
- **MVR rig exchange (v1.8b)** becomes a second arrival path for config B; no morph-side changes needed if config B is just "a config."
- **v1.7 timeline ergonomics** (edge ramps, crossfades) stays *after* morphing, as the roadmap already argues: block-model changes before the morph data model settles risk rework. Note for v1.7: fade fields must be part of the routed stream (copied with the block) — trivial if blocks carry them.
- Project-doc updates in this milestone: ROADMAP v1.5b section rewritten to this design; architecture.md gains the patch-plan artifact and lineage record.

## 10. Non-goals (v1.5b)

1. **Runtime morphing.** Never; see north star.
2. **Three-way merge on re-morph.** Blunt replace-with-manifest (§5.4). Merge is a rabbit hole; revisit only with evidence of demand.
3. **Semantic gobo/wheel mapping.** Same-fixture-type routing only; GDTF makes the future layer possible, not this milestone's problem.
4. **Blended fan-in.** HTP/priority only. Deliberate composites are editor work.
5. **Automatic quantity choreography** beyond edge transforms (no "intelligently spread 2-fixture programming across 8 movers" solver — mirror/phase/subset transforms plus rudiments' inherent count-freedom cover the real cases).
6. **Taxonomy rethink as a blocker.** Runs in parallel or later; only auto-suggest consumes it.
7. **Pre-flight cleverness.** No camera-assisted or sensor-based verification, no auto-pass, no per-fixture-model custom item authoring in v1. The item vocabulary is the four generated types (§7.3) plus calibration remediation. The checklist's value is procedure, not cleverness.
8. **Pre-flight captures written into show blocks.** Captures go to config B only (§7.1).

## 11. Open questions

1. **Colour palette-role migration timing:** in-milestone or before it? (Affects whether colour morphs as roles or literal values in v1.)
2. **Per-section metric sufficiency** for the autogen movement strategy (§5.7) — needs a code-level check against the matcher's actual inputs.
3. **Envelope-cut policy details** (§3.5): is "section boundary + edge union" enough, or do very dense shows need a coarser cut (per bar-group) to stay editable?
4. **Plan portability across setlist edits:** if the master gig gains a song after plans exist, plans should apply cleanly (edges are keyed by lane/group names) — confirm lane identity is stable enough, or introduce lane UUIDs.
5. **Headless morph CLI surface:** confirm flags and where target `.lms` + report land.
6. **Where does the seed live** — plan-global with per-edge override, or per-edge only? (Plan-global + override is the working assumption.)
7. **Focus calibration parameterization** (§7.1): is captured focus stored as focus-at-distance per fixture (interpolated per target), per-spot overrides, or both? Depends on how fixture focus channels behave across the library — needs a small survey of GDTF focus attribute definitions before committing.

## 12. Industry context (why this is different)

Consoles solve portability with palette indirection re-focused by hand per venue (MA presets, Avolites/Hog palettes, Eos palettes) and per-fixture type exchange with attribute-level mapping (MagicQ Morph Head, MA Clone/Exchange, Hog Change Type). Nobody solves quantity mismatch (the touring answer is floor packages and previz focus sessions), and nobody produces an auditable morph record. This design differs in three ways: intent is geometric and count-free *by construction* (v1.5a + rudiments), the morph unit is the lane stream rather than the attribute value, and the plan/report pair makes the whole operation user-authored and auditable. The attribute-mapping layer consoles centre on still exists here — it's just the bottom layer (GDTF vocabulary), not the whole feature.
