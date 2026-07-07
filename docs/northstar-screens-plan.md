# North Star screens: autonomous integration pass

Status: in progress on `v1.2-rebrand` (2026-07-07 evening, user away;
scope agreed as "everything visual on existing functionality plus
self-contained new screens"). Design source:
`design_handoff_lichtmaschine_app/` (card IDs in parentheses).

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

## Explicitly NOT in this pass

Live 3a/3b (v1.8; variant decision open), Morph wizard / Venue check /
Patch matrix / Patch flow (v1.5b), truss library + fixture docking
(stage data model), `.lms` show format, Home "letzte Shows" thumbnails
(needs render infra; text list ships instead), repo rename (user).

## Verification per slice

Unit tests + goldens in the same commit; full suite + offscreen boot
screenshot before each commit lands; changelog updated at the end of
the pass.
