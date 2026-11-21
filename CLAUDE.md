# CLAUDE.md

Working notes for Claude Code sessions on this repo. The user is
varghele; Die Lichtmaschine (formerly QLC+ Show Creator) is their
hobby project - standalone visual light-show authoring with native
ArtNet playback, PyQt6 + ModernGL, developed primarily on Windows.

## Working agreements

- **Branches:** milestone work happens on a milestone branch
  (`v1.1-stage-rig-data` style, matching the milestone in ROADMAP.md).
  Never commit feature work directly to `main`; `main` receives merges
  and release chores only.
- **Commits:** Claude commits directly as the user. One-line
  conventional-commit message (`feat(stage): ...`), no body, no
  `Co-Authored-By` or any AI attribution (user removed Claude from the
  contributor history and wants it kept out). Stage with explicit file
  paths, never `git add -A`. Do not push unless asked.
- **Tests:** every feature ships with tests proving it works, in the
  same commit. UI/widget changes also need visual checks - see
  `tests/README.md` (glyph-clipping sweep + golden screenshots,
  `QLC_REGEN_GOLDENS=1` to regenerate goldens after intended changes).
- **Style:** no em-dashes in any written output (docs, commit messages,
  UI strings). Roadmap additions go into focused, themed milestones
  with concrete version numbers; completed items get ticked with a
  short "Done:" note describing what shipped and where the tests live.
- **Changelog:** Keep a Changelog format; work lands under
  `[Unreleased]`; the release workflow uses that section verbatim as
  GitHub Release notes (`docs/releasing.md`).

## Where state lives

- `ROADMAP.md` - the backlog, per milestone, with done-notes.
- `CHANGELOG.md` `[Unreleased]` - what shipped since the last tag.
- `docs/` - architecture and theory notes; `qt-gotchas.md` and
  `gl-gotchas.md` are the trap references (read before Qt styling or
  ModernGL work; add entries when a diagnosis took >20 min).
  `coordinate-frames-and-orientation.md` is REQUIRED READING before
  touching stage->3D mapping, mounting presets, or pan/tilt: the three
  frames, the bugs fixed 2026-07-12/13, and the yoke findings with the
  hardware protocol that verified them.
- `tests/README.md` - suite layout + visual-regression workflow.
- `demos/README.md` - the reproducible demo rigs/shows that double as
  project templates and test data.

## Non-obvious facts that cost time to learn

- The **offscreen Qt platform on Windows has no font database**: text
  renders as fallback boxes. Pixel tests that involve glyph shapes are
  therefore per-platform (`tests/visual/goldens/<platform>/`); for a
  true-font look, render on the native platform (no QT_QPA_PLATFORM
  override - works on a desktop session).
- **QLC+ model names can carry trailing spaces** (e.g. the bundled
  Stairville par: `"Retro Flat Par 18x12W RGBW "`). Keep
  manufacturer/model strings verbatim; library lookup matches exactly.
- The **compact serializer stores show block templates in per-file
  top-level tables** (`block_defs` / `light_block_defs`). Never merge or
  copy show dicts between config YAMLs at the raw-YAML level - refs
  land in the wrong file's table and corrupt silently. Go through the
  object model (`utils/config_merge.py` is the reference).
- **Fixed-width buttons narrower than ~40px clip their glyph**: the
  theme puts 14px horizontal padding on QPushButton, and Qt clips the
  label to the content rect (the glyph truncates *inside* the widget,
  no overflow). Use `TOOLBAR_BTN_WIDTH` from
  `gui/tabs/configuration_tab.py`; the sweep in
  `tests/visual/test_widget_clipping.py` enforces this - add new
  fixed-width icon buttons to its collectors.
- **Coordinate frames:** stage/config space is X centered left-right,
  Y depth centered (negative = front/audience), Z height. Renderers
  build geometry in the Y-up SCENE frame: stage X -> scene X, stage Z
  (height) -> scene Y, stage Y -> scene Z. That mapping SWAPS two axes,
  so it is a REFLECTION (det -1) - the scene is a mirror of the stage.
  It is corrected once, at the view matrix (`DISPLAY_FLIP` in
  visualizer/renderer/camera.py, negates scene Z), giving stage ->
  display (x, z, -y), det +1. Consequences: the camera orbits in
  DISPLAY space (a given azimuth views the opposite side from what it
  used to - hand-placed test cameras carry +180), and the solver keeps
  working in the SCENE frame, so DMX is unaffected by the correction.
  Full write-up: docs/gl-gotchas.md #4. `autogen/spatial.py` uses its
  own 0..D depth convention for stage planes - do not mix them up.
