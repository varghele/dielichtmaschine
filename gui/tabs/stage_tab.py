# gui/tabs/stage_tab.py
"""Setup > Stage, rebuilt to the reference screen
design_handoff_lichtmaschine_app/screens/04-setup-stage.html.

Anatomy (top to bottom, left to right):

- a slim 38px action strip. Right-aligned: the "ACTIVE LAYER" micro
  caption, a bordered segmented chip group (ALL + one chip per stage
  layer + "+ LAYER" + "DEFINE..."), the "OTHERS: 25% · LOCKED" hint,
  a disabled "MORPH..." button and "EXPORT RIDER PDF".
- a 260px LIBRARY panel on the left: "RIG · FIXTURES" group rows (3px
  left border in the group color, caps name, "4x · FLOWN" mono count +
  dominant layer; clicking selects that group's fixtures on the plan),
  a 2-column tile grid of stage elements, a 2-column tile grid of
  trusses, a dashed hint box, and a collapsed "STAGE SETTINGS" section
  that holds every old left-rail control (dimensions, grid, view,
  marks, layers card, planes, plot/launch, TCP status).
- the plan (StageView) in the middle, with non-interactive overlay
  chrome parented to the view: a top-left caption, a top-right accent
  badge naming the active layer, a bottom-left legend and a bottom-
  right title block.
- a 380px right column: a 30px "3D PREVIEW" header with POP-OUT and a
  collapse chevron, the embedded 3D visualizer, a SELECTION card
  (name + group color, X/Y/Z stat tiles, accent LAYER combo, an
  accent-bordered hint, the orientation editor) and a LAYERS section.

Every control that used to live in the left rail kept its attribute
name; the tab's public contract (update_from_config / save_to_config,
layer chips, active-layer editing, element palette, truss docking, 3D
preview + pop-out, TCP notify + visualizer broadcast) is unchanged.
"""

import datetime
import subprocess
import sys
import os

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt, QTimer, QEvent

from utils.app_settings import app_settings
from config.models import Configuration
from .base_tab import BaseTab
from gui.StageView import StageView
from gui.stage_items import FixtureItem
from gui.dialogs.orientation_dialog import OrientationDialog, OrientationPanel
from gui.widgets.embedded_visualizer import EmbeddedVisualizer

# Reference column widths.
LIBRARY_WIDTH = 260
RIGHT_COLUMN_WIDTH = 380
STRIP_HEIGHT = 38
PREVIEW_HEADER_HEIGHT = 30

# The stage-element kinds the reference screen shows first, in its
# order. Every other catalog kind follows so the palette keeps its full
# reach (the catalog carries 14 stage elements, the reference draws 8).
REFERENCE_ELEMENT_ORDER = (
    "drum-riser", "wedge", "amp", "mic-stand",
    "keys", "distro", "riser", "foh",
)


def _active_tokens() -> dict:
    """The token dict of the theme currently applied to the app.

    Same sniff as the Fixtures screen: the applied stylesheet is the
    only reliable record of the active theme (ThemeManager.apply
    deliberately doesn't persist). Falls back to dark.
    """
    from PyQt6.QtWidgets import QApplication
    from gui.theme_tokens import THEMES

    app = QApplication.instance()
    qss = app.styleSheet() if app is not None else ""
    light = THEMES.get("light")
    if light is not None and light["window"] in qss:
        return light
    return THEMES["dark"]


def ordered_element_specs(specs):
    """Catalog specs with the reference's eight tiles first."""
    by_kind = {spec.kind: spec for spec in specs}
    ordered = [by_kind.pop(kind) for kind in REFERENCE_ELEMENT_ORDER
               if kind in by_kind]
    ordered.extend(spec for spec in specs if spec.kind in by_kind)
    return ordered


def dominant_layer(fixtures) -> str:
    """The layer name most of a group's fixtures sit on ('-' when none).

    Ties break on first appearance, which keeps the readout stable for
    the common "all of them are flown" case.
    """
    counts = {}
    for fixture in fixtures:
        name = (getattr(fixture, "layer", "") or "").strip()
        if name:
            counts[name] = counts.get(name, 0) + 1
    if not counts:
        return "-"
    return max(counts, key=lambda name: counts[name])


def group_row_readout(fixtures) -> str:
    """The mono right-hand readout of a library group row: "4x · FLOWN"."""
    return f"{len(fixtures)}x · {dominant_layer(fixtures).upper()}"


