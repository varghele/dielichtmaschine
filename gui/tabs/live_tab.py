"""LiveTab - the touch-palette busking surface, built to the reference
design_handoff_lichtmaschine_app/screens/09-live-3b-palette.html (layout
"3b").

This is a UI shell wired to an in-memory :class:`LiveState`. There is no
DMX / ArtNet output yet - every interaction mutates ``LiveState`` and
emits ``LiveState.state_changed`` so a later engine pass can subscribe an
output resolver to it without touching the widgets. ``LiveState`` is
already shaped so that a resolve is a pure function of the state plus the
fixture patch (see :meth:`LiveState.group_level`).

Regions (North Star 3b):

- TOP - a SELECT row (one tile per fixture group + ALL / ODD-EVEN
  quick-select + CLEAR SEL) and a FADE row (SNAP / 0.5s / 2s / 4s /
  1 BAR / 4 BARS as output-select chips). Touch a palette and the
  selection "fades" to it over the chosen time (recorded, not animated).
- CENTRE - a three-column pool grid: COLOUR PALETTES (fully built this
  pass) | POSITION PALETTES + MOVEMENT SHAPES (placeholder, movers-only)
  | RUDIMENTS / INTENSITY FX (placeholder, cell-fixtures gated). Below
  it a PROGRAMMER state bar names the current live look.
- RIGHT (330px) - GRAND + SUB faders, a STROBE rate + toggle,
  STROBE KILL / HOLD LOOK / RELEASE ALL, a big DBO (dead blackout) and
  an ACTIVE PLAYBACKS area (display-only: "NOTHING ELSE RUNNING").
- BOTTOM (170px) - the submaster fader bank: one vertical fader per
  group in the group's data colour with a momentary FLASH button.

Honest omissions vs. the reference (surfaces with no in-memory state to
drive them yet): the cue stack, the live 3D render / DMX meters, the
active-playbacks list, the FX-speed/size/white-wash bank slots and the
transport clock are output-engine surfaces, so they are rendered as
clearly-marked placeholders rather than faked. The colour PICKER, SONG
PALETTE link and "+ REC" capture, and the POSITION / MOVEMENT / INTENSITY
pools, are staged for later passes and marked "arrives next".
"""

from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPolygon
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
    QFrame, QPushButton, QLabel,
)

from config.models import Configuration
from gui.typography import DisplayLabel, MicroLabel, display_font, mono_font

from .base_tab import BaseTab

# Reference geometry.
RIGHT_PANEL_WIDTH = 330
BOTTOM_BANK_HEIGHT = 170

# Group fallback palette (mirrors the Auto / Stage screens) for groups
# that carry the default gray or no color.
GROUP_PALETTE = (
    "#D9A441", "#4ECBD4", "#C95FD0", "#6F9E4C",
    "#5F86C9", "#C96A5F", "#9A7FD0", "#8D9299",
)
DEFAULT_GROUP_COLOR = "#808080"

# COLOUR PALETTES pool: (id, label, primary, secondary). ``secondary`` is
# None for a solid swatch and an rgb for a two-colour diagonal split. The
# id is stored per selected group in LiveState.colours; the label is the
# swatch caption. Colours are copied verbatim from the reference screen.
COLOUR_SWATCHES: Tuple[Tuple[str, str, str, Optional[str]], ...] = (
    ("white", "White", "#FFFFFF", None),
    ("amber", "Amber", "#FFB43C", None),
    ("red", "Red", "#FF2850", None),
    ("magenta", "Magenta", "#C95FD0", None),
    ("cyan", "Cyan", "#4ECBD4", None),
    ("blue", "Blue", "#4060FF", None),
    ("green", "Green", "#40FF70", None),
    ("red_cyan", "Red / Cyan", "#FF2850", "#4ECBD4"),
    ("mag_amber", "Mag / Amber", "#C95FD0", "#FFB43C"),
)

# Fade options: (key, label, seconds). Bar-relative fades have no fixed
# second count without a clock, so their seconds is None - the key still
# selects the chip and drives future bar-locked resolves.
FADE_OPTIONS: Tuple[Tuple[str, str, Optional[float]], ...] = (
    ("snap", "SNAP", 0.0),
    ("0.5s", "0.5 s", 0.5),
    ("2s", "2 s", 2.0),
    ("4s", "4 s", 4.0),
    ("1bar", "1 BAR", None),
    ("4bars", "4 BARS", None),
)
DEFAULT_FADE_KEY = "2s"
DEFAULT_FADE_SECONDS = 2.0

# POSITION / MOVEMENT / INTENSITY pools are placeholders this pass - the
# labels seed the eventual controls but render as disabled, marked cells.
POSITION_PLACEHOLDERS = ("Centre", "Audience", "Cross", "Fan Out",
                         "Ceiling", "Drums")
MOVEMENT_PLACEHOLDERS = ("Off", "Circle", "Fig-8", "Sweep", "Size")
INTENSITY_PLACEHOLDERS = ("Static", "Pulse", "Chase", "Wave", "Sparkle",
                          "Strobe", "Ping-Pong")
