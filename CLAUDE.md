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
  Y depth centered (negative = front/audience), Z height. The 3D
  renderer is Y-up: stage X -> world X, stage Z (height) -> world Y,
  stage Y -> world Z (front = -Z). `autogen/spatial.py` uses its own
  0..D depth convention for stage planes - do not mix them up.
- The QLC+ workspace XML schema is **identical between QLC+ 4.14.4 and
  5.2.1**; the export version selector only stamps `<Creator><Version>`.

## Current state (update when it changes)

As of 2026-07-06: **v1.1 "Stage tab and rig data" is reopened.** All 8
items shipped a first pass on branch `v1.1-stage-rig-data` (894 tests
green, nothing pushed), but stage plot export and stage layers have
gaps in real-world use and are un-ticked in ROADMAP.md until a
follow-up lands. No v1.1.0 tag yet.

**Direction change (July 2026):** the QLC+ extension route was
rejected upstream; the app continues as a standalone tool. Native
ArtNet playback is the primary path, `.qxw` export stays as interop.
ROADMAP.md was restructured accordingly: new v1.2 (GDTF import spike
+ GDTF Share/MVR assessment + OSC support) and new v1.8 (live mode
control panel); former v1.2-v1.9 renumbered to v1.3-v1.11 (movement /
morphing are now v1.5a / v1.5b, live ops + clock sync is v1.7 - the
LTC/SMPTE timecode item lives there).

**GDTF decision (2026-07-06):** GDTF becomes the primary fixture
format with `.qxf` kept in parallel as fallback and QLC+ interop;
GDTF's embedded 3D models will render in the visualizer. Full
implementation plan (phases 0-4, architecture findings, GDTF Share
licensing constraints) in `docs/gdtf-integration-plan.md`; the v1.2
section of ROADMAP.md was rewritten to match. Key constraint: GDTF
Share files must never be bundled or committed (terms of use); test
and demo `.gdtf` files are authored in-repo.

**GDTF phases 0-2 shipped (2026-07-06, same branch):** Phase 0 -
all fixture-definition discovery/parsing/caching unified in
`utils/fixture_library.py` (canonical `FixtureDefinition`, byte-identical
export proven via `scripts/export_hash_check.py`; needs PYTHONHASHSEED=0
+ seeded RNG because `preset_scenes_to_xml` samples the global RNG
unseeded). Phase 1 - `utils/gdtf_loader.py` transpiles .gdtf (pygdtf)
into the same canonical model; `gdtf_fixtures/` scanned first so GDTF
wins identity clashes. Phase 2 - `Fixture.definition_source` +
`gdtf_fixture_type_id` (YAML schema bump, defaults keep old configs
loading), companion .qxf generation on export for fixtures QLC+ lacks.
Phases 1-3 are fully shipped as of 2026-07-06 evening: the spike gate
passed against real Share downloads (decision note
docs/gdtf-coverage-note.md; fetch via scripts/gdtf_share_fetch.py,
files in gitignored gdtf_fixtures/), mode-name reconciliation runs on
config load, and GDTF GLB models render in the visualizer
(utils/gdtf_mesh.py + visualizer/renderer/gdtf_draw_plan.py +
gdtf_mesh_chassis.py, shared GL resources, per-platform golden,
QLC_GDTF_MESHES=0 kill switch; verified end to end on the MagicBlade
R). Open: manual QLC+ runtime check of a companion .qxf, Phase 4
(Share browser UI) unstarted, and the test suite globally excludes
gdtf_fixtures/ (tests/conftest.py) so local Share files never shadow
bundled test definitions.

**Rebrand shipped (2026-07-07, branch `v1.2-rebrand`):** the product
is **Die Lichtmaschine** (dielichtmaschine.de). Design North Star in
`design_handoff_lichtmaschine_app/`, execution plan + follow-ups in
`docs/rebranding-plan.md`. Identity lives in `utils/app_identity.py`;
ALL QSettings access goes through `utils/app_settings.py`
`app_settings()` (one-shot migration from the old QLCShowCreator
store). Themes are token dicts (`gui/theme_tokens.py`) rendered
through `resources/themes/theme.qss.template` - there are no .qss
files anymore; accent Glutorange #F0562E, radius 0, Barlow UI font
(fonts ship in resources/fonts/, registered by gui/fonts.py; visual
tests register them via tests/visual/conftest.py, so goldens pin real
glyphs - regenerate accordingly). Structured logging
(utils/app_logging.py, QLC_LOG_DIR override) + crash dialog
(gui/dialogs/crash_dialog.py) are wired in main.py. Packaging:
`lichtmaschine.spec`. Pending user actions: GitHub repo rename to
`dielichtmaschine`, demo media regeneration. No em-dashes rule now
also covers UI copy; separator is " · ".

