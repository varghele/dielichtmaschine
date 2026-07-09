"""LiveTab - the touch-palette busking surface, built to the reference
design_handoff_lichtmaschine_app/screens/09-live-3b-palette.html (layout
"3b").

First pass: a UI shell wired to an in-memory :class:`LiveState`. There is
no DMX / ArtNet output yet - every interaction mutates ``LiveState`` and
emits ``LiveState.state_changed`` so a later pass can subscribe an output
engine to it without touching the widgets.

Anatomy (left to right):

- LEFT (a 320px inspector panel): one SELECT tile per fixture group in
  ``config.groups`` (display-caps name, fixture count, a 3px accent bar
  in the group's data color). Clicking toggles the group into the current
  multi-select. A PROGRAMMER readout underneath lists what is selected
  and which palette each selected group is staged to.
- CENTER (the grid surface): a palette grid of cells - STATIC / STROBE /
  SPARKLE / WATERFALL / CIRCLE / WHITE WASH. Touching a cell stages that
  palette and applies it to the current selection over the current fade
  time; the active cell(s) highlight in the accent. An APPLY TO SELECTION
  action re-applies the staged palette to whatever is selected now.
- RIGHT (a 340px inspector panel): a MASTER level fader (0-100%), a
  STROBE section (rate slider + a STROBE on/off toggle), a FADE TIME
  segmented control feeding the apply fade, a BLACKOUT toggle
  (destructive) that zeroes the master, and a static SONG PALETTE strip.

Honest omissions vs. the reference (things the shell cannot back yet):
the cue stack, the live 3D render / DMX meters, the active-playbacks
list, the bottom playback fader bank and the transport clock are all
output-engine surfaces with no in-memory state to drive them in this
pass, so they are left out rather than faked. The SONG PALETTE strip is
a static labelled row per the brief.
"""

from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QPushButton, QLabel,
)

from config.models import Configuration
from gui.fonts import FONT_MONO
from gui.typography import DisplayLabel, MicroLabel, display_font, mono_font

from .base_tab import BaseTab

# Reference geometry.
LEFT_PANEL_WIDTH = 320
RIGHT_PANEL_WIDTH = 340

# Group fallback palette (mirrors the Auto / Stage screens) for groups
# that carry the default gray or no color.
GROUP_PALETTE = (
    "#D9A441", "#4ECBD4", "#C95FD0", "#6F9E4C",
    "#5F86C9", "#C96A5F", "#9A7FD0", "#8D9299",
)
DEFAULT_GROUP_COLOR = "#808080"

# The starter palette shown in the centre grid: (key, display label). The
# key is the token stored in LiveState; the label is what the cell shows.
PALETTE_CELLS: Tuple[Tuple[str, str], ...] = (
    ("static", "Static"),
    ("strobe", "Strobe"),
    ("sparkle", "Sparkle"),
    ("waterfall", "Waterfall"),
    ("circle", "Circle"),
    ("white_wash", "White Wash"),
)

# Fade-time segmented control: (label, seconds). SNAP is an instant cut.
FADE_OPTIONS: Tuple[Tuple[str, float], ...] = (
    ("SNAP", 0.0),
    ("0.5 s", 0.5),
    ("2 s", 2.0),
    ("4 s", 4.0),
)
DEFAULT_FADE_SECONDS = 2.0

# Static SONG PALETTE strip (placeholder, per the brief - no state yet).
SONG_PALETTES = ("Warm", "Cool", "Red / Cyan", "Mono")


def _active_tokens() -> dict:
    """The token dict of the theme currently applied to the app.

    Sniffs the applied stylesheet (ThemeManager.apply doesn't persist);
    the light theme's window color is unique to light. Falls back to
    dark. Same trick as gui/tabs/stage_tab.py::_active_tokens.
    """
    from gui.theme_tokens import THEMES

    app = QApplication.instance()
    qss = app.styleSheet() if app is not None else ""
    light = THEMES.get("light")
    if light is not None and light["window"] in qss:
        return light
    return THEMES["dark"]


# ---------------------------------------------------------------------------
# In-memory live state (the future output engine subscribes to this)
# ---------------------------------------------------------------------------

