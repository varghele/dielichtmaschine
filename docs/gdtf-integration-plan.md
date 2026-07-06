# GDTF Integration Plan

Implementation plan for making GDTF (General Device Type Format, DIN SPEC
15800:2022-02 / GDTF 1.2) the primary fixture-definition format, with `.qxf`
kept as a parallel, second-class source, and for rendering the 3D models that
GDTF files carry in the visualizer.

> **Status:** Planned (v1.2). Direction decided 2026-07-06: GDTF becomes the
> primary citizen because it carries strictly more information than `.qxf`
> (real physical dimensions, photometrics, a geometry tree, 3D meshes). The
> spike from the original v1.2 roadmap survives as a validation gate inside
> Phase 1, producing the coverage-comparison note before the switch is
> declared done.
>
> **Sources:** full read of the fixture pipeline and the renderer (file
> references inline), the GDTF spec at gdtf.eu / mvrdevelopment/spec, pygdtf
> 1.4.5 source, GDTF Share API docs and terms, BlenderDMX as the reference
> GDTF-to-renderer implementation.

---

## 1. Decision and scope

- GDTF definitions and `.qxf` definitions run in parallel; when both exist
  for a fixture, GDTF wins. `.qxf` support never goes away (it is the
  fallback tier and the QLC+ interop path).
- GDTF's embedded 3D models render in the visualizer, replacing the
  procedural chassis when a usable mesh is present. The procedural renderer
  remains as the fallback ladder (see §6).
- GDTF Share files are never bundled or redistributed (§3.3). Test and demo
  GDTF files are authored in-repo.

Out of scope for this plan: MVR scene import (assessed separately, becomes
cheap once Phases 0-1 land), an in-app GDTF authoring editor (roadmap
non-goal; GDTF Builder exists).

---

## 2. Where we are today

### 2.1 Five parallel .qxf parsers

There is no single fixture-definition loader. QXF XML is parsed in five
places, each returning a different shape:

| # | Parser | Returns | Consumers |
|---|--------|---------|-----------|
| 1 | `utils/fixture_utils.py::load_fixture_definitions_from_qlc` (49-202) | dict keyed `"mfr_model"` with `channels`/`modes` | workspace export, color wheels, live ArtNet DMX map |
| 2 | `config/models.py::Configuration._scan_fixture_definitions` (1515-1608) | dict keyed `(mfr, model)` | `.qxw` workspace import |
| 3 | `utils/fixture_capabilities.py::detect_capabilities` (278-372) | `FixtureCapabilities` dataclass | composable 3D renderer |
| 4 | `utils/tcp/protocol.py::_parse_qxf_for_visualizer` (222+) | flat dict (physical/beam/layout/channel_mapping) | visualizer payload legacy fields |
| 5 | `gui/dialogs/fixture_browser_dialog.py::parse_qxf_summary` | summary dict | Add Fixture dialog |

Plus two ad-hoc inline parses (`fixture_utils.py::get_fixture_layout`,
`fixtures_tab.py::_add_fixtures_from_qxf`) and **five duplicated
directory-search implementations** (`fixture_utils.py:61-91`,
`models.py:1519-1537`, `fixture_capabilities.py:1215-1233`,
`fixtures_tab.py:771-807`, `tcp/protocol.py:188-205`), each putting bundled
`custom_fixtures/` first, then the platform QLC+ dirs.

Channel semantics are interpreted twice: preset-based categorization in
`utils/sublane_presets.py` + `utils/effects_utils.py::get_channels_by_property`
(the workhorse for every export path and live DMX via
`utils/artnet/dmx_manager.py::FixtureChannelMap`), and the modern
capability detection in `utils/fixture_capabilities.py` (renderer only).

**Implication:** `FixtureCapabilities` (`utils/fixture_capabilities.py:227`)
is the ready-made semantic target for GDTF, but live playback and all export
consume the older parser-1 dict. Without unification, GDTF becomes parser
number six and "primary format" is a fiction. Unification is Phase 0.

### 2.2 Fixture identity and persistence

- `Fixture` identity is `(manufacturer, model)` strings
  (`config/models.py:24-25`), never a path. Definitions are re-resolved from
  the library at runtime keyed by `(manufacturer, model, mode)`.
- Config YAML persists manufacturer/model/mode plus mode names and channel
  counts; capabilities are re-derived, not persisted.
- QLC+ model names can carry trailing spaces; strings stay verbatim.

### 2.3 The visualizer has no mesh loading

