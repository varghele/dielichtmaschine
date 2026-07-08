# North Star screens: autonomous integration pass

Status: ALL SLICES SHIPPED 2026-07-07 late evening (H1, T1, T2, S1,
SS1, TY1; scope agreed as "everything visual on existing functionality
plus self-contained new screens"). Design source:
`design_handoff_lichtmaschine_app/` (card IDs in parentheses).
1208 tests green at completion; every screen verified via goldens and
a full offscreen boot. TY1 note: most panel "titles" are QGroupBoxes
where a QSS ::title font would cascade into children, so only the true
QLabel titles (Fixtures, Universe Configuration) moved to
DisplayLabel.

## Slices

- **H1 Home screen (1a).** New landing page: rotor glyph, wordmark
  hero, slogan, quick actions (New from Template, Open Configuration),
  recent-configs list (tracked in app settings on load/save). Hosted
  in a QStackedWidget above the existing QTabWidget so tab indices
  stay untouched; wordmark/glyph click returns Home, any nav leaves it.
- **T1 Timeline lane anatomy (4a).** Lane headers grow the DIM / COL /
  MOV / SPC sub-row micro-labels aligned with their sublane rows.
- **T2 Regions row (4a).** The master timeline's part bands restyled to
  the North Star: part-color band + tint, condensed caps labels.
- **S1 Stageplot symbols (5a).** The 30-symbol SVG set from the
  handoff ships in resources/stageplot/; fixture types map onto the
  fixture symbols in the shared 2D icon painter (stage view, printable
  plot, fixture lists). Beam-tick-up orientation convention. Trusses /
  docking stay out (no data model for them yet).
- **SS1 Screensaver (11a).** Fullscreen #0E0E10, animated rotor
  (programmatic arcs, 10-16s/rev, counter-rotating outer ring), mono
  clock, wordmark, status line; any key/click exits. Manual activation
  via View menu; idle/LIVE-pause activation comes with v1.7/v1.8.
- **TY1 Typography sweep.** Panel titles across tabs move to
  DisplayLabel (condensed caps, tracked) and stray hardcoded fonts to
  the typography helpers.

## Round 2 (user-requested, 2026-07-08): per-tab rebuilds SHIPPED

Universes (1d), Fixtures (1c), Structure (1e), Timeline chrome (4a),
Stage (5a) all rebuilt to their cards; theme fixes (apply/persist
split + hermetic test settings, dark tab pages, primary-CTA display
family, micro-label tone). Remaining honest gaps, all feature work:
stage elements/trusses (data model), SWING + BAR readout (timeline
engine), fixtures GROUPS side panel + capability chips/channel map
(definition-cache lookup), autogen entry point stays on the Timeline
tab. NEEDED-QSS follow-ups: subnav-strip role (bottom-border-only
bar), accent-filled checked chip variant.

## Round 3 (2026-07-08): rebuilds against the ORIGINAL screen references

`design_handoff_lichtmaschine_app/screens/*.html` arrived (the real
per-screen design files). Rebuilt screen-by-screen against them, each
verified by golden + a real-config render: Home (01), Fixtures (1c/02),
Stage (04), Structure (05), Timeline (06), Auto (07). Ten shared QSS
roles were extracted into the theme template along the way (segment
chips, stat tiles, accent field/hint, section caption, element tile,
mode/bias chips, pane icon, grid surface, outlined CTA).

Deliberately NOT faked, because the data or engine does not exist:
timeline SWING and per-block overlap functions (XFADE/HTP/LTP, v1.6),
Auto's latency row and "MID" plane, Structure's per-part audio analysis
values (rendered as dashes with a tooltip until a generation report
exists), the reference's invented transition labels ("XFADE 2").

Screens still to diff: 03 universes (already close), 10 autogen dialog,
12 screensaver. 08/09 live and 11 morph belong to their milestones.

## Explicitly NOT in this pass

Live 3a/3b (v1.8; variant decision open), Morph wizard / Venue check /
Patch matrix / Patch flow (v1.5b), truss library + fixture docking
(stage data model), `.lms` show format, Home "letzte Shows" thumbnails
(needs render infra; text list ships instead), repo rename (user).

## Verification per slice

Unit tests + goldens in the same commit; full suite + offscreen boot
screenshot before each commit lands; changelog updated at the end of
the pass.
