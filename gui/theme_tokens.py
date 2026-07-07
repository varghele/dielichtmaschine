"""Die Lichtmaschine design tokens and the QSS template renderer.

The brand palette (docs/rebranding-plan.md, section "Design tokens" -
authoritative values in design_handoff_lichtmaschine_app/README.md) is
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
    "auto_status_bg": "#1E1E1E",
    "phase_stopped": "#ff6b6b",
    "phase_running": "#4CAF50",
    "phase_fill": "#FF9800",
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
    "auto_status_bg": "#F4F1EA",
    "phase_stopped": "#c62828",
    "phase_running": "#2E7D32",
    "phase_fill": "#ef6c00",
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
