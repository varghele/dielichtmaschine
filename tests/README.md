# Tests

```bash
python -m pytest tests/unit -n auto -q  # the main suite, parallel
python -m pytest tests/e2e -q           # end-to-end MainWindow workflows
python -m pytest tests/visual -q        # visual/pixel regression tests (serial)
python -m pytest tests/integration -q   # network/hardware-adjacent tests
```

Runtimes as of 2026-10 on a 16-core Linux box: unit about 10 s under
`-n auto`, e2e about 10 s, visual about 5 s. CI (`.github/workflows/
tests.yml`) runs unit, e2e and visual on Linux, unit and e2e on
Windows, on every push and before every release build.

Everything runs headless via `QT_QPA_PLATFORM=offscreen` (set at the top
of each Qt-touching test module).

## Parallel runs (pytest-xdist)

`-n auto` runs the unit tier across all cores (seconds on a many-core
machine, where a serial run of the same tier takes the better part of
an hour; needs `pip install pytest-xdist`). Each worker is
its own process with its own QApplication, so the Qt fixtures are safe.
Rules of thumb:

- `tests/unit` parallelizes cleanly. Tests that write files must use
  `tmp_path` (never a shared repo-root path - `test_vc_layout.py` was
  the one offender and is fixed).
- Keep `tests/visual` serial, and NEVER regenerate goldens
  (`QLC_REGEN_GOLDENS=1`) under `-n` - concurrent writers to the same
  golden PNG race.
- A parallel failure that passes serially usually means shared mutable
  state (a shared output file, QSettings cross-talk); fix the isolation,
  don't drop xdist.
- Do NOT run whole UI-heavy test files (`test_live_tab.py`,
  `test_structure_tab.py`, `test_shows_tab_chrome.py`, ...) serially in
  one process "to check a few files": their per-test fixtures re-apply
  the theme to every widget in the process, and torn-down widgets
  accumulate, so theme-apply cost grows with every test - a run that
  takes seconds per test under `-n auto` (fresh worker processes,
  tests spread out) crawls to 30+ minutes single-process (found
  2026-07-14, a three-file serial run sat in `ThemeManager.apply` for
  49 minutes). Run single test classes serially, or use `-n auto` for
  anything file-sized.
- Every test has a 120 s hang budget (`timeout` in `pytest.ini`,
  pytest-timeout, thread method). A test that blows it gets every
  thread's stack dumped and its process ended; under `-n` xdist reports
  the crashed worker and carries on. Raise it for one test with
  `@pytest.mark.timeout(N)`, never globally.
- When a run seems stuck: check `Get-Process python` ages first (a
  suite whose workers are far older than the expected runtime is hung
  or crawling, not busy), then `py-spy dump --pid <worker>` names the
  exact test and blocking call. See docs/qt-gotchas.md #7 for the
  modal-dialog variant of a silent hang.

## Layout

- `unit/` - the main suite: data model, serialization, exporters,
  effects, tabs/widgets behavior, renderer state. One
  `test_<area>.py` per area; every shipped feature has tests here.
- `visual/` - pixel-level regression tests (see below) plus a few older
  interactive scripts that open windows for manual inspection
  (`test_sublane_blocks.py`, `test_sublane_ui.py`).
- `e2e/` - end-to-end workflows driving the real `MainWindow` (universe
  -> fixtures -> stage -> structure -> timeline -> playback), asserting on
  the configuration model, never on pixels. `e2e/conftest.py` states the
  rules: only GL surfaces, sockets and hardware probes are stubbed, and
  every modal is guarded so none can block.
- `integration/` - tests that touch sockets/devices (marked
  `integration`; deselect with `-m "not integration"`).
- `fixtures/`, `test_fixtures/` - shared test data.

## Visual regression testing

Functional tests can't see a glyph that renders as a cut-off sliver.
`tests/visual/harness.py` provides two kinds of pixel checks:

**Glyph-clipping sweep** (`test_widget_clipping.py`, default suite).
Grabs each fixed-width icon button with and without its text; the diff
is exactly the glyph ink, which must stay inside the widget and span at
least the font-metrics advance. Catches the "+ clipped by QSS padding"
class of bug in both themes. When you add a fixed-width icon button,
add it to the collector for its tab. Auto-sized buttons can't clip;
long-text fixed-width buttons would false-positive under the offscreen
fallback font - review those by hand.

**Golden screenshots** (`test_golden_screenshots.py`, default suite,
skips when no golden exists for the platform). Deterministic scenes
(the stage plot PNG, the Fixtures table with tints + conflict cells,
the Stage Layers panel) compared against
`tests/visual/goldens/<platform>/*.png` with per-pixel tolerance.
After an intended UI change:

```bash
QLC_REGEN_GOLDENS=1 python -m pytest tests/visual/test_golden_screenshots.py
# review the changed PNGs, then commit them
```

Caveat: the offscreen platform on Windows has no font database - text
renders as fallback boxes. Goldens therefore pin layout, geometry, and
colors, not glyph shapes, and are per-platform. For a true-font look at
painted output (e.g. the stage plot), render on the native platform
(no `QT_QPA_PLATFORM` override) and inspect by eye.

## Conventions

- `conftest.py` provides the session `qapp` and small model fixtures
  (`sample_configuration` etc.).
- Test modules start with a docstring stating the *contract* under
  test, and where useful, the historical breakage the test pins.
- New feature = tests in the same commit; UI change = visual check in
  the same commit.
