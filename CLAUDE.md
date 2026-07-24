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
R). Open: manual QLC+ runtime check of a companion .qxf, and the test
suite globally excludes gdtf_fixtures/ (tests/conftest.py) so local
Share files never shadow bundled test definitions. Phase 4 (Share
browser) SHIPPED 2026-07-15 on v1.4-standalone-switch:
utils/gdtf_share.py (client, 24h catalog cache that serves stale
offline, ranked search, rid-pinned downloads; username in QSettings,
password ONLY via keyring with session-only fallback), GDTF SHARE tab
in the fixture browser (gui/dialogs/gdtf_share_pane.py, worker-thread
network, downloads into the user GDTF dir + auto-rescan), Settings >
GDTF Share Account with TEST LOGIN. Tests fake both the HTTP session
and the keyring module (tests/unit/test_gdtf_share.py) - a real-login
manual check sits in todo.md's gate list.

**Rebrand shipped (2026-07-07, branch `v1.2-rebrand`):** the product
is **Die Lichtmaschine** (dielichtmaschine.de). Design North Star in
`docs/design/`, execution plan + follow-ups in
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
legacy `shows:` forever (synthesized setlist; the legacy-load fixture
is tests/fixtures/legacy_band_midsize.yaml - the demos themselves
converted to .lms 2026-07-16). Export is byte-identical (hash-checked).
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
(gdtf_draw_plan._canonicalize_posture); (b) ALL FOUR wall presets
carried their opposite's yaw in the pre-rebrand table - swapped
(user-verified, back/front then left/right), migration heals the old
values; (c) the stage
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
full-pipeline aim targets all landed, standing AND hanging. The yoke
finding is CLOSED: .qxf movers get the synthetic standard yoke
(utils/yoke.fixture_yoke) and the .qxw export aims like native output
(export_aim_dmx in the three to_xml sites - spot targets, preset
scenes, VC XY-pads; mover-less rigs stay byte-identical). Movement-pattern
export closed 2026-07-14: sequence steps compute in solver DMX space
and convert whole through the yoke (utils/yoke.convert_solver_dmx,
test_export_movement_yoke.py). Last v1.5a sliver: per-fixture
DMX-direction invert flags.

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

