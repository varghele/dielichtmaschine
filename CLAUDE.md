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
  frames, the two bugs fixed 2026-07-12, and the open yoke question
  with its hardware protocol.
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
Theme roles added: lane-chip (+ QComboBox variant + lane-chip-accent),
segment/card groups, destructive-outline, QLineEdit[state="invalid"],
accent tint on output-select:checked.

**Polish round (2026-07-10/11, same branch):** timeline block strip
zone above the dimmer band (shared sublane_band_geometry - canvas,
blocks and header labels all consume it), row-aligned DIM/COL labels,
accent + BLOCK chip, lane names sized from font metrics + group
subtitle; Live BPM wears #TimeReadout; show-directory button removed
(File > Import Legacy CSV Songs replaces it); spike marks (
resources/stageplot/spike-mark.svg) render on stage canvas + printed
plot in accent, plot fonts moved to Barlow; multi-group rows get
candy-stripe tints; the Live POSITION pool is PRESETS + MARKS
(movers-only, config-pruned): computed presets from the stage setup
(utils/position_presets.py - CENTRE/AUDIENCE/CROSS/FAN OUT/CEILING +
one per placed drum-riser/keys/foh/mic-stand element) above the spike
marks, position ids namespaced preset:/preset:element:/mark: with
legacy bare spot names migrated on config sync (shipped 2026-07-11,
docs/position-presets-plan.md; targets are data-only until v1.5a
focus geometry + the output arbiter).

**Multi-group fixtures shipped (2026-07-10, same branch, stages 1-4 of
docs/multi-group-fixtures-plan.md):** `Fixture.groups: List[str]` is
the membership source of truth; `fixture.group` is a compat PROPERTY
whose setter REPLACES the whole list (UI add/remove paths must mutate
`fixture.groups` directly - the number one trap). groups[0] = primary
(drives data colour, orientation, role, export intensity - locked
first-group-wins). Legacy `group:` YAML loads forever; save dual-writes
both keys until plan stage 5 (NOT done - waits a release). Group
derivation puts a fixture in every listed group; indexed targets
(Group:N) index into that group's derived order. Export emits
per-group ChannelsGroups (QLC+ tolerates shared channels), patch
elements once, show tracks bucket under the primary. Conflicting
simultaneous blocks from two groups' lanes = the output arbiter's
problem: lane-order-wins, per docs/output-sync-plan.md (the output/
sync architecture was decided 2026-07-11 - arbiter layers + channel
masks, exclusive playback slot, dimmer-only HTP, conductor clock,
phases 0-4; todo.md now only carries roadmap pull-in candidates).
The Live tab (3b busking surface, earlier
in the pass) has BPM/TAP, SHOW/LIVE mode, 5 palette pools (effects =
riff library, scenes = scenes/scene_library.py), dual queue. Tests:
pytest-xdist is set up - `pytest tests/unit -n auto` (~2 min); visual
stays serial, never regen goldens under -n (tests/README.md). Also
new: main window nav is SETUP/SHOW/LIVE with Auto inside LIVE.

**Output arbiter phases 0-3 shipped (2026-07-11, same branch,
docs/output-sync-plan.md has status + hashes):** ONE OutputArbiter
(utils/artnet/arbiter.py) owns the one ArtNetSender and a 44 Hz pull
loop; DMXManager tracks channel CLAIM MASKS (get_frame -> values +
mask); ShowsArtNetController and AutoDMXController are layer adapters
on an EXCLUSIVE playback slot (timeline XOR auto - second producer is
REFUSED, and a producer that never held the slot must never stop the
shared loop); the Live busk surface outputs for real via
utils/artnet/live_layer.py (colours/submasters/flash/strobe,
busk-on-top, RELEASE ALL = mask fall-through; positions and
effects/scenes still data-only). Live GRAND/DBO drive the arbiter's
post-merge master stage; idle floor follows the nav section (editor
visible, LIVE blackout) - the SHELL owns policy on the shared
arbiter, adapters only on private ones. MainWindow.output_arbiter()
is the shared accessor; the arbiter forwards fixture maps to map-less
layers. Gotcha: get_channels_by_property matches preset OR group, so
RGB channels (group "Colour") land in color_wheel_channels and the
safe-idle wheel-open write claims them at 0 (documented in
tests/unit/test_dmx_masks.py). Phase 4 (conductor, pause look,
setlist runner) stays v1.7.