- **Fixture orientation has exactly ONE table**
  (`utils/orientation.py` `MOUNTING_PRESET_ANGLES`): absolute
  (yaw, pitch, roll) per mounting, in the scene frame, with
  R = Ry(yaw) @ Rx(pitch) @ Rz(roll). Never write a second copy.
  The presets are BODY orientations (how the chassis sits), NOT
  home-beam directions - a mover's aim comes from the pan/tilt solve.
  `hanging` is a +90 pitch that flips the chassis (pre-rebrand
  convention, restored 2026-07-13 after a 2026-07-12 "beam-direction"
  rewrite broke every mover rig). DO NOT re-derive these from where the
  home beam points - that is exactly what went wrong. `mounting` is a
  LABEL; the angles carry the truth, and config load corrects the
  2026-07-12 values + all-zero angles onto the table
  (`migrate_orientation_angles`). Correctness is pinned END TO END by
  `test_orientation.py::TestAimingEndToEnd` (aimed mover lands its beam
  on target), never by the home-beam direction.
- The QLC+ workspace XML schema is **identical between QLC+ 4.14.4 and
  5.2.1**; the export version selector only stamps `<Creator><Version>`.

## Current state (update when it changes)

As of 2026-11-21: **v1.5.5 is the latest release** (tag `v1.5.5` at
`aa18bbe`, 2026-10-13, published as Latest). v1.5.0 was skipped: its
alpha shipped 2026-07-27, the final never did, and 1.5.5 carries the
1.5 work plus the hardening. **In progress: v1.5.6 housekeeping** on
branch `v1.5.6-housekeeping` (ROADMAP v1.5.6): the cleanup commits
are done (dead code, unused imports, pandas, docs hygiene, multi-group
stage 5); the "needs a decision" list is being worked one item at a
time. Next feature milestone: **v1.6 stage refinement**, a new branch
off `main`. The rig-blocked checks (bench pre-flight, INVERT DMX, the
LTC bench, busking against a real node) are post-release verification
in ROADMAP's "v1.5.0 release gate" section.

Ground rules for fix and cleanup work (from v1.5.5, still in force):
no rendered-pixel changes from Linux (win32 goldens only regenerate on
Windows), and every export hash change is named in the CHANGELOG.

History: the dated session notes (July to November 2026) were
condensed into the facts below on 2026-11-21; the full log is
`git show 8ed6258:CLAUDE.md`. Per-feature decisions and status logs
live in the plan docs (`docs/*-plan.md`; finished ones in
`docs/archive/`, indexed by its README). Docs older than 2026-07-14
use the OLD milestone numbers (old v1.6 timeline = v1.7, old v1.7 sync
engine = v1.8). Pattern worth remembering from the v1.5 desk checks:
the engine maths was right every time and every defect was the UI
misreporting state, so a green suite does not mean a working surface.

## Subsystem facts and traps

### Tests and environment