**Roadmap restructured for release (2026-07-14):** the next tag is
**v1.4.0 "the standalone switch"** - LTC/SMPTE input INCLUDING setlist
SMPTE triggering (songs fire when incoming timecode reaches their
start time, playhead chases; the SMPTE slice of the trigger engine
pulled forward), GDTF Share Phase 4, MVR import/export (promoted from
evaluation), CSV lighting-table import (column mapping), diagnostics
panel + silent-fallback audit; gated on todo.md's manual hardware
checks. **v1.5.0** follows after focus geometry + morphing (v1.5a/b).
v1.1, v1.2, v1.3 are CLOSED. Stage refinement (reopened v1.1 gaps,
truss segment tiling, verify+refine truss docking, stage-setup
workflow pass) is the new v1.6; everything after slid by one:
timeline ergonomics v1.7, live ops + clock sync v1.8 (OSC folded in),
control panel v1.9, autogen v1.10, Auto hardening v1.11, visualizer
breadth v1.12 (+ truss 3D models). Crash telemetry moved to
out-of-scope. Docs and code comments predating 2026-07-14 may use the
OLD numbers (old v1.7 sync engine = new v1.8, old v1.6 timeline = new
v1.7); UI strings were made number-agnostic. Branch plan:
v1.2-rebrand merges to main untagged once the gate checks pass, then
work continues on v1.4-standalone-switch. LTC output and OSC are
explicitly NOT v1.4 (user has no LTC output on the desk; OSC "can
move further back").

**LTC chase shipped (2026-07-14, same day):** all four phases of
docs/ltc-plan.md. utils/timecode/ = tc.py (FRAME-COUNT math, DF
vectors pinned), generator.py (independent bit table, write_ltc_wav
IS the bench signal source - no TC hardware on the desk), ltc.py
(streaming biphase-mark decoder, rate-agnostic, sync word 0xBFFC
arrival-packed), chase.py (linear fit, lock/freewheel/jump,
injectable clocks everywhere), runner.py (SMPTE windows ->
duck-typed transport; NO_SIGNAL never stops the show).
audio/ltc_input.py = LTCInputService (per-drain monotonic anchoring
so audio-clock drift can't accumulate; construction never opens a
stream). Shell: MainWindow.ltc_service()/arm_ltc_chase() own policy
(arbiter pattern), ShowsTab.chase_transport() + set_chase_armed
(operator STOP disarms via hook, runner stops bypass it - the STOP
button now goes through _on_stop_clicked, NOT _stop_playback),
StructureTab ARM CHASE + device combo (SMPTE mode only,
sync_device_hint label is GONE), LiveTab.set_sync_status. Bench
checkpoint pending in todo.md. Two suite lessons the same day:
QMenu.exec froze the suite silently (guard now covers it, qt-gotchas
#7 has the py-spy diagnosis recipe) and ThemeManager.apply cost
ACCUMULATES when whole UI test files run serially in one process -
always -n auto for anything file-sized (tests/README.md rules).

**v1.4 sweep (2026-07-15, same branch):** four roadmap items shipped
in one day - GDTF Share Phase 4 (see the GDTF note above), Help >
Diagnostics (utils/diagnostics.py, guarded probes, copyable markdown
block), the silent-fallback audit (utils/user_warnings.py: warn() with
operation grouping + once-key folding, surfaced by Help > Warnings;
the WU print sites across export/library/config-load/output/render/
tabs route through it; export stays byte-identical - hash-checked),
and the CSV lighting-table wizard (utils/csv_table_import.py pure
logic + gui/dialogs/csv_import_wizard.py three-step dialog reusing
utils/fixture_io.apply_fixture_list; the topbar import button is now
an InstantPopup menu offering QLC+ workspace or CSV). MVR moved OUT
of v1.4 to the new lettered milestone v1.8b (user decision 2026-07-15:
an imported MVR must create/update stage geometry, which the v1.6
stage pass has to solve first) - so every v1.4 CODE item is done and
the milestone rests on todo.md's manual gate list. Suite: 2632+ unit,
e2e+visual green;
three stale goldens regenerated 2026-07-15 (structure tab device-hint
row removal, riff tags + dimmer-rudiment riffs) after diff review.

**v1.4.0 TAGGED (2026-07-15, evening):** the bench session was
postponed by the user - the todo.md gate list became post-release
verification (bench kit ready in the repo root: bench_kit.lms,
bench_ltc_25fps_01h.wav, bench_kit.qxw; findings land as patch
releases). v1.4-standalone-switch merged to main (--no-ff), tag
v1.4.0 pushed, GitHub repo renamed to dielichtmaschine (remote URLs,
env name, doc links all swept). Work continues on
**v1.5-focus-morphing** (v1.5a focus geometry + v1.5b morphing =
v1.5.0); the user is supplying a morphing-theory md to reconcile
against the ROADMAP v1.5a/b sections before planning.

**v1.5 code-complete (2026-07-16, branch `v1.5-focus-morphing`, ~19
commits, 2861 unit + 111 e2e/visual green):** the user's design doc
`docs/design-show-morphing.md` is the morphing authority;
`docs/focus-morphing-plan.md` is the task derivation with a CLOSED
status log recording every decision - read both before touching v1.5
code. Shipped: deterministic group topology (fixture_order/order_mode;
legacy configs snapshot, new groups spatial), stable lane ids, colour
palette roles (ColourBlock.palette_role + Song.palette/apply_palette +
editor role picker/EDIT PALETTE in the colour block dialog),
world-space movement targets (target_point everywhere; export gained
the world-plane path; Tools > Convert Movement to World Targets; AIM
click-to-aim on the Stage tab; spot/plane/point combo in the movement
editor), the WHOLE morph engine (utils/morph/: plan, compile, checker,
analysis_cache, preview, preflight + morph_cli; `python main.py morph`),
the patchbay + Morph to Venue flow (gui/dialogs/morph_patchbay.py +
gui/screens/morph_screen.py, per mockup 15-morph-patch-flow-6d;
REWORKED 2026-07-16 on the user's first desktop check: the modal
wizard became a page-stack SCREEN under Tools > Morph to Venue -
leaving keeps the in-progress plan, the menu resumes it, a project
load discards stale screens - and the patchbay got drag-and-drop
wiring alongside click-click plus the layout pass: names lead rows,
chips size to their text, arrow expanders, FlowLayout edge chips
via the promoted gui/widgets/flow_layout.py;
gui/dialogs/morph_wizard.py is GONE), the pre-flight
screen (gui/dialogs/preflight_dialog.py + utils/artnet/preflight_layer
on the arbiter's exclusive slot; capture -> Fixture.calibration ONLY;
export guard live in create_workspace + export CLI), per-fixture DMX
invert flags (orientation panel; wire+export boundaries only), and
Fixture.calibration. KEY TRAPS: morphed lane ids are DERIVED for
determinism; the morph compile MUTATES config B in two reported cases
(subset groups, default spots) - deepcopy B for dry runs; two live
standalone moderngl contexts on one thread are unsafe (preview renders
sequentially); the range-aware-export roadmap claim was STALE - the
export has aimed at real Focus ranges since the yoke work (pinned in
test_dmx_invert.py). Remaining for v1.5.0: the user's desktop/bench
checks (todo.md) + release ritual. Bench artifacts (tester.lms,
bench_kit.*, scenes/bench/) are untracked ON PURPOSE and live only on
the desk PC.

**Testing round on the recovered SBD project (2026-07-16, same
branch):** the user's real project (shoo_bee_doom/, untracked;
recovered from archive/conf_v7.yaml) exposed what demo-sized data
never could. Fixed: patchbay capability gating was a no-op on loaded
configs (now detected from definitions), the compile errored per
edge x song on per-song lanes (now skips silently), morphed songs
lost their audio reference, dimmer-only lanes were crushed in the
timeline grid (mute/solo unreachable), and three timer-driven
UI-thread costs made real projects stutter (libyaml C dumper/loader -
output text-identical, pinned; autosave snapshot-then-worker via
utils/autosave.write_snapshot; pickle-based dirty fingerprint).
Added: the Live tab's SHOW transport strip (LiveShowTransport adapter,
operator semantics - its STOP disarms an armed chase) and six
manual-authored house fixture .qxfs in custom_fixtures (Cameo
HydraBeam 4000 RGBW is modelled PER HEAD, 4x14ch per bar). PERF RULE
learned: anything on a timer that walks the whole config must be
measured against a ~1 MB project, not the demos.

