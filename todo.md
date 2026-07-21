# TODO: working agenda

Restructured 2026-07-14 with the release plan (see the top note in
ROADMAP.md): the next tag is **v1.4.0 "the standalone switch"**, then
**v1.5.0** after focus geometry + morphing. Stage refinement moved
behind the releases (v1.6), OSC folded into live ops (v1.8), crash
telemetry parked under out-of-scope. v1.1, v1.2 and v1.3 are closed.

Branch plan: `v1.2-rebrand` merges to `main` untagged once the gate
checks below pass; v1.4 work continues on `v1.4-standalone-switch`.

## v1.4 build order (rough leverage order, discuss before each)

- [x] **LTC/SMPTE input + setlist SMPTE triggering** - SHIPPED
      2026-07-14, phases 0-3 of docs/ltc-plan.md all green (~90 new
      tests: utils/timecode package, audio/ltc_input service, shell
      wiring). Only the bench checkpoint remains - added to the
      manual list below. MIDI/MTC triggers, LEARN and pause looks
      stay v1.8. Original scope, for reference: Biphase-mark decoder for the 80-bit frame, 24/25/29.97/30
      fps, freewheel on dropout, per-song offset; a setlist entry with
      an SMPTE start trigger fires its song when incoming timecode
      reaches it, playhead chases from then on. Input rides the Auto
      Mode audio-capture stack. Fully testable with synthetically
      generated LTC audio before it meets hardware. MIDI/MTC triggers,
      LEARN, pause looks stay v1.8.
- [x] **GDTF Share Phase 4** - SHIPPED 2026-07-15: utils/gdtf_share.py
      client (cached catalog serves offline, ranked search,
      revision-pinned downloads), GDTF SHARE tab in the fixture
      browser with download + auto-rescan, Settings > GDTF Share
      Account with TEST LOGIN. Password only ever in the OS credential
      store (keyring; session-only without one). 37 device-free tests.
      One manual check added to the gate list below (real login).
- [x] **MVR import spike** - moved to ROADMAP v1.8b (2026-07-15): an
      imported MVR must create and update stage geometry, which the
      v1.6 stage pass has to solve first. With this, every v1.4 CODE
      item is done; what remains before the tag is the manual gate
      list below.
- [x] **CSV lighting-table import wizard** - SHIPPED 2026-07-15:
      utils/csv_table_import.py (pure sniff/guess/map/build/resolve,
      delimiter + encoding + header tolerant) and the three-step
      wizard gui/dialogs/csv_import_wizard.py riding the existing
      resolution pipeline (library lookup, Replace/Add); nothing
      touches the config until IMPORT. The topbar import button now
      pops a workspace/CSV choice menu. 42 tests in
      tests/unit/test_csv_table_import.py.
- [x] **Silent-fallback audit** - SHIPPED 2026-07-15: 142 print sites
      inventoried, user-impacting ones route through
      utils/user_warnings.py (operation grouping, once-key folding for
      output storms, file-log mirroring) into Help > Warnings; export
      success box reports warning counts, failed project load finally
      gets an error dialog, CLI export prints warnings to stderr.
      Export byte-identical (hash-checked). 18 tests.
- [x] **Diagnostics panel** - SHIPPED 2026-07-15: Help > Diagnostics,
      utils/diagnostics.py (guarded probes: versions, GL renderer,
      audio host APIs, arbiter output state, project + log paths) and
      a COPY TO CLIPBOARD dialog. 11 probe-injected tests.

## v1.5 desktop checks (user; any PC with a GPU except the bench item)

The whole v1.5 scope is code-complete on `v1.5-focus-morphing`
(2026-07-16; status log in docs/focus-morphing-plan.md). Everything is
unit-tested offscreen; these verify the parts only a real screen or
the desk can judge:

- [ ] Morph to Venue end to end on demo data (REWORKED 2026-07-16
      after the first pass failed this check: now a full-window screen
      under Tools, drag-and-drop wiring, patchbay layout fixed): open
      demos/shows/club_band.lms, Tools > Morph to Venue, target
      demos/rigs/band_midsize.lms, AUTO-SUGGEST, eyeball the patchbay
      (wire curves, chip gating, checker strip), DRAG a source chip
      onto a target, navigate to the Stage tab mid-morph and resume
      via the menu, review page: coverage table + RENDER PREVIEW
      side-by-side under real GL, commit, open the morphed show in the
      timeline.