# Cell/pixel FX that only run on cell fixtures - gated "NEEDS CELLS".
INTENSITY_CELL_PLACEHOLDERS = ("Waterfall", "Cascade")


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


def _contrast_text(hex_color: str) -> str:
    """Dark on light swatches, light on dark ones, by relative luminance."""
    c = QColor(hex_color)
    lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
    return "#141416" if lum > 128 else "#F4F1EA"


# ---------------------------------------------------------------------------
# In-memory live state (the future output engine subscribes to this)
# ---------------------------------------------------------------------------

class LiveState(QObject):
    """The busking programmer's in-memory state.

    Plain data plus mutators; every mutator emits :attr:`state_changed`
    so the tab (and, later, an ArtNet output resolver) can re-sync from a
    single source of truth. Holds no widgets and no output plumbing.

    Output scale is modelled but not emitted: :meth:`group_level` returns
    the resolved 0..1 intensity multiplier for a group as a pure function
    of the masters, flash and blackout flags. Per-selection colour is
    stored per group in :attr:`colours` (group name -> swatch id) so a
    colour is a mutual-exclusion execute per group (newest touch wins).
    """

    state_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected: set = set()               # selected group names
        self.colours: Dict[str, str] = {}        # group name -> swatch id
        self.staged_colour: Optional[str] = None  # last touched swatch id
        # Fade time used when a palette is applied (recorded, not animated).
        self.fade_key: str = DEFAULT_FADE_KEY
        self.fade_seconds: float = DEFAULT_FADE_SECONDS
        # Masters / output scale.
        self.grandmaster: int = 100              # 0-100, all groups
        self.sub_master: int = 100               # 0-100, global secondary
        self.submasters: Dict[str, int] = {}     # group name -> 0-100
        self.flash: set = set()                  # groups flashed to full
        # Blackout flags. dbo (dead blackout) is the stronger kill and
        # overrides a held flash; the softer blackout does not.
        self.blackout: bool = False
        self.dbo: bool = False
        self.held_look: bool = False
        # Strobe.
        self.strobe_on: bool = False
        self.strobe_rate: int = 50               # 0-100

    # -- config sync ----------------------------------------------------
    def update_from_config(self, names) -> None:
        """Seed a submaster (default 100) for each group and prune state
        for groups that no longer exist. Silent - the tab re-syncs
        explicitly after a rebuild."""
        names = list(names)
        valid = set(names)
        self.selected &= valid
        self.flash &= valid
        self.colours = {g: c for g, c in self.colours.items() if g in valid}
        # Keep existing submaster values; add 100 for new groups; drop
        # stale. Rebuild as an ordered dict following the group order.
        self.submasters = {g: self.submasters.get(g, 100) for g in names}

    # -- selection ------------------------------------------------------
    def toggle_group(self, name: str) -> None:
        if name in self.selected:
            self.selected.discard(name)
        else:
            self.selected.add(name)
        self.state_changed.emit()

    def set_selection(self, names) -> None:
        self.selected = set(names)
        self.state_changed.emit()

    def clear_selection(self) -> None:
        self.selected.clear()
        self.state_changed.emit()

    # -- colour palettes ------------------------------------------------
    def stage_colour(self, colour_id: str) -> None:
        """Touch a colour swatch: record it as the staged colour and apply
        it to every selected group at the current fade time. Mutual
        exclusion - a group holds at most one colour, newest touch wins."""
        self.staged_colour = colour_id
        for group in self.selected:
            self.colours[group] = colour_id
        self.state_changed.emit()

    def active_colour_ids(self) -> set:
        """Swatch ids currently applied to any selected group - the
        swatches the pool outlines in the accent."""
        return {self.colours[g] for g in self.selected if g in self.colours}

    def release_all(self) -> None:
        """Clear the programmer (applied colours + staged + selection)
        back to nothing, releasing the rig to the show."""
        self.colours.clear()
        self.staged_colour = None
        self.selected.clear()
        self.state_changed.emit()

    # -- masters / output scale -----------------------------------------
    def set_grandmaster(self, level: int) -> None:
        self.grandmaster = max(0, min(100, int(level)))
        self.state_changed.emit()

    def set_sub_master(self, level: int) -> None:
        self.sub_master = max(0, min(100, int(level)))
        self.state_changed.emit()

    def set_submaster(self, group: str, level: int) -> None:
        self.submasters[group] = max(0, min(100, int(level)))
        self.state_changed.emit()

    def set_flash(self, group: str, on: bool) -> None:
        if on:
            self.flash.add(group)
        else:
            self.flash.discard(group)
        self.state_changed.emit()

    def set_blackout(self, on: bool) -> None:
        self.blackout = bool(on)
        self.state_changed.emit()

    def set_dbo(self, on: bool) -> None:
        self.dbo = bool(on)
        self.state_changed.emit()

    def set_hold_look(self, on: bool) -> None:
        self.held_look = bool(on)
        self.state_changed.emit()

    def group_level(self, group: str) -> float:
        """Resolved 0..1 output multiplier for a group.

        DBO (dead blackout) kills everything, overriding a held flash. A
        held flash forces full (1.0), overriding the softer blackout.
        Otherwise the scale is grand x sub x per-group submaster (each
        0..1). Unknown groups resolve to 0.
        """
        if group not in self.submasters:
            return 0.0
        if self.dbo:
            return 0.0
        if group in self.flash:
            return 1.0
        if self.blackout:
            return 0.0
        return ((self.grandmaster / 100.0) * (self.sub_master / 100.0)
                * (self.submasters[group] / 100.0))

    # -- strobe ---------------------------------------------------------
    def set_strobe_on(self, on: bool) -> None:
        self.strobe_on = bool(on)
        self.state_changed.emit()

    def strobe_kill(self) -> None:
        self.strobe_on = False
        self.state_changed.emit()

    def set_strobe_rate(self, rate: int) -> None:
        self.strobe_rate = max(0, min(100, int(rate)))
        self.state_changed.emit()

    # -- fade -----------------------------------------------------------
    def set_fade(self, key: str, seconds: Optional[float]) -> None:
        self.fade_key = key
        if seconds is not None:
            self.fade_seconds = max(0.0, float(seconds))
        self.state_changed.emit()