**Testing round, second half (2026-07-16 evening, same branch):**
playback perf (the 30 FPS visual tick demanded 4.1 s of paint per
second: dirty-rect playhead strips bypassing the sublane-label update
hook, clip-culled grid painters with time-ordered early-break, the
audio waveform renders once into a cached pixmap, and the waveform
peak cache is atomic npz now - the old JSON cache was non-atomic and
a torn write forced re-analysis on every song load forever); GDTF
AUTO-PULL on project load (utils.gdtf_share.pull_missing_gdtf, worker
in gui._start_gdtf_autopull, gated on stored credentials +
gdtf_share/auto_pull; keep gates: exact internal identity + channel
footprint + geometry, because a GDTF shadow swaps the whole
definition); morph spot baking (a movement block aiming a NAMED spot
the target rig lacks bakes the SOURCE spot's position into
target_point; dmx_manager's resolution now falls through a dangling
spot name to the world point per the documented plane > spot > point
> manual chain); the morph adopts the SOURCE SETLIST when the target
has none (order, triggers, pause looks - the setlist IS the gig).
GIG KIT (all machine-local, gitignored, must be copied by hand):
shoo_bee_doom/ = SBD master (world-targeted, SMPTE triggers) +
stellwerk_hinten rig/morphed configs (venue-true geometry: hall
16x5m, 4m ceiling, 5x5m stage at 0.5m; builder + morph scripts with
TARGET_COMPRESS look-squeeze option) + ltc/ per-song 25fps WAVs
(song N = hour N, trigger at NN:00:02:00) + audio + rider PDF;
gdtf_fixtures/ = auto-pulled Share GDTFs (Hero Spot 60 + TourLED +
ROOT PARs and more - TourLED/ROOT PAR 4 shadow the manual .qxfs,
verified wire-compatible 2026-07-17); dist/Lichtmaschine/ =
the rehearsal .exe (rebuild: pyinstaller lichtmaschine.spec).
Share credentials live in the per-machine Windows vault - re-enter
via Settings > GDTF Share Account on any new PC.

**Gig-day additions (2026-07-17 afternoon, app code + gig data):**
the minimal pause-look engine shipped (utils/artnet/pause_layer.py on
the arbiter's pause slot, BELOW playback - the next LTC-fired song
covers it; gui._ltc_tick drives activate/clear from armed+is_playing;
disarm removes the layer; PauseLook gained mode "scene" + scene key)
and scenes carry mover aims (Scene.positions {group: position id},
rendered by the busk layer's position pass - held positions win - and
by the pause layer through the shared live_layer.aim_fixture_at_
position). Venue data: all 12 entries pause to stellwerk/Red Room at
level 100 until trigger; scenes/stellwerk/ grew to 18 (six Beams
scenes aim via mark:Spot1/Spot2/SpotLeft/FloorCentre + preset:cross/
audience; Red Room + Floor Party gained aims). Also that day: the
viewer's ArtNet listener got a per-universe source lock (loopback
mirror wins - the broadcast hw frame + solver mirror both arriving
locally flapped every mover between two poses at idle), timeline
playback finally receives stage planes, provenance persists through
the .lms serializer, shows_directory heals on load, and audio loading
bundles via audio_bundle_dir instead of makedirs-ing a foreign
shows_directory.

