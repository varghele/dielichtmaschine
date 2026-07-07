# Shell + typography pass: North Star chrome on the existing tabs

Status: S1-S4 SHIPPED 2026-07-07 on branch `v1.2-rebrand`.

Component pass C1-C3 also shipped 2026-07-07: North Star line-icon set
(resources/icons/, 6 icons extracted from the boards + open/import
authored in style; gui/icons.py rasterizes currentColor SVGs in the
active theme's color, re-applied on theme switch via
apply_shell_icons), Chip widget (gui/widgets/chip.py + QSS variants;
DMX conflict count in the Fixtures tab is the first user), and 3px
group-color left borders on timeline lane headers
(timeline_ui/light_lane_widget.py, data-color widget rule).

Remaining follow-ups: contextual statusbar hints per screen (currently
a static Ready); compiled .qm for German needs a Qt lrelease (pip
install pyside6 provides pyside6-lrelease); block-frame tints and
swatch rows (next component slice); engineering-grid background motif. Follows the rebrand
(docs/rebranding-plan.md); design source is the North Star topbar/
statusbar anatomy in `design_handoff_lichtmaschine_app/README.md`
("App-Struktur") and the `.dc.html` boards. Decisions taken with the
user 2026-07-07: UI stays English with Qt i18n scaffolding (German .ts
started); the QMenuBar is removed, mockup-faithful.

## What changes visually

- A 48px **topbar** replaces the menubar row: rotor glyph + wordmark
  DIE LICHTMASCHINE on the left; three section tabs SETUP · SHOW ·
  AUTO (Barlow Condensed caps, accent underline on the active one);
  on the right 30x30 icon buttons (Save, Load, Export, Audio,
  Overflow menu), the config filename (mono), and the ArtNet /
  Visualizer status chips (still click-to-toggle).
- A ~32px **subnav row** under the topbar shows the active section's
  screens: SETUP > UNIVERSES · FIXTURES · STAGE, SHOW > STRUCTURE ·
  TIMELINE, AUTO > AUTO. The old QTabWidget stays as the page host
  with its tab bar hidden; nothing about the tabs' internals changes.
- The **statusbar** becomes the 26px mono strip: contextual hint left,
  version right; `showMessage` keeps working for transient messages.
- **Typography helpers** so condensed-caps display text and tracked
  mono micro-labels are one call instead of hand-set fonts everywhere.

## Why the structure looks like it does (codebase constraints)

- The six QTabWidget pages and their `_on_tab_changed` activation
  protocol (`on_tab_activated`/`on_tab_deactivated`, riff-browser
  visibility, `_current_tab_index`) are load-bearing; the shell drives
  `tabWidget.setCurrentIndex` and syncs back on `currentChanged`, so
  existing behaviour (incl. Ctrl+L jumping to Auto, index 5) is
  untouched.
- `gui.py` inserts the Edit and Render menus into the menu container
  by reference (`insertMenu`); the container changes from the
  QMenuBar to the overflow QMenu, same insertion points (Edit before
  Settings, Render before Help).
- QSS cannot express letter-spacing or text-transform, so tracking
  and ALL-CAPS live in code (`QFont.setLetterSpacing`, upper() in the
  label helpers). Everything else (borders, chips, underlines) is QSS
  against the existing token template.
- Actions that only live in popup menus do not fire their keyboard
  shortcuts app-wide; every shortcut-carrying action gets re-added to
  the MainWindow (`register_menu_shortcuts`) after the menus are
  built.

## Steps (one commit each, tests in the same commit)

- **S1 Typography.** `gui/typography.py`: `display_font()` /
  `mono_font()` (family from gui/fonts.py constants, weight,
  em-tracking via PercentageSpacing), `DisplayLabel` (auto-uppercase,
  display font, `role="display"`), `MicroLabel` (mono, uppercase,
  tracked, `role="micro"`). Unit tests: families, tracking applied,
  uppercase survives setText, translated text still uppercased.
- **S2 Shell.** `gui/widgets/topbar.py` (TopBar, NavButton,
  StatusChip, SubNav) + Ui_MainWindow integration: menubar removed,
  corner-widget icon buttons and status pills move into the topbar
  (attribute names `artnet_status_indicator`, `artnet_toggle_btn`,
  `tcp_*` preserved so `gui.py`'s `_update_toolbar_status` keeps
  working), overflow QMenu with File/Edit/View/Settings/Render/Help,
  `register_menu_shortcuts`, per-section last-visited screen memory,
  statusbar restyle. QSS additions in the token template
  (`#TopBar`, nav/chip/subnav roles). Tests: nav click -> right tab
  index, external setCurrentIndex -> nav/subnav sync, all menu
  actions reachable in the overflow menu, every shortcut registered
  on the window, chips still toggle. Goldens: `topbar_dark`,
  `topbar_light`, plus regenerated tab goldens if the shell shifts
  them.
- **S3 i18n scaffolding.** New shell strings wrapped in
  `QCoreApplication.translate`; `translations/lichtmaschine_de.ts`
  started with the shell vocabulary (BUEHNE, STRUKTUR, UNIVERSEN...);
  loader in main.py reads `ui/language` from app settings (default
  English, no switcher UI yet); `scripts/update_translations.py`
  wraps pylupdate6. Test: ts parses, loader tolerates missing .qm.
- **S4 Docs.** Changelog entry, CLAUDE.md state, this plan updated,
  full suite + visual verification (offscreen boot screenshot).

## Out of scope here

- LIVE section (arrives v1.7/v1.8; the nav model is data, adding a
  section is one entry).
- Panel-level redesigns, engineering-grid background motif, chips/
  swatches inside tabs (component pass, later).
- Language switcher UI and full retrofit of tr() onto existing tabs.