**North Star screens shipped (2026-07-07 late,
docs/northstar-screens-plan.md):** Home landing page
(gui/widgets/home_screen.py, hosted in Ui_MainWindow's page_stack;
recents via utils/app_settings record_recent_config/recent_configs),
screensaver (gui/screens/screensaver.py, View menu, set_phase for
deterministic tests), stageplot SVG symbols (resources/stageplot/,
routed in gui/widgets/fixture_icons.py via fixture_type kwarg with
legacy-primitive fallback), lane sub-row labels + master-timeline
region bands. Still feature-milestone work, NOT rebrand leftovers:
Live 3a/3b screens, Morph/Venue-check/Patch-flow, truss library,
.lms format. Gotcha pinned by the screensaver work: the app-wide QSS
`QWidget { font-family }` rule overrides setFont families - widgets
needing a non-Barlow family must pin it in their own stylesheet.

**Shell pass shipped (2026-07-07, same branch,
docs/shell-pass-plan.md):** there is NO QMenuBar anymore - the 48px
topbar (gui/widgets/topbar.py) carries wordmark, SETUP/SHOW/LIVE nav
(LIVE hosts the Live busking surface and Auto as sibling subnav
screens) + subnav row driving the tab-bar-hidden QTabWidget by index
(Ctrl+L etc. unchanged), icon buttons, a MENU overflow QMenu (gui.py inserts
Edit/Render into `overflow_menu`, not `menubar`), filename readout,
and the status chips. Shortcuts only work because
register_menu_shortcuts re-adds them to the window - keep that in
mind when adding menu actions. Typography: use gui/typography.py
(display/mono fonts, caps labels; QSS can't do letter-spacing or
text-transform). i18n: shell strings use literal
QCoreApplication.translate("Shell", "...") calls - pylupdate6 cannot
see literals hidden behind wrapper functions or aliases;
translations/lichtmaschine_de.ts is source of truth,
scripts/update_translations.py refreshes it (compiling .qm needs an
lrelease, not in the env).

**Setlist + timeline v3 shipped (2026-07-10, same branch, second
design pass against screens 05b/06b):** the data model is
SHOW(SETLIST) -> SONGS -> PARTS. `Show` was renamed `Song`
(config.songs); `Setlist`/`SetlistEntry`/`SongTrigger`/`PauseLook` are
new in config/models.py; YAML writes `songs:` + `setlist:` and loads
legacy `shows:` forever (synthesized setlist; demo YAMLs deliberately
stay legacy as fixtures). Export is byte-identical (hash-checked).
Structure tab = setlist rail (numbered cards, triggers, pause rows,
sync segment, drag reorder) + song editor centre + trigger/pause-look
inspector (LEARN disabled until the v1.7 engine; analysis bars read
the session-only autogen GenerationReport). Timeline = compact single
toolbar row (percentage swing 0-100), 260px shared lane headers
(HEADER_COLUMN_WIDTH in timeline_widget.py, sub-lane labels in the
header), blocks as tinted clips (part colour, header strip with bar
range, labelled sub-rows), parts band + compact audio row + accent
playhead (opt-in compact=True so the Structure tab's embedded copies
are unchanged), block inspector rows (NO overlap row until v1.6),
scenes section in the riff rail (drag mime application/x-lm-scene,
drop deferred), song selector numbered by setlist (itemData carries
the raw name - never read currentText for the key). Plans with status
+ commit hashes: docs/timeline-v3-plan.md, docs/setlist-plan.md.
Theme roles added: lane-chip (+ QComboBox variant), segment/card
groups, destructive-outline, QLineEdit[state="invalid"], accent tint
on output-select:checked. The Live tab (3b busking surface, earlier
in the pass) has BPM/TAP, SHOW/LIVE mode, 5 palette pools (effects =
riff library, scenes = scenes/scene_library.py), dual queue - all
in-memory, no output engine yet. Tests: pytest-xdist is set up -
`pytest tests/unit -n auto` (~2 min); visual stays serial, never
regen goldens under -n (tests/README.md). Known pre-existing failure:
test_fixture_browser TestMultiAdd (modal-guard, tracked). Also new:
main window nav is SETUP/SHOW/LIVE with Auto inside LIVE.