**Gig-prep night pass (2026-07-17, gig-data only, no app code):**
both .lms setlists are sync_mode smpte (make_ltc.py set triggers but
never sync_mode - ARM CHASE is hidden without it); all 12 ltc/ WAVs
decoder-verified (hour N, 25 fps, trigger inside file); every audio
ref is a basename resolving in shoo_bee_doom/audiofiles/ (three
C:/LICHT absolutes copied in, two empty refs filled). Head aims obey
the user's floor-or-stage rule via named venue spots (drag on site,
show follows): SpotLeft + Spot2 replace the two baked out-of-room
points (shoo_bee_doom/retarget_heads.py), FloorCentre/StageCentre
rescue geometry-impossible far throws and amplitudes are scaled into
the room per block (shoo_bee_doom/tame_head_envelopes.py; both
scripts MUST RE-RUN after any re-morph, in that order). Verified by
replaying playback math: 0 aim misses, 0 dominant side/ceiling
blocks, per-song 75-95% of sampled beams land on stage/floor/
backdrop. scenes/stellwerk/ = 12-scene busk cluster for the support
band (smoke-tested through LiveBuskLayer). Two v1.5 bugs exposed and
parked in todo.md: shows playback never gets stage planes;
LightBlock.provenance is dropped by the compact serializer.
Pre-pass backups: shoo_bee_doom/backup_20260717/.

**todo.md folded into ROADMAP and deleted (2026-07-23):** the working
agenda had drifted a release behind (header still said "next tag
v1.4.0", carried the completed v1.4 build-order as history). Its live
remainder - the v1.5.0 desktop checks, the release ritual, and the
post-release hardware verification - moved into a new **"## v1.5.0
release gate"** section in ROADMAP.md (after v1.5b), and the deferred
non-blocking polish (song-switch waveform stall, structure-rail
rebuild cost, per-fixture mixed-rig beam axes, LIVE pool label
truncation) moved to ROADMAP v1.6. Any historical "todo.md" mention
above or in docs/ refers to that gate list or the v1.6 deferred block
now. The 2026-07-16 morphing sweep also shipped a run of v1.5
hardening (per-group Live pools, the SMPTE busk cluster with its own
input picker, the Song lock, the Auto input meter + gain, the
native-sample-rate audio fallback, the branded About dialog) - all in
CHANGELOG [Unreleased], all CI-green on origin; only geometry/morph
code-completeness was the 2026-07-16 line.

**Live EFFECTS became composites + a COLOUR FX pool (2026-07-24):**
the per-group EFFECTS pool (riff-per-group, its own engine slot) was
REPLACED by COMPOSITE macros - a composite is a fixed (intensity FX,
movement shape) pair (`COMPOSITE_EFFECTS` in gui/tabs/live_tab.py,
split LOOPS/HITS) and `stage_composite` WRITES `state.intensities` +
`state.shapes` for the selected groups, so composites render through
the SURVIVING intensity + movement binders - there is NO effect
engine slot driven by production anymore (the engine still supports
"effect" as a generic slot; the low-level tests use it). Rationale:
an effect-as-riff-with-movement fights the busk position aim (which
overrides engine movement) and swings raw pan/tilt around centre, not
the aimed target - the macro reuses the correct dimmer + world-
anchored-movement rendering. Colour stays with the swatch; a new
COLOUR FX subsection under the colour pool (`COLOUR_FX`, currently
RAINBOW) writes `state.colour_fx` per group and renders as a moving
procedural hue in utils/artnet/live_layer.py (`_rainbow_rgb`,
overrides the static swatch). `LiveState` lost `stage_effect` /
`active_effect_keys` / `state.effects`; the gui.py effect-binder
instance is gone (intensity binder renamed `_live_intensity_binder`).
The riff library files (riffs/{builds,drops,fills,loops,movement})
were KEPT - they still back the riff browser, autogen and timeline.
Tests: test_live_tab.py TestCompositeEffectsPool + TestColourFXPool,
test_live_engine.py TestPerGroupIntensityBinder, test_live_busk_layer
TestColourFX; two live goldens regenerated.
