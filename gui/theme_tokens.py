"""Die Lichtmaschine design tokens and the QSS template renderer.

The brand palette (docs/archive/rebranding-plan.md, section "Design tokens" -
authoritative values in docs/design/README.md) is
expressed as one token dict per theme. ``render_theme(name)`` reads
``resources/themes/theme.qss.template`` and substitutes every
``$token$`` placeholder, producing the stylesheet ThemeManager hands to
``app.setStyleSheet()``.

Placeholder syntax is ``$name$`` (not ``{name}``) on purpose: QSS uses
``{ }`` for rule blocks, so a brace-based syntax could not be verified
for leftovers. A ``$name$`` that survives rendering is always a bug and
``render_theme`` raises on it.

Notes:
- Accent is Glutorange #F0562E in both themes; text on accent surfaces
  is #141416. In the light theme the accent as a line/text darkens to
  #C33E1C for contrast; accent surfaces stay #F0562E.
- Function colors (success/info/warning/destructive) are shared and
  never used as brand accents.
- timeline_master_bg / timeline_lane_bg are pinned by pixel assertions
  in tests/visual/test_master_timeline_render.py; change them there and
  here together.
- Border radius is 0 everywhere (no radius tokens exist by design).
- This module is the only place UI chrome colours are spelled out
  (tests/unit/test_theme_lint.py). Widget-local sheets read these dicts
  through gui/theme_style.py (active_tokens / bind_style, which
  re-applies on a theme switch); DATA colours (group palettes, light
  colours) stay with their code and are allowlisted in the lint.
"""

import os
import re

from utils.paths import get_project_root

TEMPLATE_RELPATH = os.path.join("resources", "themes", "theme.qss.template")


def _grid_tile(name: str) -> str:
    """Absolute forward-slash path of an engineering-grid tile, for a
    QSS url(). Computed at import so it follows the install location
    (source tree or PyInstaller _MEIPASS)."""
    return os.path.join(get_project_root(), "resources", "themes",
                        name).replace("\\", "/")

# Shared function colors: semantic roles, never brand accents.
_FUNCTION = {
    "success": "#4CAF50",
    "success_hover": "#43A047",
    "success_border": "#388E3C",
    "info": "#2196F3",
    "warning": "#FF9800",
    "destructive": "#F44336",
    "destructive_hover": "#E53935",
    "destructive_border": "#C62828",
    "on_function": "#ffffff",
    # Brighter hover shades of success/destructive (the render dialog's
    # filled Render/Cancel buttons).
    "success_light": "#66BB6A",
    "destructive_light": "#EF5350",
    # Inline error text (morph screen, patchbay gap marks, unpatch x).
    "error_text": "#e5484d",
    # Fixtures-table conflict cells: a fixed red so it reads as an
    # error on both themes and never collides with a group tint.
    "conflict": "#d9534f",
    # Timeline playhead outside the accent-playhead Shows tab.
    "playhead": "#FF4444",
    # Orientation dialog +90 buttons, matching the 3D gizmo rings.
    "axis_yaw": "#4466CC",
    "axis_pitch": "#44AA44",
    "axis_roll": "#CC4444",
    # Contrast ink over a DATA fill (group/colour swatches), picked by
    # the fill's luminance; ink_on_fill is the patchbay's checked chip.
    "ink_on_light": "#141416",
    "ink_on_dark": "#F4F1EA",
    "ink_on_fill": "#0e0e10",
}

# The screensaver is the "screen off" surface: one fixed palette, the
# same whatever theme is applied (pinned by the screensaver golden).
SCREENSAVER = {
    "background": "#0E0E10",  # a shade under the dark window token
    "ink": "#F4F1EA",         # wordmark + clock
    "muted_ink": "#8D9299",   # the state kicker above the clock
    "dim_ink": "#5C6068",     # slogan + status bar
    "rotor_segment": "#C9CDD2",  # the 8 inner arc segments
    "outer_ring": "#3F4348",  # the thin outer registration ring
    "accent": "#F0562E",      # Glutorange center dot
    "mark_ink": "#3A3A3A",    # the four corner registration crosses
}

