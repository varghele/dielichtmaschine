"""North Star styling for the riff browser panel.

Covers docs/timeline-styling-review.md item 3: the pre-rebrand
Windows-blue (`#0078d4`) selection and Material-gray surfaces
(`#4a4a4a` / `#3c3c3c` / `#2d2d2d`) inline styles are replaced by brand
theme roles and token-derived widget-local styles.

These assert the *role properties* the widgets carry and the rules from
gui.theme_tokens.render_theme("dark") where the look matters. Per the
task constraints they never assert a widget's live styleSheet() text of
the theme itself, and never open a modal (docs/qt-gotchas.md #7).
"""

import pytest

from PyQt6.QtWidgets import QPushButton

from config.models import Riff
from gui.theme_tokens import THEMES, render_theme
from timeline_ui.riff_browser_widget import (
    RiffBrowserPanel,
    RiffItemWidget,
    CollapsedRiffBar,
    _active_tokens,
)

# The pre-rebrand palette that must be gone from the widget.
MATERIAL_HEXES = ("#0078d4", "#4a4a4a", "#3c3c3c", "#2d2d2d")


@pytest.fixture
def panel(qapp):
    p = RiffBrowserPanel(
        show_collapse_button=True, on_collapse_clicked=lambda: None
    )
    yield p
    p.deleteLater()


def test_panel_container_is_inspector_role(panel):
    assert panel.property("role") == "inspector"


def test_search_and_tree_have_no_inline_stylesheet(panel):
    # They inherit the app-wide QLineEdit / QTreeView styling (brand
    # surfaces, accent focus and accent selection), so no widget-local
    # override remains. The tree in particular must not carry a
    # QTreeWidget::item rule (docs/qt-gotchas.md #1).
    assert panel.search_input.styleSheet() == ""
    assert panel.tree.styleSheet() == ""


def test_status_caption_is_micro_role(panel):
    assert panel.status_label.property("role") == "micro"


def test_collapse_chevron_is_pane_icon(panel):
    assert panel._collapse_btn.property("role") == "pane-icon"


def test_refresh_button_is_output_select(panel):
    # The refresh button is a local, so locate it by its glyph.
    refresh = [b for b in panel.findChildren(QPushButton) if b.text() == "↻"]
    assert refresh, "refresh button not found"
    assert refresh[0].property("role") == "output-select"


def test_riff_item_uses_brand_tokens_not_material(qapp):
    riff = Riff(name="test_riff", category="loops", length_beats=4.0)
    widget = RiffItemWidget(riff)
    try:
        ss = widget.styleSheet().lower()
        for hexv in MATERIAL_HEXES:
            assert hexv not in ss, f"{hexv} still present in riff item style"

        tokens = _active_tokens()  # dark when no theme is applied
        # The card surface + accent hover come from brand tokens.
        assert tokens["raised"].lower() in ss
        assert tokens["accent"].lower() in ss
    finally:
        widget.deleteLater()


def test_riff_item_info_caption_is_micro_role(qapp):
    from PyQt6.QtWidgets import QLabel

    riff = Riff(name="test_riff", category="loops", length_beats=8.0)
    widget = RiffItemWidget(riff)
    try:
        micro = [
            lbl
            for lbl in widget.findChildren(QLabel)
            if lbl.property("role") == "micro"
        ]
        assert micro, "riff info line should use the micro caption role"
    finally:
        widget.deleteLater()


def test_collapsed_bar_carries_brand_roles(qapp):
    bar = CollapsedRiffBar()
    try:
        assert bar.property("role") == "inspector"
        assert bar.expand_btn.property("role") == "pane-icon"
        assert bar.label.property("role") == "micro"
        assert bar.styleSheet() == ""  # no inline Material surface
    finally:
        bar.deleteLater()


def test_tree_selection_is_accent_in_rendered_dark_theme():
    # Where the look matters, assert the rendered theme rule rather than a
    # widget stylesheet: a selected tree row paints the brand accent, so a
    # highlighted category reads Glutorange, never the old Windows-blue.
    qss = render_theme("dark")
    accent = THEMES["dark"]["accent"]
    assert f"selection-background-color: {accent}" in qss
    assert "#0078d4" not in qss