The renderer (`visualizer/renderer/`) is entirely procedural: every chassis
is boxes/cylinders from `utils/geometry.py::GeometryBuilder`, shaders take
only `in_position` + `in_normal` (no UVs, no samplers, non-indexed,
non-interleaved, per-fixture VBOs, no instancing). No OBJ/glTF/3ds loader
exists anywhere, and no mesh-capable dependency is installed.

What the composable rewrite did provide is the seam:

- `make_chassis_geometry()` (`visualizer/renderer/chassis.py:1062`) picks the
  chassis class per fixture; a mesh-backed class drops in there.
- `MovingYokeChassisGeometry` (`chassis.py:300`) already demonstrates the
  compound pattern GDTF needs: base + yoke + head sub-geometries with
  per-part transforms, pan rotating the yoke about local Z, tilt rotating
  the head about local Y (conventions in `visualizer/renderer/reference.md`).
- Two-pass render order (beams additive first, chassis opaque second,
  `fixtures.py:3759`) and the `gl_state.set_depth_mask` requirement
  (gl-gotchas #1) apply to any new mesh pass.
- Per-fixture brightness scaling uses a lumens estimate derived from power
  consumption (`fixture_capabilities.py:1270`); GDTF replaces the estimate
  with manufacturer photometric data.

---

## 3. GDTF facts this plan relies on

### 3.1 Format and models

- A `.gdtf` file is a zip: `description.xml` plus resource folders. 3D
  models live in format subfolders `models/gltf/*.glb` (binary glTF 2.0, the
  spec-preferred format; no extensions/animations), `models/3ds/*.3ds`, and
  2D symbols in `models/svg/`. Optional LOD variants live in `*_low` /
  `*_high` folders; the default LOD targets <= 1200 vertices per device
  (real-time budget).
- `<Model>` nodes carry name, Length/Width/Height in meters (meshes scale to
  these), a `PrimitiveType` fallback (Cube / Cylinder / Sphere / Base /
  Yoke / Head / Scanner / Conventional) for when no file is present, and a
  `File` base name.
- `<Geometry>` nodes link to a Model by name and carry a 4x4 `Position`
  matrix **relative to the parent geometry**. Coordinate system:
  right-handed Z-up, origin at the center of the base plate, fixtures
  authored hanging.
- Pan/tilt are `<Axis>` geometry nodes (typically Base > Yoke(Axis, pan,
  Z-aligned) > Head(Axis, tilt, X-aligned)); a `<DMXChannel>`'s `Geometry`
  attribute names the node it drives, and its channel functions carry the
  Pan/Tilt attribute with physical degree ranges.
- `<Beam>` geometry marks the light output point (emits along -Z of its
  node) with BeamAngle, FieldAngle, LuminousFlux, BeamType, ColorTemperature.
- `GeometryReference` instances a subtree multiple times with per-instance
  DMX break offsets (pixel bars, matrices, moving-head bars).

### 3.2 pygdtf / pymvr / mesh loading

- **pygdtf 1.4.5** (MIT, zero runtime deps, Beta but production-exercised as
  BlenderDMX's parser) reads all of GDTF 1.2: modes, channels, channel
  functions, attributes, geometries, wheels, physical properties. It exposes
  a resolved geometry tree per mode
  (`geometries.get_geometry_tree(...)`, expands GeometryReferences) and
  keeps the archive open as `FixtureType._package` (a `zipfile.ZipFile`), so
  model extraction is `_package.read(f"models/gltf/{name}.glb")`.
- **pymvr 1.0.7** (MIT) reads/writes MVR 1.6; deferred to the MVR
  assessment.
- **trimesh** (MIT, numpy-only for GLB, Pillow for textures) loads GLB
  scenes with per-node transforms and vertex/normal/uv arrays. It does
  **not** read 3DS; the only Python 3DS routes are assimp bindings that need
  the native assimp library (real packaging cost on Windows). Decision:
  GLB via trimesh in the first pass, 3DS-only files fall back to
  PrimitiveType primitives, assimp reconsidered only if demand shows up.

### 3.3 GDTF Share

- Public REST API (`login.php`, `getList.php`, `downloadFile.php`), but
  authentication is mandatory (free account, 2h session cookie). No
  anonymous download.
- Terms of use do not permit redistribution; bundling downloaded `.gdtf`
  files in the app or repo is the risky move and is ruled out. The safe
  pattern (BlenderDMX, consoles): the user logs in with their own account,
  the app downloads on demand and keeps a local per-user offline cache.
- Consequence for tests/demos: author our own minimal `.gdtf` files in-repo.

### 3.4 Quality in the wild

Wild GDTF files are uneven: placeholder-cube models, meshes centered on the
bounding box instead of the base plate (pan/tilt pivots off), vertex counts
far above the LOD budget, missing Beam nodes, geometry trees authored to
satisfy one console. Some previz-tool exports are known-bad (Capture
produces placeholders). The plan bakes in a fallback ladder (§6) and
validation warnings rather than trusting files.

---

## 4. Target architecture

One `FixtureLibrary` service owning discovery, parsing, and caching for both
formats, producing one canonical definition model that every consumer uses:

```
                 .qxf parser ----\
                                  +--> FixtureDefinition --> everything else
  .gdtf loader (pygdtf) ---------/         |
                                           +- identity (manufacturer, model,
                                           |    source, gdtf_fixture_type_id?,
                                           |    revision?)
                                           +- modes -> channels with semantic
                                           |    attributes (one vocabulary,
                                           |    QXF presets and GDTF
                                           |    attributes both map into it)
                                           +- FixtureCapabilities (renderer)
                                           +- physical (dims, lumens, beam)
                                           +- geometry tree + model refs
                                                (GDTF only; None for .qxf)
```

- User-facing identity stays `(manufacturer, model)`. GDTF definitions
  additionally carry the FixtureTypeID GUID + revision for exact matching
  and Share updates.
- Resolution order when both formats define the same fixture: GDTF first,
  `.qxf` fallback.
- `get_channels_by_property`, the DMX manager buckets, the exporters, the
  browser dialog, and the capability cache all consume `FixtureDefinition`;
  the raw dict shapes disappear.

---

## 5. Phases

### Phase 0: unify the fixture-definition layer (prerequisite, pure refactor)

The largest single cost, and the one not to compromise on. Behavior
preserving; pinned by the existing suite (894 tests) plus demo-rig
round-trips.

- [x] One directory scanner + cache replacing the five duplicated search
      implementations. Bundled `custom_fixtures/` first, then platform QLC+
      dirs, then (Phase 1) the GDTF folder. Done:
      `utils/fixture_library.py::fixture_search_dirs` / `iter_fixture_files`
      / `find_fixture_file` (first-match-wins index with negative caching).
- [x] Canonical `FixtureDefinition` model; the QXF parse produces it once.
      Done: `parse_fixture_file` -> `FixtureDefinition` with
      `to_legacy_dict()` for the export/DMX dict consumers and `summary()`
      for the browser. Migrated: `load_fixture_definitions_from_qlc`,
      `_scan_fixture_definitions` (workspace import), `parse_qxf_summary`,
      `_scan_fixture_files` + `_add_fixtures_from_qxf` (Fixtures tab),
      `get_fixture_layout`. One deliberate cleanup: the old loader's
      `.//Channel` XPath swept per-mode channel references into the channel
      list as junk `{'name': None}` entries; the canonical model drops them
      (no consumer could match them).
- [x] `detect_capabilities` consumes the library's parse. Done with a
      scope adjustment: it keeps its internal XML walk (exactly tuned and
      golden-tested) but `_find_and_parse_qxf` now returns
      `FixtureDefinition.root` from the library, so discovery, duplicate
      resolution, parsing, and caching are shared. Same for the visualizer
      payload parse (`_parse_qxf_for_visualizer`). Rewriting their
      extraction onto structured fields adds risk for no behaviour gain;
      revisit only if Phase 1 needs it.
- [x] Acceptance: byte-identical `.qxw` export for the five demo rigs before
      vs after (`scripts/export_hash_check.py`; needs `PYTHONHASHSEED=0`
      plus a pinned RNG seed, because set order affects definition load
      order and `preset_scenes_to_xml` samples the global RNG unseeded);
      no test regressions (948 unit/integration + 33 visual green).

### Phase 1: GDTF definition import (includes the spike deliverable)

Design note (implemented): the loader **transpiles instead of forking**.
`utils/gdtf_loader.py` maps the GDTF model onto a synthesized QLC-format
XML root and runs it through the same `definition_from_qxf_root` extraction
as a real `.qxf`, so `detect_capabilities`, the visualizer payload parse,
`get_channels_by_property`, and the exporters stay format-agnostic. The
synthesized root doubles as the Phase 2 companion-`.qxf` generator.

- [x] Add `pygdtf`. GDTF loader producing `FixtureDefinition`. Done:
      attribute-to-preset table (`_ATTR_MAP`), channel functions/sets to
      `<Capability>` ranges scaled to the coarse byte, wheel slots resolved
      to names + sRGB hex (CIE xyY conversion, `cie_xyy_to_hex`), 16-bit
      offsets to coarse + `...Fine` channel pairs, `GeometryReference`
      instances to numbered per-cell channels + `<Head>` blocks (detected
      as `CellArray` downstream).
- [x] Physical data from the geometry tree. Done: dimensions from the root
      geometry's Model, beam angle + LuminousFlux + color temperature from
      Beam nodes, pan/tilt ranges from the Pan/Tilt channel functions'
      physical values. The visualizer payload falls back to declared bulb
      lumens when there is no power figure (the GDTF case); preferring
      declared lumens outright is deferred to the v1.5b physical-metadata
      pass so existing rigs render unchanged.
- [x] Library discovery. Done: `gdtf_fixtures/` scanned first (GDTF wins
      identity clashes per the primary-format decision), cheap `.gdtf`
      header reads via description.xml without a full pygdtf parse, the
      browser tags `[GDTF]` entries. The per-user folder location
      revisits with the v1.4 data-dir work.
- [ ] **Spike gate (kept from the original roadmap):** rebuild the five demo
      rigs from GDTF definitions, compare capability coverage against the
      `.qxf` parse, write the decision note in `docs/`. Blocked on GDTF
      Share downloads (user account required; files cannot be committed).
      The mapping itself is proven by the synthetic end-to-end tests.
- [x] Tests: `tests/unit/test_gdtf_loader.py` (11) against self-authored
      in-test `.gdtf` archives - canonical parse, preset resolution for
      export/DMX, capability detection, cells/heads, GDTF-over-QXF
      precedence, broken-archive tolerance, plus `.qxw` export and
      visualizer payload end to end. The coverage-diff script arrives with
      the spike gate.

### Phase 2: persistence and interop

- [x] `Fixture` gains provenance fields. Done: `definition_source`
      (default `qxf`; pre-GDTF configs load unchanged) and
      `gdtf_fixture_type_id` (the GDTF GUID, for exact re-resolution and
      future Share update checks). Stamped when patching from the browser
      and when fixture-list import resolves against the library.
- [x] `utils/fixture_io.py`. Done: `resolve_modes_from_library` resolves
      GDTF via the unified cache and stamps provenance; the JSON rig
      format records source + GUID on the deduplicated definitions.
- [x] `.qxw` export of GDTF-patched fixtures. Done in
      `create_workspace._write_gdtf_companion_qxfs`: fixtures whose
      identity also exists as a real `.qxf` anywhere in the library
      (`find_qxf_twin`) need nothing; the rest get a companion `.qxf`
      serialized from the transpiled definition
      (`serialize_definition_to_qxf`) into `gdtf_companion_fixtures/`
      next to the workspace, with a printed report naming the mechanism
      per fixture. The companion round-trips: re-parsing it yields a
      legacy dict identical to the GDTF definition's
      (`tests/unit/test_gdtf_persistence.py`, 6 tests). Residual: load a
      companion + workspace in real QLC+ binaries, like the v1.0 runtime
      check (manual, pending).
- [x] Native ArtNet playback needs nothing special (it consumes the semantic
      channel map; proven by the preset-resolution tests).

### Phase 3: render GDTF models in the visualizer

Groundwork already in place (shipped alongside Phases 1-2): the
GDTF-native lane exists structurally. `FixtureDefinition.gdtf`
(`utils/gdtf_data.py`) carries the geometry tree with per-node parent-
relative transforms and Pan/Tilt axis attribution, model references with
dimensions + primitive fallbacks + in-archive file paths
(`GdtfModel.glb_path()`), beam photometrics, and full-resolution
per-channel physical values (`GdtfChannelPhysical`; also what v1.5a's
inverse kinematics wants). `.qxf` definitions carry `gdtf = None` and
keep the procedural path. Phase 3 consumes this lane directly; nothing
below goes through the transpiled channel model.

- [ ] Mesh pipeline: extract GLB from the archive (pygdtf `_package`), parse
      with trimesh, bake to interleaved indexed position+normal+uv buffers,
      scale to the Model node's Length/Width/Height, cache baked meshes in
      the per-OS data dir keyed by FixtureTypeID + model name + revision.
      Default LOD; hard vertex cap with a validation warning for oversized
      wild files.
- [ ] `MeshChassisGeometry(ChassisGeometry)` selected in
      `make_chassis_geometry()` when the definition carries a geometry tree
      with usable model files. Builds the kinematic chain the way
      `MovingYokeChassisGeometry` does procedurally: accumulate node
      transforms, pan rotation at the Yoke Axis node, tilt at the Head Axis
      node. BlenderDMX's tree walk is the reference implementation.
- [ ] Coordinate adapter, one function, unit-pinned: GDTF right-handed Z-up
      / origin at base plate / beam along -Z of the Beam node, into the
      chassis-local convention of `visualizer/renderer/reference.md` (Z-up,
      beam +X for yokes, +Z static). This is exactly the frame-mixup trap
      CLAUDE.md warns about; tests before wiring.
- [ ] Shader work: textured variant of the fixture shader (UV attribute +
      sampler; Pillow decodes GLB-embedded PNG/JPEG; untextured materials
      use the baseColor factor). Mesh chassis renders in the opaque
      `render_chassis` pass; depth writes via `gl_state.set_depth_mask` only.
- [ ] Beam emission origin/direction from the Beam geometry node instead of
      the procedural lens offset; GeometryReference instances yield one
      emission each (pixel bars, MH bars get correct per-cell beam origins).
- [ ] Mesh sharing: one baked mesh + VAO set shared across all instances of
      a fixture type (today each fixture owns private VBOs; that does not
      scale to the 60-fixture festival rig with real meshes).
- [ ] Fallback ladder (§6) wired and tested.
- [ ] Tests: unit tests for tree walk + frame conversion + LOD/cap logic
      against self-authored `.gdtf` files (tiny GLBs), golden screenshots
      per the visual-regression workflow, a real-GL smoke, and the clipping
      sweep untouched.

### Phase 4: GDTF Share browser (optional, last)

- [ ] Settings-stored user credentials (their own Share account), catalog
      via `getList.php`, download + local cache in the per-OS data dir,
      update check via revision IDs. Never bundled, never redistributed.
- [ ] Baseline that ships with Phase 1 regardless: drop `.gdtf` files into
      the fixtures folder manually.

---

## 6. Fallback ladder (render path per fixture)

1. GDTF with sane GLB model(s): `MeshChassisGeometry`.
2. GDTF with PrimitiveType only (or 3DS-only, or model fails validation:
   oversized, unreadable, degenerate): existing procedural chassis; the
   GDTF primitives (Base/Yoke/Head/Cube/Cylinder) map almost one-to-one
   onto what `chassis.py` already draws.
3. `.qxf` fixture: current behavior, unchanged.

The procedural renderer never goes away; it is tiers 2-3 and the rollback
path.

---

## 7. Risks and open questions

- **Phase 0 scope creep.** It touches ~35-40 call sites across ~20 modules.
  Mitigation: land it as its own PR-sized series with byte-identical export
  acceptance, before any GDTF code.
- **.qxw export of GDTF-only fixtures** (Phase 2) is the weakest interop
  point; the generated-companion-.qxf route needs real-QLC+ verification
  like the v1.0 runtime check.
- **Wild-file quality** (§3.4): the fallback ladder and warnings are load
  bearing, not nice-to-have.
- **3DS-only files**: accepted gap in the first pass (primitives fallback).
  Revisit assimp only on demand.
- **Coordinate frames**: three conventions in play (GDTF Z-up base-plate
  origin, chassis-local, stage/world). One adapter function with tests, no
  inline math at call sites.
- **Performance**: textured indexed meshes + sharing should be cheaper per
  fixture than today's per-fixture procedural VBOs, but the festival rig is
  the benchmark; keep the offline renderer's FPS measurement in the loop.
- **Trailing-space model names / verbatim strings** still apply to the
  GDTF-vs-qxf matching layer.

## 8. Dependencies and licensing

| Dependency | Purpose | License | Notes |
|---|---|---|---|
| pygdtf >= 1.4.5 | GDTF container + description.xml | MIT | zero runtime deps |
| trimesh | GLB mesh loading | MIT | numpy-only for GLB; Pillow (already present) for textures |
| pymvr | MVR (assessment only) | MIT | not added until the MVR item lands |

No native libraries; PyInstaller packaging unaffected. GDTF Share content is
never bundled (§3.3); in-repo test fixtures are self-authored.