# Shared typography. Sizes are deliberately NOT tokens: existing layouts
# depend on the current sizes, and display typography (Barlow Condensed)
# lands with the screen redesigns, not the retokenization.
_FONTS = {
    "font_ui": '"Barlow"',
    "font_display": '"Barlow Condensed"',
    "font_mono": '"IBM Plex Mono"',
}

DARK = {
    **_FONTS,
    **_FUNCTION,
    # Engineering-grid background tile (scripts/generate_grid_tiles.py)
    "grid_tile": _grid_tile("grid-dark.png"),
    # Surfaces
    "window": "#141416",
    "panel": "#1E1E1E",
    "raised": "#252526",
    "border": "#3A3A3A",
    # Text
    "text": "#F4F1EA",
    "text_secondary": "#8D9299",
    "text_disabled": "#5C6068",
    # Accent (Glutorange). accent_line is what borders/underlines use.
    "accent": "#F0562E",
    "on_accent": "#141416",
    "accent_line": "#F0562E",
    "accent_hover": "#FF6B45",
    "accent_pressed": "#C33E1C",
    "accent_tint": "rgba(240, 86, 46, 0.14)",
    # Scrollbars
    "scroll_handle": "#3A3A3A",
    "scroll_handle_hover": "#5C6068",
    # Timeline (master/lane values pinned by test_master_timeline_render)
    "timeline_master_bg": "#252526",
    "timeline_lane_bg": "#2a2a2a",
    "audio_lane_bg": "#1a2a3a",
    "audio_lane_border": "#2d4060",
    # Playback time readout (success-tinted numeric readout)
    "readout_bg": "#0d1f0d",
    "readout_fg": "#4CAF50",
    "readout_border": "#2a4a2a",
    # Stage view custom-paint colors (qproperty-*)
    "stage_bg": "#141416",
    "stage_fill": "#252526",
    "stage_outline": "#8D9299",
    # Auto tab status frame + phase colors
    "phase_stopped": "#ff6b6b",
    "phase_running": "#4CAF50",
    "phase_fill": "#FF9800",
    # --- Chrome roles from the v1.5.6 theme sweep (formerly inline hex
    # literals; tests/unit/test_theme_lint.py keeps them here) ---
    # Pre-rebrand dialog look: render dialog + progress dialogs + the
    # status-bar progress meter.
    "legacy_dialog_bg": "#3d3d3d",
    "legacy_dialog_field": "#2d2d2d",
    "legacy_dialog_border": "#555555",
    "legacy_dialog_text": "#ffffff",
    "legacy_dialog_log_bg": "#1e1e1e",
    "legacy_dialog_log_text": "#cccccc",
    "legacy_dialog_disabled": "#555555",
    # Muted explanatory text in dialogs, and its dimmer variant
    # (empty-state notes, the Stage tab's idle TCP status).
    "hint_text": "#888888",
    "hint_text_dim": "#666666",
    # Borders around DATA swatches (structure part-colour button, auto
    # colour wheel).
    "color_button_border": "#666666",
    "color_button_border_hover": "#999999",
    "swatch_border": "#555555",
    # The "/" between the time-signature spin boxes.
    "separator_glyph": "#ffffff",
    # Morph screen step rail (inactive steps).
    "morph_step_idle": "#8D9299",
    # Morph patchbay chrome.
    "patchbay_halo": "#F4F1EA",
    "patchbay_chip_border": "#3A3A3A",
    "patchbay_neutral": "#8D9299",
    "patchbay_disabled_text": "#5C6068",
    "patchbay_rule": "#2D2D2D",
    # Painted meters (universe channel bar, analysis bars) and the
    # universe status dot.
    "meter_track": "#2D2D2D",
    "meter_fill": "#8D9299",
    "status_dot_idle": "#5C6068",
    # Dashed outline of a stage element whose SVG failed to load.
    "stage_placeholder": "#8D9299",
}