class StageTab(BaseTab):
    """Stage layout and fixture positioning tab.

    Composes the StageView 2D plan with a fixture/element library on the
    left and the 3D preview + selection inspector on the right.
    """

    def __init__(self, config: Configuration, parent=None):
        """Initialize stage tab

        Args:
            config: Shared Configuration object
            parent: Parent widget (typically MainWindow)
        """
        self._tokens = _active_tokens()

        super().__init__(config, parent)

        # Tab active state (for pausing TCP updates when not visible)
        self._tab_active = False

        # Throttle timer for TCP updates (avoid flooding during drag)
        self._tcp_update_timer = QTimer()
        self._tcp_update_timer.setSingleShot(True)
        self._tcp_update_timer.setInterval(100)  # 100ms throttle
        self._tcp_update_timer.timeout.connect(self._do_tcp_update)
        self._tcp_update_pending = False

    # ── UI construction ───────────────────────────────────────────────

    def setup_ui(self):
        """Build the reference screen: action strip, library panel, plan
        with overlay chrome, 3D preview + inspector column."""
        self._tokens = _active_tokens()

        outer_layout = QtWidgets.QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        outer_layout.addWidget(self._build_action_strip())

        body_layout = QtWidgets.QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self._build_library_panel())
        body_layout.addWidget(self._build_plan_column(), 1)
        body_layout.addWidget(self._build_right_column())
        outer_layout.addLayout(body_layout, 1)

        self._refresh_layer_list()
        self._refresh_group_rows()
        self._update_selection_inspector([])
        self._refresh_plan_overlays()

    @staticmethod
    def _caption(text):
        """Micro-caption section header (replaces group-box chrome)."""
        from gui.typography import MicroLabel
        label = MicroLabel(text, point_size=8, tracking_em=0.12)
        # A non-wrapping QLabel reports its full text advance as its
        # minimum width, so a long caption would widen the 260px library
        # (and, in the offscreen font-less renders, blow it apart).
        label.setMinimumWidth(1)
        return label

    # -- action strip ---------------------------------------------------

    def _build_action_strip(self) -> QtWidgets.QWidget:
        """38px strip: ACTIVE LAYER chips, lock hint, MORPH, EXPORT."""
        from PyQt6.QtGui import QFont
        from gui.icons import line_icon
        from gui.typography import MicroLabel, display_font, mono_font

        tokens = self._tokens
        self._chip_font = mono_font(8, tracking_em=0.05)

        self.action_strip = strip = QtWidgets.QWidget()
        strip.setObjectName("StageActionStrip")
        strip.setProperty("role", "tab-page")
        strip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        strip.setFixedHeight(STRIP_HEIGHT)
        strip_row = QtWidgets.QHBoxLayout(strip)
        strip_row.setContentsMargins(16, 0, 16, 0)
        strip_row.setSpacing(8)
        strip_row.addStretch(1)

        strip_row.addWidget(
            MicroLabel("Active layer", point_size=8, tracking_em=0.12))

        # Bordered segmented chip group. role="card" supplies the panel
        # background + 1px border; each segment is borderless and paints
        # accent-filled when checked (widget-local, see NEEDED-QSS).
        self.layer_bar = QtWidgets.QWidget()
        self.layer_bar.setProperty("role", "card")
        self.layer_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,
                                    True)
        bar_layout = QtWidgets.QHBoxLayout(self.layer_bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(0)

        self._layer_chip_group = QtWidgets.QButtonGroup(self)
        self._layer_chip_group.setExclusive(True)

        self.all_layers_chip = QtWidgets.QPushButton("ALL")
        self.all_layers_chip.setCheckable(True)
        self.all_layers_chip.setChecked(True)
        self.all_layers_chip.setToolTip(
            "Edit all layers (no active-layer ghosting)")
        self._style_segment(self.all_layers_chip)
        self._layer_chip_group.addButton(self.all_layers_chip)
        bar_layout.addWidget(self.all_layers_chip)

        # Per-layer chips are rebuilt from the config in
        # _refresh_layer_chips; this sub-layout keeps them grouped
        # between the ALL chip and the + LAYER chip.
        self._chip_host = QtWidgets.QHBoxLayout()
        self._chip_host.setSpacing(0)
        bar_layout.addLayout(self._chip_host)
        self.layer_chips = {}

        self.add_layer_chip = QtWidgets.QPushButton("+ LAYER")
        self.add_layer_chip.setToolTip("Add a stage layer (named Z-plane)")
        self._style_segment(self.add_layer_chip, divider=True)
        bar_layout.addWidget(self.add_layer_chip)

        self.define_layer_chip = QtWidgets.QPushButton("DEFINE...")
        self.define_layer_chip.setToolTip(
            "Rename the active layer or move it to another height")
        self._style_segment(self.define_layer_chip, divider=True)
        bar_layout.addWidget(self.define_layer_chip)

        strip_row.addWidget(self.layer_bar)

        # Mirrors the reference's "ANDERE: 25 % · GESPERRT" hint - only
        # shown while a layer is active.
        self.layer_lock_hint = MicroLabel(
            "Others: 25% · locked", point_size=8, tracking_em=0.12)
        self.layer_lock_hint.setVisible(False)
        strip_row.addWidget(self.layer_lock_hint)

        strip_font = display_font(11, QFont.Weight.DemiBold, tracking_em=0.08)

        self.morph_btn = QtWidgets.QPushButton("MORPH...")
        self.morph_btn.setIcon(line_icon("morph", tokens["text_disabled"]))
        self.morph_btn.setFont(strip_font)
        self.morph_btn.setEnabled(False)
        self.morph_btn.setToolTip("Arrives with the morph milestone")
        strip_row.addWidget(self.morph_btn)

        self.export_rider_btn = QtWidgets.QPushButton("EXPORT RIDER PDF")
        self.export_rider_btn.setIcon(
            line_icon("export", tokens["text_secondary"]))
        self.export_rider_btn.setFont(strip_font)
        self.export_rider_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_rider_btn.setToolTip(
            "Export the rig as a PDF or PNG stage plot")
        strip_row.addWidget(self.export_rider_btn)
        return strip

    def _style_segment(self, chip: QtWidgets.QPushButton,
                       divider: bool = False) -> None:
        """Segmented-chip chrome, theme-owned: QPushButton[role="segment"]
        is borderless, accent-FILLED when checked, and grows a left
        hairline with [divider="true"]."""
        chip.setProperty("role", "segment")
        chip.setProperty("divider", "true" if divider else "false")
        chip.setFont(self._chip_font)
        chip.setCursor(Qt.CursorShape.PointingHandCursor)

    # -- left library panel ---------------------------------------------

    def _build_library_panel(self) -> QtWidgets.QWidget:
        """The 260px library: fixtures, elements, trusses, settings."""
        from gui.typography import MicroLabel

        # role=tab-page so the rail paints the themed window background
        # even when rendered standalone (golden tests grab it bare).
        self.control_panel = QtWidgets.QWidget()
        self.control_panel.setObjectName("StageLibrary")
        self.control_panel.setProperty("role", "tab-page")
        self.control_panel.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True)
        self.control_panel.setFixedWidth(LIBRARY_WIDTH)
        panel_layout = QtWidgets.QVBoxLayout(self.control_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QtWidgets.QWidget()
        control_layout = QtWidgets.QVBoxLayout(inner)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(0)
        scroll.setWidget(inner)
        panel_layout.addWidget(scroll, 1)

        control_layout.addWidget(self._section_caption("Rig · fixtures"))

        self._group_rows_container = QtWidgets.QWidget()
        self._group_rows_layout = QtWidgets.QVBoxLayout(
            self._group_rows_container)
        self._group_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._group_rows_layout.setSpacing(0)
        control_layout.addWidget(self._group_rows_container)

        self.groups_empty_hint = MicroLabel(
            "No fixture groups yet", point_size=8, tracking_em=0.1)
        self.groups_empty_hint.setMinimumWidth(1)
        self.groups_empty_hint.setContentsMargins(16, 8, 16, 8)
        control_layout.addWidget(self.groups_empty_hint)

        # Element palette: click a symbol to place a static stage element
        # at stage center; drag it into place on the plan. Symbols and
        # default footprints come from utils/stage_element_catalog.py.
        from utils.stage_element_catalog import (
            CATEGORY_STAGE, CATEGORY_TRUSS, specs_for_category,
        )
        self.element_buttons = {}

        control_layout.addWidget(
            self._section_caption("Stage elements · click to place"))
        control_layout.addLayout(
            self._element_grid(ordered_element_specs(
                specs_for_category(CATEGORY_STAGE))))

        control_layout.addWidget(
            self._section_caption("Trusses · height freely set"))
        control_layout.addLayout(
            self._element_grid(specs_for_category(CATEGORY_TRUSS)))

        self.truss_hint = QtWidgets.QLabel(
            "Drag a truss, set height + length; fixtures dock to it. "
            "Ground support = tower at both ends.")
        self.truss_hint.setProperty("role", "hint-box")
        self.truss_hint.setWordWrap(True)
        hint_font = self.truss_hint.font()
        hint_font.setPointSize(8)
        self.truss_hint.setFont(hint_font)
        hint_wrap = QtWidgets.QVBoxLayout()
        hint_wrap.setContentsMargins(12, 10, 12, 10)
        hint_wrap.addWidget(self.truss_hint)
        control_layout.addLayout(hint_wrap)

        control_layout.addStretch(1)
        control_layout.addWidget(self._build_settings_section())
        return self.control_panel

    def _section_caption(self, text: str) -> QtWidgets.QWidget:
        """A caption with the reference's hairline separators."""
        holder = QtWidgets.QWidget()
        holder.setObjectName("StageSectionCaption")
        holder.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Theme-owned: QWidget[role="section-caption"].
        holder.setProperty("role", "section-caption")
        row = QtWidgets.QHBoxLayout(holder)
        row.setContentsMargins(16, 8, 16, 8)
        row.addWidget(self._caption(text))
        row.addStretch()
        return holder

    def _element_grid(self, specs) -> QtWidgets.QGridLayout:
        """A 2-column tile grid: 30px symbol above a mono caps label."""
        from PyQt6.QtCore import QSize
        from PyQt6.QtGui import QIcon
        from gui.fonts import FONT_MONO
        from utils.stage_element_catalog import symbol_path

        grid = QtWidgets.QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(1)
        # Equal columns: without this the wider label ("WEDGE MONITOR")
        # steals the column and the right tile clips at the panel edge.
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        for i, spec in enumerate(specs):
            tile = QtWidgets.QToolButton()
            tile.setIcon(QIcon(symbol_path(spec.kind)))
            tile.setIconSize(QSize(30, 30))
            tile.setText(spec.label.upper())
            tile.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            # Theme-owned: QToolButton[role="element-tile"] (mono 9px
            # caption, bordered, accent on hover).
            tile.setProperty("role", "element-tile")
            tile.setStyleSheet("QToolButton { padding: 8px 2px; }")
            tile.setMinimumHeight(62)
            # A QToolButton's minimumSizeHint is its label advance; leave
            # it and the wider label wins the column (and the second tile
            # clips at the panel edge). Explicit minimum + Ignored policy
            # splits the panel in two even halves.
            tile.setMinimumWidth(1)
            # Ignored horizontally: the tile takes exactly half the panel
            # instead of the label's natural advance (which differs per
            # label and would break the 2-column rhythm).
            tile.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                               QtWidgets.QSizePolicy.Policy.Fixed)
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.setToolTip(f"{spec.label} "
                            f"({spec.width:g} x {spec.depth:g} m)")
            tile.clicked.connect(
                lambda _=False, k=spec.kind: self._add_stage_element(k))
            grid.addWidget(tile, i // 2, i % 2)
            self.element_buttons[spec.kind] = tile
        return grid

    # -- stage settings (the old left-rail controls) ---------------------

    def _build_settings_section(self) -> QtWidgets.QWidget:
        """Collapsed-by-default section holding every old left-rail
        control, attribute names unchanged."""
        from PyQt6.QtGui import QFont
        from gui.fonts import FONT_MONO
        from gui.icons import line_icon
        from gui.typography import MicroLabel, display_font, mono_font

        holder = QtWidgets.QWidget()
        holder_layout = QtWidgets.QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.setSpacing(0)

        self.settings_toggle = QtWidgets.QToolButton()
        self.settings_toggle.setText("STAGE SETTINGS")
        self.settings_toggle.setCheckable(True)
        self.settings_toggle.setChecked(False)
        self.settings_toggle.setIcon(
            line_icon("settings", self._tokens["text_secondary"]))
        self.settings_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.settings_toggle.setProperty("role", "topbar-icon")
        self.settings_toggle.setStyleSheet(
            "QToolButton {"
            f" font-family: \"{FONT_MONO}\"; font-size: 10px;"
            " padding: 8px 16px; text-align: left; }")
        self.settings_toggle.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed)
        self.settings_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_toggle.setToolTip(
            "Stage dimensions, grid, view, marks, layers, planes, export")
        holder_layout.addWidget(self.settings_toggle)

        self.settings_container = QtWidgets.QWidget()
        self.settings_container.setVisible(False)
        control_layout = QtWidgets.QVBoxLayout(self.settings_container)
        control_layout.setContentsMargins(16, 8, 16, 12)
        control_layout.setSpacing(6)

        caption = self._caption

        # Stage dimensions: compact mono-labelled fields.
        control_layout.addWidget(caption("Stage"))
        dims_row = QtWidgets.QHBoxLayout()
        dims_row.setSpacing(6)

        self.stage_width = QtWidgets.QSpinBox()
        self.stage_width.setRange(1, 1000)
        self.stage_width.setValue(10)  # Default 10 meters
        self.stage_width.setFont(mono_font(10))

        self.stage_height = QtWidgets.QSpinBox()
        self.stage_height.setRange(1, 1000)
        self.stage_height.setValue(6)  # Default 6 meters
        self.stage_height.setFont(mono_font(10))

        # No "Update Stage" button — the spinboxes' valueChanged signal
        # already drives _update_stage live, matching how the grid-size
        # spinbox below works.
        for label_text, spin in (("Width / m", self.stage_width),
                                 ("Depth / m", self.stage_height)):
            col = QtWidgets.QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(MicroLabel(label_text, point_size=8,
                                     tracking_em=0.1))
            col.addWidget(spin)
            dims_row.addLayout(col)
        control_layout.addLayout(dims_row)

        # Grid: 0.5 m default, snap on.
        control_layout.addSpacing(4)
        control_layout.addWidget(caption("Grid"))

        self.grid_size = QtWidgets.QDoubleSpinBox()
        self.grid_size.setRange(0.1, 50)
        self.grid_size.setValue(0.5)  # Default 0.5m grid
        self.grid_size.setSingleStep(0.1)
        self.grid_size.setFont(mono_font(10))

        grid_size_row = QtWidgets.QHBoxLayout()
        grid_size_row.setSpacing(6)
        grid_size_row.addWidget(MicroLabel("Size / m", point_size=8,
                                           tracking_em=0.1))
        grid_size_row.addWidget(self.grid_size, 1)
        control_layout.addLayout(grid_size_row)

        self.grid_toggle = QtWidgets.QCheckBox("Show grid")
        self.grid_toggle.setChecked(True)  # Grid visible by default
        control_layout.addWidget(self.grid_toggle)

        self.snap_to_grid = QtWidgets.QCheckBox("Snap to grid")
        self.snap_to_grid.setChecked(True)  # Enable by default
        control_layout.addWidget(self.snap_to_grid)

        # View: fit-view + orientation axes. The 'F' shortcut (wired in
        # connect_signals) duplicates the button so the user can reset
        # without moving the mouse off the plot.
        control_layout.addSpacing(4)
        control_layout.addWidget(caption("View"))
        self.fit_view_btn = QtWidgets.QPushButton("Fit View (F)")
        self.fit_view_btn.setToolTip(
            "Reset zoom and pan to fit the whole stage.\n\n"
            "Stage controls:\n"
            "  • Mouse wheel — zoom (around cursor)\n"
            "  • Space + left-drag — pan\n"
            "  • F — fit view"
        )
        control_layout.addWidget(self.fit_view_btn)

        # Single checkbox - when on, every fixture draws its XYZ
        # axes. The previous two-checkbox UX (selected-only by
        # default, with a separate "Show all" toggle) was non-
        # discoverable and read as broken.
        self.show_axes_checkbox = QtWidgets.QCheckBox("Show orientation axes")
        self.show_axes_checkbox.setToolTip("Show XYZ axes on every fixture")
        control_layout.addWidget(self.show_axes_checkbox)

        # Stage marks.
        control_layout.addSpacing(4)
        control_layout.addWidget(caption("Stage marks"))
        self.add_spot_btn = QtWidgets.QPushButton("Add Mark")
        self.remove_item_btn = QtWidgets.QPushButton("Remove Selected")
        control_layout.addWidget(self.add_spot_btn)
        control_layout.addWidget(self.remove_item_btn)

        # Stage layers card - named Z-planes (ground stack / mid-truss /
        # top-truss). Checkbox = visibility; hidden layers disappear from
        # the 2D plot and every 3D preview. Fixtures are assigned via the
        # stage right-click menu ("Assign to Layer") or the inspector's
        # Layer combo.
        control_layout.addSpacing(4)
        self.layer_panel = QtWidgets.QWidget()
        self.layer_panel.setProperty("role", "card")
        self.layer_panel.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True)
        layer_layout = QtWidgets.QVBoxLayout(self.layer_panel)
        layer_layout.setContentsMargins(10, 8, 10, 8)
        layer_layout.setSpacing(6)
        layer_layout.addWidget(caption("Stage layers"))

        self.layer_list = QtWidgets.QListWidget()
        self.layer_list.setMaximumHeight(110)
        self.layer_list.setToolTip(
            "Named Z-planes of the rig. Uncheck a layer to hide its\n"
            "fixtures on the stage plot and in the 3D previews.\n"
            "Assign fixtures via right-click on the stage.\n\n"
            "Double-click a layer (or press L to cycle) to edit only\n"
            "that layer: its fixtures stay live, everything else ghosts\n"
            "to a faint locked reference."
        )
        layer_layout.addWidget(self.layer_list)

        self.active_layer_label = QtWidgets.QLabel("Editing: all layers")
        self.active_layer_label.setFont(mono_font(8))
        self.active_layer_label.setToolTip(
            "Active-layer editing. Double-click a layer or press L to cycle;\n"
            "double-click the active layer again to return to all layers."
        )
        layer_layout.addWidget(self.active_layer_label)

        # TOOLBAR_BTN_WIDTH (40), not less: the theme's 14px horizontal
        # button padding clips the glyph's content rect on anything
        # narrower — a 32px "+" renders as a cut-off sliver. Same
        # convention as FixturesTab's toolbar (see test_fixtures_tab.py).
        from gui.tabs.configuration_tab import TOOLBAR_BTN_WIDTH
        layer_btn_row = QtWidgets.QHBoxLayout()
        self.add_layer_btn = QtWidgets.QPushButton("+")
        self.add_layer_btn.setFixedWidth(TOOLBAR_BTN_WIDTH)
        self.add_layer_btn.setToolTip("Add Layer")
        self.remove_layer_btn = QtWidgets.QPushButton("-")
        self.remove_layer_btn.setFixedWidth(TOOLBAR_BTN_WIDTH)
        self.remove_layer_btn.setToolTip(
            "Remove Layer (fixtures keep their height)")
        self.edit_layer_btn = QtWidgets.QPushButton("Edit")
        self.edit_layer_btn.setToolTip(
            "Rename the layer or move it to another height")
        layer_btn_row.addWidget(self.add_layer_btn)
        layer_btn_row.addWidget(self.remove_layer_btn)
        layer_btn_row.addWidget(self.edit_layer_btn)
        layer_btn_row.addStretch()
        layer_layout.addLayout(layer_btn_row)
        control_layout.addWidget(self.layer_panel)

        # Stage planes - picker for the 6 faces of the stage bounding
        # cuboid. Hovering an entry highlights that face in the
        # embedded 3D preview; clicking selects it persistently; clicking
        # the selected entry again clears. Display-only for now — plane
        # *targeting* from movement blocks is v1.4a.
        from visualizer.renderer.stage_planes import PLANE_NAMES
        control_layout.addSpacing(4)
        control_layout.addWidget(caption("Stage planes"))

        self.plane_list = QtWidgets.QListWidget()
        self.plane_list.setMaximumHeight(120)
        self.plane_list.setMouseTracking(True)
        self.plane_list.setToolTip(
            "The 6 faces of the stage bounding box.\n"
            "Hover to preview, click to keep highlighted in the 3D view,\n"
            "click again to clear."
        )
        for plane_name in PLANE_NAMES:
            item = QtWidgets.QListWidgetItem(plane_name)
            item.setData(Qt.ItemDataRole.UserRole, plane_name)
            self.plane_list.addItem(item)
        self._selected_plane = None
        control_layout.addWidget(self.plane_list)

        # Bottom actions: Plot Stage (the deliverable, same handler as
        # the strip's EXPORT RIDER PDF) + 3D visualizer launch.
        control_layout.addSpacing(4)
        self.plot_stage_btn = QtWidgets.QPushButton("PLOT STAGE")
        self.plot_stage_btn.setProperty("role", "primary")
        self.plot_stage_btn.setFont(display_font(11, QFont.Weight.Bold,
                                                 tracking_em=0.08))
        self.plot_stage_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.plot_stage_btn.setToolTip(
            "Export the rig as a PDF or PNG stage plot")
        control_layout.addWidget(self.plot_stage_btn)

        self.launch_visualizer_btn = QtWidgets.QPushButton("LAUNCH VISUALIZER")
        self.launch_visualizer_btn.setFont(
            display_font(11, QFont.Weight.DemiBold, tracking_em=0.08))
        self.launch_visualizer_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.launch_visualizer_btn.setToolTip(
            "Start the 3D Visualizer application")
        control_layout.addWidget(self.launch_visualizer_btn)

        # TCP status indicator
        tcp_status_layout = QtWidgets.QHBoxLayout()
        tcp_status_layout.setSpacing(6)
        tcp_status_layout.addWidget(
            MicroLabel("TCP server", point_size=8, tracking_em=0.1))
        self.tcp_status_label = QtWidgets.QLabel()
        self.tcp_status_label.setStyleSheet("font-weight: bold;")
        self.tcp_status_label.setFont(mono_font(8))
        tcp_status_layout.addWidget(self.tcp_status_label)
        tcp_status_layout.addStretch()
        control_layout.addLayout(tcp_status_layout)

        # Visualizer process reference
        self.visualizer_process = None

        # Timer to update TCP status
        self.tcp_status_timer = QTimer()
        self.tcp_status_timer.timeout.connect(self._update_tcp_status)
        self.tcp_status_timer.start(1000)  # Update every second

        # Initial status update
        self._update_tcp_status()

        holder_layout.addWidget(self.settings_container)
        return holder

    # -- centre plan + overlay chrome ------------------------------------

    def _build_plan_column(self) -> QtWidgets.QWidget:
        """The StageView plus its non-interactive overlay chrome."""
        from gui.typography import MicroLabel, mono_font

        tokens = self._tokens

        self.stage_view = StageView(self)
        self.stage_view.set_config(self.config)
        self.stage_view.installEventFilter(self)

        def overlay(widget):
            widget.setParent(self.stage_view)
            widget.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            widget.raise_()
            return widget

        self.plan_caption = overlay(
            MicroLabel("Stage plan", point_size=8, tracking_em=0.12))

        self.active_layer_badge = overlay(QtWidgets.QLabel(""))
        self.active_layer_badge.setObjectName("StagePlanBadge")
        self.active_layer_badge.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True)
        self.active_layer_badge.setFont(mono_font(7, tracking_em=0.1))
        self.active_layer_badge.setStyleSheet(
            "#StagePlanBadge {"
            f" background-color: {tokens['raised']};"
            f" border: 1px solid {tokens['accent']};"
            f" color: {tokens['accent_line']};"
            " padding: 4px 10px; }")
        self.active_layer_badge.setVisible(False)

        self.plan_legend = overlay(self._build_legend())
        self.title_block = overlay(self._build_title_block())
        return self.stage_view

    def _swatch(self, style: str, width: int, height: int) -> QtWidgets.QWidget:
        swatch = QtWidgets.QWidget()
        swatch.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        swatch.setFixedSize(width, height)
        swatch.setStyleSheet(f"QWidget {{ {style} }}")
        return swatch

    def _build_legend(self) -> QtWidgets.QWidget:
        """Bottom-left legend row (mono 9px, four swatched entries)."""
        from gui.typography import mono_font

        tokens = self._tokens
        line = tokens["stage_outline"]
        dim = tokens["text_disabled"]

        legend = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(legend)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)

        def entry(swatch, text):
            holder = QtWidgets.QWidget()
            inner = QtWidgets.QHBoxLayout(holder)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.setSpacing(6)
            inner.addWidget(swatch)
            label = QtWidgets.QLabel(text)
            label.setFont(mono_font(7, tracking_em=0.05))
            label.setStyleSheet(f"color: {tokens['text_secondary']};")
            inner.addWidget(label)
            row.addWidget(holder)
            return label

        self.legend_active_label = entry(
            self._swatch(f"border-top: 2px solid {line};", 20, 3),
            "ALL LAYERS")
        entry(self._swatch(f"border-top: 2px dashed {dim};", 20, 3),
              "OTHER LAYERS")
        entry(self._swatch(
            f"border: 2px dashed {dim}; border-radius: 6px;", 12, 12),
            "FIXTURE (OTHER LAYER)")
        entry(self._swatch(f"border: 2px solid {line};", 14, 9),
              "FIXTURE (ACTIVE)")
        return legend

    def _build_title_block(self) -> QtWidgets.QWidget:
        """Bottom-right 2x2 mono title block (drawing-sheet convention)."""
        from gui.typography import mono_font

        tokens = self._tokens
        block = QtWidgets.QWidget()
        block.setObjectName("StageTitleBlock")
        block.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        block.setStyleSheet(
            "#StageTitleBlock {"
            f" background-color: {tokens['raised']};"
            f" border: 1px solid {tokens['border']}; }}")
        grid = QtWidgets.QGridLayout(block)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        def cell(row, col, strong=False):
            label = QtWidgets.QLabel("")
            label.setFont(mono_font(7, tracking_em=0.05))
            color = tokens["text"] if strong else tokens["text_secondary"]
            right = (f"border-right: 1px solid {tokens['border']};"
                     if col == 0 else "")
            bottom = (f"border-bottom: 1px solid {tokens['border']};"
                      if row == 0 else "")
            label.setStyleSheet(
                f"QLabel {{ color: {color}; padding: 5px 10px;"
                f" {right} {bottom} }}")
            grid.addWidget(label, row, col)
            return label

        self.title_name = cell(0, 0, strong=True)
        self.title_sheet = cell(0, 1)
        self.title_dims = cell(1, 0)
        self.title_date = cell(1, 1)
        return block

    def _position_plan_overlays(self) -> None:
        """Keep the overlay chrome pinned to the plan's corners."""
        if not hasattr(self, "title_block"):
            return
        width = self.stage_view.width()
        height = self.stage_view.height()
        for widget in (self.plan_caption, self.active_layer_badge,
                       self.plan_legend, self.title_block):
            widget.adjustSize()
        self.plan_caption.move(14, 10)
        self.active_layer_badge.move(
            max(14, width - self.active_layer_badge.width() - 14), 8)
        self.plan_legend.move(
            14, max(0, height - self.plan_legend.height() - 12))
        self.title_block.move(
            max(14, width - self.title_block.width() - 14),
            max(0, height - self.title_block.height() - 12))

    def _refresh_plan_overlays(self) -> None:
        """Reload the overlay texts from the config + active layer."""
        if not hasattr(self, "title_block"):
            return
        grid_m = getattr(self.stage_view, "grid_size_m", 0.5)
        self.plan_caption.setText(
            f"Stage plan · top view · 1 square = {grid_m:g} m")

        active = getattr(self.stage_view, "active_layer", None)
        layer = self.config.get_stage_layer(active) if active else None
        if layer is not None:
            self.active_layer_badge.setText(
                f"ACTIVE LAYER: {layer.name.upper()} "
                f"{layer.z_height:g} M · OTHERS DIMMED")
            self.active_layer_badge.setVisible(True)
            self.legend_active_label.setText(
                f"{layer.name.upper()} {layer.z_height:g} m")
        else:
            self.active_layer_badge.setVisible(False)
            self.legend_active_label.setText("ALL LAYERS")

        loaded_from = getattr(self.config, "_loaded_from", None)
        name = (os.path.splitext(os.path.basename(loaded_from))[0]
                if loaded_from else "") or "UNTITLED"
        self.title_name.setText(f"STAGE PLAN · {name.upper()}")
        self.title_sheet.setText("SHEET 1/1")
        self.title_dims.setText(
            f"{self.config.stage_width:g}x{self.config.stage_height:g} m")
        self.title_date.setText(datetime.date.today().isoformat())
        self._position_plan_overlays()

    # -- right column: 3D preview + inspector ----------------------------

    def _build_right_column(self) -> QtWidgets.QWidget:
        """3D preview header, the embedded visualizer, the inspector."""
        from PyQt6.QtCore import QSize
        from gui.icons import line_icon
        from gui.typography import MicroLabel, mono_font

        tokens = self._tokens

        column = QtWidgets.QWidget()
        column.setObjectName("StageRightColumn")
        column.setProperty("role", "tab-page")
        column.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        column.setFixedWidth(RIGHT_COLUMN_WIDTH)
        column_layout = QtWidgets.QVBoxLayout(column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(0)

        header = QtWidgets.QWidget()
        header.setFixedHeight(PREVIEW_HEADER_HEIGHT)
        header_row = QtWidgets.QHBoxLayout(header)
        header_row.setContentsMargins(14, 0, 10, 0)
        header_row.setSpacing(10)
        header_row.addWidget(MicroLabel("3D preview", point_size=8,
                                        tracking_em=0.12))
        header_row.addStretch()

        self.popout_btn = QtWidgets.QPushButton("POP-OUT")
        self.popout_btn.setProperty("role", "nav")
        self.popout_btn.setFont(mono_font(8, tracking_em=0.1))
        self.popout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.popout_btn.setToolTip("Pop the 3D preview out to a second screen")
        header_row.addWidget(self.popout_btn)

        self.preview_collapse_btn = QtWidgets.QToolButton()
        self.preview_collapse_btn.setCheckable(True)
        self.preview_collapse_btn.setIcon(
            line_icon("chevron-right", tokens["text_secondary"]))
        self.preview_collapse_btn.setIconSize(QSize(14, 14))
        self.preview_collapse_btn.setFixedSize(24, 24)
        self.preview_collapse_btn.setProperty("role", "topbar-icon")
        self.preview_collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview_collapse_btn.setToolTip("Collapse the 3D preview")
        header_row.addWidget(self.preview_collapse_btn)
        column_layout.addWidget(header)

        # Embedded 3D preview (unchanged); the header above owns pop-out
        # so the widget's own duplicate button is hidden.
        self.embedded_visualizer = EmbeddedVisualizer(self)
        self.embedded_visualizer.set_pop_out_callback(self._launch_visualizer)
        self.embedded_visualizer.set_config(self.config)
        self.embedded_visualizer.set_preview_mode("build")
        # The pane header carries POP-OUT (reference 04); don't offer it twice.
        self.embedded_visualizer.set_inner_pop_out_visible(False)

        inspector_scroll = QtWidgets.QScrollArea()
        inspector_scroll.setWidgetResizable(True)
        inspector_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        inspector_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inspector_scroll.setWidget(self._build_inspector())

        right_splitter = QtWidgets.QSplitter(Qt.Orientation.Vertical)
        right_splitter.addWidget(self.embedded_visualizer)
        right_splitter.addWidget(inspector_scroll)
        right_splitter.setStretchFactor(0, 4)
        right_splitter.setStretchFactor(1, 6)
        self._right_splitter = right_splitter

        settings = app_settings()
        right_state = settings.value("stage/right_splitter")
        if right_state is not None:
            try:
                right_splitter.restoreState(right_state)
            except Exception:
                pass

        column_layout.addWidget(right_splitter, 1)
        return column

    def _stat_tile(self, caption_text):
        """Reference stat tile: raised bordered cell, mono micro caption
        over a mono value. Theme-owned via role="stat-tile" (shared with
        the Structure inspector)."""
        from gui.typography import MicroLabel, mono_font

        tile = QtWidgets.QWidget()
        tile.setProperty("role", "stat-tile")
        tile.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QtWidgets.QVBoxLayout(tile)
        layout.setContentsMargins(9, 7, 9, 7)
        layout.setSpacing(2)
        caption = MicroLabel(caption_text, point_size=7, tracking_em=0.1)
        caption.setProperty("role", "stat-caption")
        layout.addWidget(caption)
        value = QtWidgets.QLabel("-")
        value.setProperty("role", "stat-value")
        value.setFont(mono_font(11))
        layout.addWidget(value)
        return tile, value

    def _build_inspector(self) -> QtWidgets.QWidget:
        """SELECTION card + LAYERS section (reference right column)."""
        from PyQt6.QtGui import QFont
        from gui.typography import DisplayLabel, MicroLabel, mono_font

        tokens = self._tokens

        self.inspector_panel = QtWidgets.QWidget()
        self.inspector_panel.setObjectName("StageInspector")
        self.inspector_panel.setProperty("role", "inspector")
        self.inspector_panel.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True)
        inspector_layout = QtWidgets.QVBoxLayout(self.inspector_panel)
        inspector_layout.setContentsMargins(16, 14, 16, 14)
        inspector_layout.setSpacing(10)

        # -- SELECTION --------------------------------------------------
        header_row = QtWidgets.QHBoxLayout()
        header_row.setSpacing(8)
        self.selection_label = DisplayLabel("No fixture selected",
                                            point_size=13,
                                            weight=QFont.Weight.Bold)
        self.selection_label.setWordWrap(True)
        header_row.addWidget(self.selection_label, 1)
        self.selection_group_label = MicroLabel("", point_size=8,
                                                tracking_em=0.1)
        header_row.addWidget(self.selection_group_label)
        inspector_layout.addLayout(header_row)

        stats_row = QtWidgets.QHBoxLayout()
        stats_row.setSpacing(8)
        tile_x, self.stat_x = self._stat_tile("X / m")
        tile_y, self.stat_y = self._stat_tile("Y / m")
        tile_z, self.stat_z = self._stat_tile("Z / m")
        for tile in (tile_x, tile_y, tile_z):
            stats_row.addWidget(tile, 1)
        inspector_layout.addLayout(stats_row)

        layer_combo_row = QtWidgets.QHBoxLayout()
        layer_combo_row.setSpacing(8)
        layer_combo_row.addWidget(
            MicroLabel("Layer", point_size=8, tracking_em=0.12))
        self.layer_combo = QtWidgets.QComboBox()
        self.layer_combo.setFont(mono_font(9))
        self.layer_combo.setEnabled(False)
        # Accent field, per the reference. Theme-owned:
        # QComboBox[role="accent-field"].
        self.layer_combo.setProperty("role", "accent-field")
        self.layer_combo.setToolTip(
            "Assign the selected fixtures to a stage layer.\n"
            "Assignment snaps the fixtures' Z to the layer height\n"
            "(same as right-click > Assign to Layer)."
        )
        layer_combo_row.addWidget(self.layer_combo, 1)
        inspector_layout.addLayout(layer_combo_row)

        self.selection_hint = QtWidgets.QLabel(
            "Only elements on the active layer are selectable and movable. "
            "To move fixtures on other layers, switch layer or reassign "
            "the fixture.")
        self.selection_hint.setObjectName("StageSelectionHint")
        self.selection_hint.setWordWrap(True)
        hint_font = self.selection_hint.font()
        hint_font.setPointSize(8)
        self.selection_hint.setFont(hint_font)
        # Theme-owned: QLabel[role="hint-accent"].
        self.selection_hint.setProperty("role", "hint-accent")
        inspector_layout.addWidget(self.selection_hint)

        # Persistent inline orientation editor — re-bound by the
        # right-click "Set Orientation" flow and by plain selection.
        self.orientation_panel = OrientationPanel([], self.config, self)
        self.orientation_panel.values_changed.connect(
            self._on_inline_orientation_changed)
        # The SELECTION header above owns the selection readout; the
        # panel's internal info label would repeat it.
        self.orientation_panel.info_label.setVisible(False)
        inspector_layout.addWidget(self._caption("Orientation"))
        # The orientation editor's three side-by-side group boxes have a
        # minimum width wider than this 380px column. Left as a direct
        # child it would drag the inspector's minimumSizeHint past the
        # column and silently clip the SELECTION card above it; its own
        # scroll area keeps the column honest.
        orientation_scroll = QtWidgets.QScrollArea()
        orientation_scroll.setWidgetResizable(True)
        orientation_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        orientation_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        orientation_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        orientation_scroll.setWidget(self.orientation_panel)
        # A minimum equal to the panel's full sizeHint made the inspector
        # taller than its column, so on short windows Qt overlapped the
        # LAYERS rows on top of it. The scroll area exists precisely to
        # absorb that: give it a modest floor and let it scroll.
        orientation_scroll.setMinimumHeight(200)
        inspector_layout.addWidget(orientation_scroll, 1)

        # -- LAYERS -----------------------------------------------------
        inspector_layout.addWidget(self._caption("Layers"))
        self._layer_rows_container = QtWidgets.QWidget()
        self._layer_rows_layout = QtWidgets.QVBoxLayout(
            self._layer_rows_container)
        self._layer_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._layer_rows_layout.setSpacing(0)
        inspector_layout.addWidget(self._layer_rows_container)

        self.rider_hint = QtWidgets.QLabel(
            "Rider export: top view + legend + title block as PDF.")
        self.rider_hint.setProperty("role", "hint-box")
        self.rider_hint.setWordWrap(True)
        rider_font = self.rider_hint.font()
        rider_font.setPointSize(8)
        self.rider_hint.setFont(rider_font)
        inspector_layout.addWidget(self.rider_hint)

        inspector_layout.addStretch(1)
        return self.inspector_panel

    # ── Signals ───────────────────────────────────────────────────────

    def connect_signals(self):
        """Connect widget signals to handlers"""
        # Stage dimension controls - auto-update on change.
        self.stage_width.valueChanged.connect(self._update_stage)
        self.stage_height.valueChanged.connect(self._update_stage)

        # Grid controls
        self.grid_toggle.stateChanged.connect(
            lambda state: self.stage_view.updateGrid(visible=bool(state))
        )
        self.grid_size.valueChanged.connect(self._update_grid_size)
        self.snap_to_grid.stateChanged.connect(
            lambda state: self.stage_view.set_snap_to_grid(bool(state))
        )

        # Connect fixture changes to TCP update (for live visualizer sync)
        # AND broadcast a refresh to every embedded visualizer (Stage,
        # Shows, Live) so the 3D previews on other tabs follow 2D edits.
        self.stage_view.fixtures_changed.connect(self._notify_tcp_update)
        self.stage_view.fixtures_changed.connect(self._broadcast_visualizer_refresh)

        # Spot/mark controls
        self.add_spot_btn.clicked.connect(lambda: self.stage_view.add_spot())
        self.remove_item_btn.clicked.connect(self.stage_view.remove_selected_items)

        # Stage layer controls
        self.add_layer_btn.clicked.connect(self._add_layer)
        self.remove_layer_btn.clicked.connect(self._remove_layer)
        self.edit_layer_btn.clicked.connect(self._edit_layer)
        self.layer_list.itemChanged.connect(self._on_layer_item_changed)
        self.layer_list.itemDoubleClicked.connect(self._on_layer_double_clicked)

        # Layer chip row: ALL leaves active-layer editing, + LAYER runs
        # the same add flow as the panel's + button, DEFINE... opens the
        # edit dialog for the active (or first) layer. Per-layer chips
        # connect their own clicked handlers when built.
        self.all_layers_chip.clicked.connect(
            lambda: self._set_active_layer(None))
        self.add_layer_chip.clicked.connect(self._add_layer)
        self.define_layer_chip.clicked.connect(self._define_layer)

        # Inspector layer combo - activated (user picks) only, so
        # programmatic syncs never trigger an assignment.
        self.layer_combo.activated.connect(self._on_layer_combo_activated)

        # L cycles the active layer (all -> layer 1 -> ... -> all), scoped
        # to the Stage tab like the F fit-view shortcut.
        from PyQt6.QtGui import QShortcut, QKeySequence
        self._layer_cycle_shortcut = QShortcut(QKeySequence("L"), self)
        self._layer_cycle_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._layer_cycle_shortcut.activated.connect(self._cycle_active_layer)

        # Stage plane picker: hover previews, click toggles persistence.
        # The event filter catches the mouse leaving the list so a pure
        # hover (no click) reverts to the persistent selection.
        self.plane_list.itemEntered.connect(self._on_plane_hovered)
        self.plane_list.itemClicked.connect(self._on_plane_clicked)
        self.plane_list.viewport().installEventFilter(self)

        # Stage plot export: strip CTA and the settings-section button
        # share one handler.
        self.plot_stage_btn.clicked.connect(self._export_stage_plot)
        self.export_rider_btn.clicked.connect(self._export_stage_plot)

        # Visualizer controls
        self.launch_visualizer_btn.clicked.connect(self._launch_visualizer)
        self.popout_btn.clicked.connect(self._launch_visualizer)
        self.preview_collapse_btn.toggled.connect(self._on_preview_collapsed)

        # Stage settings section
        self.settings_toggle.toggled.connect(
            self.settings_container.setVisible)

        # Orientation display control
        self.show_axes_checkbox.stateChanged.connect(self._on_show_axes_changed)

        # Orientation dialog trigger from right-click menu
        self.stage_view.set_orientation_requested.connect(self._on_set_orientation_requested)

        # Auto-bind the inline orientation panel whenever the user changes
        # the selection on the 2D StageView — single-click on a fixture is
        # enough to start editing it, no right-click required.
        self.stage_view.scene.selectionChanged.connect(self._on_stage_selection_changed)

        # Fit View — button + F shortcut. The shortcut is scoped to this
        # tab (``WidgetWithChildrenShortcut`` on ``self``) so F doesn't
        # collide with the same key in other tabs / inputs and only
        # fires when the user's focus is somewhere in the Stage tab.
        self.fit_view_btn.clicked.connect(self.stage_view.fit_to_stage)
        self._fit_shortcut = QShortcut(QKeySequence("F"), self)
        self._fit_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._fit_shortcut.activated.connect(self.stage_view.fit_to_stage)

    def _on_preview_collapsed(self, collapsed: bool) -> None:
        """Chevron in the 3D preview header: hide/show the GL pane."""
        from gui.icons import line_icon
        self.embedded_visualizer.setVisible(not collapsed)
        self.preview_collapse_btn.setIcon(line_icon(
            "chevron-left" if collapsed else "chevron-right",
            self._tokens["text_secondary"]))
        self.preview_collapse_btn.setToolTip(
            "Expand the 3D preview" if collapsed
            else "Collapse the 3D preview")

    def _add_stage_element(self, kind: str):
        """Palette click: place a static element at stage center."""
        self.stage_view.add_stage_element(kind)
        self._refresh_layer_list()

    # ── Config sync ───────────────────────────────────────────────────

    def update_from_config(self):
        """Refresh stage view from configuration"""
        if self.stage_view:
            self.stage_view.set_config(self.config)

        # Load stage dimensions and grid size from config
        if self.config:
            self.stage_width.blockSignals(True)
            self.stage_height.blockSignals(True)
            self.grid_size.blockSignals(True)

            self.stage_width.setValue(int(self.config.stage_width))
            self.stage_height.setValue(int(self.config.stage_height))
            if hasattr(self.config, 'grid_size'):
                self.grid_size.setValue(self.config.grid_size)

            self.stage_width.blockSignals(False)
            self.stage_height.blockSignals(False)
            self.grid_size.blockSignals(False)

            # The StageView keeps its own stage_width_m / stage_depth_m /
            # grid_size_m attributes (defaulted in __init__). set_config
            # above doesn't refresh them, and blockSignals(True) on the
            # spinboxes suppresses the valueChanged → _update_stage path
            # we'd otherwise rely on. Without the explicit calls below
            # the 2D plot stays at the default 10 × 6 m / 0.5 m grid no
            # matter what the loaded YAML says.
            if self.stage_view:
                self.stage_view.updateStage(
                    width_m=float(self.config.stage_width),
                    depth_m=float(self.config.stage_height),
                )
                if hasattr(self.config, 'grid_size'):
                    self.stage_view.updateGrid(size_m=float(self.config.grid_size))
                # meters_to_pixels reads stage_width_m / stage_depth_m, so
                # the items placed by set_config above were mapped with the
                # PREVIOUS stage size. Re-place them now that the view knows
                # the real dimensions - otherwise a 12 m stage draws (and,
                # on the next save, stores) its fixtures at 10 m spacing.
                self.stage_view.update_from_config()

            self._refresh_layer_list()
            self._refresh_group_rows()

        self._refresh_plan_overlays()
        self._refresh_embedded_visualizer()

    def save_to_config(self):
        """Save fixture positions and spots back to configuration"""
        if self.stage_view:
            self.stage_view.save_positions_to_config()

    def _update_stage(self):
        """Update stage dimensions from spin box values"""
        width = self.stage_width.value()
        height = self.stage_height.value()

        # Update StageView
        self.stage_view.updateStage(width, height)
        self.stage_view.update_from_config()

        # Update Configuration for TCP sync
        if self.config:
            self.config.stage_width = float(width)
            self.config.stage_height = float(height)

            # Notify TCP server if running (for live visualizer updates)
            self._notify_tcp_update()

        self._refresh_plan_overlays()

        # Push the new dimensions to every embedded 3D preview (Stage's
        # own + Shows + Live). Without this the Shows/Live previews
        # stay stuck on the old stage size until the user manually
        # activates them; even the Stage tab's own preview wouldn't
        # repaint without an explicit refresh because updateStage on
        # its own doesn't emit fixtures_changed.
        self._broadcast_visualizer_refresh()

    def _update_grid_size(self, value: float):
        """Update grid size from spin box value"""
        # Update StageView
        self.stage_view.updateGrid(size_m=value)

        # Update Configuration for TCP sync
        if self.config:
            self.config.grid_size = value

            # Notify TCP server if running (for live visualizer updates)
            self._notify_tcp_update()

        self._refresh_plan_overlays()

    def _launch_visualizer(self):
        """Launch the 3D Visualizer application."""
        # Check if visualizer is already running
        if self.visualizer_process is not None:
            poll_result = self.visualizer_process.poll()
            if poll_result is None:
                # Process is still running
                QtWidgets.QMessageBox.information(
                    self,
                    "Visualizer Running",
                    "The Visualizer is already running."
                )
                return

        # Check if TCP server is running, offer to start it if not
        if not self._ensure_tcp_server_running():
            return

        # Get path to visualizer main.py
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        visualizer_path = os.path.join(project_root, "visualizer", "main.py")

        if not os.path.exists(visualizer_path):
            QtWidgets.QMessageBox.warning(
                self,
                "Visualizer Not Found",
                f"Could not find visualizer at:\n{visualizer_path}"
            )
            return

        try:
            # Launch visualizer as subprocess
            self.visualizer_process = subprocess.Popen(
                [sys.executable, visualizer_path],
                cwd=project_root
            )
            print(f"Visualizer launched (PID: {self.visualizer_process.pid})")
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Launch Error",
                f"Failed to launch Visualizer:\n{str(e)}"
            )

    def _ensure_tcp_server_running(self) -> bool:
        """
        Ensure TCP server is running before launching visualizer.

        Returns:
            True if server is running (or was started), False if user cancelled
        """
        try:
            main_window = self.window()
            if not main_window:
                return True  # Can't check, proceed anyway

            shows_tab = getattr(main_window, 'shows_tab', None)
            if not shows_tab:
                return True  # Can't check, proceed anyway

            tcp_server = getattr(shows_tab, 'tcp_server', None)

            # Check if server is running
            if tcp_server and tcp_server.is_running():
                return True  # Already running

            # Server not running - ask user if they want to start it
            reply = QtWidgets.QMessageBox.question(
                self,
                "Start TCP Server?",
                "The TCP server is not running.\n\n"
                "The Visualizer needs the TCP server to receive stage configuration.\n\n"
                "Start the TCP server now?",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.Yes
            )

            if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                # Start the TCP server via ShowsTab
                try:
                    # Use _on_tcp_toggle which handles all the init logic
                    if hasattr(shows_tab, '_on_tcp_toggle'):
                        shows_tab._on_tcp_toggle(True)

                        # Update the checkbox in ShowsTab if it exists
                        tcp_checkbox = getattr(shows_tab, 'tcp_checkbox', None)
                        if tcp_checkbox:
                            tcp_checkbox.blockSignals(True)
                            tcp_checkbox.setChecked(True)
                            tcp_checkbox.blockSignals(False)
                    else:
                        QtWidgets.QMessageBox.warning(
                            self,
                            "Cannot Start Server",
                            "TCP server initialization not available.\n"
                            "Please enable 'Visualizer Server' in the Shows tab."
                        )
                        return False

                    # Verify it started
                    tcp_server = getattr(shows_tab, 'tcp_server', None)
                    if tcp_server and tcp_server.is_running():
                        print("TCP server started successfully")
                        self._update_tcp_status()
                        return True
                    else:
                        QtWidgets.QMessageBox.warning(
                            self,
                            "Server Start Failed",
                            "Failed to start TCP server.\n"
                            "Please check the Shows tab for errors."
                        )
                        return False

                except Exception as e:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Server Start Failed",
                        f"Failed to start TCP server:\n{str(e)}"
                    )
                    return False
            else:
                # User chose not to start server
                return False

        except Exception as e:
            print(f"Error checking TCP server: {e}")
            return True  # Proceed anyway on error

    def _update_tcp_status(self):
        """Update TCP server status indicator."""
        # Try to get TCP server from ShowsTab via parent (MainWindow)
        tcp_server = None
        try:
            # Navigate up to MainWindow via Qt parent hierarchy
            main_window = self.window()
            if main_window:
                shows_tab = getattr(main_window, 'shows_tab', None)
                if shows_tab:
                    tcp_server = getattr(shows_tab, 'tcp_server', None)
        except Exception:
            pass

        if tcp_server is None:
            self.tcp_status_label.setText("Not initialized")
            self.tcp_status_label.setStyleSheet("color: #666; font-weight: bold;")
        elif not tcp_server.is_running():
            self.tcp_status_label.setText("Stopped")
            self.tcp_status_label.setStyleSheet("color: #f44336; font-weight: bold;")
        else:
            client_count = tcp_server.get_client_count()
            if client_count == 0:
                self.tcp_status_label.setText("Running (no clients)")
                self.tcp_status_label.setStyleSheet("color: #2196F3; font-weight: bold;")
            else:
                self.tcp_status_label.setText(f"Connected ({client_count})")
                self.tcp_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")

    def on_tab_activated(self):
        """Called when stage tab becomes visible."""
        self._tab_active = True
        # Send current state to visualizer when tab becomes active
        self._notify_tcp_update()
        # Embedded preview defaults to build mode (full-on lighting) on the
        # Stage tab — playback lives in the Shows tab.
        if hasattr(self, "embedded_visualizer") and self.embedded_visualizer is not None:
            self.embedded_visualizer.set_preview_mode("build")
            self._refresh_embedded_visualizer()

    def on_tab_deactivated(self):
        """Called when switching away from stage tab."""
        self._tab_active = False
        # Stop any pending updates
        self._tcp_update_timer.stop()
        self._tcp_update_pending = False
        self._save_splitter_state()

    def _save_splitter_state(self) -> None:
        """Persist the preview/inspector splitter sizes via QSettings so
        the Stage tab opens with the same proportions next session."""
        if not hasattr(self, "_right_splitter"):
            return
        settings = app_settings()
        settings.setValue("stage/right_splitter", self._right_splitter.saveState())

    def _notify_tcp_update(self):
        """Notify TCP server about configuration changes (throttled for live updates)."""
        # Only send updates when tab is active (reduces lag when working on other tabs)
        if not getattr(self, "_tab_active", False):
            return

        # Use throttle timer to avoid flooding during drag operations
        self._tcp_update_pending = True
        if not self._tcp_update_timer.isActive():
            self._tcp_update_timer.start()

    def _do_tcp_update(self):
        """Actually send the TCP update (called by throttle timer)."""
        if not self._tcp_update_pending:
            return
        self._tcp_update_pending = False

        try:
            # Get shows_tab which hosts the TCP server
            main_window = self.parent()
            while main_window and not hasattr(main_window, 'shows_tab'):
                main_window = main_window.parent()

            if main_window and hasattr(main_window, 'shows_tab'):
                shows_tab = main_window.shows_tab
                tcp_server = getattr(shows_tab, 'tcp_server', None)

                if tcp_server and tcp_server.is_running() and self.config:
                    # Update the server's config and push to clients
                    tcp_server.update_config(self.config)
        except Exception as e:
            print(f"Error notifying TCP server: {e}")

    # ── Stage plot export ─────────────────────────────────────────────

    def _export_stage_plot(self):
        """EXPORT RIDER PDF / PLOT STAGE: export the rig as a PDF or PNG.

        Small options dialog (paper size + PNG resolution), then a save
        dialog whose extension picks the format.
        """
        from gui.stage_plot import PAPER_PRESETS, StagePlotRenderer

        if not self.config.fixtures:
            QtWidgets.QMessageBox.warning(
                self, "No Fixtures",
                "Add fixtures before exporting a stage plot."
            )
            return

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Export Stage Plot")
        layout = QtWidgets.QFormLayout(dialog)

        paper_combo = QtWidgets.QComboBox()
        paper_combo.addItems(list(PAPER_PRESETS.keys()))
        layout.addRow("Paper size (landscape):", paper_combo)

        dpi_combo = QtWidgets.QComboBox()
        dpi_combo.addItems(["150", "300"])
        dpi_combo.setCurrentText("300")
        dpi_combo.setToolTip("Only used for PNG output; PDF is vector.")
        layout.addRow("PNG resolution (dpi):", dpi_combo)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        renderer = StagePlotRenderer(self.config)
        loaded_from = getattr(self.config, '_loaded_from', None)
        default_dir = os.path.dirname(loaded_from) if loaded_from else ""
        default_name = f"{renderer.title}_stage_plot.pdf"
        default_path = os.path.join(default_dir, default_name) if default_dir else default_name

        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Stage Plot", default_path,
            "PDF (*.pdf);;PNG (*.png)"
        )
        if not file_path:
            return
        if not os.path.splitext(file_path)[1]:
            file_path += ".pdf"

        try:
            fmt = renderer.render(
                file_path,
                paper=paper_combo.currentText(),
                dpi=int(dpi_combo.currentText()),
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Export Failed",
                f"Could not export the stage plot:\n{e}"
            )
            return

        QtWidgets.QMessageBox.information(
            self, "Exported",
            f"Stage plot exported as {fmt.upper()}:\n{file_path}"
        )

    # ── Stage planes ──────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        """Revert the plane highlight to the persistent selection when
        the mouse leaves the plane list (ends a hover preview), and keep
        the plan's overlay chrome pinned to the view's corners."""
        if (hasattr(self, "plane_list") and obj is self.plane_list.viewport()
                and event.type() == QEvent.Type.Leave):
            self._apply_plane_highlight(self._selected_plane)
        if (hasattr(self, "stage_view") and obj is self.stage_view
                and event.type() in (QEvent.Type.Resize, QEvent.Type.Show)):
            self._position_plan_overlays()
        return super().eventFilter(obj, event)

    def _rig_height(self) -> float:
        """Ceiling height of the stage cuboid: the tallest fixture's
        effective Z, floored at 3 m — the same rule autogen's
        compute_stage_planes uses, so the highlighted ceiling matches
        where Auto Mode aims."""
        max_z = 3.0
        for fixture in self.config.fixtures:
            group = self.config.groups.get(fixture.group) if fixture.group else None
            z = fixture.get_effective_z(group)
            if z > max_z:
                max_z = z
        return max_z

    def _apply_plane_highlight(self, name):
        if hasattr(self, "embedded_visualizer") and self.embedded_visualizer is not None:
            self.embedded_visualizer.set_highlighted_plane(name, self._rig_height())

    def _on_plane_hovered(self, item):
        self._apply_plane_highlight(item.data(Qt.ItemDataRole.UserRole))

    def _on_plane_clicked(self, item):
        name = item.data(Qt.ItemDataRole.UserRole)
        if self._selected_plane == name:
            self._selected_plane = None
            self.plane_list.clearSelection()
        else:
            self._selected_plane = name
        self._apply_plane_highlight(self._selected_plane)

    # ── Library: fixture group rows ───────────────────────────────────

    def _fixtures_of_group(self, name):
        return [f for f in self.config.fixtures if f.group == name]

    def _refresh_group_rows(self):
        """Rebuild the RIG · FIXTURES rows from config.groups."""
        if not hasattr(self, "_group_rows_layout"):
            return
        while self._group_rows_layout.count():
            entry = self._group_rows_layout.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.deleteLater()

        names = list(self.config.groups.keys()) if self.config else []
        self.groups_empty_hint.setVisible(not names)
        for name in names:
            self._group_rows_layout.addWidget(self._make_group_row(name))

    def _make_group_row(self, name: str) -> QtWidgets.QWidget:
        from PyQt6.QtGui import QFont
        from gui.fonts import FONT_UI
        from gui.tabs.fixtures_tab import _GroupRow
        from gui.typography import MicroLabel

        group = self.config.groups.get(name)
        color = getattr(group, "color", "") or self._tokens["text_secondary"]
        fixtures = self._fixtures_of_group(name)

        row = _GroupRow(name)
        # Only the DATA color is widget-local; the hairline comes from
        # the theme's #GroupRow rule.
        row.setStyleSheet(f"#GroupRow {{ border-left: 3px solid {color}; }}")
        row.setToolTip(f"Select the fixtures of '{name}' on the plan")

        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(13, 8, 16, 8)
        layout.setSpacing(8)

        name_label = QtWidgets.QLabel(name.upper())
        name_font = QFont(FONT_UI, 10)
        name_font.setWeight(QFont.Weight.DemiBold)
        name_label.setFont(name_font)
        name_label.setMinimumWidth(1)  # never widen the 260px library
        layout.addWidget(name_label, 1)
        readout = MicroLabel(group_row_readout(fixtures), point_size=8,
                             tracking_em=0.08)
        readout.setMinimumWidth(1)
        layout.addWidget(readout)

        row.clicked.connect(self._on_group_row_clicked)
        return row

    def _on_group_row_clicked(self, name: str):
        """Select that group's fixtures on the 2D plan."""
        self.stage_view.select_group_fixtures(name)

    # ── Stage layers ──────────────────────────────────────────────────

    def _refresh_layer_list(self):
        """Rebuild the layer list widget, the chip row, the inspector's
        LAYERS section and the layer combo from config.stage_layers."""
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        for layer in self.config.stage_layers:
            item = QtWidgets.QListWidgetItem(f"{layer.name} ({layer.z_height:g} m)")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked
            )
            item.setData(Qt.ItemDataRole.UserRole, layer.name)
            self.layer_list.addItem(item)
        self.layer_list.blockSignals(False)
        self._refresh_layer_chips()
        self._refresh_layer_rows()
        self._refresh_layer_combo_items()
        self._update_active_layer_ui()

    def _refresh_layer_rows(self):
        """The inspector's LAYERS section: one mono row per layer."""
        from gui.typography import mono_font

        if not hasattr(self, "_layer_rows_layout"):
            return
        tokens = self._tokens
        while self._layer_rows_layout.count():
            entry = self._layer_rows_layout.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.deleteLater()

        for layer in self.config.stage_layers:
            row = QtWidgets.QWidget()
            row.setObjectName("GroupRow")  # theme hairline
            row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            row_layout = QtWidgets.QHBoxLayout(row)
            row_layout.setContentsMargins(0, 6, 0, 6)
            name_label = QtWidgets.QLabel(layer.name)
            name_label.setFont(mono_font(9))
            name_label.setStyleSheet(f"color: {tokens['text_secondary']};")
            row_layout.addWidget(name_label, 1)
            height_label = QtWidgets.QLabel(f"H {layer.z_height:g} m")
            height_label.setFont(mono_font(9))
            height_label.setStyleSheet(f"color: {tokens['text']};")
            row_layout.addWidget(height_label)
            self._layer_rows_layout.addWidget(row)

    # ── Layer chip row ────────────────────────────────────────────────

    @staticmethod
    def _chip_text(layer) -> str:
        """Mono-caps chip label per the reference: 'NAME · <z>M'."""
        return f"{layer.name} · {layer.z_height:g}M".upper()

    def _refresh_layer_chips(self):
        """Rebuild the per-layer chips between ALL and + LAYER."""
        for chip in self.layer_chips.values():
            self._layer_chip_group.removeButton(chip)
            self._chip_host.removeWidget(chip)
            chip.deleteLater()
        self.layer_chips = {}
        if not self.config:
            return
        for layer in self.config.stage_layers:
            chip = QtWidgets.QPushButton(self._chip_text(layer))
            chip.setCheckable(True)
            self._style_segment(chip)
            chip.setToolTip(
                f"Edit only '{layer.name}' (others ghost to a locked "
                "reference).\nRight-click for visibility / edit / remove."
            )
            chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            chip.clicked.connect(
                lambda _=False, n=layer.name: self._set_active_layer(n))
            chip.customContextMenuRequested.connect(
                lambda pos, n=layer.name, c=chip:
                self._show_layer_chip_menu(c, n, pos))
            self._layer_chip_group.addButton(chip)
            self._chip_host.addWidget(chip)
            self.layer_chips[layer.name] = chip

    def _show_layer_chip_menu(self, chip, name, pos):
        """Right-click menu on a layer chip: visibility / edit / remove."""
        layer = self.config.get_stage_layer(name)
        if layer is None:
            return
        menu = QtWidgets.QMenu(self)
        vis_action = menu.addAction(
            "Hide layer" if layer.visible else "Show layer")
        edit_action = menu.addAction("Edit...")
        remove_action = menu.addAction("Remove")
        action = menu.exec(chip.mapToGlobal(pos))
        if action is vis_action:
            self._set_layer_visible(name, not layer.visible)
        elif action is edit_action:
            self._select_layer_row(name)
            self._edit_layer()
        elif action is remove_action:
            self._select_layer_row(name)
            self._remove_layer()

    def _define_layer(self):
        """DEFINE... segment: edit the active layer (or the first one)."""
        if not self.config.stage_layers:
            return
        name = (self.stage_view.active_layer
                or self.config.stage_layers[0].name)
        self._select_layer_row(name)
        self._edit_layer()

    def _select_layer_row(self, name):
        """Point the panel list's current row at the named layer (the
        edit/remove flows operate on the current row)."""
        for i in range(self.layer_list.count()):
            if self.layer_list.item(i).data(Qt.ItemDataRole.UserRole) == name:
                self.layer_list.setCurrentRow(i)
                return

    def _set_layer_visible(self, name, visible):
        """Flip a layer's visibility through the panel checkbox so the
        chip menu and the list share one code path
        (_on_layer_item_changed)."""
        for i in range(self.layer_list.count()):
            item = self.layer_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == name:
                item.setCheckState(
                    Qt.CheckState.Checked if visible
                    else Qt.CheckState.Unchecked)
                return

    # ── Active-layer editing ──────────────────────────────────────────

    def _set_active_layer(self, name):
        """Enter/leave active-layer editing (None = edit all layers).

        Activating a hidden layer force-shows it — editing an invisible
        layer would mean dragging fixtures you can't see.
        """
        if name:
            layer = self.config.get_stage_layer(name)
            if layer is None:
                name = None
            elif not layer.visible:
                layer.visible = True
                self._refresh_layer_list()
                self._notify_tcp_update()
                self._broadcast_visualizer_refresh()
        self.stage_view.set_active_layer(name)
        self._update_active_layer_ui()

    def _on_layer_double_clicked(self, item):
        name = item.data(Qt.ItemDataRole.UserRole)
        if self.stage_view.active_layer == name:
            self._set_active_layer(None)
        else:
            self._set_active_layer(name)

    def _cycle_active_layer(self):
        """L shortcut: all layers -> first layer -> ... -> all layers."""
        order = [None] + [layer.name for layer in self.config.stage_layers]
        if len(order) == 1:
            return
        current = self.stage_view.active_layer
        idx = order.index(current) if current in order else 0
        self._set_active_layer(order[(idx + 1) % len(order)])

    def _update_active_layer_ui(self):
        """Sync the chip row, bold the active layer's row, update the
        status label, the lock hint and the plan overlays."""
        active = self.stage_view.active_layer if hasattr(self, "stage_view") else None
        self.active_layer_label.setText(
            f"Editing: {active} only" if active else "Editing: all layers"
        )
        # setFont emits itemChanged; these are not check-state edits.
        self.layer_list.blockSignals(True)
        for i in range(self.layer_list.count()):
            item = self.layer_list.item(i)
            font = item.font()
            font.setBold(item.data(Qt.ItemDataRole.UserRole) == active)
            item.setFont(font)
        self.layer_list.blockSignals(False)

        # Chips: checked = accent fill (exclusive group unchecks the
        # rest). Programmatic setChecked doesn't emit clicked, so no
        # feedback loop into _set_active_layer.
        target = self.layer_chips.get(active) if active else self.all_layers_chip
        if target is not None:
            target.setChecked(True)
        self.layer_lock_hint.setVisible(active is not None)
        self.define_layer_chip.setEnabled(bool(self.config.stage_layers))
        self._refresh_plan_overlays()

    def _on_layer_item_changed(self, item):
        """Checkbox toggle — flip the layer's visible flag everywhere."""
        layer = self.config.get_stage_layer(item.data(Qt.ItemDataRole.UserRole))
        if layer is None:
            return
        layer.visible = item.checkState() == Qt.CheckState.Checked
        if not layer.visible and self.stage_view.active_layer == layer.name:
            # Hiding the layer being edited ends the editing session —
            # you can't place fixtures you can't see.
            self.stage_view.set_active_layer(None)
            self._update_active_layer_ui()
        self.stage_view.apply_layer_visibility()
        self._notify_tcp_update()
        self._broadcast_visualizer_refresh()

    def _layer_dialog(self, title, name="", z_height=3.0):
        """Small name + height dialog. Returns (name, z_height) or None."""
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(title)
        layout = QtWidgets.QFormLayout(dialog)

        name_edit = QtWidgets.QLineEdit(name)
        name_edit.setPlaceholderText("e.g. Top truss")
        layout.addRow("Name:", name_edit)

        z_spin = QtWidgets.QDoubleSpinBox()
        z_spin.setRange(0.0, 100.0)
        z_spin.setSingleStep(0.5)
        z_spin.setValue(z_height)
        layout.addRow("Height (m):", z_spin)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return None
        new_name = name_edit.text().strip()
        if not new_name:
            return None
        return new_name, z_spin.value()

    def _add_layer(self):
        from config.models import StageLayer
        result = self._layer_dialog("Add Stage Layer")
        if result is None:
            return
        name, z_height = result
        if self.config.get_stage_layer(name) is not None:
            QtWidgets.QMessageBox.warning(
                self, "Layer Exists", f"A layer named '{name}' already exists."
            )
            return
        self.config.stage_layers.append(StageLayer(name=name, z_height=z_height))
        self._refresh_layer_list()

    def _selected_layer(self):
        item = self.layer_list.currentItem()
        if item is None:
            return None
        return self.config.get_stage_layer(item.data(Qt.ItemDataRole.UserRole))

    def _edit_layer(self):
        """Rename a layer and/or move it to another height.

        Moving the layer moves everything on it: all assigned fixtures
        get the new height (the truss goes up, the lamps go with it).
        """
        layer = self._selected_layer()
        if layer is None:
            return
        result = self._layer_dialog("Edit Stage Layer", layer.name, layer.z_height)
        if result is None:
            return
        new_name, new_z = result
        if new_name != layer.name and self.config.get_stage_layer(new_name) is not None:
            QtWidgets.QMessageBox.warning(
                self, "Layer Exists", f"A layer named '{new_name}' already exists."
            )
            return

        old_name = layer.name
        z_changed = new_z != layer.z_height
        layer.name = new_name
        layer.z_height = new_z
        for fixture in self.config.fixtures:
            if fixture.layer == old_name:
                fixture.layer = new_name
                if z_changed:
                    fixture.z = new_z
                    fixture.z_uses_group_default = False
        if self.stage_view.active_layer == old_name:
            self.stage_view.active_layer = new_name

        self._refresh_layer_list()
        self._refresh_group_rows()
        self.stage_view.update_from_config()
        self._notify_tcp_update()
        self._broadcast_visualizer_refresh()

    def _remove_layer(self):
        """Delete a layer. Fixtures on it lose the assignment but keep
        their current height."""
        layer = self._selected_layer()
        if layer is None:
            return
        assigned = sum(1 for f in self.config.fixtures if f.layer == layer.name)
        if assigned:
            reply = QtWidgets.QMessageBox.question(
                self, "Remove Layer?",
                f"'{layer.name}' has {assigned} fixture(s) assigned.\n\n"
                "Remove the layer? The fixtures keep their height but lose "
                "the layer assignment.",
                QtWidgets.QMessageBox.StandardButton.Yes |
                QtWidgets.QMessageBox.StandardButton.No
            )
            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        for fixture in self.config.fixtures:
            if fixture.layer == layer.name:
                fixture.layer = ""
        self.config.stage_layers.remove(layer)
        if self.stage_view.active_layer == layer.name:
            self.stage_view.set_active_layer(None)
        self._refresh_layer_list()
        self._refresh_group_rows()
        self.stage_view.update_from_config()
        self._notify_tcp_update()
        self._broadcast_visualizer_refresh()

    def _on_show_axes_changed(self, state):
        """Handle show orientation axes checkbox change.

        Toggling a class-level attribute doesn't dirty any individual
        QGraphicsItem, so ``viewport().update()`` alone wasn't
        reliably getting the items to re-paint in the live app — each
        item keeps its own bounding-rect-based dirty tracking and
        treats itself as "still clean" when nothing about *itself*
        changed. Calling ``item.update()`` on every fixture is the
        canonical way to force a per-item repaint; ``scene.update()``
        adds the viewport-level invalidation as defence in depth.
        """
        FixtureItem.show_orientation_axes = bool(state)
        scene = self.stage_view.scene
        for item in scene.items():
            item.update()
        scene.update()

    def _on_set_orientation_requested(self, fixture_items: list):
        """Handle right-click "Set Orientation" — re-bind the inline panel.

        Replaces the legacy modal flow. The persistent OrientationPanel in
        the right-side splitter rebinds to the selected fixtures and live-
        edits write through via :meth:`_on_inline_orientation_changed`.
        """
        if not fixture_items:
            return
        self._inline_orientation_fixtures = list(fixture_items)
        self.orientation_panel.set_fixtures(self._inline_orientation_fixtures)

    def _on_stage_selection_changed(self):
        """Re-bind the inline orientation panel to whatever fixtures are
        currently selected on the 2D StageView. Empty selection → panel
        shows "No fixture selected" and disables its inputs.
        """
        selected = [
            item for item in self.stage_view.scene.selectedItems()
            if isinstance(item, FixtureItem)
        ]
        self._inline_orientation_fixtures = selected
        self.orientation_panel.set_fixtures(selected)
        self._update_selection_inspector(selected)

    # ── Selection inspector (layer field) ─────────────────────────────

    def _refresh_layer_combo_items(self):
        """Rebuild the inspector's layer combo from config.stage_layers.
        Item data carries the layer name ('' = no layer)."""
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        self.layer_combo.addItem("No layer", "")
        if self.config:
            for layer in self.config.stage_layers:
                self.layer_combo.addItem(
                    f"{layer.name} · {layer.z_height:g} m", layer.name)
        self.layer_combo.blockSignals(False)
        self._sync_layer_combo_to_selection()

    def _selected_fixture_items(self):
        if not hasattr(self, "stage_view"):
            return []
        return [
            item for item in self.stage_view.scene.selectedItems()
            if isinstance(item, FixtureItem)
        ]

    def _update_selection_inspector(self, selected):
        """Selection name, group color, X/Y/Z stat tiles, combo enable."""
        if not selected:
            self.selection_label.setText("No fixture selected")
        elif len(selected) == 1:
            self.selection_label.setText(selected[0].fixture_name)
        else:
            self.selection_label.setText(f"{len(selected)} fixtures")

        group_names = {getattr(item, "group", "") or "" for item in selected}
        if len(group_names) == 1 and next(iter(group_names)):
            name = next(iter(group_names))
            group = self.config.groups.get(name) if self.config else None
            color = (getattr(group, "color", "")
                     or self._tokens["text_secondary"])
            self.selection_group_label.setText(name)
            self.selection_group_label.setStyleSheet(f"color: {color};")
        else:
            self.selection_group_label.setText("")
            self.selection_group_label.setStyleSheet("")

        if len(selected) == 1:
            item = selected[0]
            x_m, y_m = self.stage_view.pixels_to_meters(
                item.pos().x(), item.pos().y())
            self.stat_x.setText(f"{x_m:.2f}")
            self.stat_y.setText(f"{y_m:.2f}")
            self.stat_z.setText(f"{item.z_height:.2f}")
        else:
            for label in (self.stat_x, self.stat_y, self.stat_z):
                label.setText("-")

        self.layer_combo.setEnabled(
            bool(selected) and self.layer_combo.count() > 1)
        self._sync_layer_combo_to_selection()

    def _sync_layer_combo_to_selection(self):
        """Point the combo at the selection's layer; mixed selection or
        no selection shows no entry."""
        selected = self._selected_fixture_items()
        layers = {getattr(item, "layer", "") for item in selected}
        self.layer_combo.blockSignals(True)
        if len(layers) == 1:
            index = self.layer_combo.findData(layers.pop())
            self.layer_combo.setCurrentIndex(index if index >= 0 else 0)
        else:
            self.layer_combo.setCurrentIndex(-1)
        self.layer_combo.blockSignals(False)

    def _on_layer_combo_activated(self, index):
        """User picked a layer in the inspector - assign the selection
        through the same StageView path as the right-click menu (snaps
        Z to the layer plane, saves, re-applies visibility/ghosting)."""
        name = self.layer_combo.itemData(index) or ""
        self.stage_view.assign_selected_to_layer(name)
        # Z changed with the assignment: re-load the orientation panel
        # so its Z-Height spin shows the layer plane.
        selected = self._selected_fixture_items()
        self._inline_orientation_fixtures = selected
        self.orientation_panel.set_fixtures(selected)
        self._sync_layer_combo_to_selection()
        self._update_selection_inspector(selected)
        self._refresh_group_rows()

    def _on_inline_orientation_changed(self):
        """Slot fired by OrientationPanel.values_changed — push edits live
        to the currently-bound fixtures, the config, and any group default."""
        fixture_items = getattr(self, "_inline_orientation_fixtures", None)
        if not fixture_items:
            return
        values = self.orientation_panel.get_orientation_values()
        self._apply_orientation_to_fixtures(fixture_items, values)

    def _open_orientation_dialog(self):
        """Modal-dialog fallback. No longer wired to the right-click flow,
        but kept for any future multi-edit-confirm path that wants Apply/
        Cancel semantics."""
        fixture_items = getattr(self, '_pending_orientation_fixtures', None)
        if not fixture_items:
            return

        self._pending_orientation_fixtures = None

        dialog = OrientationDialog(fixture_items, self.config, self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self._apply_orientation_to_fixtures(fixture_items, dialog.get_orientation_values())

    def _apply_orientation_to_fixtures(self, fixture_items: list, values: dict) -> None:
        """Write a values dict (mounting, yaw, pitch, roll, z_height,
        apply_to_group) back to the fixture items, the config, and group
        defaults if requested. Shared by the inline panel and the modal."""
        for fixture_item in fixture_items:
            fixture_item.mounting = values['mounting']
            fixture_item.rotation_angle = values['yaw']  # yaw maps to rotation_angle
            fixture_item.pitch = values['pitch']
            fixture_item.roll = values['roll']
            fixture_item.z_height = values['z_height']
            fixture_item.orientation_uses_group_default = False
            fixture_item.z_uses_group_default = False
            fixture_item.update()

            if self.config:
                config_fixture = next(
                    (f for f in self.config.fixtures if f.name == fixture_item.fixture_name),
                    None
                )
                if config_fixture:
                    config_fixture.mounting = values['mounting']
                    config_fixture.yaw = values['yaw']
                    config_fixture.pitch = values['pitch']
                    config_fixture.roll = values['roll']
                    config_fixture.z = values['z_height']
                    config_fixture.orientation_uses_group_default = False
                    config_fixture.z_uses_group_default = False

        if values.get('apply_to_group') and self.config:
            groups = set(f.group for f in fixture_items if hasattr(f, 'group') and f.group)
            selected_fixture_names = {f.fixture_name for f in fixture_items}

            for group_name in groups:
                if group_name in self.config.groups:
                    group = self.config.groups[group_name]
                    group.default_mounting = values['mounting']
                    group.default_yaw = values['yaw']
                    group.default_pitch = values['pitch']
                    group.default_roll = values['roll']
                    group.default_z_height = values['z_height']

                    for config_fixture in self.config.fixtures:
                        if (config_fixture.group == group_name and
                                config_fixture.name not in selected_fixture_names):
                            if config_fixture.orientation_uses_group_default:
                                config_fixture.mounting = values['mounting']
                                config_fixture.yaw = values['yaw']
                                config_fixture.pitch = values['pitch']
                                config_fixture.roll = values['roll']
                            if config_fixture.z_uses_group_default:
                                config_fixture.z = values['z_height']

                            if config_fixture.name in self.stage_view.fixtures:
                                stage_item = self.stage_view.fixtures[config_fixture.name]
                                if config_fixture.orientation_uses_group_default:
                                    stage_item.mounting = values['mounting']
                                    stage_item.rotation_angle = values['yaw']
                                    stage_item.pitch = values['pitch']
                                    stage_item.roll = values['roll']
                                if config_fixture.z_uses_group_default:
                                    stage_item.z_height = values['z_height']
                                stage_item.update()

        self.stage_view.save_positions_to_config()
        self._update_selection_inspector(self._selected_fixture_items())
        self._notify_tcp_update()
        self._broadcast_visualizer_refresh()

    def _refresh_embedded_visualizer(self) -> None:
        """Push the latest config to the embedded 3D preview. Cheap to call
        repeatedly — RenderEngine batches GL state internally."""
        if hasattr(self, "embedded_visualizer") and self.embedded_visualizer is not None:
            self.embedded_visualizer.set_config(self.config)

    def _broadcast_visualizer_refresh(self) -> None:
        """Ask MainWindow to refresh every embedded visualizer (Stage,
        Shows, Live). Used after stage edits / fixture moves so all
        three 3D previews stay in sync — without it, only Stage tab's
        preview tracks edits made on the 2D Stage view, and the Shows /
        Live previews go stale until the user manually activates them.

        Falls back to a local-only refresh if MainWindow doesn't expose
        the central method (e.g. tab being driven from a test harness).
        """
        main_window = self.window()
        broadcast = getattr(main_window, "on_visualizer_config_changed", None)
        if callable(broadcast):
            broadcast()
        else:
            self._refresh_embedded_visualizer()