# ---------------------------------------------------------------------------
# Painted primitives
# ---------------------------------------------------------------------------

class _HFader(QWidget):
    """A flat horizontal 0-100 fader: track + coloured fill + text handle.

    ``set_value`` is silent (the tab drives it from LiveState); only user
    drags emit ``value_changed`` so there is no sync feedback loop. The
    fill token key selects the fill colour (accent for GRAND, secondary
    for SUB).
    """

    value_changed = pyqtSignal(int)

    def __init__(self, fill: str = "accent", parent=None):
        super().__init__(parent)
        self.setFixedHeight(18)
        self.setMinimumWidth(80)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self._value = 100
        self._fill = fill

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
            painter.fillRect(0, track_top, filled, 10, QColor(tokens[self._fill]))
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


class _VerticalFader(QWidget):
    """A vertical 0-100 submaster fader painted in the group's data colour.

    Silent ``set_value`` (tab drives it from LiveState); drags emit
    ``value_changed``. The fill colour is the group colour so the bottom
    bank reads as one fader per group at a glance.
    """

    value_changed = pyqtSignal(int)

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self._value = 100
        self.setMinimumSize(12, 40)
        self.setCursor(Qt.CursorShape.SizeVerCursor)

    def value(self) -> int:
        return self._value

    def set_value(self, value: int) -> None:
        self._value = max(0, min(100, int(value)))
        self.update()

    def set_color(self, color: str) -> None:
        self._color = color
        self.update()

    def _set_from_y(self, y: float) -> None:
        frac = 1.0 - max(0.0, min(1.0, y / max(1, self.height())))
        value = int(round(frac * 100))
        if value != self._value:
            self._value = value
            self.update()
            self.value_changed.emit(value)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._set_from_y(event.position().y())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._set_from_y(event.position().y())

    def paintEvent(self, event):
        tokens = _active_tokens()
        painter = QPainter(self)
        w, h = self.width(), self.height()
        track_w = 8
        track_x = (w - track_w) // 2
        painter.fillRect(track_x, 0, track_w, h, QColor(tokens["border"]))
        fill_h = int(round(h * self._value / 100.0))
        if fill_h > 0:
            painter.fillRect(track_x, h - fill_h, track_w, fill_h,
                             QColor(self._color))
        handle_y = max(0, h - fill_h - 2)
        painter.fillRect(0, handle_y, w, 4, QColor(tokens["text"]))
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
        layout.setContentsMargins(12, 7, 14, 7)
        layout.setSpacing(1)
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


class _ColourSwatch(QWidget):
    """A COLOUR PALETTES cell painted in its actual colour.

    Solid or a two-colour diagonal split; a small mono name in contrast-
    picked text; an accent outline when the colour is active on the
    current selection. Touching emits ``clicked`` with the swatch id.
    """

    clicked = pyqtSignal(str)

    def __init__(self, colour_id: str, label: str, primary: str,
                 secondary: Optional[str], parent=None):
        super().__init__(parent)
        self.colour_id = colour_id
        self.label = label
        self._primary = primary
        self._secondary = secondary
        self._active = False
        self.setMinimumSize(84, 84)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{label} - touch to fade the selection to it")

    def is_active(self) -> bool:
        return self._active

    def set_active(self, active: bool) -> None:
        active = bool(active)
        if active != self._active:
            self._active = active
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.colour_id)

    def paintEvent(self, event):
        tokens = _active_tokens()
        painter = QPainter(self)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor(self._primary))
        if self._secondary is not None:
            # Lower-right triangle in the secondary colour (diagonal split).
            poly = QPolygon([QPoint(w, 0), QPoint(w, h), QPoint(0, h)])
            painter.setBrush(QColor(self._secondary))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(poly)
        if self._active:
            pen = painter.pen()
            pen.setColor(QColor(tokens["accent"]))
            pen.setWidth(3)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(2, 2, w - 4, h - 4)
        # Name (contrast text), bottom-left. Offscreen QPA has no font DB
        # so this is a fallback box in headless renders - fine for the
        # per-platform golden, real glyphs on a desktop session.
        text_hex = _contrast_text(self._secondary or self._primary)
        painter.setPen(QColor(text_hex))
        painter.setFont(mono_font(7, QFont.Weight.Medium))
        suffix = " OK" if self._active else ""
        painter.drawText(6, h - 6, (self.label + suffix).upper())
        painter.end()