class LiveState(QObject):
    """The busking programmer's in-memory state.

    Plain data plus mutators; every mutator emits :attr:`state_changed`
    so the tab (and, later, an ArtNet output engine) can re-sync from a
    single source of truth. Holds no widgets and no output plumbing.
    """

    state_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected: set = set()                 # selected group names
        self.group_palettes: Dict[str, str] = {}   # group name -> palette key
        self.staged_palette: Optional[str] = None  # last touched palette
        self.master: int = 100                     # 0-100
        self.blackout: bool = False
        self._master_before_blackout: int = 100
        self.strobe_on: bool = False
        self.strobe_rate: int = 50                 # 0-100
        self.fade_seconds: float = DEFAULT_FADE_SECONDS

    # -- selection ------------------------------------------------------
    def toggle_group(self, name: str) -> None:
        if name in self.selected:
            self.selected.discard(name)
        else:
            self.selected.add(name)
        self.state_changed.emit()

    def clear_selection(self) -> None:
        self.selected.clear()
        self.state_changed.emit()

    def prune_groups(self, valid_names) -> None:
        """Drop selection / palette entries for groups that no longer
        exist (called when the config's groups change). Silent - the tab
        re-syncs explicitly after a rebuild."""
        valid = set(valid_names)
        self.selected &= valid
        self.group_palettes = {
            g: p for g, p in self.group_palettes.items() if g in valid}

    # -- palettes -------------------------------------------------------
    def stage_palette(self, key: str) -> None:
        """Touch a palette cell: stage it and apply it to the current
        selection over the current fade time (recorded, no real fade yet)."""
        self.staged_palette = key
        for group in self.selected:
            self.group_palettes[group] = key
        self.state_changed.emit()

    def apply_to_selection(self) -> None:
        """Re-apply the staged palette to whatever is selected now."""
        if self.staged_palette is not None:
            for group in self.selected:
                self.group_palettes[group] = self.staged_palette
        self.state_changed.emit()

    def active_palette_keys(self) -> set:
        """Palette keys currently applied to any selected group - the
        cells the grid highlights."""
        return {self.group_palettes[g] for g in self.selected
                if g in self.group_palettes}

    # -- masters --------------------------------------------------------
    def set_master(self, level: int) -> None:
        self.master = max(0, min(100, int(level)))
        # Moving the master off zero implicitly releases a blackout.
        if self.master > 0 and self.blackout:
            self.blackout = False
        self.state_changed.emit()

    def set_blackout(self, on: bool) -> None:
        on = bool(on)
        if on and not self.blackout:
            self._master_before_blackout = self.master
            self.master = 0
        elif not on and self.blackout:
            self.master = self._master_before_blackout
        self.blackout = on
        self.state_changed.emit()

    # -- strobe ---------------------------------------------------------
    def set_strobe_on(self, on: bool) -> None:
        self.strobe_on = bool(on)
        self.state_changed.emit()

    def set_strobe_rate(self, rate: int) -> None:
        self.strobe_rate = max(0, min(100, int(rate)))
        self.state_changed.emit()

    # -- fade -----------------------------------------------------------
    def set_fade_seconds(self, seconds: float) -> None:
        self.fade_seconds = max(0.0, float(seconds))
        self.state_changed.emit()


# ---------------------------------------------------------------------------
# Painted primitives
# ---------------------------------------------------------------------------

class _MasterFader(QWidget):
    """A flat horizontal 0-100 fader: track + accent fill + a text handle.

    ``set_value`` is silent (the tab drives it from LiveState); only user
    drags emit ``value_changed`` so there is no sync feedback loop.
    """

    value_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(18)
        self.setMinimumWidth(80)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self._value = 100

    def value(self) -> int:
        return self._value

    def set_value(self, value: int) -> None:
        self._value = max(0, min(100, int(value)))
        self.update()

    def _set_from_x(self, x: float) -> None:
        value = int(round(max(0.0, min(1.0, x / max(1, self.width()))) * 100))
        if value != self._value:
            self._value = value
            self.update()
            self.value_changed.emit(value)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._set_from_x(event.position().x())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._set_from_x(event.position().x())

    def paintEvent(self, event):
        tokens = _active_tokens()
        painter = QPainter(self)
        track_top = (self.height() - 10) // 2
        painter.fillRect(0, track_top, self.width(), 10,
                         QColor(tokens["border"]))
        filled = int(round(self.width() * self._value / 100.0))
        if filled > 0:
            painter.fillRect(0, track_top, filled, 10, QColor(tokens["accent"]))
        handle_x = min(self.width() - 5, max(0, filled - 2))
        painter.fillRect(handle_x, 0, 5, self.height(), QColor(tokens["text"]))
        painter.end()


