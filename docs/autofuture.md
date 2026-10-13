# Auto-Generation — Future Improvements

## Investigation / Debugging System

**Priority: HIGH**

The auto-generation algorithm is currently a black box. When it produces unexpected results, there's no way to understand WHY it made specific decisions. We need a decision logging/investigation system.

### Requirements:
- Log every decision the algorithm makes: which rudiments were considered, scores, why one was picked over another
- Log per-section: audio analysis values, target flux, selected rudiments per group, movement strategy, color assignment
- Log per-group: diversity adjustments, complement bonuses, final scores
- Log iterative selection: how many rounds, what changed per round, why it stabilized
- Exportable as a readable report (markdown or HTML) that the user can review alongside the generated show
- Optionally display in the UI (collapsible panel or separate window)

### Possible approaches:
1. **GenerationReport dataclass** returned alongside the lanes, containing all decision data
2. **Structured logging** to a file during generation, parseable after the fact
3. **Interactive inspector** in the UI that lets you click a generated block and see why it was chosen

### When to implement:
After the core algorithm is stable and producing reasonable results. The investigation system helps fine-tune, not build.

## 3D flux / transient plot in the Generation Inspector

**Status: built, not wired up (kept on purpose, 2026-10-12)**

`FluxPlot3DWidget` in `gui/dialogs/generation_inspector.py` draws a
song's audio trajectory in 3D (X = time, Y = spectral flux, Z =
transient sharpness), coloured by section, with an orbit camera, zoom
and a playback cursor. It takes the per-frame features the
`GenerationReport` already carries (`frame_times`, `frame_flux`,
`frame_transient`, `sections`). Nothing opens it yet; a smoke test
(`tests/unit/test_generation_inspector.py::test_flux_plot_orbit_and_zoom`)
keeps it painting while it waits.

### When to implement:
With the Generation Inspector UI pass (ROADMAP v1.10). It would sit
next to the existing feature-curve plot as a second view of the same
song, sharing its cursor.