**Mirrored stage + mounting presets fixed (2026-07-12, same branch):**
two long-standing coordinate bugs the user spotted ("everything is
flipped"; "hanging fixtures behave like wall-back"). (1) The scene
frame swaps two axes = a REFLECTION, so the 3D view was a mirror of
the stage and the default camera sat upstage; corrected with one
DISPLAY_FLIP on the view matrix (DMX untouched, hash-verified). (2)
The mounting-preset table was rewritten to a "beam-direction" set
(hanging = beam straight down, etc.). **This half (2) was WRONG and was
REVERTED 2026-07-13** - see the next note; the DISPLAY_FLIP half (1)
stands. The write-up is in
`docs/coordinate-frames-and-orientation.md` - start there.

**Mounting presets reverted (2026-07-13, same branch):** the 2026-07-12
"beam-direction" mounting table broke every mover rig that was correct
before the rebrand. Root cause: it treated a mounting preset as a
home-beam direction, but a preset is a BODY orientation - a mover aims
via the pan/tilt solve, so the home beam is irrelevant. Restored the
pre-rebrand values (`hanging` = pitch +90, chassis flip; `standing` =
pitch -90; walls back to yaw-only), verified by the user against real
fixtures. `migrate_orientation_angles` now corrects the 2026-07-12
values on load. Tests re-pinned: `TestMountingPresets` (values) +
`TestAimingEndToEnd` (closed-loop aim). **Export changes back for any
rig with movers** (mover-less rigs like theatre_static unaffected).
Still open (mixed rigs): a hanging PAR wants beam-down while a hanging
mover wants a vertical pan axis - one Euler triple can't do both;
per-fixture beam/base axes from GDTF are the real fix (ROADMAP v1.5a).
Follow-ups landed 2026-07-13: (a) GDTF meshes are authored HANGING
(tree extends -Z below the attachment origin) while the chassis frame
is standing-authored, so the presets flipped them upside down -
build_draw_plan now canonicalizes posture by tree z-extent
(gdtf_draw_plan._canonicalize_posture); (b) wall_back/wall_front
carried each other's yaw in the pre-rebrand table - swapped
(user-verified), migration heals both old values; (c) the stage
canvas's custom-orientation ring now compares against the preset
triple instead of "any non-zero pitch/roll"; (d) the GDTF chain is the
REAL yoke (beam along the pan axis at tilt centre) while the solver
aims beam-perpendicular - solver degrees fed into the chain missed
every spot, so gdtf_draw_plan.solver_to_gdtf_axes converts at the
GDTF chassis boundary, pinned by hit-the-spot closed-loop tests; (e)
the OUTPUT arbiter applies the same conversion to hardware packets
only (utils/yoke, mirror/callback stay solver-convention); (f)
HARDWARE-VERIFIED on a real Hero Spot 60 (bench protocol, section 4-5
of the coordinate doc): positive physical pan/tilt rotates OPPOSITE
to right-handed about the GDTF axis nodes - negated in
DrawItem.compose + solver_to_gdtf_axes; three raw poses and four
full-pipeline aim targets all landed. The yoke finding is CLOSED for
GDTF movers; per-fixture axes for mixed PAR/mover rigs remain v1.5a.

**Solo pull-ins (2026-07-12 evening, same branch):** two roadmap
items shipped while the user was away. (1) Headless export CLI (v1.3):
`python main.py export config.yaml --out x.qxw --qlc-version 5.2.1`
plus `--no-vc`/`--dark-mode`; main.py dispatches to
utils/export_cli.py BEFORE any PyQt import (keep new subcommands above
the Qt imports); no console-script entry because there is no pip
packaging, and the packaged exe is windowed so its console output is
invisible. (2) Configurable fixture library paths (v1.2): Settings >
Fixture Libraries... dialog, `library/user_gdtf_dir`/`user_qxf_dir`
keys (empty = app-data default from utils/app_identity.user_data_dir,
which app_logging.log_dir now shares), sources `user-gdtf`/`user-qxf`
in fixture_search_dirs (priority: user GDTF > gdtf_fixtures >
custom_fixtures > user QXF > QLC+ dirs), setters invalidate the
definition cache, tests/conftest.py filters the user sources from the
hermetic suite and parks the unwrapped function as
`fl._real_fixture_search_dirs`. GDTF Share Phase 4 is unblocked again.
The fixture browser's manufacturer/model separator became " · " (was
an em-dash, banned in UI copy).

