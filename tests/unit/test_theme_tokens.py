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
    assert tm.apply(qapp, name) is True
    assert qapp.styleSheet().strip(), "apply() must set a non-empty stylesheet"
    assert "#F0562E" in qapp.styleSheet()


def test_theme_manager_available_themes_match_token_dicts():
    from gui.theme_manager import ThemeManager

    assert sorted(ThemeManager().available_themes()) == THEME_NAMES


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