class _RateSlider(QWidget):
    """A flat 0-100 slider (strobe rate). Silent set, drag emits."""

    value_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(16)
        self.setMinimumWidth(80)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self._value = 50

    def value(self) -> int:
        return self._value

    def set_value(self, value: int) -> None:
        self._value = max(0, min(100, int(value)))
        self.update()

    def _set_from_x(self, x: float) -> None:
        value = int(round(max(0.0, min(1.0, x / max(1, self.width()))) * 100))
        if value != self._value:
            self._value = value
            self.update()
            self.value_changed.emit(value)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._set_from_x(event.position().x())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._set_from_x(event.position().x())

    def paintEvent(self, event):
        tokens = _active_tokens()
        painter = QPainter(self)
        track_top = (self.height() - 8) // 2
        painter.fillRect(0, track_top, self.width(), 8,
                         QColor(tokens["border"]))
        filled = int(round(self.width() * self._value / 100.0))
        if filled > 0:
            painter.fillRect(0, track_top, filled, 8,
                             QColor(tokens["text_secondary"]))
        handle_x = min(self.width() - 4, max(0, filled - 2))
        painter.fillRect(handle_x, 0, 4, self.height(), QColor(tokens["text"]))
        painter.end()


# ---------------------------------------------------------------------------
# Tiles / cells
# ---------------------------------------------------------------------------

class _SelectTile(QWidget):
    """A group SELECT tile: 3px data-color bar, caps name, fixture count.

    Toggles selection on click (emits ``clicked``); selected state paints
    an accent border + raised fill (widget-local, token-derived colors).
    """

    clicked = pyqtSignal(str)

    def __init__(self, group_name: str, count: int, color: str, parent=None):
        super().__init__(parent)
        self.group_name = group_name
        self._color = color
        self._selected = False
        self.setObjectName("LiveSelectTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 9, 14, 9)
        layout.setSpacing(2)
        self.name_label = DisplayLabel(group_name, point_size=13,
                                       weight=QFont.Weight.Bold,
                                       tracking_em=0.05)
        self.name_label.setMinimumWidth(1)
        layout.addWidget(self.name_label)
        count_text = "1 fixture" if count == 1 else f"{count} fixtures"
        self.count_label = MicroLabel(count_text, point_size=7,
                                      tracking_em=0.1)
        self.count_label.setMinimumWidth(1)
        layout.addWidget(self.count_label)
        self._restyle()

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool) -> None:
        selected = bool(selected)
        if selected != self._selected:
            self._selected = selected
        self._restyle()

    def _restyle(self) -> None:
        tokens = _active_tokens()
        bg = tokens["raised"] if self._selected else tokens["panel"]
        border = tokens["accent"] if self._selected else tokens["border"]
        self.setStyleSheet(
            "#LiveSelectTile {"
            f" background-color: {bg};"
            f" border: 1px solid {border};"
            f" border-left: 3px solid {self._color}; }}")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.group_name)


class _PaletteCell(QWidget):
    """A centre-grid palette cell: caps label, accent when active."""

    clicked = pyqtSignal(str)

    def __init__(self, key: str, label: str, parent=None):
        super().__init__(parent)
        self.palette_key = key
        self._active = False
        self.setObjectName("LivePaletteCell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(120, 88)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.label = DisplayLabel(label, point_size=15,
                                  weight=QFont.Weight.Bold, tracking_em=0.04)
        self.label.setMinimumWidth(1)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label, alignment=Qt.AlignmentFlag.AlignCenter)
        self._restyle()

    def is_active(self) -> bool:
        return self._active

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._restyle()

    def _restyle(self) -> None:
        tokens = _active_tokens()
        if self._active:
            bg = tokens["accent_tint"]
            border = tokens["accent"]
            text = tokens["accent_line"]
        else:
            bg = tokens["raised"]
            border = tokens["border"]
            text = tokens["text"]
        self.setStyleSheet(
            "#LivePaletteCell {"
            f" background-color: {bg};"
            f" border: 1px solid {border}; }}")
        self.label.setStyleSheet(f"color: {text}; background: transparent;")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.palette_key)


# ---------------------------------------------------------------------------
# The tab
# ---------------------------------------------------------------------------