LIGHT = {
    **_FONTS,
    **_FUNCTION,
    # Engineering-grid background tile (scripts/generate_grid_tiles.py)
    "grid_tile": _grid_tile("grid-light.png"),
    # Surfaces
    "window": "#ECE9E2",
    "panel": "#F4F1EA",
    "raised": "#FAF8F3",
    "border": "#C9C4B8",
    # Text
    "text": "#141416",
    "text_secondary": "#5C6068",
    "text_disabled": "#8D9299",
    # Accent: surfaces stay Glutorange with dark text; as a line/text it
    # darkens to keep contrast on light ground.
    "accent": "#F0562E",
    "on_accent": "#141416",
    "accent_line": "#C33E1C",
    "accent_hover": "#FF6B45",
    "accent_pressed": "#C33E1C",
    "accent_tint": "rgba(240, 86, 46, 0.14)",
    # Scrollbars
    "scroll_handle": "#C9C4B8",
    "scroll_handle_hover": "#8D9299",
    # Timeline (master/lane values pinned by test_master_timeline_render)
    "timeline_master_bg": "#fafafa",
    "timeline_lane_bg": "#f8f8f8",
    "audio_lane_bg": "#f5f7fa",
    "audio_lane_border": "#d0dae8",
    # Playback time readout
    "readout_bg": "#f0fff0",
    "readout_fg": "#2E7D32",
    "readout_border": "#c8e6c9",
    # Stage view custom-paint colors (qproperty-*)
    "stage_bg": "#F4F1EA",
    "stage_fill": "#ECE9E2",
    "stage_outline": "#141416",
    # Auto tab status frame + phase colors
    "phase_stopped": "#c62828",
    "phase_running": "#2E7D32",
    "phase_fill": "#ef6c00",
    # --- Chrome roles from the v1.5.6 theme sweep: same roles as DARK,
    # light values from the light palette (window / raised / border /
    # text / text_secondary / text_disabled). The gray hints, swatch
    # borders, morph step rail, status dot and stage placeholder kept
    # the value they always showed: it reads on light ground ---
    "legacy_dialog_bg": "#ECE9E2",
    "legacy_dialog_field": "#FAF8F3",
    "legacy_dialog_border": "#C9C4B8",
    "legacy_dialog_text": "#141416",
    "legacy_dialog_log_bg": "#FAF8F3",
    "legacy_dialog_log_text": "#5C6068",
    "legacy_dialog_disabled": "#C9C4B8",
    "hint_text": "#888888",
    "hint_text_dim": "#666666",
    "color_button_border": "#666666",
    "color_button_border_hover": "#999999",
    "swatch_border": "#555555",
    "separator_glyph": "#141416",
    "morph_step_idle": "#8D9299",
    "patchbay_halo": "#141416",
    "patchbay_chip_border": "#C9C4B8",
    "patchbay_neutral": "#5C6068",
    "patchbay_disabled_text": "#8D9299",
    "patchbay_rule": "#C9C4B8",
    "meter_track": "#C9C4B8",
    "meter_fill": "#5C6068",
    "status_dot_idle": "#5C6068",
    "stage_placeholder": "#8D9299",
}

THEMES = {
    "dark": DARK,
    "light": LIGHT,
}

_PLACEHOLDER_RE = re.compile(r"\$([A-Za-z0-9_]+)\$")


def template_path() -> str:
    """Absolute path of the shared QSS template."""
    return os.path.join(get_project_root(), TEMPLATE_RELPATH)


def render_theme(name: str) -> str:
    """Render the QSS template with the named theme's tokens.

    Raises KeyError for an unknown theme name or a placeholder missing
    from the token dict, OSError if the template file cannot be read,
    and ValueError if any placeholder survives substitution (malformed
    placeholder such as ``$typo`` would slip the regex otherwise).
    """
    if name not in THEMES:
        raise KeyError(f"unknown theme '{name}' (have: {sorted(THEMES)})")
    tokens = THEMES[name]

    with open(template_path(), "r", encoding="utf-8") as f:
        template = f.read()

    def substitute(match: "re.Match") -> str:
        key = match.group(1)
        if key not in tokens:
            raise KeyError(f"theme '{name}' has no token '{key}'")
        return tokens[key]

    rendered = _PLACEHOLDER_RE.sub(substitute, template)
    if "$" in rendered:
        raise ValueError(
            f"unsubstituted placeholder left in rendered '{name}' theme QSS"
        )
    return rendered
