# Rebranding plan: QLC+ Show Creator becomes Die Lichtmaschine

Status: phases B0-B5 SHIPPED 2026-07-07 on branch `v1.2-rebrand` (off
`v1.1-stage-rig-data`). Remaining follow-ups are listed at the bottom.
Source of truth for the design: `design_handoff_lichtmaschine_app/`
(README + the two `.dc.html` North Star boards). This document covers the
*rebranding* slice of that package: identity, tokens, packaging, and the
plumbing pulled forward so breakage is self-reporting. The full screen
redesigns (Home hero, Live 3a/3b, Morph wizard, Patch flow, Screensaver)
are NOT this plan; they land with their feature milestones (see the
roadmap pointers below).

## Naming decisions

| Thing | Value |
|---|---|
| Product name (display) | Die Lichtmaschine |
| Wordmark (UI, caps) | DIE LICHTMASCHINE |
| Domain | dielichtmaschine.de |
| Slogan | DE "ES WERDE LICHT" / EN "LET THERE BE LIGHT" |
| QSettings / app-data org | dielichtmaschine |
| QSettings / app-data app | Lichtmaschine |
| Executable / PyInstaller name | Lichtmaschine |
| Repo name (later, user action) | dielichtmaschine |
| Python entry point | unchanged (`main.py`) |
| File formats | unchanged (config YAML, `.qxw` export stays as interop; a `.lms` show format is a North Star idea, not part of this plan) |

Separator in UI copy is " · ", never an em-dash (project-wide rule).

## Design tokens (from the handoff, decided)

Accent: Glutorange `#F0562E` (final; brass gold was rejected). Text on
accent surfaces: `#141416`.

Dark (default): window `#141416` · panel `#1E1E1E` · raised `#252526` ·
border `#3A3A3A` · text `#F4F1EA` (warm off-white, never `#FFF`) ·
text-secondary `#8D9299` · text-tertiary `#5C6068` · accent tint
rgba(240,86,46,0.10-0.18).

Light: window `#ECE9E2` · panel `#F4F1EA` · raised `#FAF8F3` · border
`#C9C4B8` · text `#141416` · text-secondary `#5C6068` · accent as
line/text darkens to `#C33E1C`, accent surfaces stay `#F0562E`.

Function colors (never for brand accents): success `#4CAF50`, info
`#2196F3`, warning `#FF9800`, destructive `#F44336`.

Group colors (dark/light): amber `#D9A441`/`#B07F24`, cyan
`#4ECBD4`/`#2A9AA3`, magenta `#C95FD0`/`#A53FAE`, green
`#6F9E4C`/`#557D36`, steel `#8D9299`/`#5C6068`.

Typography (ships with the app, all OFL): Barlow Condensed 600-800 for
display/headlines/tab labels (ALL CAPS, tracked), Barlow 400-600 for UI
text, IBM Plex Mono 400-600 for numeric readouts and micro-labels.

Shape: border-radius 0 everywhere, no shadows, no gradients outside
functional surfaces (color swatches, region tints).

## Phases

Each phase is one or more commits, each with tests in the same commit,
changelog kept current under `[Unreleased]`.

- **B0 (this commit): plan + roadmap reshuffle.** Commit the design
  handoff package as the in-repo North Star reference, this plan, and
  the ROADMAP.md changes (v1.2 branding item concretized; structured
  logging + crash reporter pulled from v1.4 into v1.2 so later phases
  are self-reporting when they break something).
- **B1: brand foundation.** `resources/brand/` (icons, favicon, banner,
  a generated multi-size `.ico`), `resources/fonts/` (Barlow, Barlow
  Condensed, IBM Plex Mono TTFs + OFL license), `utils/app_identity.py`
  as the single source of truth for name/org/slogan/version strings,
  and font registration at startup. Tests: assets exist and load,
  fonts register under the expected family names, identity constants.
- **B2: identity switchover.** Window title, `QApplication`
  org/app name, app icon, About dialog, `--version` output, visualizer
  window title, theme-manager QSettings org with a one-shot migration
  that copies the old `QLCShowCreator` settings so users keep their
  theme and paths. Tests: title, migration, version string.
