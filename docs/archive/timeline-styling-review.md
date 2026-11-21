# Timeline tab: North Star styling review

Review of the Show Timeline tab (`gui/tabs/shows_tab.py` + `timeline_ui/`)
against the North Star reference
`docs/design/screens/06-show-timeline.html`.

Method: compared the reference's tokens/layout to the live tab (rendered
offscreen) and to the source. "Old styling" = pre-rebrand Material /
Windows colors and inline `setStyleSheet`, versus the brand tokens
(accent `#F0562E`, surfaces `#141416` / `#1E1E1E` / `#252526`, text
`#F4F1EA` / `#8D9299` / `#5C6068`, radius 0, Barlow Condensed + IBM Plex
Mono).

## Already on the North Star (keep as-is)

These went through the shell/component passes and match the reference:

- **Toolbar** - SHOW field, green "+ Add Light Lane", accent
  "Auto-Generate", Inspector, the GRID chips, SNAP, the new SWING chip,
  ZOOM, accent Save. Uses theme roles; golden `shows_toolbar_dark`.
- **Transport bar** - green Play / accent Stop / BAR.beat readout.
  Golden `shows_transport_dark`.
- **Status footer** - "N LANES · N BLOCKS · GRID · ZOOM". Golden
  `shows_footer_dark`.
- **Block inspector** (right, when a block is selected) - stat tiles.
  Golden `shows_block_inspector_dark`.
- **Master timeline + part bands** - the song-part colored bands and
  playhead. Golden `master_timeline_dark`. The part tinting is the data
  color, which is correct.

## The gap: the timeline body is still pre-rebrand

Everything the toolbar sits above - the lanes, the blocks, the riff
browser, and the block-edit dialogs - still uses Material / Windows
colors and inline stylesheets. Rendered, the lane area reads as a
different (older) product than the chrome around it.

### 1. Lane header controls - Material colors

`timeline_ui/light_lane_widget.py`, `timeline_ui/audio_lane_widget.py`

- Mute button `#d32f2f` (Material red), Solo `#FFC107` (Material amber),
  name label a bare `font-weight: bold; font-size: 12px` inline style,
  snap checkbox inline font. The reference lane header is: 260px column,
  `#1E1E1E` bg, a 3px left border in the group's data color, the lane
  name in Barlow Condensed caps, a mono "N FIX" count, mute/solo as
  subtle chips, and a vertical `DIM / COL / MOV / SPC` sub-lane label
  column in mono `#5C6068`.
- **Action:** rebuild the lane header to the reference; mute/solo become
  theme chips (a muted/among role, accent-on-active), name uses the
  display caps treatment, add the "N FIX" count and the sub-lane label
  column.

### 2. Block rendering - hardcoded sub-lane fills

`timeline_ui/light_block_widget.py` (custom-painted, no QSS)

- The block *header* already tints with the group's data color and uses
  the brand accent for selection (good). But the per-sub-lane fills are
  hardcoded: yellow-brown `QColor(180,150,50)`, green `QColor(50,150,80)`,
  Material `#9C27B0` / `#E91E63` / `#607D8B`, and generic grays
  (`30,30,30` / `60,60,60` / `100,100,100`) with pure-white text. That is
  what makes the blocks read tan/brown/orange instead of the reference's
  clean rows.
- The reference draws each 24px sub-row as `rgba(groupColor, ~0.22)` with
  a group-color hairline, a left-to-right gradient for color blocks, a
  dashed border for fades, and accent tint + "SELECTED" for the selected
  block. Text is `#F4F1EA` / the group color, not pure white.
- **Action:** derive the sub-row fills from the group data color + the
  brand neutrals, not a fixed Material palette; white text -> `#F4F1EA`;
  empty sub-rows -> a faint brand neutral, not `#3C3C3C`.

### 3. Riff browser panel - the worst offender

`timeline_ui/riff_browser_widget.py` (11 inline `setStyleSheet`)

- Windows-blue `#0078d4` selection, gray `#4a4a4a` / `#3c3c3c` / `#2d2d2d`
  surfaces. No brand tokens.
- **Action:** move to theme roles (`card`, `output-select`, list/table
  styling from the template); accent = `#F0562E`, surfaces from tokens.

### 4. Block-edit dialogs - Material colors

`colour_block_dialog.py`, `movement_block_dialog.py`,
`dimmer_block_dialog.py`, `special_block_dialog.py`,
`target_selection_dialog.py`, `save_riff_dialog.py`

- `#0078d4` accents and gray surfaces throughout. These are modal editors
  opened from the timeline, so they read as clearly "old" when opened.
- **Action:** restyle to the theme (primary/cta roles, token surfaces),
  same treatment the autogen dialog got.

## Where we should deviate from the mockup

The reference is a static, idealized mockup; the tab is a functional
editor. Deviate where fidelity would fight the data or the toolkit:

- **Custom-painted widgets read tokens directly.** QSS roles cannot reach
  a `QPainter`. The lanes/blocks/master already paint by hand, so they
  must pull brand colors from `_active_tokens()` (or `pyqtProperty`
  theme colors, the pattern `gui/StageView.py` uses) rather than QSS.
  This is a mechanism deviation, not a token deviation.
- **Sub-lanes follow the fixture, not a fixed four.** The mockup always
  shows DIM / COL / MOV / SPC. The real model only has the sub-lanes a
  group's fixtures actually support (this is the mode-aware capability
  work; see `docs/bug-reports.md`). Keep showing only real sub-lanes -
  do not pad to four for looks.
- **Decorative flourishes only where backed by data.** The mockup's
  "OVERLAP: XFADE · 2 BARS" chip, per-color gradients, and "N SUB"
  badges are nice but should appear only when the block actually carries
  that data (same honest-omission rule used across the rebrand). Omit or
  simplify the rest rather than fake it.
- **Zoom/scroll reality.** The mockup is one fixed viewport; the live
  lanes scroll and zoom. Header column stays pinned, block widths are
  data-driven - keep that behavior over pixel-matching the mockup's
  fixed bar widths.

## Suggested order (each its own commit, with goldens)

1. **Lane header + block painting** (biggest visual win): items 1 and 2.
   Regenerate the lane/block goldens; add a populated-timeline golden if
   one does not exist.
2. **Riff browser** (item 3).
3. **Block-edit dialogs** (item 4).

Chrome (toolbar / transport / footer / inspector) needs no work.