class LiveTab(BaseTab):
    """Live busking palette surface (reference screen 09, layout 3b).

    A UI shell over :class:`LiveState`; no output engine is wired yet.
    """

    def __init__(self, config: Configuration, parent=None):
        # Non-UI state must exist before super().__init__ runs setup_ui().
        self.state = LiveState()
        self._select_tiles: Dict[str, _SelectTile] = {}
        self._palette_cells: Dict[str, _PaletteCell] = {}
        self._fade_buttons: List[Tuple[QPushButton, float]] = []
        self._group_colors: Dict[str, str] = {}
        self._current_groups_fingerprint = None

        super().__init__(config, parent)

        self.state.state_changed.connect(self._sync_from_state)
        self._rebuild_group_tiles()
        self._sync_from_state()

    # -- BaseTab ---------------------------------------------------------

    def setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self._build_left_panel())
        main_layout.addWidget(self._build_center_panel(), 1)
        main_layout.addWidget(self._build_right_panel())

    def update_from_config(self):
        """Refresh the SELECT tiles when the config's groups change."""
        self._rebuild_group_tiles()
        self._sync_from_state()

    # -- LEFT: SELECT tiles + PROGRAMMER ---------------------------------

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("LiveSelectPanel")
        panel.setProperty("role", "inspector")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setFixedWidth(LEFT_PANEL_WIDTH)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(16, 12, 16, 8)
        header_row.addWidget(MicroLabel("Select", point_size=8,
                                        tracking_em=0.12))
        header_row.addStretch()
        self._clear_sel_btn = QPushButton("CLEAR SEL")
        self._clear_sel_btn.setProperty("role", "output-select")
        self._clear_sel_btn.setFont(mono_font(8, QFont.Weight.Medium))
        self._clear_sel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_sel_btn.setToolTip("Clear the current group selection")
        self._clear_sel_btn.clicked.connect(self.state.clear_selection)
        header_row.addWidget(self._clear_sel_btn)
        layout.addWidget(header)

        tiles_scroll = QScrollArea()
        tiles_scroll.setWidgetResizable(True)
        tiles_scroll.setFrameShape(QFrame.Shape.NoFrame)
        tiles_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tiles_container = QWidget()
        self._tiles_layout = QVBoxLayout(self._tiles_container)
        self._tiles_layout.setContentsMargins(12, 4, 12, 8)
        self._tiles_layout.setSpacing(6)
        self._tiles_layout.addStretch(1)
        tiles_scroll.setWidget(self._tiles_container)
        layout.addWidget(tiles_scroll, 1)

        self._groups_empty_hint = MicroLabel("No fixture groups yet",
                                             point_size=8, tracking_em=0.1)
        self._groups_empty_hint.setMinimumWidth(1)
        self._groups_empty_hint.setContentsMargins(16, 4, 16, 4)
        self._tiles_layout.insertWidget(0, self._groups_empty_hint)

        # PROGRAMMER readout.
        programmer = QWidget()
        programmer.setObjectName("LiveProgrammer")
        programmer.setProperty("role", "section-caption")
        programmer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        prog_layout = QVBoxLayout(programmer)
        prog_layout.setContentsMargins(16, 10, 16, 12)
        prog_layout.setSpacing(4)
        self._programmer_caption = MicroLabel("Programmer", point_size=8,
                                              tracking_em=0.14)
        self._programmer_caption.setStyleSheet(
            f"color: {_active_tokens()['accent_line']};")
        prog_layout.addWidget(self._programmer_caption)
        self._programmer_body = QWidget()
        self._programmer_body_layout = QVBoxLayout(self._programmer_body)
        self._programmer_body_layout.setContentsMargins(0, 0, 0, 0)
        self._programmer_body_layout.setSpacing(2)
        prog_layout.addWidget(self._programmer_body)
        layout.addWidget(programmer)
        return panel

    def _rebuild_group_tiles(self) -> None:
        """Rebuild the SELECT tiles from ``config.groups`` when the group
        set changes. Skips the rebuild if the group names are unchanged."""
        group_names = list(self.config.groups.keys())
        fingerprint = tuple(group_names)
        if fingerprint == self._current_groups_fingerprint:
            return
        self._current_groups_fingerprint = fingerprint

        # Drop stale state for groups that no longer exist.
        self.state.prune_groups(group_names)

        while self._tiles_layout.count() > 1:
            item = self._tiles_layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self._groups_empty_hint:
                widget.deleteLater()
        # Re-add the (persistent) empty hint at the top.
        self._tiles_layout.insertWidget(0, self._groups_empty_hint)
        self._select_tiles = {}
        self._group_colors = {}

        for index, name in enumerate(group_names):
            color = self._group_color(index, name)
            self._group_colors[name] = color
            group = self.config.groups.get(name)
            count = len(getattr(group, "fixtures", []) or [])
            tile = _SelectTile(name, count, color)
            tile.clicked.connect(self.state.toggle_group)
            self._tiles_layout.insertWidget(
                self._tiles_layout.count() - 1, tile)
            self._select_tiles[name] = tile

        self._groups_empty_hint.setVisible(not group_names)

    def _group_color(self, index: int, group_name: str) -> str:
        group = self.config.groups.get(group_name)
        saved = getattr(group, "color", None) if group is not None else None
        if saved and saved != DEFAULT_GROUP_COLOR and QColor(saved).isValid():
            return QColor(saved).name()
        return GROUP_PALETTE[index % len(GROUP_PALETTE)]

    # -- CENTER: palette grid + apply ------------------------------------

    def _build_center_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("LivePaletteStage")
        panel.setProperty("role", "grid-surface")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        layout.addWidget(MicroLabel("Palettes · touch to apply", point_size=8,
                                    tracking_em=0.12))

        grid_host = QWidget()
        from PyQt6.QtWidgets import QGridLayout
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        columns = 3
        for i, (key, label) in enumerate(PALETTE_CELLS):
            cell = _PaletteCell(key, label)
            cell.clicked.connect(self._on_palette_touched)
            grid.addWidget(cell, i // columns, i % columns)
            self._palette_cells[key] = cell
        for col in range(columns):
            grid.setColumnStretch(col, 1)
        layout.addWidget(grid_host, 1)

        # APPLY row + programmer state line.
        apply_row = QHBoxLayout()
        apply_row.setSpacing(12)
        self._programmer_state = MicroLabel("", point_size=8, tracking_em=0.1)
        self._programmer_state.setMinimumWidth(1)
        apply_row.addWidget(self._programmer_state, 1)
        self._apply_btn = QPushButton("APPLY TO SELECTION")
        self._apply_btn.setProperty("role", "cta-accent")
        self._apply_btn.setFont(display_font(15, QFont.Weight.ExtraBold,
                                             tracking_em=0.08))
        self._apply_btn.setFixedHeight(44)
        self._apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_btn.setToolTip(
            "Re-apply the staged palette to the current selection")
        self._apply_btn.clicked.connect(self.state.apply_to_selection)
        apply_row.addWidget(self._apply_btn)
        layout.addLayout(apply_row)
        return panel

    def _on_palette_touched(self, key: str) -> None:
        self.state.stage_palette(key)

    # -- RIGHT: masters, strobe, fade, blackout, song palette ------------

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("LiveMasterPanel")
        panel.setProperty("role", "inspector")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setFixedWidth(RIGHT_PANEL_WIDTH)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        # MASTER.
        layout.addWidget(MicroLabel("Master", point_size=8, tracking_em=0.14))
        master_row = QHBoxLayout()
        master_row.setSpacing(8)
        self._master_fader = _MasterFader()
        self._master_fader.value_changed.connect(self.state.set_master)
        master_row.addWidget(self._master_fader, 1)
        self._master_value = MicroLabel("100", point_size=9, tracking_em=0.0)
        self._master_value.setFixedWidth(30)
        self._master_value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        master_row.addWidget(self._master_value)
        layout.addLayout(master_row)

        # STROBE.
        layout.addWidget(MicroLabel("Strobe", point_size=8, tracking_em=0.14))
        strobe_row = QHBoxLayout()
        strobe_row.setSpacing(8)
        self._strobe_slider = _RateSlider()
        self._strobe_slider.value_changed.connect(self.state.set_strobe_rate)
        strobe_row.addWidget(self._strobe_slider, 1)
        self._strobe_btn = QPushButton("STROBE")
        self._strobe_btn.setCheckable(True)
        self._strobe_btn.setProperty("role", "output-select")
        self._strobe_btn.setFont(mono_font(8, QFont.Weight.DemiBold))
        self._strobe_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._strobe_btn.setToolTip("Toggle the strobe effect on the rig")
        self._strobe_btn.toggled.connect(self.state.set_strobe_on)
        strobe_row.addWidget(self._strobe_btn)
        layout.addLayout(strobe_row)

        # FADE TIME.
        layout.addWidget(MicroLabel("Fade time · apply", point_size=8,
                                    tracking_em=0.12))
        fade_row = QHBoxLayout()
        fade_row.setSpacing(4)
        for label, seconds in FADE_OPTIONS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setProperty("role", "output-select")
            btn.setFont(mono_font(8, QFont.Weight.Medium))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda _checked=False, s=seconds:
                self.state.set_fade_seconds(s))
            fade_row.addWidget(btn, 1)
            self._fade_buttons.append((btn, seconds))
        layout.addLayout(fade_row)

        # BLACKOUT.
        self._blackout_btn = QPushButton("BLACKOUT")
        self._blackout_btn.setCheckable(True)
        self._blackout_btn.setProperty("role", "destructive")
        self._blackout_btn.setFont(display_font(16, QFont.Weight.ExtraBold,
                                               tracking_em=0.1))
        self._blackout_btn.setFixedHeight(52)
        self._blackout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._blackout_btn.setToolTip("Zero the master output")
        self._blackout_btn.toggled.connect(self.state.set_blackout)
        layout.addWidget(self._blackout_btn)

        layout.addStretch(1)

        # SONG PALETTE strip (static placeholder).
        layout.addWidget(MicroLabel("Song palette", point_size=8,
                                    tracking_em=0.12))
        song_row = QHBoxLayout()
        song_row.setSpacing(4)
        for name in SONG_PALETTES:
            chip = QLabel(name.upper())
            chip.setProperty("role", "output-chip")
            chip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            chip.setFont(mono_font(8, QFont.Weight.Medium))
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setToolTip("Song palettes arrive with the show-link pass")
            song_row.addWidget(chip, 1)
        layout.addLayout(song_row)
        return panel

    # -- state -> widgets (single source of truth) -----------------------

    def _sync_from_state(self) -> None:
        state = self.state
        for name, tile in self._select_tiles.items():
            tile.set_selected(name in state.selected)

        active_keys = state.active_palette_keys()
        for key, cell in self._palette_cells.items():
            cell.set_active(key in active_keys)

        self._master_fader.set_value(state.master)
        self._master_value.setText(str(state.master))
        self._strobe_slider.set_value(state.strobe_rate)

        if self._strobe_btn.isChecked() != state.strobe_on:
            self._strobe_btn.blockSignals(True)
            self._strobe_btn.setChecked(state.strobe_on)
            self._strobe_btn.blockSignals(False)

        if self._blackout_btn.isChecked() != state.blackout:
            self._blackout_btn.blockSignals(True)
            self._blackout_btn.setChecked(state.blackout)
            self._blackout_btn.blockSignals(False)

        for btn, seconds in self._fade_buttons:
            btn.setChecked(abs(seconds - state.fade_seconds) < 1e-6)

        self._refresh_programmer()

    def _refresh_programmer(self) -> None:
        state = self.state
        # Centre state line.
        selected = sorted(state.selected)
        if not selected:
            self._programmer_state.setText("No groups selected")
        else:
            staged = state.staged_palette
            palette_word = self._palette_label(staged) if staged else "no palette"
            self._programmer_state.setText(
                f"{len(selected)} selected · staged: {palette_word}")

        # Left programmer body: one line per selected group.
        layout = self._programmer_body_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not selected:
            empty = MicroLabel("Select groups, then touch a palette",
                               point_size=7, tracking_em=0.05)
            empty.setMinimumWidth(1)
            layout.addWidget(empty)
            return
        for name in selected:
            key = state.group_palettes.get(name)
            palette_word = self._palette_label(key) if key else "-"
            line = MicroLabel(f"{name} · {palette_word}", point_size=7,
                              tracking_em=0.05)
            line.setMinimumWidth(1)
            layout.addWidget(line)

    @staticmethod
    def _palette_label(key: Optional[str]) -> str:
        for cell_key, label in PALETTE_CELLS:
            if cell_key == key:
                return label
        return key or "-"

    # -- theme switches --------------------------------------------------

    def changeEvent(self, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.StyleChange:
            for tile in self._select_tiles.values():
                tile._restyle()
            for cell in self._palette_cells.values():
                cell._restyle()
            if hasattr(self, "_programmer_caption"):
                self._programmer_caption.setStyleSheet(
                    f"color: {_active_tokens()['accent_line']};")
        super().changeEvent(event)