class _PlaceholderCell(QWidget):
    """A disabled, clearly-marked pool cell (POSITION / INTENSITY pools).

    Renders the eventual control's name greyed, with an optional sub-note
    ("NEEDS CELLS"), and is non-interactive - an honest "arrives next"
    placeholder rather than a faked working cell.
    """

    def __init__(self, label: str, sub: Optional[str] = None,
                 dashed: bool = False, parent=None):
        super().__init__(parent)
        self._dashed = dashed
        self.setObjectName("LivePlaceholderCell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("placeholder", True)
        self.setEnabled(False)
        self.setMinimumSize(84, 62)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(1)
        layout.addStretch(1)
        self.label = DisplayLabel(label, point_size=12,
                                  weight=QFont.Weight.Bold, tracking_em=0.04)
        self.label.setMinimumWidth(1)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)
        self.sub_label = None
        if sub:
            self.sub_label = MicroLabel(sub, point_size=7, tracking_em=0.08)
            self.sub_label.setMinimumWidth(1)
            self.sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.sub_label)
        layout.addStretch(1)
        self._restyle()

    def _restyle(self) -> None:
        tokens = _active_tokens()
        style = "dashed" if self._dashed else "solid"
        self.setStyleSheet(
            "#LivePlaceholderCell {"
            f" background-color: {tokens['panel']};"
            f" border: 1px {style} {tokens['border']}; }}")
        self.label.setStyleSheet(
            f"color: {tokens['text_disabled']}; background: transparent;")
        if self.sub_label is not None:
            self.sub_label.setStyleSheet(
                f"color: {tokens['text_disabled']}; background: transparent;")


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
        self._colour_swatches: Dict[str, _ColourSwatch] = {}
        self._colour_placeholders: Dict[str, QWidget] = {}
        self._position_cells: List[_PlaceholderCell] = []
        self._intensity_cells: List[_PlaceholderCell] = []
        self._fade_buttons: List[Tuple[QPushButton, str, Optional[float]]] = []
        self._submaster_faders: Dict[str, _VerticalFader] = {}
        self._flash_buttons: Dict[str, QPushButton] = {}
        self._group_colors: Dict[str, str] = {}
        self._accent_labels: List[QLabel] = []
        self._current_groups_fingerprint = None

        super().__init__(config, parent)

        self.state.state_changed.connect(self._sync_from_state)
        self._rebuild_groups()
        self._sync_from_state()

    # -- BaseTab ---------------------------------------------------------

    def setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_centre_column(), 1)
        body.addWidget(self._build_right_panel())
        outer.addLayout(body, 1)

        outer.addWidget(self._build_submaster_bank())

    def update_from_config(self):
        """Refresh SELECT tiles + submaster bank when the groups change."""
        self._rebuild_groups()
        self._sync_from_state()

    # -- CENTRE: select row, fade row, pools, programmer bar -------------

    def _build_centre_column(self) -> QWidget:
        panel = QWidget()
        panel.setProperty("role", "tab-page")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_select_row())
        layout.addWidget(self._build_fade_row())
        layout.addWidget(self._build_pools(), 1)
        layout.addWidget(self._build_programmer_bar())
        return panel

    def _build_select_row(self) -> QWidget:
        row = QWidget()
        row.setProperty("role", "section-caption")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hbox = QHBoxLayout(row)
        hbox.setContentsMargins(16, 8, 16, 8)
        hbox.setSpacing(8)
        hbox.addWidget(MicroLabel("Select", point_size=8, tracking_em=0.12))

        # The group tiles are rebuilt from the config here.
        self._tiles_host = QHBoxLayout()
        self._tiles_host.setSpacing(6)
        hbox.addLayout(self._tiles_host)

        self._groups_empty_hint = MicroLabel("No fixture groups yet",
                                             point_size=8, tracking_em=0.1)
        self._groups_empty_hint.setMinimumWidth(1)
        hbox.addWidget(self._groups_empty_hint)

        self._all_btn = self._quick_chip("ALL", "Select every group")
        self._all_btn.clicked.connect(self._on_select_all)
        hbox.addWidget(self._all_btn)

        # ODD/EVEN is a fixture-level selection tool; without a fixture
        # programmer it is an honest placeholder this pass.
        self._oddeven_btn = self._quick_chip(
            "ODD/EVEN", "Odd/even fixture split arrives with the "
            "fixture programmer")
        self._oddeven_btn.setEnabled(False)
        hbox.addWidget(self._oddeven_btn)

        hbox.addStretch(1)

        self._clear_sel_btn = self._quick_chip(
            "CLEAR SEL", "Clear the current group selection")
        self._clear_sel_btn.clicked.connect(self.state.clear_selection)
        hbox.addWidget(self._clear_sel_btn)
        return row

    def _quick_chip(self, text: str, tip: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setProperty("role", "output-select")
        btn.setFont(mono_font(8, QFont.Weight.Medium))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(tip)
        return btn

    def _build_fade_row(self) -> QWidget:
        row = QWidget()
        row.setProperty("role", "section-caption")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hbox = QHBoxLayout(row)
        hbox.setContentsMargins(16, 6, 16, 6)
        hbox.setSpacing(6)
        hbox.addWidget(MicroLabel("Fade", point_size=8, tracking_em=0.12))
        for key, label, seconds in FADE_OPTIONS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setProperty("role", "output-select")
            btn.setFont(mono_font(8, QFont.Weight.Medium))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda _checked=False, k=key, s=seconds:
                self.state.set_fade(k, s))
            hbox.addWidget(btn)
            self._fade_buttons.append((btn, key, seconds))
        hint = MicroLabel(
            "Touch a palette · selection fades to it over this time",
            point_size=7, tracking_em=0.08)
        hint.setMinimumWidth(1)
        hbox.addSpacing(6)
        hbox.addWidget(hint)
        hbox.addStretch(1)
        return row

    # -- pools -----------------------------------------------------------

    def _build_pools(self) -> QWidget:
        host = QWidget()
        host.setObjectName("LivePoolsHost")
        host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._pools_host = host
        hbox = QHBoxLayout(host)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(1)   # 1px gaps read as separators over the host bg
        self._colour_pool = self._build_colour_pool()
        self._position_pool = self._build_position_pool()
        self._intensity_pool = self._build_intensity_pool()
        hbox.addWidget(self._colour_pool, 11)
        hbox.addWidget(self._position_pool, 10)
        hbox.addWidget(self._intensity_pool, 10)
        self._restyle_pools_host()
        return host

    def _restyle_pools_host(self) -> None:
        tokens = _active_tokens()
        self._pools_host.setStyleSheet(
            f"#LivePoolsHost {{ background-color: {tokens['border']}; }}")

    def _pool_shell(self) -> Tuple[QWidget, QVBoxLayout]:
        pool = QWidget()
        pool.setProperty("role", "tab-page")
        pool.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(pool)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        return pool, layout

    def _pool_header(self, title: str, tag: Optional[str] = None,
                     tag_accent: bool = False) -> QWidget:
        header = QWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(14, 8, 14, 4)
        row.setSpacing(8)
        row.addWidget(MicroLabel(title, point_size=8, tracking_em=0.12))
        row.addStretch(1)
        if tag:
            tag_label = MicroLabel(tag, point_size=7, tracking_em=0.08)
            tag_label.setMinimumWidth(1)
            if tag_accent:
                self._accent_labels.append(tag_label)
                tag_label.setStyleSheet(
                    f"color: {_active_tokens()['accent_line']};")
            row.addWidget(tag_label)
        return header

    def _marker(self, text: str) -> QLabel:
        label = MicroLabel(text, point_size=7, tracking_em=0.1)
        label.setMinimumWidth(1)
        label.setContentsMargins(14, 0, 14, 6)
        return label

    def _build_colour_pool(self) -> QWidget:
        pool, layout = self._pool_shell()
        layout.addWidget(self._pool_header("Colour palettes"))

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(14, 0, 14, 12)
        grid.setSpacing(6)
        columns = 4
        cells: List[QWidget] = []
        for colour_id, label, primary, secondary in COLOUR_SWATCHES:
            swatch = _ColourSwatch(colour_id, label, primary, secondary)
            swatch.clicked.connect(self._on_colour_touched)
            self._colour_swatches[colour_id] = swatch
            cells.append(swatch)
        # Placeholders (stage 7): song palette link, colour picker, + REC.
        song = _PlaceholderCell("Song Palette")
        song.setToolTip("Song palettes arrive with the show-link pass")
        picker = _PlaceholderCell("Picker")
        picker.setToolTip("Colour picker wheel arrives with the picker pass")
        rec = _PlaceholderCell("+ REC", dashed=True)
        rec.setToolTip("Capture the current look as a palette (stage 7)")
        self._colour_placeholders = {
            "song_palette": song, "picker": picker, "rec": rec}
        cells.extend((song, picker, rec))
        for i, cell in enumerate(cells):
            grid.addWidget(cell, i // columns, i % columns)
        for col in range(columns):
            grid.setColumnStretch(col, 1)
        layout.addWidget(grid_host)
        layout.addStretch(1)
        return pool

    def _build_position_pool(self) -> QWidget:
        pool, layout = self._pool_shell()
        layout.addWidget(self._pool_header(
            "Position palettes", "Applies to: movers", tag_accent=True))
        layout.addWidget(self._marker("Arrives next"))

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(14, 0, 14, 10)
        grid.setSpacing(6)
        columns = 3
        for i, name in enumerate(POSITION_PLACEHOLDERS):
            cell = _PlaceholderCell(name)
            self._position_cells.append(cell)
            grid.addWidget(cell, i // columns, i % columns)
        for col in range(columns):
            grid.setColumnStretch(col, 1)
        layout.addWidget(grid_host)

        layout.addWidget(self._pool_header("Movement shapes"))
        shape_row = QWidget()
        shbox = QHBoxLayout(shape_row)
        shbox.setContentsMargins(14, 0, 14, 12)
        shbox.setSpacing(6)
        for name in MOVEMENT_PLACEHOLDERS:
            cell = _PlaceholderCell(name)
            cell.setMinimumSize(1, 30)
            self._position_cells.append(cell)
            shbox.addWidget(cell, 1)
        layout.addWidget(shape_row)
        layout.addStretch(1)
        return pool

    def _build_intensity_pool(self) -> QWidget:
        pool, layout = self._pool_shell()
        layout.addWidget(self._pool_header(
            "Rudiments · Intensity FX", "Rate 1/4"))
        layout.addWidget(self._marker("Arrives next"))

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(14, 0, 14, 8)
        grid.setSpacing(6)
        columns = 3
        cells: List[_PlaceholderCell] = []
        for name in INTENSITY_PLACEHOLDERS:
            cells.append(_PlaceholderCell(name))
        for name in INTENSITY_CELL_PLACEHOLDERS:
            cells.append(_PlaceholderCell(name, sub="Needs cells"))
        for i, cell in enumerate(cells):
            self._intensity_cells.append(cell)
            grid.addWidget(cell, i // columns, i % columns)
        for col in range(columns):
            grid.setColumnStretch(col, 1)
        layout.addWidget(grid_host)
        layout.addWidget(self._marker(
            "Greyed = doesn't apply to selection (no cell fixtures)"))
        layout.addStretch(1)
        return pool

    def _on_colour_touched(self, colour_id: str) -> None:
        self.state.stage_colour(colour_id)

    def _on_select_all(self) -> None:
        self.state.set_selection(self.config.groups.keys())

    # -- programmer bar --------------------------------------------------

    def _build_programmer_bar(self) -> QWidget:
        bar = QWidget()
        bar.setProperty("role", "section-caption")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 8, 16, 8)
        row.setSpacing(10)
        self._programmer_label = MicroLabel("", point_size=8, tracking_em=0.1)
        self._programmer_label.setMinimumWidth(1)
        self._accent_labels.append(self._programmer_label)
        self._programmer_label.setStyleSheet(
            f"color: {_active_tokens()['accent_line']};")
        row.addWidget(self._programmer_label, 1)
        return bar

    # -- RIGHT: masters, strobe, kills, DBO, playbacks -------------------

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("LiveMasterPanel")
        panel.setProperty("role", "inspector")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setFixedWidth(RIGHT_PANEL_WIDTH)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        # ACTIVE PLAYBACKS (display-only placeholder).
        layout.addWidget(MicroLabel("Active playbacks", point_size=8,
                                    tracking_em=0.14))
        self._active_playbacks_label = QLabel("NOTHING ELSE RUNNING")
        self._active_playbacks_label.setProperty("role", "hint-box")
        self._active_playbacks_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._active_playbacks_label.setFont(mono_font(8, tracking_em=0.1))
        self._active_playbacks_label.setToolTip(
            "The running show cue + busk stacks list here once the "
            "output engine lands")
        layout.addWidget(self._active_playbacks_label)

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

        # STROBE KILL / HOLD LOOK / RELEASE ALL.
        kills_row = QHBoxLayout()
        kills_row.setSpacing(6)
        self._strobe_kill_btn = QPushButton("STROBE KILL")
        self._strobe_kill_btn.setProperty("role", "output-select")
        self._strobe_kill_btn.setFont(mono_font(8, QFont.Weight.Medium))
        self._strobe_kill_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._strobe_kill_btn.setToolTip("Force the strobe off")
        self._strobe_kill_btn.clicked.connect(self.state.strobe_kill)
        kills_row.addWidget(self._strobe_kill_btn, 1)

        self._hold_look_btn = QPushButton("HOLD LOOK")
        self._hold_look_btn.setCheckable(True)
        self._hold_look_btn.setProperty("role", "output-select")
        self._hold_look_btn.setFont(mono_font(8, QFont.Weight.Medium))
        self._hold_look_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hold_look_btn.setToolTip("Latch the current look (block the "
                                       "show from taking it back)")
        self._hold_look_btn.toggled.connect(self.state.set_hold_look)
        kills_row.addWidget(self._hold_look_btn, 1)

        self._release_all_btn = QPushButton("RELEASE ALL")
        self._release_all_btn.setProperty("role", "cta-outline")
        self._release_all_btn.setFont(display_font(12, QFont.Weight.DemiBold,
                                                   tracking_em=0.06))
        self._release_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._release_all_btn.setToolTip(
            "Clear the programmer and release the rig to the show")
        self._release_all_btn.clicked.connect(self.state.release_all)
        kills_row.addWidget(self._release_all_btn, 1)
        layout.addLayout(kills_row)

        layout.addStretch(1)

        # GRAND + SUB.
        grand_row = QHBoxLayout()
        grand_row.setSpacing(8)
        grand_row.addWidget(MicroLabel("Grand", point_size=8,
                                       tracking_em=0.12))
        self._grand_fader = _HFader(fill="accent")
        self._grand_fader.value_changed.connect(self.state.set_grandmaster)
        grand_row.addWidget(self._grand_fader, 1)
        self._grand_value = MicroLabel("100", point_size=9, tracking_em=0.0)
        self._grand_value.setFixedWidth(30)
        self._grand_value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        grand_row.addWidget(self._grand_value)
        layout.addLayout(grand_row)

        sub_row = QHBoxLayout()
        sub_row.setSpacing(8)
        sub_row.addWidget(MicroLabel("Sub", point_size=8, tracking_em=0.12))
        self._sub_fader = _HFader(fill="text_secondary")
        self._sub_fader.value_changed.connect(self.state.set_sub_master)
        sub_row.addWidget(self._sub_fader, 1)
        self._sub_value = MicroLabel("100", point_size=9, tracking_em=0.0)
        self._sub_value.setFixedWidth(30)
        self._sub_value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        sub_row.addWidget(self._sub_value)
        layout.addLayout(sub_row)

        # DBO - dead blackout (destructive, latch).
        self._dbo_btn = QPushButton("DBO")
        self._dbo_btn.setCheckable(True)
        self._dbo_btn.setProperty("role", "destructive")
        self._dbo_btn.setFont(display_font(17, QFont.Weight.ExtraBold,
                                           tracking_em=0.1))
        self._dbo_btn.setFixedHeight(52)
        self._dbo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dbo_btn.setToolTip("Dead blackout - zero all output")
        self._dbo_btn.toggled.connect(self.state.set_dbo)
        layout.addWidget(self._dbo_btn)
        return panel

    # -- BOTTOM: submaster bank ------------------------------------------

    def _build_submaster_bank(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("LiveSubmasterBank")
        panel.setProperty("role", "section-caption")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setFixedHeight(BOTTOM_BANK_HEIGHT)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(16, 8, 16, 6)
        header_row.addWidget(MicroLabel("Playbacks · submasters",
                                        point_size=8, tracking_em=0.12))
        header_row.addStretch(1)
        header_row.addWidget(MicroLabel(
            "One fader per group · FLASH is momentary", point_size=7,
            tracking_em=0.08))
        layout.addWidget(header)

        self._bank_host = QWidget()
        self._bank_layout = QHBoxLayout(self._bank_host)
        self._bank_layout.setContentsMargins(12, 4, 12, 12)
        self._bank_layout.setSpacing(8)

        self._bank_empty_hint = MicroLabel("No fixture groups yet",
                                           point_size=8, tracking_em=0.1)
        self._bank_empty_hint.setMinimumWidth(1)
        self._bank_layout.addWidget(self._bank_empty_hint)
        self._bank_layout.addStretch(1)
        layout.addWidget(self._bank_host, 1)
        return panel

    def _make_submaster_column(self, name: str, color: str) -> QWidget:
        column = QWidget()
        column.setObjectName("LiveSubmasterColumn")
        column.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        column.setProperty("_group_color", color)
        col_layout = QVBoxLayout(column)
        col_layout.setContentsMargins(6, 6, 6, 6)
        col_layout.setSpacing(4)

        name_label = MicroLabel(name, point_size=8, tracking_em=0.06)
        name_label.setMinimumWidth(1)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col_layout.addWidget(name_label)

        fader = _VerticalFader(color)
        fader.value_changed.connect(
            lambda level, g=name: self.state.set_submaster(g, level))
        col_layout.addWidget(fader, 1, Qt.AlignmentFlag.AlignHCenter)
        self._submaster_faders[name] = fader

        flash = QPushButton("FLASH")
        flash.setProperty("role", "output-select")
        flash.setFont(mono_font(8, QFont.Weight.Medium))
        flash.setCursor(Qt.CursorShape.PointingHandCursor)
        flash.setToolTip(f"Flash {name} to full while held")
        flash.pressed.connect(lambda g=name: self.state.set_flash(g, True))
        flash.released.connect(lambda g=name: self.state.set_flash(g, False))
        col_layout.addWidget(flash)
        self._flash_buttons[name] = flash

        self._restyle_submaster_column(column, color)
        return column

    def _restyle_submaster_column(self, column: QWidget, color: str) -> None:
        tokens = _active_tokens()
        column.setStyleSheet(
            "#LiveSubmasterColumn {"
            f" background-color: {tokens['panel']};"
            f" border: 1px solid {tokens['border']};"
            f" border-top: 3px solid {color}; }}")

    # -- group rebuild ---------------------------------------------------

    def _group_color(self, index: int, group_name: str) -> str:
        group = self.config.groups.get(group_name)
        saved = getattr(group, "color", None) if group is not None else None
        if saved and saved != DEFAULT_GROUP_COLOR and QColor(saved).isValid():
            return QColor(saved).name()
        return GROUP_PALETTE[index % len(GROUP_PALETTE)]

    def _rebuild_groups(self) -> None:
        """Rebuild the SELECT tiles + submaster bank from ``config.groups``
        when the group set changes; skip if the group names are unchanged."""
        group_names = list(self.config.groups.keys())
        fingerprint = tuple(group_names)
        if fingerprint == self._current_groups_fingerprint:
            return
        self._current_groups_fingerprint = fingerprint

        # Seed/prune the state's per-group data for the new group set.
        self.state.update_from_config(group_names)

        self._group_colors = {}
        for index, name in enumerate(group_names):
            self._group_colors[name] = self._group_color(index, name)

        self._rebuild_select_tiles(group_names)
        self._rebuild_submaster_bank(group_names)

    def _rebuild_select_tiles(self, group_names) -> None:
        while self._tiles_host.count():
            item = self._tiles_host.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._select_tiles = {}
        for name in group_names:
            group = self.config.groups.get(name)
            count = len(getattr(group, "fixtures", []) or [])
            tile = _SelectTile(name, count, self._group_colors[name])
            tile.clicked.connect(self.state.toggle_group)
            self._tiles_host.addWidget(tile)
            self._select_tiles[name] = tile
        self._groups_empty_hint.setVisible(not group_names)

    def _rebuild_submaster_bank(self, group_names) -> None:
        while self._bank_layout.count():
            item = self._bank_layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self._bank_empty_hint:
                widget.deleteLater()
        self._submaster_faders = {}
        self._flash_buttons = {}
        self._bank_layout.addWidget(self._bank_empty_hint)
        for name in group_names:
            self._bank_layout.addWidget(
                self._make_submaster_column(name, self._group_colors[name]), 1)
        self._bank_layout.addStretch(1)
        self._bank_empty_hint.setVisible(not group_names)

    # -- state -> widgets (single source of truth) -----------------------

    def _sync_from_state(self) -> None:
        state = self.state
        for name, tile in self._select_tiles.items():
            tile.set_selected(name in state.selected)

        active_ids = state.active_colour_ids()
        for colour_id, swatch in self._colour_swatches.items():
            swatch.set_active(colour_id in active_ids)

        for name, fader in self._submaster_faders.items():
            fader.set_value(state.submasters.get(name, 100))

        self._grand_fader.set_value(state.grandmaster)
        self._grand_value.setText(str(state.grandmaster))
        self._sub_fader.set_value(state.sub_master)
        self._sub_value.setText(str(state.sub_master))
        self._strobe_slider.set_value(state.strobe_rate)

        self._sync_toggle(self._strobe_btn, state.strobe_on)
        self._sync_toggle(self._hold_look_btn, state.held_look)
        self._sync_toggle(self._dbo_btn, state.dbo)

        for btn, key, _seconds in self._fade_buttons:
            btn.setChecked(key == state.fade_key)

        self._refresh_programmer()

    @staticmethod
    def _sync_toggle(button: QPushButton, on: bool) -> None:
        if button.isChecked() != on:
            button.blockSignals(True)
            button.setChecked(on)
            button.blockSignals(False)

    def _refresh_programmer(self) -> None:
        state = self.state
        selected = sorted(state.selected)
        if selected:
            groups_txt = " + ".join(selected)
            colour_ids = state.active_colour_ids()
            if colour_ids:
                colours_txt = " · ".join(
                    sorted(self._colour_label(c) for c in colour_ids))
                text = f"PROGRAMMER: {groups_txt} · {colours_txt}"
            else:
                text = f"PROGRAMMER: {groups_txt} · NO COLOUR"
        elif state.colours:
            groups_txt = " + ".join(sorted(state.colours))
            text = f"PROGRAMMER: {groups_txt} (HELD) · RELEASE TO SHOW"
        else:
            text = "PROGRAMMER: EMPTY · SELECT A GROUP · TOUCH A PALETTE"
        self._programmer_label.setText(text)

    @staticmethod
    def _colour_label(colour_id: Optional[str]) -> str:
        for cid, label, _p, _s in COLOUR_SWATCHES:
            if cid == colour_id:
                return label
        return colour_id or "-"

    # -- theme switches --------------------------------------------------

    def changeEvent(self, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.StyleChange:
            for tile in self._select_tiles.values():
                tile._restyle()
            for swatch in self._colour_swatches.values():
                swatch.update()
            for cell in list(self._colour_placeholders.values()):
                if isinstance(cell, _PlaceholderCell):
                    cell._restyle()
            for cell in self._position_cells + self._intensity_cells:
                cell._restyle()
            for fader in self._submaster_faders.values():
                fader.update()
            if hasattr(self, "_pools_host"):
                self._restyle_pools_host()
            accent_line = _active_tokens()["accent_line"]
            for label in self._accent_labels:
                label.setStyleSheet(f"color: {accent_line};")
            # Re-tint submaster columns (data colour top border stays).
            for name, fader in self._submaster_faders.items():
                column = fader.parentWidget()
                if column is not None:
                    self._restyle_submaster_column(
                        column, self._group_colors.get(name, DEFAULT_GROUP_COLOR))
        super().changeEvent(event)
