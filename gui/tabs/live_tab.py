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
- CENTRE - a five-column pool grid: COLOUR PALETTES (fully built) |
  POSITION PALETTES + MOVEMENT SHAPES (placeholder, movers-only) |
  INTENSITY FX (placeholder, cell-fixtures gated) | EFFECTS (riffs from
  the shared RiffLibrary, selection-scoped: greyed with no selection) |
  SCENES (whole-rig looks from the SceneLibrary, always enabled). Below
  it a PROGRAMMER state bar names the current live look.
- RIGHT (330px) - the dual queue: an ACTIVE PLAYBACKS stack (in SHOW
  mode a pinned non-killable show row marked "NO ENGINE YET", then one
  row per running effect/scene with PAUSE/RESUME + KILL; "NOTHING ELSE
  RUNNING" when empty in LIVE mode) and a NEXT UP list (the QUEUE latch
  arms touch-to-enqueue on the EFFECTS/SCENES pools, each queued row has
  a remove X, GO fires the head). Below: a STROBE rate + toggle and
  STROBE KILL / HOLD LOOK / RELEASE ALL (the panic release also clears
  the running stack + staged effect/scene). Paused/killed only mutate
  state - nothing fakes playback.
- BOTTOM (170px) - the submaster fader bank: a GRAND master column
  first (an accent vertical fader with the DBO dead-blackout button
  under it) set off by a thin divider, then one vertical fader per
  group in the group's data colour with a momentary FLASH button.

