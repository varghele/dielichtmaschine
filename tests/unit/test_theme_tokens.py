"""Rendered-QSS contract for the Die Lichtmaschine theme tokens.

The two themes are token dicts in gui/theme_tokens.py rendered through
resources/themes/theme.qss.template. These tests pin the brand rules
that must hold for ANY future token/template edit:

- the Glutorange accent #F0562E appears in both rendered themes
- border-radius is 0 everywhere (hard edges, datasheet aesthetic)
- every $token$ placeholder gets substituted (the $name$ syntax exists
  so leftovers are detectable despite QSS's own { } blocks)
- ThemeManager.apply works for both themes and sets a stylesheet
- the template is the single source: the old verbatim .qss files are
  gone and the loader no longer looks for them
"""

import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.theme_tokens import DARK, LIGHT, THEMES, render_theme, template_path

THEME_NAMES = sorted(THEMES)


# ---------------------------------------------------------------------------
# Rendered QSS contracts
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", THEME_NAMES)
def test_accent_present_in_rendered_theme(name):
    qss = render_theme(name)
    assert "#F0562E" in qss, (
        f"theme '{name}' lost the Glutorange accent - selection/highlight "
        "surfaces must use the brand accent"
    )


@pytest.mark.parametrize("name", THEME_NAMES)
def test_no_nonzero_border_radius(name):
    qss = render_theme(name)
    for value in re.findall(r"border(?:-\w+)*-radius\s*:\s*([^;}]+)", qss):
        cleaned = value.strip().rstrip("px").strip()
        assert cleaned in ("0", ""), (
            f"theme '{name}' has a nonzero border-radius '{value.strip()}' - "
            "the brand is radius 0 everywhere"
        )


@pytest.mark.parametrize("name", THEME_NAMES)
def test_all_placeholders_substituted(name):
    qss = render_theme(name)
    # $name$ placeholder syntax: any surviving '$' is an unsubstituted
    # or malformed placeholder. render_theme itself raises on this too;
    # asserting here keeps the contract visible even if that guard is
    # ever loosened.
    assert "$" not in qss, f"theme '{name}' has unsubstituted placeholders"


@pytest.mark.parametrize("name", THEME_NAMES)
def test_barlow_is_the_app_font(name):
    qss = render_theme(name)
    assert '"Barlow"' in qss, "app-wide UI font family must be Barlow"


def test_dark_and_light_define_the_same_tokens():
    """The shared template needs every token in both themes."""
    assert set(DARK) == set(LIGHT)


def test_render_unknown_theme_raises():
    with pytest.raises(KeyError):
        render_theme("solarized")


# ---------------------------------------------------------------------------
# ThemeManager integration
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", THEME_NAMES)
def test_theme_manager_apply_sets_stylesheet(qapp, name):
    from gui.theme_manager import ThemeManager

    tm = ThemeManager()
    try:
        assert tm.apply(qapp, name) is True
        assert qapp.styleSheet().strip(), \
            "apply() must set a non-empty stylesheet"
        assert "#F0562E" in qapp.styleSheet()
    finally:
        # Never leak a non-dark theme into other tests on this xdist
        # worker: token painters sniff the GLOBAL stylesheet
        # (gui.theme_style.active_tokens), so a left-over light theme
        # flips brand-token assertions elsewhere - an
        # order-dependent flake. Restore the default (dark).
        tm.apply(qapp, "dark")


def test_apply_never_persists_the_choice(qapp):
    """Regression: apply() persisting let TEST RUNS overwrite the
    user's saved theme (golden tests apply light/dark against the real
    store). Only the explicit View > Theme action may persist."""
    from gui.theme_manager import ThemeManager

    tm = ThemeManager()
    tm.set_current("dark")
    tm.apply(qapp, "light")
    assert tm.current() == "dark", (
        "apply() persisted the applied theme - it must not; persistence "
        "belongs to set_current() on explicit user action")
    tm.apply(qapp, "dark")


def test_theme_manager_available_themes_match_token_dicts():
    from gui.theme_manager import ThemeManager

    assert sorted(ThemeManager().available_themes()) == THEME_NAMES


# ---------------------------------------------------------------------------
# Engineering-grid motif
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,tile", [("dark", "grid-dark.png"),
                                       ("light", "grid-light.png")])
def test_grid_tile_wired_into_theme(name, tile):
    qss = render_theme(name)
    assert f"{tile}" in qss and "background-repeat: repeat-xy" in qss
    path = THEMES[name]["grid_tile"]
    assert os.path.isfile(path), path
    assert "\\" not in path, "QSS url() needs forward slashes"