- Linux env: `~/miniforge3/envs/lichtmaschine/bin/python` (no
  `python` on PATH). New PC: `pip install -r requirements.txt`
  (pytest-timeout is in it; the suite's 120 s budget needs it).
- `pytest tests/unit -n auto` and `tests/e2e -n auto`; `tests/visual`
  SERIAL, and never regenerate goldens under `-n` (tests/README.md).
  Run anything file-sized with `-n auto`: ThemeManager.apply cost
  accumulates when whole UI files run serially in one process.
- `QMenu.exec` freezes the suite silently (guarded; qt-gotchas #7 has
  the py-spy recipe). `processEvents()` never delivers DeferredDelete,
  so a suite-wide autouse fixture flushes it (qt-gotchas #9).
- Anything that destroys a MainWindow without closing it must call
  `MainWindow.wait_for_background_workers()` first (the autosave
  QThread abort of the 1.5.5 release run).
- GL tests: the Windows OFFSCREEN platform never initialises a
  QOpenGLWidget (`isValid()` False), so skip on that, not on
  `context() is None`; the Windows desk has a real standalone moderngl
  context (GL 3.3). On Mesa, `simple_framebuffer` leaves
  GL_INVALID_OPERATION behind: drain `ctx.error` first. Several GL test
  processes at once can crash the Windows driver. Two live standalone
  moderngl contexts on one thread are unsafe.
- Python locks are not fair: bound the writers in concurrency tests.
- Export hashes: `PYTHONHASHSEED=0 python scripts/export_hash_check.py
  out.txt` covers the demo RIGS only; hash the demo SHOWS with
  `main.py export demos/shows/<x>.lms --out ...`. The export draws only
  from its own `random.Random` instances. Compare base vs head on ONE
  machine: the user GDTF dir and the gitignored `gdtf_fixtures/` shadow
  definitions, and a git worktree lacks `gdtf_fixtures/`.
- `tests/conftest.py` excludes `gdtf_fixtures/` and the user library
  sources from the hermetic suite (the unwrapped function is parked as
  `fl._real_fixture_search_dirs`).
- Known one-off CI intermittents (steps run `-v` to name a repeat):
  Ubuntu `test_screensaver.py::test_grid_and_corner_marks_are_painted`
  read a 239 background once; a Windows e2e run died silently once.
- PERF RULE: anything on a timer that walks the whole config must be
  measured against a ~1 MB project, not the demos.

### Shell, Qt, theme, i18n

- There is NO QMenuBar: the topbar (`gui/widgets/topbar.py`) carries
  SETUP/SHOW/LIVE nav driving a tab-bar-hidden QTabWidget by index;
  gui.py inserts Edit/Render into `overflow_menu`. Shortcuts only work
  because `register_menu_shortcuts` re-adds them to the window.
- Themes are token dicts (`gui/theme_tokens.py`) rendered through
  `resources/themes/theme.qss.template`; there are no .qss files.
  Accent Glutorange #F0562E, radius 0, Barlow UI font (fonts in
  `resources/fonts/`, registered by `gui/fonts.py`; visual tests
  register them too, so goldens pin real glyphs). The app-wide
  `QWidget { font-family }` rule overrides `setFont`: a widget that
  needs another family pins it in its own stylesheet. Letter-spacing
  and caps go through `gui/typography.py` (QSS cannot).
- ALL QSettings access goes through `utils/app_settings.app_settings()`;
  identity lives in `utils/app_identity.py`.
- i18n: shell strings are literal
  `QCoreApplication.translate("Shell", "...")` calls (pylupdate6 cannot
  see wrappers or aliases); `translations/lichtmaschine_de.ts` is the
  source of truth, `scripts/update_translations.py` refreshes it.
- UI separator is " · ". Song combo itemData carries the raw name:
  never read `currentText` for the key.
- `main.py` dispatches CLI subcommands (`export`, `morph`) BEFORE any
  PyQt import; keep new subcommands above the Qt imports. The packaged
  exe (`lichtmaschine.spec`) is windowed, so console output is
  invisible.

### Data model and persistence

- SHOW (setlist) -> SONGS -> PARTS. `Song` was `Show` (`config.songs`);
  YAML writes `songs:` + `setlist:` and loads legacy `shows:` forever
  (fixture: `tests/fixtures/legacy_band_midsize.yaml`).
- **Multi-group fixtures:** `Fixture.groups` is the source of truth;
  there is NO `fixture.group` (removed in v1.5.6, stage 5 of
  `docs/multi-group-fixtures-plan.md`). Read the primary with
  `config.models.primary_group_name` / `primary_group`, write
  `fixture.groups`. groups[0] is primary (data colour, orientation,
  role, export intensity: first-group-wins). Legacy `group:` loads
  forever; save writes only `groups` (CSV/JSON fixture lists still
  carry the primary as `group`). Indexed targets (`Group:N`) index into
  that group's derived order. Two groups' lanes writing the same
  channel is the output arbiter's job: lane order wins.
- `Configuration.save` writes a temp file and swaps it in; unknown keys
  from newer files are skipped and listed in Help > Warnings. libyaml C
  dumper/loader; autosave snapshots on the UI thread and writes on a
  worker (`utils/autosave.write_snapshot`); the dirty fingerprint is
  pickle-based.
- Fixture definitions: one canonical `FixtureDefinition`
  (`utils/fixture_library.py`); GDTF via `utils/gdtf_loader.py`. Search
  priority: user GDTF > `gdtf_fixtures/` > `custom_fixtures/` > user
  QXF > QLC+ dirs. Every rescan calls `invalidate_fixture_caches()`,
  which clears caches in other modules BY NAME (vulture reports those
  clearers as unused: keep them). GDTF Share files must never be
  committed or bundled; the Share password lives only in keyring.
  GDTF auto-pull keeps its gates (exact identity + channel footprint +
  geometry), because a GDTF shadow swaps the whole definition.
- Positions: ids are namespaced `preset:` / `preset:element:` /
  `mark:`. The Stage tab PLACES marks, the movement dialog PICKS one,
  the Live POSITION pool AIMS movers at one. Movement targets resolve
  plane > spot > point > manual, and a dangling spot name falls
  through to the world point.
- Morph (`utils/morph/`, authority `docs/design-show-morphing.md`):
  morphed lane ids are DERIVED for determinism; the compile MUTATES
  config B in two reported cases, so deepcopy B for dry runs. Patchbay
  edges are GROUP-keyed (format 2); `migrate_legacy_edges` collapses
  format 1 and broadens coverage (union semantics).

### Output and playback

- ONE `OutputArbiter` (`utils/artnet/arbiter.py`) owns the one
  ArtNetSender and a 44 Hz pull loop; layers carry channel CLAIM masks.
  The playback slot is EXCLUSIVE (timeline XOR Auto, contended at PLAY
  time; a second producer is refused, and a producer that never held
  the slot must never stop the shared loop). The SHELL owns policy on
  the shared arbiter (`MainWindow.output_arbiter()`), adapters only on
  private ones. Pause layer sits below playback, the Live busk layer on
  top; Live composites write `state.intensities` + `state.shapes`
  (there is no effect engine slot in production). Native output is
  ArtNet only.
- `get_channels_by_property` matches preset OR group, so RGB channels
  land in `color_wheel_channels` (documented in
  `tests/unit/test_dmx_masks.py`).
- Timeline edits during playback: one
  `utils/timeline_edit_lock.TIMELINE_EDIT_LOCK`; never take the
  controller's `_render_lock` inside it.
- LTC: `MainWindow.ltc_service()` / `arm_ltc_chase()` own policy; the
  STOP button goes through `_on_stop_clicked` (operator stop disarms),
  runner stops bypass it; NO_SIGNAL never stops the show.
- The visualizer feed is off by default; the viewer's ArtNet listener
  locks each universe to one source (loopback mirror wins).

### Geometry and visualizer

(The coordinate-frame and mounting-preset facts are in "Non-obvious
facts" above; `docs/coordinate-frames-and-orientation.md` has the
detail.)

- GDTF meshes are authored HANGING; `gdtf_draw_plan` canonicalizes
  posture by tree z-extent. The GDTF chain is the real yoke:
  `solver_to_gdtf_axes` converts solver degrees at the GDTF chassis
  boundary and in the arbiter (hardware packets only; mirror and
  callbacks stay in solver convention). Physical pan/tilt rotate
  opposite-handed about the GDTF axes (hardware-verified on a Hero
  Spot 60). `.qxf` movers get the synthetic yoke
  (`utils/yoke.fixture_yoke`) and the `.qxw` export aims like native
  output (`export_aim_dmx`).
- The composable renderer is the default; `FIXTURE_RENDERER=legacy`
  and failed capability detection fall back to the legacy classes in
  `visualizer/renderer/fixtures.py`. `QLC_GDTF_MESHES=0` disables GDTF
  meshes. `RenderEngine` replays its last state on every
  `initializeGL`.

### Gig kit (machine-local, never committed)

`shoo_bee_doom/` (the real SBD project, venue configs, per-song LTC
WAVs, audio), `gdtf_fixtures/`, `dist/Lichtmaschine/` (rebuild:
`pyinstaller lichtmaschine.spec`) and the bench kit (`bench_kit.*`,
`tester.lms`, `scenes/bench/`) live only on the desk PC.
`retarget_heads.py` then `tame_head_envelopes.py` must re-run after
any re-morph, in that order; both match on `target_point`. Share
credentials sit in each machine's Windows vault (re-enter via
Settings > GDTF Share Account).
