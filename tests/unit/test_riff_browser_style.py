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

from PyQt6.QtWidgets import QLabel, QPushButton

from config.models import Riff, Scene
from gui.theme_tokens import THEMES, render_theme
from scenes.scene_library import SceneLibrary
from timeline_ui.riff_browser_widget import (
    RiffBrowserPanel,
    RiffItemWidget,
    SceneItemWidget,
    CollapsedRiffBar,
    SCENE_MIME_TYPE,
    SCENES_EMPTY_TEXT,
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


# ── Scenes section (timeline v3 stage T5) ────────────────────────────
#
# The library rail lists the shared SceneLibrary below the riff
# categories. Display + drag SOURCE only: the rows carry a distinct
# scene mime type, and no timeline accepts it - cross-lane scene drops
# are deferred to the capability-mapping pass (docs/timeline-v3-plan.md
# "Deferred"), so the drag is inert by design.


def _empty_scene_library() -> SceneLibrary:
    # A directory that does not exist yields an empty library (that is
    # SceneLibrary's documented missing-dir behaviour).
    return SceneLibrary(scenes_directory="__no_such_scenes_dir__")


def _scene_library(*scenes) -> SceneLibrary:
    lib = _empty_scene_library()
    for scene in scenes:
        lib.add_scene(scene, scene.category)
    return lib


@pytest.fixture
def scenes_panel(qapp):
    lib = _scene_library(
        Scene(name="Drop Total", category="general", color="#F0562E",
              groups=["Front", "Back", "Movers", "Blinders"]),
        Scene(name="Warm Pause", category="general",
              groups=["Front"]),
    )
    panel = RiffBrowserPanel(scene_library=lib)
    yield panel
    panel.deleteLater()


def _scene_row_widgets(panel):
    section = panel._scenes_item
    return [panel.tree.itemWidget(section.child(i), 0)
            for i in range(section.childCount())]


def test_scenes_section_is_last_and_labelled(scenes_panel):
    from PyQt6.QtCore import Qt
    tree = scenes_panel.tree
    last = tree.topLevelItem(tree.topLevelItemCount() - 1)
    assert last is scenes_panel._scenes_item
    assert "Scenes (2)" in last.text(0)
    data = last.data(0, Qt.ItemDataRole.UserRole)
    assert data["type"] == "scene_category"


def test_scene_rows_show_name_chip_and_group_tag(scenes_panel):
    rows = _scene_row_widgets(scenes_panel)
    assert all(isinstance(w, SceneItemWidget) for w in rows)
    by_name = {w.scene.name: w for w in rows}

    coloured = by_name["Drop Total"]
    names = [lbl.text() for lbl in coloured.findChildren(QLabel)
             if lbl.text()]
    assert "Drop Total" in names
    assert coloured.tag_label.text() == "4 GROUPS"
    # The colour chip is an ACTUAL painted swatch of scene.color.
    assert coloured.chip_label is not None
    pixmap = coloured.chip_label.pixmap()
    assert not pixmap.isNull()
    center = pixmap.toImage().pixelColor(pixmap.width() // 2,
                                         pixmap.height() // 2)
    assert center.name().upper() == "#F0562E"

    plain = by_name["Warm Pause"]
    assert plain.chip_label is None  # no colour set -> no chip
    assert plain.tag_label.text() == "1 GROUP"


def test_scene_drag_mime_is_distinct_from_riffs(scenes_panel):
    import json
    assert SCENE_MIME_TYPE == "application/x-lm-scene"
    widget = _scene_row_widgets(scenes_panel)[0]
    mime = widget._build_mime_data()
    assert mime.hasFormat(SCENE_MIME_TYPE)
    # NOT the riff mime: timelines only accept riff drops, so the scene
    # drag stays inert until the deferred drop handler lands.
    assert not mime.hasFormat("application/x-qlc-riff")
    payload = json.loads(bytes(mime.data(SCENE_MIME_TYPE)).decode())
    assert payload["key"] == "general/Drop Total"
    assert payload["groups"] == ["Front", "Back", "Movers", "Blinders"]


def test_empty_scene_library_shows_the_live_tab_marker(qapp):
    panel = RiffBrowserPanel(scene_library=_empty_scene_library())
    try:
        section = panel._scenes_item
        assert "Scenes (0)" in section.text(0)
        assert section.childCount() == 1
        marker = panel.tree.itemWidget(section.child(0), 0)
        assert isinstance(marker, QLabel)
        assert marker.text() == SCENES_EMPTY_TEXT
        assert marker.text() == \
            "No scenes yet · predefined looks arrive later"
        assert marker.property("role") == "micro"
    finally:
        panel.deleteLater()


def test_scene_library_resolves_to_safe_empty_fallback(panel):
    # No injected library and no main-window scene_library attribute:
    # the panel must still render a (possibly empty) scenes section
    # rather than crash - the same fallback the Live tab uses.
    assert panel._scenes_item is not None
    lib = panel._resolve_scene_library()
    assert lib is not None


def test_tree_selection_is_accent_in_rendered_dark_theme():
    # Where the look matters, assert the rendered theme rule rather than a
    # widget stylesheet: a selected tree row paints the brand accent, so a
    # highlighted category reads Glutorange, never the old Windows-blue.
    qss = render_theme("dark")
    accent = THEMES["dark"]["accent"]
    assert f"selection-background-color: {accent}" in qss
    assert "#0078d4" not in qss


# =============================================================================
# Riff tagging in the browser (v1.3): tags on the card, Edit Tags menu
# =============================================================================

@pytest.fixture
def tag_panel(qapp, tmp_path):
    from riffs.riff_library import RiffLibrary
    library = RiffLibrary(str(tmp_path))
    library.save_riff(Riff(name="warm_wash", tags=["chorus", "slow"]),
                      "loops")
    library.save_riff(Riff(name="plain", tags=[]), "loops")
    p = RiffBrowserPanel(riff_library=library)
    yield p, library
    p.deleteLater()


def _riff_items(panel):
    """{riff name: (tree item, riff)} for every riff row."""
    from PyQt6.QtCore import Qt
    out = {}
    for i in range(panel.tree.topLevelItemCount()):
        cat = panel.tree.topLevelItem(i)
        for j in range(cat.childCount()):
            child = cat.child(j)
            data = child.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get("type") == "riff":
                out[data["riff"].name] = (child, data["riff"])
    return out


def test_card_shows_tags_when_present(tag_panel):
    panel, _ = tag_panel
    item, _riff = _riff_items(panel)["warm_wash"]
    widget = panel.tree.itemWidget(item, 0)
    labels = [l.text() for l in widget.findChildren(QLabel)]
    assert "#chorus #slow" in labels

    item, _riff = _riff_items(panel)["plain"]
    widget = panel.tree.itemWidget(item, 0)
    assert not any(t.startswith("#") for t in
                   (l.text() for l in widget.findChildren(QLabel)))


def test_edit_tags_saves_and_rerenders(tag_panel, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QInputDialog
    from riffs.riff_library import RiffLibrary
    panel, library = tag_panel

    _item, riff = _riff_items(panel)["plain"]
    monkeypatch.setattr(
        QInputDialog, "getText",
        staticmethod(lambda *a, **k: ("Punchy, #drop", True)))
    panel._edit_riff_tags(riff)

    assert riff.tags == ["Punchy", "drop"]
    # Persisted: a fresh library reads the tags back from disk.
    assert RiffLibrary(str(tmp_path)).get_riff("loops/plain").tags == \
        ["Punchy", "drop"]
    # ...and the rebuilt card shows them.
    item, _r = _riff_items(panel)["plain"]
    widget = panel.tree.itemWidget(item, 0)
    labels = [l.text() for l in widget.findChildren(QLabel)]
    assert "#Punchy #drop" in labels


def test_edit_tags_cancel_changes_nothing(tag_panel, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QInputDialog
    from riffs.riff_library import RiffLibrary
    panel, _library = tag_panel
    _item, riff = _riff_items(panel)["warm_wash"]
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("ignored", False)))
    panel._edit_riff_tags(riff)
    assert riff.tags == ["chorus", "slow"]
    assert RiffLibrary(str(tmp_path)).get_riff(
        "loops/warm_wash").tags == ["chorus", "slow"]


def test_search_by_hash_tag_filters_the_tree(tag_panel):
    panel, _ = tag_panel
    panel._on_search_changed("#chorus")
    names = set(_riff_items(panel))
    assert names == {"warm_wash"}
