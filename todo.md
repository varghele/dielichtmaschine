# TODO: working agenda

Re-baselined 2026-07-23 for the **v1.5.0** release. v1.4.0 tagged
2026-07-15; v1.5a (focus geometry) + v1.5b (morphing) are code-complete
on `v1.5-focus-morphing` (status log `docs/focus-morphing-plan.md`,
CLOSED; roadmap done-notes in ROADMAP.md v1.5a/b). What remains before
the tag: the manual desktop/bench checks and the release ritual below.
Deferred non-blocking polish (song-switch waveform stall, structure-rail
rebuild cost, per-fixture mixed-rig beam axes, LIVE pool label
truncation) moved to ROADMAP v1.6. v1.1-v1.4 are closed - their build
history lives in CHANGELOG.md and the ROADMAP done-notes, not here.

## v1.5 feature pull-ins (all shipped, code-complete)

Agreed and shipped across the v1.5 hardening rounds:

- [x] **Lock finished shows against accidental edits** (2026-07-22) -
      `Song.locked`, LOCK chip on the Structure song header AND the
      Timeline toolbar, belt-and-braces edit guards; `test_song_lock.py`.
- [x] **Auto mode input level meter + gain** (2026-07-21) - INPUT
      LEVEL dB bar + GAIN slider + momentary AUTO, idle capture;
      `test_input_gain.py`.
- [x] **Per-group Live pools** (2026-07-22) - effects, intensity FX
      and movement shapes are all per-group like colour/position
      (scenes stay the one whole-rig override); EFFECTS grouped by
      riff category, riff pools scroll; the engine grew
      `effect/intensity/movement:<group>` slots with phase-coherent
      joins.
- [x] **Live SMPTE cluster** (2026-07-22) - the busk surface owns the
      chase: sync input device picker (moved off the Structure rail - a
      venue concern, not show structure), ARM chip, inline timecode
      readout.
- [x] **Audio inputs that refuse 44.1 kHz** (2026-07-22) -
      `LiveAudioInput` falls back to the device native rate / 48 kHz;
      the LTC decoder and Auto analyzer follow the actual rate.
- [x] **Render Show to Video moved into Tools**; overflow menu order is
      File, Edit, View, Tools, Settings, Help (2026-07-23).
- [x] **Branded About dialog + hand-written body** (2026-07-21/23).

## v1.5 desktop checks (user; any PC with a GPU except the bench item)

Everything is unit-tested offscreen; these verify what only a real
screen or the desk can judge:

- [ ] **Morph to Venue end to end on demo data**: open
      `demos/shows/club_band.lms`, Tools > Morph to Venue, target
      `demos/rigs/band_midsize.lms`, AUTO-SUGGEST, eyeball the patchbay
      (wire curves, chip gating, checker strip), DRAG a source chip
      onto a target, leave to the Stage tab mid-morph and resume via
      the menu, review page: coverage table + RENDER PREVIEW under real
      GL, commit, open the morphed show in the timeline.
- [ ] **Click-to-aim live**: select a movement block in the Shows tab,
      Stage tab AIM toggle, click the plan - the block's target and the
      3D beam follow.
- [ ] **Tools > Convert Movement to World Targets** on a real project -
      read the report table, apply, confirm beams land where they did.
- [ ] **Colour palette roles**: tag two blocks with a role, EDIT
      PALETTE, change the colour - both blocks re-skin.
- [ ] **Pre-flight against the bench rig** (desk PC): Tools > Venue
      Pre-Flight with the Hero Spots patched - flash, aim at Spot1,
      capture focus, complete; then export and see the guard stay quiet
      (and warn after touching an orientation).
- [ ] **Orientation panel**: the two INVERT DMX checkboxes on a mover,
      confirm the head mirrors on the wire and in a fresh .qxw.

## Release ritual (user, at tag time - docs/releasing.md)

- [ ] Drop the `-dev` suffix (`_version.py`: `1.5.0-dev` -> `1.5.0`).
- [ ] Rename CHANGELOG `[Unreleased]` to `[1.5.0]` with the date.
- [ ] Re-render the brand assets (`python scripts/render_brand_assets.py`
      - the README banner + social preview stamp the version at render
      time; the About dialog golden too, `test_about_dialog_golden.py`).
- [ ] Merge `v1.5-focus-morphing` to `main` (`--no-ff`), tag `v1.5.0`,
      push. (There are unpushed commits on the branch - push first.)

## Post-release hardware verification (user, needs the rig)

The software half of each is tested; these verify the physical links.
Findings land as patch releases. Bench kit sits in the repo root
(gitignored, machine-local): `bench_kit.lms` / `bench_ltc_25fps_01h.wav`
/ `bench_kit.qxw`.

- [ ] **LTC chase bench checkpoint, hardware half**: play a
      `write_ltc_wav` file from a phone/DAW into the picked input, ARM,
      see one song fire. (Device-open + native-rate decode already
      proven 2026-07-22 arming on a Realtek mic; a real analog LTC feed
      is the remaining half.)
- [ ] **QLC+ export aim check**: export a mover project to .qxw, fire a
      position preset from the Virtual Console at the hung head - the
      beam lands where Lichtmaschine lands it; also run an exported
      circle movement pattern.
- [ ] **Busk a colour over a playing show** against a real ArtNet node
      or the standalone visualizer.
- [ ] **Topbar VISUALIZER OPEN end to end**: one press = feed up +
      viewer launched + client count ticks to 1 (process launch is
      stubbed in tests).
- [ ] **Eyeball the rebranded visualizer frame** under a live GL
      context (header spacing, statusbar colours).
- [ ] **GDTF Share online check**: Add Fixture > GDTF SHARE, CONNECT
      with the real account, search, download one fixture, see it
      appear [GDTF] and patch it (the flow is fake-API tested; this
      closes the live-endpoint + real-keyring link).