Honest omissions vs. the reference (surfaces with no in-memory state to
drive them yet): the live 3D render / DMX meters, the
FX-speed/size/white-wash bank slots and the transport clock are
output-engine surfaces, so they are rendered as clearly-marked
placeholders rather than faked. The dual queue is state-only: PAUSE and
KILL mutate records, no output pauses or dies yet. The colour PICKER, SONG
PALETTE link and "+ REC" capture, and the POSITION / MOVEMENT / INTENSITY
pools, are staged for later passes and marked "arrives next".
"""

from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPolygon
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
    QFrame, QPushButton, QLabel, QButtonGroup,
)

from auto.bpm_detector import TapBPM
from config.models import Configuration
from gui.typography import DisplayLabel, MicroLabel, display_font, mono_font

from .base_tab import BaseTab

# Reference geometry.
RIGHT_PANEL_WIDTH = 330
BOTTOM_BANK_HEIGHT = 170
# Each submaster / master column is capped so that with only a couple of
# groups the bank stays readable and left-aligned instead of stretching
# each fader to an absurd width.
SUBMASTER_COLUMN_WIDTH = 120
# Colour-pool swatches are square cells of this side length.
SWATCH_SIZE = 92

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
        # Masters / output scale. The grandmaster now lives as the first
        # column of the submaster bank; there is no separate global sub.
        self.grandmaster: int = 100              # 0-100, all groups
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
        # Tempo reference for rate-based controls (strobe rate, rudiment
        # "1/4" etc.). Free-busk drives it from the TAP cluster; a running
        # show would later sync it. Clamped to the TapBPM range 30-300.
        self.bpm: float = 120.0
        # Busk-on-top mode: the surface is ALWAYS live; "mode" only says
        # whether a predefined show also runs underneath ("show") or not
        # ("live", the default). No engine merges them yet.
        self.mode: str = "live"                  # "show" | "live"
        # Library-backed staging. An effect is a riff (key "category/name")
        # scoped to the current SELECT state; a scene is a whole-rig look
        # (key "category/name") independent of the selection. Both toggle;
        # neither is tied to the group set, so update_from_config leaves
        # them alone (like bpm / mode).
        self.effect: Optional[str] = None        # staged riff key
        self.scene: Optional[str] = None         # staged scene key
        # Dual queue. ``running`` is the running-playbacks stack - plain
        # dict records {"kind": "effect"|"scene", "key", "label",
        # "paused"} mirroring the single active effect/scene (at most one
        # record per kind, rendered as individual playback rows).
        # ``next_up`` holds preloaded records (same shape, no "paused")
        # staged via enqueue(); fire_next() (GO) pops the head and
        # applies it. Both survive update_from_config (like bpm / mode).
        # Paused/killed are state-only until the output engine lands.
        self.running: List[dict] = []
        self.next_up: List[dict] = []

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
        """Panic release: clear the programmer (applied colours + staged
        + selection) AND the running playbacks (staged effect/scene +
        the running stack), releasing the rig to the show. The next_up
        queue is deliberately kept - it is preloaded, not output."""
        self.colours.clear()
        self.staged_colour = None
        self.selected.clear()
        self.effect = None
        self.scene = None
        self.running.clear()
        self.state_changed.emit()

    # -- masters / output scale -----------------------------------------
    def set_grandmaster(self, level: int) -> None:
        self.grandmaster = max(0, min(100, int(level)))
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
        Otherwise the scale is grandmaster x per-group submaster (each
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
        return (self.grandmaster / 100.0) * (self.submasters[group] / 100.0)

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

    # -- tempo / mode ---------------------------------------------------
    def set_bpm(self, value: float) -> None:
        """Set the tempo reference, clamped to the TapBPM range 30-300."""
        self.bpm = max(30.0, min(300.0, float(value)))
        self.state_changed.emit()

    def set_mode(self, mode: str) -> None:
        """Set busk-on-top mode ("show" runs a predefined show underneath;
        "live" has nothing else running). Anything but "show" reads live."""
        self.mode = "show" if mode == "show" else "live"
        self.state_changed.emit()

    # -- library staging (effects / scenes) -----------------------------
    def set_effect(self, key: Optional[str]) -> None:
        """Toggle the staged effect (a riff, selection-scoped). Touching
        the same key again clears it. Mirrors into the running stack."""
        self.effect = None if key == self.effect else key
        self._sync_running("effect", self.effect)
        self.state_changed.emit()

    def set_scene(self, key: Optional[str]) -> None:
        """Toggle the staged scene (a whole-rig look, selection-agnostic).
        Touching the same key again clears it. Mirrors into the running
        stack."""
        self.scene = None if key == self.scene else key
        self._sync_running("scene", self.scene)
        self.state_changed.emit()

    def _sync_running(self, kind: str, key: Optional[str]) -> None:
        """Mirror the single active effect/scene into the running stack:
        at most one record per kind; staging replaces/creates it, clearing
        removes it. Silent - the calling mutator emits."""
        index = next((i for i, rec in enumerate(self.running)
                      if rec["kind"] == kind), None)
        if key is None:
            if index is not None:
                del self.running[index]
            return
        record = {"kind": kind, "key": key,
                  "label": key.split("/")[-1], "paused": False}
        if index is None:
            self.running.append(record)
        else:
            self.running[index] = record

    # -- dual queue (running stack + next-up list) ----------------------
    def enqueue(self, kind: str, key: str, label: str) -> None:
        """Stage a record in the next-up list (repeats allowed)."""
        kind = "scene" if kind == "scene" else "effect"
        self.next_up.append({"kind": kind, "key": key, "label": label})
        self.state_changed.emit()

    def remove_queued(self, index: int) -> None:
        """Drop a next-up record by position."""
        if 0 <= index < len(self.next_up):
            del self.next_up[index]
            self.state_changed.emit()

    def fire_next(self) -> None:
        """GO: pop the head of next_up and apply it live via
        set_effect/set_scene. Applies, never toggles - firing a key that
        is already running keeps it running."""
        if not self.next_up:
            return
        record = self.next_up.pop(0)
        if record["kind"] == "scene":
            if record["key"] != self.scene:
                self.set_scene(record["key"])
                return
        else:
            if record["key"] != self.effect:
                self.set_effect(record["key"])
                return
        self.state_changed.emit()

    def kill_playback(self, index: int) -> None:
        """Remove a running record and clear the matching staged
        effect/scene (state-only - no output engine yet)."""
        if not 0 <= index < len(self.running):
            return
        record = self.running.pop(index)
        if record["kind"] == "scene":
            self.scene = None
        else:
            self.effect = None
        self.state_changed.emit()

    def toggle_pause(self, index: int) -> None:
        """Flip a running record's paused flag. Honest: state-only until
        the output engine lands - nothing actually pauses."""
        if not 0 <= index < len(self.running):
            return
        self.running[index]["paused"] = not self.running[index]["paused"]
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

    The cell is a fixed square (:data:`SWATCH_SIZE` on a side) so the pool
    reads as a tidy grid of squares rather than stretched rectangles.
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
        self.setFixedSize(SWATCH_SIZE, SWATCH_SIZE)
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
        # 10pt (not 12): the longest single-word labels (WATERFALL) must
        # fit a 2-column grid cell in the narrow five-column centre, and
        # word wrap cannot split a single word.
        self.label = DisplayLabel(label, point_size=10,
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


class _LibraryCell(QWidget):
    """A clickable pool cell for a library item (an effect riff or a scene).

    Shows the item name and, for scenes, an optional small colour chip
    when the item carries a display colour. An accent outline (token
    ``accent_line``) marks the active item; touching emits ``clicked``
    with the item's "category/name" key. Greying is driven by the pool's
    ``setEnabled`` - the cell restyles to the disabled palette when its
    enabled state changes (effects pool greys out with no selection).

    Colours come from :func:`_active_tokens` (never hardcoded) via
    ``_restyle``; the same restyle runs on a theme switch.
    """

    clicked = pyqtSignal(str)

    def __init__(self, item_key: str, label: str,
                 chip_color: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.item_key = item_key
        self._chip_color = chip_color
        self._active = False
        self.setObjectName("LiveLibraryCell")
        self.setProperty("role", "card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(84, 46)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)
        self._chip = None
        if chip_color:
            chip = QWidget()
            chip.setObjectName("LiveLibraryChip")
            chip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            chip.setFixedHeight(4)
            chip.setStyleSheet(
                f"#LiveLibraryChip {{ background-color: {chip_color}; }}")
            layout.addWidget(chip)
            self._chip = chip
        self.name_label = DisplayLabel(label, point_size=11,
                                       weight=QFont.Weight.Bold,
                                       tracking_em=0.03)
        self.name_label.setMinimumWidth(1)
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label)
        layout.addStretch(1)
        self._restyle()

    def is_active(self) -> bool:
        return self._active

    def set_active(self, active: bool) -> None:
        active = bool(active)
        if active != self._active:
            self._active = active
            self.setProperty("selected", active)
            self._restyle()

    def _restyle(self) -> None:
        tokens = _active_tokens()
        if not self.isEnabled():
            border = tokens["border"]
            text_color = tokens["text_disabled"]
        else:
            border = tokens["accent_line"] if self._active else tokens["border"]
            text_color = tokens["text"]
        self.setStyleSheet(
            "#LiveLibraryCell {"
            f" background-color: {tokens['panel']};"
            f" border: 1px solid {border}; }}")
        self.name_label.setStyleSheet(
            f"color: {text_color}; background: transparent;")

    def changeEvent(self, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.EnabledChange:
            self._restyle()
        super().changeEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.item_key)


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
        # Tap-tempo estimator (shared class with the Auto tab): tap()
        # returns the running BPM estimate or None (< 3 taps), reset()
        # clears the tap history.
        self._tap_bpm = TapBPM()
        self._select_tiles: Dict[str, _SelectTile] = {}
        self._colour_swatches: Dict[str, _ColourSwatch] = {}
        self._colour_placeholders: Dict[str, QWidget] = {}
        self._position_cells: List[_PlaceholderCell] = []
        self._intensity_cells: List[_PlaceholderCell] = []
        # Library-backed pools (wired to the shared RiffLibrary and a new
        # SceneLibrary; injected by gui.py, lazily resolved otherwise).
        self._effect_library = None
        self._scene_library = None
        self._effect_cells: Dict[str, _LibraryCell] = {}
        self._scene_cells: Dict[str, _LibraryCell] = {}
        self._fade_buttons: List[Tuple[QPushButton, str, Optional[float]]] = []
        # Dual-queue rows (rebuilt on every state sync).
        self._pause_buttons: List[QPushButton] = []
        self._kill_buttons: List[QPushButton] = []
        self._queue_remove_buttons: List[QPushButton] = []
        self._pinned_show_label: Optional[QLabel] = None
        self._pinned_show_marker: Optional[QLabel] = None
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

        # SHOW / LIVE busk-on-top toggle (top-left, by SELECT). Exclusive
        # segment; the surface is always live, the mode only says whether a
        # predefined show also runs underneath. Default LIVE.
        hbox.addWidget(MicroLabel("Mode", point_size=8, tracking_em=0.12))
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._show_mode_btn = self._mode_chip("SHOW", "show",
            "Run a predefined show underneath the live surface (merge "
            "arrives with the output engine)")
        self._live_mode_btn = self._mode_chip("LIVE", "live",
            "Free-busk: nothing else runs underneath the live surface")
        hbox.addWidget(self._show_mode_btn)
        hbox.addWidget(self._live_mode_btn)
        hbox.addSpacing(8)

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

    def _mode_chip(self, text: str, mode: str, tip: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setProperty("role", "output-select")
        btn.setFont(mono_font(8, QFont.Weight.DemiBold))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(tip)
        self._mode_group.addButton(btn)
        btn.clicked.connect(lambda _checked=False, m=mode: self.state.set_mode(m))
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

        # Tempo cluster (right end): a BPM readout + TAP + RESET. This is
        # the reference tempo for the rate-based controls (strobe rate, the
        # rudiment "1/4"); this pass only surfaces and stores it.
        hbox.addWidget(MicroLabel("Tempo", point_size=8, tracking_em=0.12))
        self._bpm_display = QLabel(f"{self.state.bpm:.1f} BPM")
        self._bpm_display.setProperty("role", "micro")
        self._bpm_display.setFont(mono_font(10, QFont.Weight.DemiBold))
        self._bpm_display.setToolTip("Tempo reference for rate controls "
                                     "(strobe rate, rudiments)")
        hbox.addWidget(self._bpm_display)

        self._tap_btn = QPushButton("TAP")
        self._tap_btn.setProperty("role", "output-select")
        self._tap_btn.setFont(mono_font(8, QFont.Weight.DemiBold))
        self._tap_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tap_btn.setToolTip("Tap in time to set the tempo")
        self._tap_btn.clicked.connect(self._on_tap_tempo)
        hbox.addWidget(self._tap_btn)

        self._tap_reset_btn = QPushButton("RESET")
        self._tap_reset_btn.setProperty("role", "output-select")
        self._tap_reset_btn.setFont(mono_font(8, QFont.Weight.Medium))
        self._tap_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tap_reset_btn.setToolTip("Clear the tap history (keeps the "
                                       "current BPM)")
        self._tap_reset_btn.clicked.connect(self._on_reset_tempo)
        hbox.addWidget(self._tap_reset_btn)
        return row

    def _on_tap_tempo(self) -> None:
        """Register a tap; if the estimator has enough taps for a reading,
        store it as the tempo reference (which re-syncs the readout)."""
        bpm = self._tap_bpm.tap()
        if bpm is not None:
            self.state.set_bpm(bpm)

    def _on_reset_tempo(self) -> None:
        """Clear the tap history. The stored BPM is deliberately kept so a
        reset does not blank the reference mid-show; the next tap builds a
        fresh estimate."""
        self._tap_bpm.reset()

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
        self._effects_pool = self._build_effects_pool()
        self._scenes_pool = self._build_scenes_pool()
        # Five narrower columns: COLOUR · POSITION · INTENSITY-FX · EFFECTS
        # · SCENES. The COLOUR pool holds a fixed-width 3-wide swatch grid
        # (~316px minimum), so it gets the largest stretch; the four
        # text-cell pools compress fine as 2-column grids and share the
        # rest. Tuned so all five fit at 1600x900 (centre ~1270px) with no
        # horizontal overflow.
        hbox.addWidget(self._colour_pool, 15)
        hbox.addWidget(self._position_pool, 11)
        hbox.addWidget(self._intensity_pool, 11)
        hbox.addWidget(self._effects_pool, 11)
        hbox.addWidget(self._scenes_pool, 11)
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
        # Wrap instead of truncating - the five-column centre is narrow
        # and a silently clipped marker reads as garbage.
        label.setWordWrap(True)
        label.setContentsMargins(14, 0, 14, 6)
        return label

    def _build_colour_pool(self) -> QWidget:
        pool, layout = self._pool_shell()
        layout.addWidget(self._pool_header("Colour palettes"))

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(14, 0, 14, 12)
        grid.setSpacing(6)
        # Three columns so the fixed-square swatch grid stays narrow enough
        # to sit in one of five centre columns at 1600x900.
        columns = 3
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
        # Left-align the square block: a phantom trailing column soaks up
        # the slack so the real columns stay at the swatch's fixed width.
        grid.setColumnStretch(columns, 1)
        layout.addWidget(grid_host)
        layout.addStretch(1)
        return pool

    def _build_position_pool(self) -> QWidget:
        pool, layout = self._pool_shell()
        # Tag kept short ("Movers only", not "Applies to: movers") - the
        # narrow five-column header truncates longer tags silently.
        layout.addWidget(self._pool_header(
            "Position palettes", "Movers only", tag_accent=True))
        layout.addWidget(self._marker("Arrives next"))

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(14, 0, 14, 10)
        grid.setSpacing(6)
        columns = 2
        for i, name in enumerate(POSITION_PLACEHOLDERS):
            cell = _PlaceholderCell(name)
            self._position_cells.append(cell)
            grid.addWidget(cell, i // columns, i % columns)
        for col in range(columns):
            grid.setColumnStretch(col, 1)
        layout.addWidget(grid_host)

        layout.addWidget(self._pool_header("Movement shapes"))
        # A 2-per-row grid (like the palettes above), not one packed row:
        # five cells side by side in a fifth of the centre truncate their
        # labels to slivers at 1600x900.
        shapes_host = QWidget()
        shape_grid = QGridLayout(shapes_host)
        shape_grid.setContentsMargins(14, 0, 14, 12)
        shape_grid.setSpacing(6)
        shape_columns = 2
        for i, name in enumerate(MOVEMENT_PLACEHOLDERS):
            cell = _PlaceholderCell(name)
            cell.setMinimumSize(84, 34)
            self._position_cells.append(cell)
            shape_grid.addWidget(cell, i // shape_columns, i % shape_columns)
        for col in range(shape_columns):
            shape_grid.setColumnStretch(col, 1)
        layout.addWidget(shapes_host)
        layout.addStretch(1)
        return pool

    def _build_intensity_pool(self) -> QWidget:
        pool, layout = self._pool_shell()
        # Title shortened from "Rudiments · Intensity FX" so the Rate tag
        # fits beside it in the narrow five-column header.
        layout.addWidget(self._pool_header("Intensity FX", "Rate 1/4"))
        layout.addWidget(self._marker("Arrives next"))

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(14, 0, 14, 8)
        grid.setSpacing(6)
        columns = 2
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
        layout.addWidget(self._marker("Greyed = needs cell fixtures"))
        layout.addStretch(1)
        return pool

    # -- library pools (effects / scenes) --------------------------------

    def _build_effects_pool(self) -> QWidget:
        """EFFECTS pool: riffs from the shared RiffLibrary. Selection-scoped
        - the whole pool greys out when nothing is selected (an effect
        applies to the current SELECT state)."""
        pool, layout = self._pool_shell()
        layout.addWidget(self._pool_header(
            "Effects", "Applies to: selection", tag_accent=True))
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(14, 0, 14, 10)
        grid.setSpacing(6)
        self._effects_grid = grid
        layout.addWidget(grid_host)
        layout.addStretch(1)
        self._populate_effects_pool()
        return pool

    def _build_scenes_pool(self) -> QWidget:
        """SCENES pool: whole-rig looks from the SceneLibrary. Always
        enabled - a scene spans multiple groups, independent of the
        current selection."""
        pool, layout = self._pool_shell()
        layout.addWidget(self._pool_header("Scenes", "Whole rig"))
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(14, 0, 14, 10)
        grid.setSpacing(6)
        self._scenes_grid = grid
        layout.addWidget(grid_host)
        layout.addStretch(1)
        self._populate_scenes_pool()
        return pool

    @staticmethod
    def _clear_grid(grid: QGridLayout) -> None:
        while grid.count():
            item = grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _empty_riff_library(self):
        """A quiet empty RiffLibrary (never crashes). Used when no library
        is injected and the window has none."""
        from riffs.riff_library import RiffLibrary
        lib = RiffLibrary()
        lib.riffs = {}
        lib.by_category = {}
        return lib

    def _resolve_effect_library(self):
        if self._effect_library is not None:
            return self._effect_library
        window = self.window()
        lib = getattr(window, "riff_library", None) if window is not None \
            else None
        self._effect_library = lib if lib is not None \
            else self._empty_riff_library()
        return self._effect_library

    def _resolve_scene_library(self):
        if self._scene_library is not None:
            return self._scene_library
        window = self.window()
        lib = getattr(window, "scene_library", None) if window is not None \
            else None
        if lib is None:
            from scenes.scene_library import SceneLibrary
            lib = SceneLibrary()
        self._scene_library = lib
        return self._scene_library

    def _populate_effects_pool(self) -> None:
        self._clear_grid(self._effects_grid)
        self._effect_cells = {}
        library = self._resolve_effect_library()
        riffs = library.get_all_riffs() if library is not None else []
        if not riffs:
            self._effects_grid.addWidget(
                self._marker("No effects yet · save riffs from the timeline"),
                0, 0, 1, 2)
            return
        columns = 2
        for i, riff in enumerate(riffs):
            key = f"{riff.category}/{riff.name}"
            cell = _LibraryCell(key, riff.name)
            cell.clicked.connect(self._on_effect_touched)
            self._effect_cells[key] = cell
            self._effects_grid.addWidget(cell, i // columns, i % columns)
        for col in range(columns):
            self._effects_grid.setColumnStretch(col, 1)

    def _populate_scenes_pool(self) -> None:
        self._clear_grid(self._scenes_grid)
        self._scene_cells = {}
        library = self._resolve_scene_library()
        scenes = library.get_all_scenes() if library is not None else []
        if not scenes:
            self._scenes_grid.addWidget(
                self._marker("No scenes yet · predefined looks arrive later"),
                0, 0, 1, 2)
            return
        columns = 2
        for i, scene in enumerate(scenes):
            key = f"{scene.category}/{scene.name}"
            chip = scene.color if scene.color else None
            cell = _LibraryCell(key, scene.name, chip_color=chip)
            cell.clicked.connect(self._on_scene_touched)
            self._scene_cells[key] = cell
            self._scenes_grid.addWidget(cell, i // columns, i % columns)
        for col in range(columns):
            self._scenes_grid.setColumnStretch(col, 1)

    def set_effect_library(self, library) -> None:
        """Inject the shared RiffLibrary and rebuild the EFFECTS pool."""
        self._effect_library = library if library is not None \
            else self._empty_riff_library()
        self._populate_effects_pool()
        self._sync_from_state()

    def set_scene_library(self, library) -> None:
        """Inject the SceneLibrary and rebuild the SCENES pool."""
        if library is None:
            from scenes.scene_library import SceneLibrary
            library = SceneLibrary()
        self._scene_library = library
        self._populate_scenes_pool()
        self._sync_from_state()

    def _on_colour_touched(self, colour_id: str) -> None:
        # Colour swatches stay fire-only this pass: the QUEUE latch only
        # covers EFFECTS and SCENES cells (queueing colours can come
        # later once a queued colour has a defined target selection).
        self.state.stage_colour(colour_id)

    def _on_effect_touched(self, key: str) -> None:
        """Latched QUEUE stages the effect in next_up (cell stays
        inactive); unlatched fires it live via the toggle."""
        if self._queue_latch_btn.isChecked():
            self.state.enqueue("effect", key, self._key_name(key))
        else:
            self.state.set_effect(key)

    def _on_scene_touched(self, key: str) -> None:
        """Latched QUEUE stages the scene in next_up; unlatched fires."""
        if self._queue_latch_btn.isChecked():
            self.state.enqueue("scene", key, self._key_name(key))
        else:
            self.state.set_scene(key)

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

    # -- RIGHT: playbacks, strobe, kills ---------------------------------

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("LiveMasterPanel")
        panel.setProperty("role", "inspector")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setFixedWidth(RIGHT_PANEL_WIDTH)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        # ACTIVE PLAYBACKS: the running stack. In SHOW mode a pinned,
        # non-killable show row sits on top (honestly marked - there is
        # no output engine yet); then one row per running record with
        # PAUSE/RESUME + KILL. Rows are rebuilt in _refresh_playback_rows.
        layout.addWidget(MicroLabel("Active playbacks", point_size=8,
                                    tracking_em=0.14))
        self._playbacks_host = QWidget()
        self._playbacks_box = QVBoxLayout(self._playbacks_host)
        self._playbacks_box.setContentsMargins(0, 0, 0, 0)
        self._playbacks_box.setSpacing(6)
        layout.addWidget(self._playbacks_host)

        self._active_playbacks_label = QLabel("NOTHING ELSE RUNNING")
        self._active_playbacks_label.setProperty("role", "hint-box")
        self._active_playbacks_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._active_playbacks_label.setFont(mono_font(8, tracking_em=0.1))
        self._active_playbacks_label.setWordWrap(True)
        self._active_playbacks_label.setToolTip(
            "Fired effects and scenes stack here; actual output arrives "
            "with the engine pass")
        layout.addWidget(self._active_playbacks_label)

        # NEXT UP: the preloaded queue + the QUEUE arm latch beside the
        # caption. Latched, touching an EFFECTS or SCENES cell stages it
        # here instead of firing it; GO pops the head and fires it live.
        next_caption = QHBoxLayout()
        next_caption.setSpacing(8)
        next_caption.addWidget(MicroLabel("Next up", point_size=8,
                                          tracking_em=0.14))
        next_caption.addStretch(1)
        self._queue_latch_btn = QPushButton("QUEUE")
        self._queue_latch_btn.setCheckable(True)
        self._queue_latch_btn.setProperty("role", "output-select")
        self._queue_latch_btn.setFont(mono_font(8, QFont.Weight.DemiBold))
        self._queue_latch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._queue_latch_btn.setToolTip(
            "Latch, then touch an EFFECTS or SCENES cell to stage it in "
            "NEXT UP instead of firing it live · unlatch to fire live "
            "again (colour swatches always fire live)")
        next_caption.addWidget(self._queue_latch_btn)
        layout.addLayout(next_caption)

        self._next_up_host = QWidget()
        self._next_up_box = QVBoxLayout(self._next_up_host)
        self._next_up_box.setContentsMargins(0, 0, 0, 0)
        self._next_up_box.setSpacing(6)
        layout.addWidget(self._next_up_host)

        self._queue_empty_hint = QLabel(
            "QUEUE EMPTY · LATCH QUEUE THEN TOUCH A PALETTE")
        self._queue_empty_hint.setProperty("role", "hint-box")
        self._queue_empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._queue_empty_hint.setFont(mono_font(8, tracking_em=0.1))
        self._queue_empty_hint.setWordWrap(True)
        layout.addWidget(self._queue_empty_hint)

        self._go_btn = QPushButton("GO")
        self._go_btn.setProperty("role", "cta-accent")
        self._go_btn.setFont(display_font(14, QFont.Weight.Bold,
                                          tracking_em=0.08))
        self._go_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._go_btn.setToolTip("Fire the first NEXT UP item live")
        self._go_btn.setEnabled(False)
        self._go_btn.clicked.connect(self.state.fire_next)
        layout.addWidget(self._go_btn)

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
            "Panic release: clear the programmer and the running "
            "playbacks (the NEXT UP queue is kept)")
        self._release_all_btn.clicked.connect(self.state.release_all)
        kills_row.addWidget(self._release_all_btn, 1)
        layout.addLayout(kills_row)

        layout.addStretch(1)
        # GRAND + the DBO dead-blackout now live as the first column of
        # the bottom submaster bank (see _make_master_column), so the
        # right panel keeps only playbacks, strobe and the kills.
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
            "GRAND + one fader per group · FLASH is momentary",
            point_size=7, tracking_em=0.08))
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

    def _make_master_column(self) -> QWidget:
        """The GRAND master column: an accent vertical fader with the DBO
        dead-blackout button under it. Always the first column of the
        bank, set off from the per-group columns by a thin divider."""
        accent = _active_tokens()["accent"]
        column = QWidget()
        column.setObjectName("LiveMasterColumn")
        column.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        column.setMaximumWidth(SUBMASTER_COLUMN_WIDTH)
        self._grand_column = column
        col_layout = QVBoxLayout(column)
        col_layout.setContentsMargins(6, 6, 6, 6)
        col_layout.setSpacing(4)

        name_label = MicroLabel("GRAND", point_size=8, tracking_em=0.06)
        name_label.setMinimumWidth(1)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col_layout.addWidget(name_label)

        fader = _VerticalFader(accent)
        fader.value_changed.connect(self.state.set_grandmaster)
        col_layout.addWidget(fader, 1, Qt.AlignmentFlag.AlignHCenter)
        self._grand_fader = fader

        dbo = QPushButton("DBO")
        dbo.setCheckable(True)
        dbo.setProperty("role", "destructive")
        dbo.setFont(mono_font(8, QFont.Weight.DemiBold))
        dbo.setCursor(Qt.CursorShape.PointingHandCursor)
        dbo.setToolTip("Dead blackout - zero all output")
        dbo.toggled.connect(self.state.set_dbo)
        col_layout.addWidget(dbo)
        self._dbo_btn = dbo

        self._restyle_master_column(column, accent)
        return column

    def _make_bank_divider(self) -> QWidget:
        """A 1px vertical rule separating the GRAND master column from the
        per-group submaster columns."""
        divider = QWidget()
        divider.setObjectName("LiveBankDivider")
        divider.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        divider.setFixedWidth(1)
        self._bank_divider = divider
        self._restyle_bank_divider(divider)
        return divider

    def _restyle_bank_divider(self, divider: QWidget) -> None:
        tokens = _active_tokens()
        divider.setStyleSheet(
            f"#LiveBankDivider {{ background-color: {tokens['border']}; }}")

    def _restyle_master_column(self, column: QWidget, accent: str) -> None:
        tokens = _active_tokens()
        column.setStyleSheet(
            "#LiveMasterColumn {"
            f" background-color: {tokens['panel']};"
            f" border: 1px solid {tokens['border']};"
            f" border-top: 3px solid {accent}; }}")

    def _make_submaster_column(self, name: str, color: str) -> QWidget:
        column = QWidget()
        column.setObjectName("LiveSubmasterColumn")
        column.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        column.setProperty("_group_color", color)
        column.setMaximumWidth(SUBMASTER_COLUMN_WIDTH)
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
        # GRAND + DBO master column first, then a divider, then one bounded
        # column per group; a trailing stretch left-aligns the bank so few
        # groups do not stretch the columns to a comical width.
        self._bank_layout.addWidget(self._make_master_column())
        self._bank_layout.addWidget(self._make_bank_divider())
        self._bank_layout.addWidget(self._bank_empty_hint)
        for name in group_names:
            self._bank_layout.addWidget(
                self._make_submaster_column(name, self._group_colors[name]))
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

        # EFFECTS: selection-scoped. Grey the whole pool with no selection,
        # then outline the active effect. SCENES: whole-rig, always enabled.
        self._effects_pool.setEnabled(bool(state.selected))
        for key, cell in self._effect_cells.items():
            cell.set_active(key == state.effect)
        for key, cell in self._scene_cells.items():
            cell.set_active(key == state.scene)

        for name, fader in self._submaster_faders.items():
            fader.set_value(state.submasters.get(name, 100))

        self._grand_fader.set_value(state.grandmaster)
        self._strobe_slider.set_value(state.strobe_rate)

        self._sync_toggle(self._strobe_btn, state.strobe_on)
        self._sync_toggle(self._hold_look_btn, state.held_look)
        self._sync_toggle(self._dbo_btn, state.dbo)

        for btn, key, _seconds in self._fade_buttons:
            btn.setChecked(key == state.fade_key)

        self._bpm_display.setText(f"{state.bpm:.1f} BPM")
        self._sync_toggle(self._show_mode_btn, state.mode == "show")
        self._sync_toggle(self._live_mode_btn, state.mode == "live")
        self._refresh_playback_rows()

        self._refresh_programmer()

    # -- dual-queue rows (rebuilt on every state sync) --------------------

    @staticmethod
    def _clear_box(box: QVBoxLayout) -> None:
        while box.count():
            item = box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _row_shell(self) -> Tuple[QWidget, QHBoxLayout]:
        """A playback/queue row: a card with a compact horizontal layout."""
        row = QWidget()
        row.setProperty("role", "card")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hbox = QHBoxLayout(row)
        hbox.setContentsMargins(8, 6, 8, 6)
        hbox.setSpacing(6)
        return row, hbox

    def _row_text(self, hbox: QHBoxLayout, label: str,
                  tag: str) -> Tuple[QLabel, QLabel]:
        """Name + kind tag stacked in the row's stretching text column."""
        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        name = QLabel(label.upper())
        name.setFont(mono_font(8, QFont.Weight.DemiBold))
        name.setMinimumWidth(1)
        name.setWordWrap(True)
        text_col.addWidget(name)
        tag_label = MicroLabel(tag, point_size=7, tracking_em=0.1)
        tag_label.setMinimumWidth(1)
        tag_label.setWordWrap(True)
        text_col.addWidget(tag_label)
        hbox.addLayout(text_col, 1)
        return name, tag_label

    def _row_button(self, text: str, role: str, tip: str) -> QPushButton:
        # No fixed width: the theme's 14px QPushButton padding sizes the
        # button from its text, so the glyph can never clip (CLAUDE.md).
        btn = QPushButton(text)
        btn.setProperty("role", role)
        btn.setFont(mono_font(8, QFont.Weight.Medium))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(tip)
        return btn

    def _make_pinned_show_row(self) -> QWidget:
        """SHOW mode's pinned, non-killable show row. Honest: no output
        engine yet, so the show named here does not actually run."""
        shows = getattr(self.config, "shows", {}) or {}
        name = next(iter(shows), None)
        row, hbox = self._row_shell()
        self._pinned_show_label, self._pinned_show_marker = self._row_text(
            hbox, name if name else "SHOW",
            "Show mode · pinned · no engine yet")
        return row

    def _make_running_row(self, index: int, record: dict) -> QWidget:
        row, hbox = self._row_shell()
        tag = "FX" if record["kind"] == "effect" else "SCENE"
        self._row_text(hbox, record["label"],
                       f"{tag} · PAUSED" if record["paused"] else tag)
        pause = self._row_button(
            "RESUME" if record["paused"] else "PAUSE", "output-select",
            "Pause flag only - actual output pause arrives with the "
            "engine pass")
        pause.clicked.connect(
            lambda _checked=False, i=index: self.state.toggle_pause(i))
        hbox.addWidget(pause)
        self._pause_buttons.append(pause)
        kill = self._row_button(
            "KILL", "destructive",
            "Remove this playback and clear its staged state")
        kill.clicked.connect(
            lambda _checked=False, i=index: self.state.kill_playback(i))
        hbox.addWidget(kill)
        self._kill_buttons.append(kill)
        return row

    def _make_queued_row(self, index: int, record: dict) -> QWidget:
        row, hbox = self._row_shell()
        tag = "FX" if record["kind"] == "effect" else "SCENE"
        self._row_text(hbox, record["label"], tag)
        remove = self._row_button("X", "output-select",
                                  "Remove this item from the queue")
        remove.clicked.connect(
            lambda _checked=False, i=index: self.state.remove_queued(i))
        hbox.addWidget(remove)
        self._queue_remove_buttons.append(remove)
        return row

    def _refresh_playback_rows(self) -> None:
        """Rebuild the ACTIVE PLAYBACKS stack and the NEXT UP queue rows
        from state. In SHOW mode a pinned show row leads the stack; the
        empty hints show when nothing runs (LIVE mode) / nothing is
        queued; GO is enabled only with a queue head to fire."""
        state = self.state
        self._clear_box(self._playbacks_box)
        self._pause_buttons = []
        self._kill_buttons = []
        self._pinned_show_label = None
        self._pinned_show_marker = None
        if state.mode == "show":
            self._playbacks_box.addWidget(self._make_pinned_show_row())
        for index, record in enumerate(state.running):
            self._playbacks_box.addWidget(
                self._make_running_row(index, record))
        self._active_playbacks_label.setVisible(
            not state.running and state.mode != "show")

        self._clear_box(self._next_up_box)
        self._queue_remove_buttons = []
        for index, record in enumerate(state.next_up):
            self._next_up_box.addWidget(self._make_queued_row(index, record))
        self._queue_empty_hint.setVisible(not state.next_up)
        self._go_btn.setEnabled(bool(state.next_up))

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
        if state.effect:
            text += f" · FX: {self._key_name(state.effect).upper()}"
        if state.scene:
            text += f" · SCENE: {self._key_name(state.scene).upper()}"
        self._programmer_label.setText(text)

    @staticmethod
    def _key_name(key: Optional[str]) -> str:
        """The display name from a "category/name" library key."""
        if not key:
            return "-"
        return key.split("/")[-1]

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
            for cell in list(self._effect_cells.values()) + \
                    list(self._scene_cells.values()):
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
            # Re-tint the GRAND master column + divider in the new accent.
            accent = _active_tokens()["accent"]
            if getattr(self, "_grand_column", None) is not None:
                self._restyle_master_column(self._grand_column, accent)
            if getattr(self, "_grand_fader", None) is not None:
                self._grand_fader.set_color(accent)
            if getattr(self, "_bank_divider", None) is not None:
                self._restyle_bank_divider(self._bank_divider)
        super().changeEvent(event)
