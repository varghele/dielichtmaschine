# TODO: working agenda

Restructured 2026-07-14 with the release plan (see the top note in
ROADMAP.md): the next tag is **v1.4.0 "the standalone switch"**, then
**v1.5.0** after focus geometry + morphing. Stage refinement moved
behind the releases (v1.6), OSC folded into live ops (v1.8), crash
telemetry parked under out-of-scope. v1.1, v1.2 and v1.3 are closed.

Branch plan: `v1.2-rebrand` merges to `main` untagged once the gate
checks below pass; v1.4 work continues on `v1.4-standalone-switch`.

## v1.4 build order (rough leverage order, discuss before each)

- [ ] **LTC/SMPTE input + setlist SMPTE triggering** - the marquee
      item. PLAN: docs/ltc-plan.md (phases 0-3 + bench checkpoint,
      written 2026-07-14). Biphase-mark decoder for the 80-bit frame, 24/25/29.97/30
      fps, freewheel on dropout, per-song offset; a setlist entry with
      an SMPTE start trigger fires its song when incoming timecode
      reaches it, playhead chases from then on. Input rides the Auto
      Mode audio-capture stack. Fully testable with synthetically
      generated LTC audio before it meets hardware. MIDI/MTC triggers,
      LEARN, pause looks stay v1.8.
- [ ] **GDTF Share Phase 4** - in-app login/browse/download into the
      user GDTF dir. API proven by scripts/gdtf_share_fetch.py;
      credentials via keyring or session-only prompt, never plaintext.
- [ ] **MVR import spike** - read a real MVR from a previz tool into a
      patched, placed rig (pymvr), then decide export scope.
- [ ] **CSV lighting-table import wizard** - column mapping onto the
      existing resolution pipeline (library lookup, Replace/Add),
      preview before commit.
- [ ] **Silent-fallback audit** - convert the print-and-continue paths
      to structured warnings with a visible panel.
- [ ] **Diagnostics panel** - Help > Diagnostics, copyable markdown
      block for bug reports.

## Release gate: pending manual verification (user, needs hardware/desktop)

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
