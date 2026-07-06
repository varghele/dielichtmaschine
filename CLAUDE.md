# CLAUDE.md

Working notes for Claude Code sessions on this repo. The user is
varghele; QLC+ Show Creator is their hobby project (visual show
authoring for QLC+, PyQt6 + ModernGL, developed primarily on Windows).

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

As of 2026-07-06: **v1.1 "Stage tab and rig data" is complete** (all 8
roadmap items) on branch `v1.1-stage-rig-data`, 894 tests green,
nothing pushed. Waiting on the user to merge to `main` and decide on
tagging `v1.1.0` (flow: `docs/releasing.md` - retitle `[Unreleased]`,
bump `_version.py`; CI has a dispatch trigger to test builds before
tagging). Next milestone: v1.2 "Authoring polish". LTC/SMPTE timecode
input was added to the v1.6 milestone.