**Live position palettes make light (2026-07-12, same branch):**
pulled forward from v1.5a/v1.8 (GDTF Share Phase 4 deferred in trade).
Per-group policy: LiveState.positions is Dict[group -> position id]
(stage_position applies to the selected groups, second touch on a
fully-held id releases those groups; position_labels carries id ->
label for the programmer bar; old single-slot position/position_label
attributes are GONE). The busk layer (utils/artnet/live_layer.py)
aims each holding mover group via calculate_pan_tilt/pan_tilt_to_dmx,
claiming pan+tilt+fines-to-zero ONLY (pre-aim dark works; release =
mask fall-through). Ranges: FixtureChannelMap.pan_range/tilt_range
now read the definition's <Physical><Focus> (parsed into
FixtureDefinition.pan_max/tilt_max, exposed via to_legacy_dict
'physical' key; 540/270 fallback when absent/0) and the native
playback spot/plane aiming uses them too - the EXPORT pipeline still
assumes 540/270 (byte-identical invariant; range-aware export is a
v1.5a leftover). group_has_movers lives in utils/position_presets.py
(live_tab aliases it). Manual check pending: aim palettes at real
movers/visualizer (todo.md).

**Output shell polish (2026-07-12, same branch, commits 5820f77 ·
5170f90 · bb8e046):** Live fade row carries OUT + SYNC status chips
(#OutputReadout QSS id; OUT polls arbiter.status() via
LiveTab.set_status_arbiter at 500 ms - wire truth, activity dot,
* marker when universes are configured E1.31/DMX USB since native
output is ARTNET-ONLY; SYNC INT until v1.7). DBO is
destructive-outline (filled red only when :checked);
output-select:pressed fills accent (FLASH). Topbar chips renamed
OUTPUT + VISUALIZER: OUTPUT is the master switch and the playback
slot is contended at PLAY time (ShowsArtNetController acquires in
start_playback, releases in stop_playback - enable-to-busk never
locks Auto out; teardown never stops a loop another owner streams
through). VISUALIZER chip = labelled OPEN/STOP button that starts the
TCP feed AND launches the viewer in one press; tcp_enabled now
defaults False and toggle_tcp derives from tcp_server.is_running()
(the stale-flag double-press bug). The standalone visualizer frame is
rebranded (visualizer/main.py: brand boot fonts+icon+theme, #TopBar
header with glyph/wordmark/chips replacing the QToolBar, token-driven
mono statusbar; tests/unit/test_visualizer_frame.py stubs
engine/listener/client - no GL, no sockets). PENDING MANUAL CHECKS
(need hardware or a desktop session): busk a colour over a playing
show against a real node/visualizer, the VISUALIZER OPEN flow
end-to-end (process launch is stubbed in tests), and the rebranded
viewer frame under a live GL context.