- [ ] Click-to-aim live: select a movement block in the Shows tab,
      Stage tab AIM toggle, click the plan - the block's target and
      the 3D beam should follow.
- [ ] Tools > Convert Movement to World Targets on a real project -
      read the report table, apply, confirm beams land where they did.
- [ ] Colour palette roles: tag two blocks with a role, EDIT PALETTE,
      change the colour - both blocks re-skin.
- [ ] Pre-flight against the bench rig (desk PC): Tools > Venue
      Pre-Flight with the Hero Spots patched - flash, aim at Spot1,
      capture focus, complete; then export and see the guard stay
      quiet (and warn after touching an orientation).
- [ ] Orientation panel: the two INVERT DMX checkboxes on a mover,
      confirm the head mirrors on the wire and in a fresh .qxw.
- [ ] **Write the About text by hand (user)** - noted 2026-07-21
      ("not nice"); the dialog itself was reworked the same day into
      a branded card (gui/dialogs/about_dialog.py: glyph + wordmark +
      slogan, rating plate shared with the README banner via
      app_identity.rating_plate, domain link). What remains for the
      user is only the body paragraph: replace the `ABOUT_BODY`
      constant at the top of about_dialog.py (a placeholder sentence
      sits there now), then regenerate the dialog golden. House
      rules: no em-dashes, separator is " · ".

## v1.5 feature pull-ins (agreed 2026-07-21)

- [ ] **Auto mode input level meter + gain** - a live audio bar in the
      Auto screen showing what the microphone actually picks up (so
      "does it react to sound at all" is a glance, not a guess), a
      GAIN control beside it to amplify or dampen the incoming signal
      before analysis (makes a too-quiet source usable), and an AUTO
      button that sets the gain from the measured level.

## Bugs exposed by the 2026-07-17 gig-prep night (v1.5 follow-ups)

Found while sweeping the Stellwerk kit; neither blocks the gig (the
show has zero plane-targeted blocks and the venue file is generated,
not hand-edited), but both undercut shipped v1.5 features:

- [x] **Timeline playback never receives stage planes** - FIXED
      2026-07-17: ShowsArtNetController._refresh_stage_planes feeds
      compute_stage_planes (raw spatial frame, matching what export
      and Auto mode already pass - parity, not correction) at
      construction, on set_light_lanes and on update_fixtures. Pinned
      by test_world_targets.py::TestShowsPlaybackPlaneTargets
      (controller-fed renderer == manually-fed reference, planes
      track fixture height changes).
- [x] **LightBlock.provenance does not survive .lms save/load** -
      FIXED 2026-07-17: provenance rides the compact ENTRY (written
      only when set - pre-provenance files byte-stable, old files
      load as ""); the dedup template stays provenance-free so
      identical blocks still share one def. Pinned by
      test_compact_serializer.py::TestProvenance incl. a real
      Configuration.save/load round trip.

## Small-screen (720p) layout pass (exposed + fixed 2026-07-18)

The app could not fit a 1280x720 display: the LIVE pools demanded
~1128x624 and the STRUCTURE centre column ~589x578, driving the
WM-enforced WINDOW minimum to 1462x1020. FIXED with explicit 720p
minimum-size floors on the two containers (explicit minimums
override the layout hints per axis; squeezed, the layouts compress
their gaps and clip pool labels but stay fully usable). Window
minimum now fits 720p; every tab pinned by
tests/visual/test_720p_layout.py (per-tab fit checks + goldens of
the squeezed renders + the window-level guarantee).

- [ ] v1.6 polish, not a blocker: the LIVE pools under the floor
      truncate cell labels (CASCADE, pool names) - a real
      collapse/scroll re-layout of the pool grid would recover the
      text at small sizes.

## Performance follow-ups (parked 2026-07-16, after the big three)

