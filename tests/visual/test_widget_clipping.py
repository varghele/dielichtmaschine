"""Glyph-clipping sweep over every fixed-width text button.

Origin: the Stage tab's layer "+" button was created 32px wide while the
theme puts 14px of horizontal padding on buttons — Qt clips the label to
the 4px content rect and the user saw a cut-off sliver instead of a
plus. Functional tests can't see that; this sweep grabs each button and
asserts the rendered ink matches the text's expected extent (see
tests/visual/harness.py::assert_text_not_clipped for the two conditions).

Scope: every FIXED-WIDTH short-glyph button (the icon-button class).
Auto-sized buttons can't clip — their sizeHint uses the same font
metrics as the render. Long-text fixed-width buttons (e.g. the
Configuration tab's 115px "Refresh Devices", verified 82px of text in an
87px content rect natively) would false-positive under the offscreen
platform's wide fallback font, so they stay out of the offscreen sweep;
review those by hand when changing widths. When adding a fixed-width
icon button anywhere, add it to the collector for its tab.

Run (part of the default suite):
    pytest tests/visual/test_widget_clipping.py -q
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.visual.harness import assert_text_not_clipped


def _fixtures_tab_buttons(config):
    from gui.tabs.fixtures_tab import FixturesTab
    tab = FixturesTab(config, parent=None)
    # Duplicate/Remove moved to the inspector footer as auto-sized text
    # buttons - out of sweep scope (auto-width buttons can't clip, and
    # blanking their text re-layouts the stretch row, breaking the
    # with/without-text diff). Only the fixed-width buttons stay.
    return tab, {
        "add": tab.add_btn,
        "group_add": tab.group_add_btn,
    }


def _stage_tab_buttons(config):
    from gui.tabs.stage_tab import StageTab
    tab = StageTab(config, parent=None)
    return tab, {
        "layer_add": tab.add_layer_btn,
        "layer_remove": tab.remove_layer_btn,
        "mark_add": tab.add_spot_btn,
        "mark_remove": tab.remove_item_btn,
    }


_COLLECTORS = {
    "fixtures": _fixtures_tab_buttons,
    "stage": _stage_tab_buttons,
}


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("tab_name", sorted(_COLLECTORS))
def test_no_button_glyph_is_clipped(qapp, sample_configuration, theme, tab_name):
    from gui.theme_manager import ThemeManager
    ThemeManager().apply(qapp, theme)

    tab, buttons = _COLLECTORS[tab_name](sample_configuration)
    try:
        assert buttons, f"collector for {tab_name} found no buttons"
        for name, button in buttons.items():
            button.adjustSize()
            try:
                assert_text_not_clipped(button)
            except AssertionError as e:
                raise AssertionError(f"[{theme}/{tab_name}.{name}] {e}") from e
    finally:
        tab.deleteLater()