@pytest.mark.parametrize("tile", ["grid-dark.png", "grid-light.png"])
def test_grid_tile_is_a_faint_48px_grid(tile):
    """48x48 RGBA, 1px steel line top+left at near-invisible alpha,
    transparent elsewhere (the handoff's 0.04-0.07 alpha motif)."""
    from PIL import Image
    path = os.path.join(os.path.dirname(template_path()), tile)
    image = Image.open(path).convert("RGBA")
    assert image.size == (48, 48)
    r, g, b, a = image.getpixel((10, 0))
    assert (r, g, b) == (141, 146, 153)
    assert 5 <= a <= 25, f"grid line alpha {a} outside the faint range"
    assert image.getpixel((0, 10))[3] == a
    assert image.getpixel((10, 10))[3] == 0  # cell interior transparent


# ---------------------------------------------------------------------------
# Single source of truth
# ---------------------------------------------------------------------------
def test_template_is_the_single_source():
    themes_dir = os.path.dirname(template_path())
    assert os.path.isfile(template_path())
    leftovers = [f for f in os.listdir(themes_dir) if f.endswith(".qss")]
    assert leftovers == [], (
        f"verbatim .qss files reappeared in resources/themes: {leftovers} - "
        "the token template is the single source of truth"
    )


# The numeric QColor literals the v1.5.6 follow-up moved onto tokens,
# as the painters spelled them: the move is pixel-identical only while
# these hold (test_theme_lint keeps new literals out).
_HISTORIC_PAINTED = {
    "plan_select_pen": (0, 0, 255), "plan_item_pen": (0, 0, 0),
    "mount_hanging": (60, 120, 255), "mount_standing": (255, 140, 0),
    "mount_wall": (100, 180, 100), "mount_unknown": (128, 128, 128),
    "plan_axis_red": (255, 80, 80), "plan_axis_green": (80, 200, 80),
    "plan_axis_blue": (80, 80, 255), "plan_text_fallback": (0, 0, 0),
    "plan_label_fallback": (120, 120, 120),
    "stage_fallback_outline": (0, 0, 0),
    "stage_fallback_fill": (240, 240, 240),
    "stage_fallback_grid": (200, 200, 200),
    "stage_fallback_label": (60, 60, 60),
    "stage_fallback_fixture_text": (0, 0, 0),
    "icon_glyph": (220, 220, 220), "timeline_grid_line": (127, 127, 127),
    "timeline_ruler_ink": (141, 146, 153), "selection_blue": (0, 120, 215),
    "waveform": (100, 150, 255), "waveform_bg": (30, 30, 30),
    "waveform_text": (200, 200, 200), "waveform_error": (255, 100, 100),
    "waveform_hint": (150, 150, 150), "pantilt_grid": (50, 50, 70),
    "pantilt_center": (100, 100, 120), "pantilt_boundary": (255, 100, 100),
    "pantilt_amplitude": (100, 200, 100), "pantilt_shape": (0, 200, 255),
    "pantilt_position": (255, 165, 0), "pantilt_position_dot": (255, 200, 50),
    "pantilt_label": (150, 150, 150), "wheel_marker": (255, 255, 255),
    "wheel_marker_outline": (0, 0, 0), "invalid_text": (255, 0, 0),
    "disabled_cell_text": (127, 127, 127),
}
_HISTORIC_ANALYSIS_PLOT = {
    "panel": (40, 40, 48), "text": (200, 200, 210), "grid": (60, 60, 70),
    "cursor": (255, 40, 40), "line_light": (255, 255, 255),
    "band_even": (50, 50, 58), "band_odd": (42, 42, 50),
    "axis_text": (140, 140, 150), "dim_text": (120, 120, 130),
    "inactive_cell": (50, 50, 55), "mark": (255, 255, 100),
    "selected_text": (255, 255, 200), "dot_outline": (180, 180, 180),
    "tracker_bg": (20, 20, 30), "tracker_grid": (50, 50, 60),
}
_HISTORIC_STAGE_PLOT = {
    "paper": (255, 255, 255), "ink": (20, 20, 20), "gray": (150, 150, 150),
    "subtitle": (80, 80, 80), "grid": (225, 225, 225),
    "meter_labels": (100, 100, 100), "audience": (120, 120, 120),
    "legend_text": (60, 60, 60),
}


def _rgb(hex_value):
    h = hex_value.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


@pytest.mark.parametrize("table,historic", [
    ("PAINTED", _HISTORIC_PAINTED),
    ("ANALYSIS_PLOT", _HISTORIC_ANALYSIS_PLOT),
    ("STAGE_PLOT", _HISTORIC_STAGE_PLOT),
])
def test_painter_tokens_keep_the_literals_they_replaced(table, historic):
    import gui.theme_tokens as tt
    values = getattr(tt, table)
    assert set(values) == set(historic)
    for key, rgb in historic.items():
        assert _rgb(values[key]) == rgb, key


def test_painted_chrome_is_in_both_themes_unchanged():
    from gui.theme_tokens import DARK, LIGHT, PAINTED
    for key, value in PAINTED.items():
        assert DARK[key] == LIGHT[key] == value, key