The 2026-07-16 perf pass fixed the timer-driven UI freezes (libyaml
fast path, async autosave, pickle fingerprint). Two smaller hitches
remain, both one-off rather than periodic:

- [ ] Song switching blocks ~90 ms on the audio-waveform worker
      (audio/audio_waveform_widget.py run/wait during _load_show) -
      let the waveform arrive late instead of waiting.
- [ ] Structure tab full rebuild costs ~265 ms (setlist rail re-style:
      82 setStyleSheet calls per pass) - cache or diff the rail.

## Post-release verification (user, needs hardware/desktop)

Originally the v1.4.0 release gate; the bench session was postponed
(decision 2026-07-15) and v1.4.0 tagged without it. The software
half of every item is tested; what follows verifies the physical
links. Findings land as patch releases.

> **Bench kit prepared 2026-07-15** (untracked, in the repo root like
> tester.lms): `bench_kit.lms` = tester.lms rig + two 16 s songs with
> a circle movement block on the Movers and SMPTE triggers at
> 01:00:02:00 / 01:00:20:00; `bench_ltc_25fps_01h.wav` = 45 s of
> 25 fps LTC from 01:00:00:00 (decoder-verified round trip) - play it
> into the line-in for the LTC check; `bench_kit.qxw` = the same
> project exported for the QLC+ aim + movement-pattern check.

- [ ] LTC chase bench checkpoint, HARDWARE HALF ONLY: the full bench
      script (arm, songs fire at their timecodes, playhead chases,
      cable-pull freewheels and never stops the show, replug re-locks
      into the next song, STOP disarms) is verified in software by
      tests/e2e/test_ltc_chase_e2e.py against the real shell and a
      real generated WAV (2026-07-15). What remains on the desk is
      only the physical line-in: pick the input in the Structure tab,
      play a write_ltc_wav file from a phone/DAW into it, ARM CHASE,
      and see one song fire - that proves device open + analog decode.
- [ ] QLC+ export aim check: export tester.lms (or any mover project)
      to .qxw, open in QLC+, fire a position preset from the Virtual
      Console at the hung head - the beam should land where
      Lichtmaschine lands it (the export now goes through
      utils/yoke.export_aim_dmx: real ranges + the hardware-verified
      yoke conversion; this check closes the last interop link).
      EXTENDED 2026-07-14: also run an animated movement pattern
      (circle) from the exported show in QLC+ - the export now
      converts every sequence step through the yoke, so the figure
      should match native output on the rig.
- [ ] Busk a colour over a playing show against a real ArtNet node or
      the standalone visualizer (merge is unit-tested, never touched
      hardware)
- [ ] Topbar VISUALIZER OPEN end to end: one press = feed up + viewer
      launched + client count ticks to 1 (process launch is stubbed
      in tests)
- [ ] Eyeball the rebranded visualizer frame under a live GL context
      (header spacing, statusbar colors)
- [ ] GDTF Share online check: Add Fixture > GDTF SHARE tab, CONNECT
      with the real account (REMEMBER stores the password in the
      Windows vault), search, download one fixture, see it appear
      [GDTF] in the library list and patch it. The whole flow is
      tested against a fake API; this closes the only untested link
      (the live gdtf-share.com endpoints + real keyring backend).

## Resolved reference

- **The pan/tilt yoke model**: hardware-verified on the bench
  2026-07-13 (Hero Spot 60, three raw poses + four aimed targets,
  standing and hanging); full write-up in
  docs/coordinate-frames-and-orientation.md section 4. Movement
  patterns in the export converted per step 2026-07-14. Remaining
  slivers (per-fixture DMX-invert flags, per-fixture beam/base axes
  for mixed rigs) live in ROADMAP v1.5a.
- **All live-output-plan checkpoints closed on the bench 2026-07-13**:
  swatches, scenes, riffs, movement shapes (meter-based orbits),
  intensity FX conjunction, stagger - the Live tab works end to end
  on real hardware.
- The 2026-07-12/13 pull-in log (headless CLI, library paths, .lms,
  riff tags, untangle/compact, undo/redo) lives in CHANGELOG.md and
  the ROADMAP done-notes; dropped from here.