- **B3: theme retokenization.** Replace the verbatim `dark.qss` /
  `light.qss` with one QSS template rendered from per-theme token
  dicts (the handoff's card 8a architecture), carrying the palette
  above, radius 0, and the Barlow families. The old themes' widget
  coverage is kept; only tokens and shape change. Visual safety net:
  the glyph-clipping sweep (fonts change widths), regenerated goldens
  reviewed by eye, and new unit tests on the rendered QSS (accent
  present, no nonzero border-radius, both themes render and apply).
- **B4: structured logging + crash reporter** (pulled forward from
  v1.4). Default-on rotating file log under the per-OS app-data dir of
  the new brand, `sys.excepthook` + Qt message handler capture, Help
  menu "Reveal log folder" action, and a crash dialog (traceback, app
  version, copy / save affordances). No automatic upload. Tests: log
  file lifecycle, excepthook capture, dialog content offscreen.
- **B5: packaging + docs.** PyInstaller spec renamed and pointed at
  the new icon/name, release workflow artifact names, README rebrand
  (banner, name, QLC+ export reframed as one interop path), FEATURES.md
  and docs mentions where user-facing. Ends with the repo-rename
  checklist below.

## What is deliberately out of scope here

- Screen redesigns from the North Star (Home 1a, Setup tables 1c/1d,
  Timeline 4a, Auto 1h, Live 3a/3b, Morph 6a-6d, Screensaver 11a).
  Each belongs to the milestone that owns the feature.
- The `assets/stageplot/` SVG symbol set: it replaces
  `paint_fixture_icon` rendering in the Stage tab / stage plot, which
  is the reopened v1.1 stage work, not the rebrand.
- Tab restructuring (SETUP · SHOW · AUTO · LIVE topbar): the LIVE tab
  does not exist yet (v1.7/v1.8); restructuring now would rename half
  the GUI for no user benefit. The rebrand keeps current tabs.
- `.lms` show file format.

## Repo rename checklist (user action, do when ready)

1. GitHub: Settings > rename repository to `dielichtmaschine`
   (old URLs redirect automatically).
2. Locally: `git remote set-url origin <new URL>`.
3. In-repo references to the old repo URL/path (README badges/links,
   docs) - covered by phase B5 where already known; grep
   `QLCplusShowCreator` after the rename for stragglers.
4. Optional: rename the local project folder; PyCharm project name.
5. GitHub repo social preview: upload
   `resources/brand/social-preview-1280x640.png`.

## Open items / decisions not needed yet

- Live screen variant 3a vs 3b: decision explicitly open in the
  handoff; needed for v1.8, not for the rebrand.
- GDTF Share credentials: not needed for any rebrand phase; needed
  only when Phase 4 (Share browser UI) starts.
- Data-dir migration beyond QSettings: the app stores no per-user
  files outside QSettings today (logs are new in B4), so nothing else
  migrates.

## Follow-ups after B0-B5 (shipped 2026-07-07)

- **Repo rename** (user action): checklist above; afterwards grep
  `QLCplusShowCreator` for leftover URLs (docs/releasing.md example
  URL, README links) - GitHub redirects in the meantime.
- **Demo media regeneration**: the README GIF + stills under
  `demos/media/` show the old light-gray UI. Regenerate via
  `python -m demos.generate_media <rig>` once the look settles
  (they render the visualizer, so the delta is smaller than it
  sounds, but the GUI stills in any future docs need the new theme).
- **Light-theme timeline pixel pins**: `timeline_master_bg` /
  `timeline_lane_bg` light values are pinned to legacy pixels by
  `tests/visual/test_master_timeline_render.py` (#fafafa/#f8f8f8
  instead of on-token #FAF8F3). Move them onto the token and update
  that test together.
- **Barlow Condensed display typography**: deliberately not applied
  anywhere yet; lands with the North Star screen redesigns.
- **Wordmark in the UI chrome**: the North Star topbar (glyph +
  DIE LICHTMASCHINE wordmark) belongs to the tab-restructure work,
  not the rebrand.
