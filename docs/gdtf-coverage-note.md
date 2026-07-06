# GDTF Coverage Note (Phase 1 spike gate)

Decision-gate deliverable from `docs/gdtf-integration-plan.md` Phase 1:
the demo-rig fixtures parsed from GDTF Share definitions vs the bundled
`.qxf` files, both through the same canonical pipeline
(`utils/fixture_library.py`), capability detection included.

Date: 2026-07-06. Source files: `gdtf_fixtures/` (Share downloads, not
committed per Share terms; re-fetch with `scripts/gdtf_share_fetch.py`).
Comparison generator: `scripts/gdtf_coverage_diff.py` (richest mode of
each definition).

## Decision

**GDTF as primary format is confirmed; `.qxf` stays as parallel
fallback and QLC+ interop.** DMX semantics reach parity through the
transpile; GDTF adds data `.qxf` cannot carry (photometrics, beam
angles, meshes, full-resolution physical values); the failure modes
found are wild-file quality issues that the fallback ladder already
anticipates, not format problems.

## Comparison (richest mode per definition)

| fixture | src | mode(ch) | chassis | pan/tilt | color | wheel | gobo | strobe | zoom | emitter | dims m | lumens | beam deg | models |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MAC Aura [exact] | qxf | Extended(25) | MOVING_YOKE | 539/231 | - | 2 | 0 | False | True | CellArray(2) | 0.30x0.30x0.36 | 3850 | 11-58 | - |
|  | gdtf | Extended(25) | MOVING_YOKE | 540/270 | - | 47 | 0 | True | True | CellArray(2) | 0.22x0.07x0.13 | 4120 | 24-110 | 3 (0 glb) |
| MagicBlade R [exact] | qxf | Ex (44ch)(44) | MOVING_YOKE | 630/540 | - | 9 | 0 | True | False | CellArray(7) | 0.57x0.27x0.18 | 3200 | 4-4 | - |
|  | gdtf | Extended(44) | MOVING_YOKE | 480/480 | - | 1 | 0 | True | False | CellArray(7) | 0.46x0.10x0.18 | 4571 | 4-4 | 3 (1 glb) |
| Sunstrip Active [successor MKII] | qxf | 10 Channels Mode(10) | BAR | - | - | 0 | 0 | False | False | CellArray(10) | 1.00x0.13x0.08 | 18750 | 0-0 | - |
|  | gdtf | 10 Ch(10) | BAR | - | - | 0 | 0 | False | False | CellArray(10) | 0.08x0.11x1.00 | 16000 | 24-24 | 1 (1 glb) |
| LED Matrix Blinder 5x5 [exact] | qxf | 28-Channel(28) | PANEL | - | - | 0 | 0 | False | False | CellArray(25) | 0.64x0.66x0.11 | 2400 | 55-55 | - |
|  | gdtf | 26 CH Mode(26) | BAR | - | - | 0 | 0 | False | False | CellArray(26) | 0.50x0.05x0.50 | 250000 | 25-25 | 0 (0 glb) |
| Hero Spot 60 [exact] | qxf | 14 Channel(14) | MOVING_YOKE | 540/190 | - | 8 | 11 | True | False | PointEmitter | 0.21x0.35x0.14 | 44600 | 15-15 | - |
|  | gdtf | 14-channel DMX mode(14) | MOVING_YOKE | 540/220 | - | 9 | 9 | True | False | PointEmitter | 0.21x0.08x0.14 | 44600 | 10-10 | 0 (0 glb) |
| Giga Bar 5 LED RGBW [exact] | qxf | 51 Channels(51) | BAR | - | - | 0 | 0 | False | False | CellArray(12) | 1.07x0.14x0.17 | 15500 | 0-0 | - |
|  | gdtf | 51 Channel Mode(51) | BAR | - | - | 1 | 0 | False | False | CellArray(12) | 1.07x0.14x0.08 | 16451 | 15-15 | 0 (0 glb) |
| Wild Wash Pro 648 [different model: 132] | qxf | 6 Channel(6) | BAR | - | RGB | 0 | 0 | True | False | PointEmitter | 0.39x0.26x0.10 | 13000 | 0-0 | - |
|  | gdtf | 6CH(6) | PAR | - | RGB | 0 | 0 | True | False | PointEmitter | 0.25x0.30x0.37 | 1000 | 25-25 | 0 (0 glb) |
| Retro Flat Par 18x12W RGBW [no GDTF on Share] | qxf | 8 Channel(8) | PAR | - | RGBW | 16 | 0 | True | False | PointEmitter | 0.27x0.28x0.27 | 18800 | 0-0 | - |
| LED BAR [own fixture, .qxf only] | qxf | 40 Channels Mode(40) | BAR | - | - | 0 | 0 | False | False | CellArray(10) | 0.05x1.00x0.05 | 3000 | 0-0 | - |

## Findings

**Parity and wins.**

- Matched modes have identical DMX footprints (25/44/10/14/51 ch): the
  transpile reproduces channel semantics one to one.
- Cell/head detection agrees everywhere it should (2, 7, 10, 12 cells).
- GDTF supplies beam angles where the `.qxf` had none (Sunstrip 24,
  Giga Bar 15, Wild Wash 25 degrees) and real luminous flux.
- MAC Aura (manufacturer-official file): GDTF finds the strobe channel
  the `.qxf` misses, carries a far richer color wheel (47 entries incl
  split colors vs 2), and its physical pan/tilt ranges are authoritative
  (540/270 vs the `.qxf`'s approximate 539/231).
- Meshes exist only in manufacturer-authored files here: MagicBlade R
  (1 GLB + 3DS), Sunstrip Active MKII (1 GLB), MAC Aura (3DS only).

**Wild-file weaknesses (fallback ladder handles all of these).**

- User-uploaded files carry junk physical data: the Blinder claims
  250,000 lm (per-cell flux times 25), the Wild Wash file is a
  different product entirely (132 W vs Pro 648). Where physical data
  matters, an exact `.qxf` may beat a sloppy GDTF; per-fixture source
  choice stays possible because both remain in the library.
- Dimension extraction from the root geometry model alone
  underestimates or axis-swaps chassis size (MAC Aura base-only 0.22 m;
  Sunstrip transposed). Fix planned in Phase 3: bounds from the whole
  geometry tree with per-node transforms, which the native lane
  (`FixtureDefinition.gdtf`) already carries.
- MagicBlade R's `.qxf` exposes 9 color-wheel entries; the GDTF routes
  them through an unmapped `ColorMacro1` attribute (macro semantics,
  deliberately not mapped to a wheel). Coverage gap to revisit only if
  it bites in authoring.
- MAC Aura's geometry tree has no Axis nodes (pan/tilt linked by other
  means); MagicBlade Neo's cells share one geometry name (no per-cell
  channels). Phase 3's tree walk needs the name-convention fallbacks
  BlenderDMX uses.
- Not everything exists on Share: the Retro Flat Par (Thomann house
  brand) has no GDTF; the bundled `.qxf` covers it. Own fixtures
  (Varghele LED BAR) remain `.qxf` until authored in GDTF Builder.

## Consequences

1. Keep the current architecture exactly as built: GDTF preferred on
   identity clashes, `.qxf` as fallback tier, one canonical pipeline.
2. Phase 3 must compute chassis dimensions from the geometry tree, not
   the root model, and needs axis-detection fallbacks for files without
   proper Axis nodes.
3. Treat wild-file physical data as untrusted input: plausibility
   checks (lumens, dimensions) before it feeds brightness scaling or
   plot scale, warnings surfaced per the v1.4 audit item.
