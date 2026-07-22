"""LiveTab - the touch-palette busking surface, built to the reference
docs/design/screens/09-live-3b-palette.html (layout
"3b").

This is a UI shell wired to an in-memory :class:`LiveState`; every
interaction mutates ``LiveState`` and emits ``LiveState.state_changed``.
Since the output-arbiter pass (docs/output-sync-plan.md phase 3) the
busk surface makes real light: utils/artnet/live_layer.py renders the
applied colours, submaster levels, flash and strobe as the arbiter's
LIVE layer whenever ArtNet output is enabled, riding on top of
whatever plays underneath (busk-on-top); the Live grandmaster and DBO
drive the arbiter's post-merge master stage, capping playback too.
The resolve stays a pure function of the state plus the fixture patch
(see :meth:`LiveState.group_level` / :meth:`group_level_local`).

Regions (North Star 3b):

- TOP - a SELECT row (one tile per fixture group + ALL / ODD-EVEN
  quick-select + CLEAR SEL) and a FADE row (SNAP / 0.5s / 2s / 4s /
  1 BAR / 4 BARS as output-select chips). Touch a palette and the
  selection "fades" to it over the chosen time (recorded, not animated).
- CENTRE - a five-column pool grid: COLOUR PALETTES (fully built) |
  POSITION PALETTES (a PRESETS subsection of targets computed from the
  stage setup via utils/position_presets.py, then a MARKS subsection
  with one cell per ``config.spots`` spike mark; movers-only gated as a
  whole) + MOVEMENT SHAPES (the registry rudiments, movers-only) |
  INTENSITY FX (bundled dimmer riffs, selection-scoped) | EFFECTS
  (riffs from the shared RiffLibrary, selection-scoped: greyed with no
  selection) |
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

Honest omissions vs. the reference: the live 3D render / DMX meters,
the FX-speed/size/white-wash bank slots and the transport clock are
still placeholders. SCENES make real light (the busk layer renders the
active scene's colour on its listed groups, below explicit swatches);
EFFECTS play riffs through the live engine (one lane per selected
group on the looping beat clock; PAUSE/KILL/GO are real); MOVEMENT
SHAPES loop the registry rudiments on the selected mover groups,
anchored at each group's held position; INTENSITY FX loops the
bundled dimmer riffs on its own concurrent slot; POSITION PALETTES
aim for real (16-bit pan/tilt claims). The colour PICKER, SONG
PALETTE link and "+ REC" capture are staged for later passes and
marked "arrives next".
"""

from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPolygon
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
    QFrame, QPushButton, QLabel, QButtonGroup, QComboBox,
)

from auto.bpm_detector import TapBPM
from config.models import Configuration
from gui.typography import DisplayLabel, MicroLabel, display_font, mono_font
from utils.position_presets import (
    ELEMENT_PRESET_PREFIX, KIND_POINT, MARK_PREFIX, PRESET_PREFIX,
    compute_presets, element_preset_ids, group_has_movers, mark_id,
    mark_name,
)

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
# The tempo RESET target and LiveState's starting bpm.
DEFAULT_LIVE_BPM = 120.0

# MOVEMENT SHAPES: the effects/movement_effects.MOVEMENT_REGISTRY
# rudiments (minus "static" - the POSITION palettes above ARE the
# static aim). Ids are registry keys; the live engine's movement
# binder replays the touched shape anchored at each group's held
# position (docs/live-output-plan.md phase 4).
MOVEMENT_SHAPES: Tuple[Tuple[str, str], ...] = (
    ("circle", "Circle"),
    ("figure_8", "Fig-8"),
    ("diamond", "Diamond"),
    ("square", "Square"),
    ("triangle", "Triangle"),
    ("lissajous", "Lissajous"),
    ("linear_sweep", "Sweep"),
    ("bounce", "Bounce"),
    ("random", "Random"),
    ("fan", "Fan"),
)
# INTENSITY FX: the riff-library category the pool lists (bundled
# dimmer-only riffs in riffs/intensity/). Staged on the engine's own
# "intensity" slot, concurrent with a colour riff from EFFECTS.
INTENSITY_CATEGORY = "intensity"

# Movement-shape orbit sizes (label, radius in meters) - the shapes
# trace in stage space around their anchor, so size is physical.
SHAPE_SIZES: Tuple[Tuple[str, float], ...] = (
    ("S", 0.4),
    ("M", 0.75),
    ("L", 1.5),
)
DEFAULT_SHAPE_SIZE_M = 0.75


def _display_name(raw: Optional[str]) -> str:
    """Human-readable label for a library item name. Riff and scene
    names double as file keys ("intensity_crescendo_8bar"), so the
    underscores come out for display - the spaces also let the pool
    cells word-wrap long names onto a second line instead of running
    an unbreakable token past the cell edge. Keys stay raw everywhere;
    only what the operator reads goes through here."""
    return " ".join((raw or "").replace("_", " ").split())


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


# _group_has_movers moved to utils/position_presets.py (group_has_movers)
# so the busk output layer shares the exact gating; imported above.
_group_has_movers = group_has_movers


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
        self.bpm: float = DEFAULT_LIVE_BPM
        # Busk-on-top mode: the surface is ALWAYS live; "mode" only says
        # whether a predefined show also runs underneath ("show") or not
        # ("live", the default). No engine merges them yet.
        self.mode: str = "live"                  # "show" | "live"
        # Library-backed staging. EFFECTS are riffs (key
        # "category/name") applied PER GROUP (2026-07-22, the
        # positions pattern): staging assigns the riff to every
        # selected group, a second touch on a fully-held key releases
        # those groups, and an effect KEEPS RUNNING on its group after
        # deselection - selection scopes staging, never playback. A
        # scene is a whole-rig look independent of the selection.
        self.effects: Dict[str, str] = {}        # group name -> riff key
        self.scene: Optional[str] = None         # staged scene key
        # MOVEMENT SHAPES, PER GROUP (2026-07-22, same pattern as
        # effects): group name -> MOVEMENT_REGISTRY rudiment id.
        # Each mover group traces its own shape at its own held-
        # position anchor; a shape keeps running after deselection.
        self.shapes: Dict[str, str] = {}
        # Orbit radius in METERS (the S/M/L chips) - live shapes trace
        # in stage space around their anchor, so the size is physical,
        # not a DMX amplitude. A preference like fade/bpm: survives
        # release_all and update_from_config.
        self.shape_size: float = DEFAULT_SHAPE_SIZE_M
        # Stagger (0-100): spreads the mover heads of each group
        # around the shape's loop instead of moving in unison - 0 is
        # lockstep, 100 fans the heads evenly across the whole cycle.
        # A preference like shape_size.
        self.shape_stagger: int = 0
        # INTENSITY FX, PER GROUP (2026-07-22): group name -> bundled
        # "intensity/..." dimmer riff key. Same pattern as effects, on
        # its own engine slot family, so each group's dimmer pattern
        # runs concurrently with its colour riff.
        self.intensities: Dict[str, str] = {}
        # Applied position palettes, PER GROUP (group name -> namespaced
        # id: "preset:centre", "preset:element:<id>", "mark:<spot name>"
        # - see utils/position_presets.py). Mirrors ``colours``: staging
        # a position applies it to every selected group, so one group
        # aims at the drum riser while another holds the audience -
        # the busk output layer renders each group's movers at its own
        # target. ``position_labels`` accumulates id -> display label
        # for the programmer bar. Unlike effect/scene the ids are
        # config-bound: update_from_config prunes a mark whose spot
        # left the config and an element preset whose element did;
        # geometry presets are never pruned.
        self.positions: Dict[str, str] = {}       # group name -> id
        self.position_labels: Dict[str, str] = {}  # id -> display label
        # Dual queue. ``running`` is the running-playbacks stack - plain
        # dict records {"kind", "key", "label", "paused"}; effect-kind
        # records additionally carry "groups" (sorted list) and there
        # is one PER DISTINCT RIFF KEY held in ``effects``; the other
        # kinds keep at most one record each.
        # ``next_up`` holds preloaded records (same shape, no "paused")
        # staged via enqueue(); fire_next() (GO) pops the head and
        # applies it. Both survive update_from_config (like bpm / mode).
        # Paused/killed are state-only until the output engine lands.
        self.running: List[dict] = []
        self.next_up: List[dict] = []

    # -- config sync ----------------------------------------------------
    def update_from_config(self, names, spot_names=(),
                           valid_element_ids=()) -> None:
        """Seed a submaster (default 100) for each group and prune state
        for groups that no longer exist. Positions are config-bound
        (unlike effect/scene): a staged "mark:" position whose spike
        mark is no longer in ``spot_names`` and a "preset:element:"
        position no longer in ``valid_element_ids`` (removed on the
        Stage tab) are pruned to None; geometry presets are never
        pruned. Silent - the tab re-syncs explicitly after a rebuild."""
        names = list(names)
        valid = set(names)
        self.selected &= valid
        self.flash &= valid
        self.colours = {g: c for g, c in self.colours.items() if g in valid}
        # Keep existing submaster values; add 100 for new groups; drop
        # stale. Rebuild as an ordered dict following the group order.
        self.submasters = {g: self.submasters.get(g, 100) for g in names}
        self.positions = {g: p for g, p in self.positions.items()
                          if g in valid}
        self._prune_positions(spot_names, valid_element_ids)
        # Per-group effects/intensity/shapes follow their group out of
        # the config (the keys themselves are library-bound).
        self.effects = {g: k for g, k in self.effects.items()
                        if g in valid}
        self.intensities = {g: k for g, k in self.intensities.items()
                            if g in valid}
        self.shapes = {g: k for g, k in self.shapes.items()
                       if g in valid}
        self._sync_running_grouped("effect", self.effects)
        self._sync_running_grouped("intensity", self.intensities)
        self._sync_running_grouped("shape", self.shapes)

    def _prune_positions(self, spot_names, valid_element_ids) -> None:
        spot_names = set(spot_names)
        valid_element_ids = set(valid_element_ids)
        pruned: Dict[str, str] = {}
        for group, position_id in self.positions.items():
            if not position_id.startswith((PRESET_PREFIX, MARK_PREFIX)):
                # Migrate the pre-namespace ids (raw spot names, shipped
                # one release before the namespacing) instead of
                # accreting a second id scheme.
                position_id = mark_id(position_id)
            if position_id.startswith(ELEMENT_PRESET_PREFIX):
                keep = position_id in valid_element_ids
            elif position_id.startswith(MARK_PREFIX):
                keep = mark_name(position_id) in spot_names
            else:
                keep = True   # geometry presets always exist
            if keep:
                pruned[group] = position_id
        self.positions = pruned

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
    def stage_colour(self, colour_id: str) -> int:
        """Touch a colour swatch: record it as the staged colour and apply
        it to every selected group at the current fade time. Mutual
        exclusion - a group holds at most one colour, newest touch wins.
        Touching the swatch every selected group already holds RELEASES
        it from those groups (the same toggle contract as positions) -
        the group falls through to the active scene or the show
        underneath. Returns the number of groups affected (applied or
        released) - 0 means nothing was selected and the touch changed
        no output (the tab turns that into visible feedback instead of
        silence)."""
        self.staged_colour = colour_id
        if self.selected and all(self.colours.get(g) == colour_id
                                 for g in self.selected):
            for group in self.selected:
                self.colours.pop(group, None)
        else:
            for group in self.selected:
                self.colours[group] = colour_id
        self.state_changed.emit()
        return len(self.selected)

    def active_colour_ids(self) -> set:
        """Swatch ids currently applied to any selected group - the
        swatches the pool outlines in the accent."""
        return {self.colours[g] for g in self.selected if g in self.colours}

    def release_all(self) -> None:
        """Panic release: clear the programmer (applied colours + staged
        + selection + staged position) AND the running playbacks (staged
        effect/scene + the running stack), releasing the rig to the show.
        The next_up queue is deliberately kept - it is preloaded, not
        output."""
        self.colours.clear()
        self.staged_colour = None
        self.selected.clear()
        self.effects.clear()
        self.scene = None
        self.shapes.clear()
        self.intensities.clear()
        self.positions.clear()
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

    def group_level_local(self, group: str) -> float:
        """The PRE-GRANDMASTER 0..1 level the busk output layer renders
        (utils/artnet/live_layer.py): flash forces full, the soft
        blackout zeroes, else the submaster. Grandmaster and DBO are
        deliberately excluded - they live in the output arbiter's
        post-merge stage so they also cap timeline/Auto playback
        (docs/output-sync-plan.md); group_level keeps the full product
        for consumers that want the final number."""
        if group not in self.submasters:
            return 0.0
        if group in self.flash:
            return 1.0
        if self.blackout:
            return 0.0
        return self.submasters[group] / 100.0

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

    # -- library staging (effects / intensity / shapes / scenes) --------
    def _stage_grouped(self, mapping: Dict[str, str], kind: str,
                       key: str, apply_only: bool = False) -> int:
        """The shared per-group touch (the positions pattern): apply
        ``key`` to every selected group in ``mapping``; touching a key
        every selected group already runs RELEASES it from those groups
        unless ``apply_only`` (GO fires apply-only: never toggles). A
        staged key KEEPS RUNNING on its group after deselection.
        Returns the number of groups affected - 0 means nothing was
        selected and the touch was a no-op the tab must surface."""
        if not self.selected:
            self.state_changed.emit()
            return 0
        if not apply_only and all(mapping.get(g) == key
                                  for g in self.selected):
            for group in self.selected:
                mapping.pop(group, None)
        else:
            for group in self.selected:
                mapping[group] = key
        self._sync_running_grouped(kind, mapping)
        self.state_changed.emit()
        return len(self.selected)

    def stage_effect(self, key: str, apply_only: bool = False) -> int:
        """Touch an effect riff (per-group, see _stage_grouped)."""
        return self._stage_grouped(self.effects, "effect", key,
                                   apply_only)

    def stage_intensity(self, key: str) -> int:
        """Touch an intensity FX (per-group, see _stage_grouped)."""
        return self._stage_grouped(self.intensities, "intensity", key)

    def stage_shape(self, key: str) -> int:
        """Touch a movement shape (per-group; non-mover groups hold
        the id silently - the binder only drives movers)."""
        return self._stage_grouped(self.shapes, "shape", key)

    @staticmethod
    def _active_keys(mapping: Dict[str, str], selected) -> set:
        return {mapping[g] for g in selected if g in mapping}

    def active_effect_keys(self) -> set:
        """Riff keys running on any SELECTED group - the cells the
        pool outlines in the accent (mirrors active_position_ids)."""
        return self._active_keys(self.effects, self.selected)

    def active_intensity_keys(self) -> set:
        return self._active_keys(self.intensities, self.selected)

    def active_shape_keys(self) -> set:
        return self._active_keys(self.shapes, self.selected)

    def _grouped_mapping(self, kind: str) -> Optional[Dict[str, str]]:
        return {"effect": self.effects, "intensity": self.intensities,
                "shape": self.shapes}.get(kind)

    def _sync_running_grouped(self, kind: str,
                              mapping: Dict[str, str]) -> None:
        """Rebuild ``kind``'s running records from its per-group
        mapping: one record per DISTINCT key carrying its sorted group
        list. Existing records keep their position and paused flag;
        emptied records leave; new keys append. Silent - the calling
        mutator emits."""
        groups_by_key: Dict[str, list] = {}
        for group, key in mapping.items():
            groups_by_key.setdefault(key, []).append(group)
        kept: List[dict] = []
        for record in self.running:
            if record.get("kind") != kind:
                kept.append(record)
                continue
            groups = groups_by_key.pop(record["key"], None)
            if groups:
                record["groups"] = sorted(groups)
                kept.append(record)
        for key in groups_by_key:
            label = key.split("/")[-1] if "/" in key else key
            kept.append({"kind": kind, "key": key,
                         "label": _display_name(label),
                         "groups": sorted(groups_by_key[key]),
                         "paused": False})
        self.running[:] = kept

    def set_scene(self, key: Optional[str]) -> None:
        """Toggle the staged scene (a whole-rig look, selection-agnostic).
        Touching the same key again clears it. Mirrors into the running
        stack."""
        self.scene = None if key == self.scene else key
        self._sync_running("scene", self.scene)
        self.state_changed.emit()

    def set_shape_size(self, meters: float) -> None:
        """Set the movement-shape orbit radius (meters, clamped to a
        sane stage range). A running shape restages to the new size."""
        self.shape_size = max(0.1, min(5.0, float(meters)))
        self.state_changed.emit()

    def set_shape_stagger(self, percent: int) -> None:
        """Set the movement-shape stagger (0-100): how far each
        group's heads spread around the loop instead of moving in
        unison. A running shape restages to the new spread."""
        self.shape_stagger = max(0, min(100, int(percent)))
        self.state_changed.emit()

    def stage_position(self, position_id: str,
                       label: Optional[str] = None) -> int:
        """Touch a position palette (a namespaced preset or spike-mark
        id, movers-only): apply it to every selected group, mutual
        exclusion per group like colours. Touching an id every selected
        group already holds RELEASES it from those groups (pan/tilt
        falls back to the show underneath) - the same toggle contract
        as colours. ``label`` is the display name the
        programmer bar shows for the id. Not a playback, so it does not
        mirror into the running stack. Returns the number of groups
        affected (applied or released) - 0 means nothing was selected
        and the touch was a no-op the tab must surface, not swallow."""
        if not self.selected:
            self.state_changed.emit()
            return 0
        if label is not None:
            self.position_labels[position_id] = label
        if all(self.positions.get(g) == position_id
               for g in self.selected):
            for group in self.selected:
                self.positions.pop(group, None)
        else:
            for group in self.selected:
                self.positions[group] = position_id
        self.state_changed.emit()
        return len(self.selected)

    def active_position_ids(self) -> set:
        """Position ids applied to any selected group - the cells the
        pool outlines in the accent (mirrors active_colour_ids)."""
        return {self.positions[g] for g in self.selected
                if g in self.positions}

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
                  "label": _display_name(key.split("/")[-1]),
                  "paused": False}
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
        """GO: pop the head of next_up and apply it live. Applies,
        never toggles - firing a key the selection already runs keeps
        it running (stage_effect apply_only)."""
        if not self.next_up:
            return
        record = self.next_up.pop(0)
        if record["kind"] == "scene":
            if record["key"] != self.scene:
                self.set_scene(record["key"])
                return
        else:
            self.stage_effect(record["key"], apply_only=True)
            return
        self.state_changed.emit()

    def kill_playback(self, index: int) -> None:
        """Remove a running record and clear the matching staged
        effect/scene - the engine binder and busk layer drop the
        output on the next state sync."""
        if not 0 <= index < len(self.running):
            return
        record = self.running.pop(index)
        if record["kind"] == "scene":
            self.scene = None
        else:
            # Grouped kinds (effect/intensity/shape): release ONLY
            # this record's groups; other keys keep running on theirs.
            mapping = self._grouped_mapping(record["kind"])
            if mapping is not None:
                for group in record.get("groups") or ():
                    mapping.pop(group, None)
        self.state_changed.emit()

    def toggle_pause(self, index: int) -> None:
        """Flip a running record's paused flag. The engine binder maps
        an "effect" record's flag onto the slot clock - a paused riff
        freezes mid-pose and keeps streaming that frame; scenes are
        static, so pausing one only marks the record."""
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
    """A group SELECT tile: 3px data-color bar, caps name, fixture
    count, and the group's RUNNING EFFECT name (per-group effects,
    2026-07-22 - the auto tab's per-group riff readout precedent).

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
        # 4px vertical margins (were 7): the third line (running
        # effect) grew the tile, and the tile drives the LIVE tab's
        # height minimum - which drives the WINDOW minimum. Linux CI
        # renders fonts a few px taller, so the 720p guarantee needs
        # headroom, not exactness (caught 2026-07-22 at 725/720).
        layout.setContentsMargins(12, 4, 14, 4)
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
        self.effect_label = MicroLabel("-", point_size=7,
                                       tracking_em=0.1)
        self.effect_label.setMinimumWidth(1)
        layout.addWidget(self.effect_label)
        self._restyle()

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool) -> None:
        selected = bool(selected)
        if selected != self._selected:
            self._selected = selected
        self._restyle()

    def set_running_effect(self, label: str) -> None:
        """The group's running effect display name ("" / "-" = none)."""
        self.effect_label.setText(label or "-")

    def _restyle(self) -> None:
        tokens = _active_tokens()
        bg = tokens["raised"] if self._selected else tokens["panel"]
        border = tokens["accent"] if self._selected else tokens["border"]
        self.setStyleSheet(
            "#LiveSelectTile {"
            f" background-color: {bg};"
            f" border: 1px solid {border};"
            f" border-left: 3px solid {self._color}; }}")
        self.effect_label.setStyleSheet(
            f"color: {tokens['accent']}; background: transparent;")

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
    """A clickable pool cell for a library item (an effect riff, a scene
    or a position spike mark).

    Shows the item name and, for scenes, an optional small colour chip
    when the item carries a display colour; ``tag`` adds a small mono
    sub-line (position cells use it for the mark's stage coordinates).
    An accent outline (token ``accent_line``) marks the active item;
    touching emits ``clicked`` with the item's key. Greying is driven by
    the pool's ``setEnabled`` - the cell restyles to the disabled
    palette when its enabled state changes (effects pool greys out with
    no selection, position pool with no mover groups selected).

    Colours come from :func:`_active_tokens` (never hardcoded) via
    ``_restyle``; the same restyle runs on a theme switch.
    """

    clicked = pyqtSignal(str)

    def __init__(self, item_key: str, label: str,
                 chip_color: Optional[str] = None,
                 tag: Optional[str] = None, parent=None):
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
        # 10pt (was 11): library names word-wrap since the underscore
        # cleanup, but QLabel cannot break INSIDE a word - a long single
        # word ("CRESCENDO") must fit the cell width in one piece.
        self.name_label = DisplayLabel(label, point_size=10,
                                       weight=QFont.Weight.Bold,
                                       tracking_em=0.03)
        self.name_label.setMinimumWidth(1)
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label)
        self.tag_label = None
        if tag:
            self.tag_label = QLabel(tag)
            self.tag_label.setFont(mono_font(7, QFont.Weight.Medium))
            self.tag_label.setMinimumWidth(1)
            layout.addWidget(self.tag_label)
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
            tag_color = tokens["text_disabled"]
        else:
            border = tokens["accent_line"] if self._active else tokens["border"]
            text_color = tokens["text"]
            tag_color = tokens["text_secondary"]
        self.setStyleSheet(
            "#LiveLibraryCell {"
            f" background-color: {tokens['panel']};"
            f" border: 1px solid {border}; }}")
        self.name_label.setStyleSheet(
            f"color: {text_color}; background: transparent;")
        if self.tag_label is not None:
            self.tag_label.setStyleSheet(
                f"color: {tag_color}; background: transparent;")

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

    A UI shell over :class:`LiveState`. Output happens in
    utils/artnet/live_layer.py, which renders this state as the
    arbiter's LIVE layer whenever ArtNet output is enabled: colours,
    scenes, submasters, flash, strobe and position aims are real;
    effects wait on the live engine (docs/live-output-plan.md).
    """

    #: ARM toggled by the operator on the busk surface (2026-07-22);
    #: the shell arms/disarms and reflects the ACTUAL state back via
    #: set_chase_armed - same contract as the Structure tab's chip.
    chase_arm_requested = pyqtSignal(bool)

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
        # POSITION PALETTES: computed-preset cells + one cell per
        # config.spots spike mark, keyed by namespaced position id.
        # _position_labels maps id -> display label for the programmer.
        # MOVEMENT SHAPES: one real cell per registry rudiment, keyed
        # by the rudiment id (the "static" aim IS the position pool).
        self._position_cells: Dict[str, _LibraryCell] = {}
        self._position_labels: Dict[str, str] = {}
        self._movement_cells: Dict[str, _LibraryCell] = {}
        # INTENSITY FX: bundled dimmer riffs, keyed "intensity/<name>".
        self._intensity_cells: Dict[str, _LibraryCell] = {}
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
        self._current_positions_fingerprint = None
        # OUT chip source: the shared OutputArbiter, injected by gui.py
        # when output is first enabled (None = nothing streams).
        self._status_arbiter = None
        self._show_transport = None
        self._last_frames_sent = None

        super().__init__(config, parent)

        self.state.state_changed.connect(self._sync_from_state)
        self._rebuild_groups()
        self._sync_from_state()

        # Poll the arbiter status at glance rate; polling keeps the
        # 44 Hz output thread free of cross-thread signal traffic.
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(500)
        self._status_timer.timeout.connect(self._refresh_output_status)
        self._status_timer.timeout.connect(self._refresh_show_transport)
        self._status_timer.start()

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
        """Refresh SELECT tiles + submaster bank when the groups change
        and the POSITION PALETTES pool when the spike marks, the
        preset-relevant stage elements or the stage dimensions change."""
        self._rebuild_groups()
        self._rebuild_positions()
        self._select_persisted_sync_device()
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
        layout.addWidget(self._build_show_row())
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
            "Run a predefined show underneath the live surface · the "
            "busk rides on top (busk-on-top merge)")
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

    def _build_show_row(self) -> QWidget:
        """The show transport strip: pick a song, start/stop it, and
        see where it is - the thing you busk OVER. Display + control
        ride the shell-injected transport (set_show_transport); with
        none injected the strip reads as disabled. The slot rules are
        untouched: PLAY acquires the playback slot exactly like the
        Shows tab's own Play (busk-on-top keeps working), STOP is the
        operator's STOP (it also disarms an armed LTC chase)."""
        row = QWidget()
        row.setProperty("role", "section-caption")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hbox = QHBoxLayout(row)
        hbox.setContentsMargins(16, 6, 16, 6)
        hbox.setSpacing(6)

        hbox.addWidget(MicroLabel("Show", point_size=8, tracking_em=0.12))
        self._show_combo = QComboBox()
        self._show_combo.setMinimumWidth(180)
        self._show_combo.setProperty("role", "lane-chip")
        self._show_combo.setToolTip(
            "The song the busk rides over (setlist order, then extras)")
        self._show_combo.activated.connect(self._on_show_song_activated)
        hbox.addWidget(self._show_combo)

        self._show_play_btn = QPushButton("PLAY")
        self._show_play_btn.setCheckable(True)
        self._show_play_btn.setProperty("role", "output-select")
        self._show_play_btn.setFont(mono_font(8, QFont.Weight.DemiBold))
        self._show_play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._show_play_btn.setToolTip(
            "Start / stop the selected show under the busk surface")
        self._show_play_btn.clicked.connect(self._on_show_play_clicked)
        hbox.addWidget(self._show_play_btn)

        # Same LED-readout voice as the BPM: what is playing, where.
        self._show_time = QLabel("--:-- / --:--")
        self._show_time.setObjectName("TimeReadout")
        self._show_time.setToolTip("Show position / total")
        hbox.addWidget(self._show_time)

        self._show_hint = MicroLabel(
            "No show transport - open a project with songs",
            point_size=7, tracking_em=0.08)
        self._show_hint.setMinimumWidth(1)
        hbox.addSpacing(6)
        hbox.addWidget(self._show_hint)
        hbox.addStretch(1)
        self._refresh_show_transport()
        return row

    def set_show_transport(self, transport) -> None:
        """Wire the Shows tab's transport adapter (gui.py injects it;
        None reads as no transport). The tab polls it at glance rate -
        display truth comes from the Shows tab, never local state."""
        self._show_transport = transport
        self._refresh_show_transport()

    @staticmethod
    def _format_show_time(seconds: float) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _on_show_song_activated(self, index: int) -> None:
        transport = getattr(self, "_show_transport", None)
        if transport is None:
            return
        name = self._show_combo.itemData(index)
        if name:
            transport.select(name)

    def _on_show_play_clicked(self) -> None:
        transport = getattr(self, "_show_transport", None)
        if transport is None:
            return
        if transport.is_playing():
            transport.stop()
        else:
            name = self._show_combo.currentData()
            if name:
                transport.select(name)
            transport.play()
        self._refresh_show_transport()

    def _refresh_show_transport(self) -> None:
        """Glance-rate poll (same 500 ms timer as the OUT chip): sync
        the song list, follow the Shows tab's current song while the
        combo is closed, and restyle PLAY/readout from wire truth."""
        transport = getattr(self, "_show_transport", None)
        combo = getattr(self, "_show_combo", None)
        if combo is None:
            return
        if transport is None:
            for widget in (combo, self._show_play_btn):
                widget.setEnabled(False)
            self._show_time.setText("--:-- / --:--")
            self._show_hint.setVisible(True)
            return

        songs = transport.songs()
        known = [(combo.itemData(i), combo.itemText(i))
                 for i in range(combo.count())]
        if songs != known:
            combo.blockSignals(True)
            combo.clear()
            for name, label in songs:
                combo.addItem(label, name)
            combo.blockSignals(False)
        current = transport.current()
        if current and combo.currentData() != current \
                and not combo.view().isVisible():
            index = combo.findData(current)
            if index >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(index)
                combo.blockSignals(False)

        playing = transport.is_playing()
        combo.setEnabled(bool(songs))
        self._show_play_btn.setEnabled(bool(songs))
        self._show_play_btn.setChecked(playing)
        self._show_play_btn.setText("STOP" if playing else "PLAY")
        self._show_hint.setVisible(not songs)
        self._show_hint.setText("No songs in this project"
                                if songs == [] else self._show_hint.text())
        if songs:
            self._show_time.setText(
                f"{self._format_show_time(transport.position())} / "
                f"{self._format_show_time(transport.duration())}")
        else:
            self._show_time.setText("--:-- / --:--")

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

        # Engine-status chips (left of the tempo cluster, same glance
        # line as the BPM): OUT shows what is actually on the wire -
        # the arbiter's stream, polled via set_status_arbiter - and
        # SYNC names the clock reference (internal TAP until the sync
        # work slaves external sources: LTC/SMPTE v1.4, the rest v1.8).
        self._out_chip = QLabel()
        self._out_chip.setObjectName("OutputReadout")
        hbox.addWidget(self._out_chip)
        self._sync_chip = QLabel("SYNC INT")
        self._sync_chip.setObjectName("OutputReadout")
        self._sync_chip.setProperty("state", "on")
        self._sync_chip.setToolTip(
            "Tempo reference: internal (TAP). External sync - MIDI "
            "clock, MTC, LTC - arrives with the sync engine and will "
            "slave the clock shown here")
        hbox.addWidget(self._sync_chip)
        # Incoming SMPTE readout (2026-07-22): the received timecode,
        # inline instead of tooltip-only - the operator glance line.
        # Empty (hidden) while the sync is internal.
        self._sync_tc_label = QLabel("")
        self._sync_tc_label.setObjectName("TimeReadout")
        self._sync_tc_label.setToolTip("Last received SMPTE timecode")
        self._sync_tc_label.hide()
        hbox.addWidget(self._sync_tc_label)
        # Sync input DEVICE (2026-07-22, moved here from the Structure
        # rail): the physical input is a VENUE concern - it changes
        # with the rig, not with the show - so it lives on the busk
        # surface (the Auto tab precedent). The choice still persists
        # in setlist.sync_device (the project remembers its venue).
        # Device enumeration is not free: populated on tab activation.
        self._sync_device_combo = QComboBox()
        self._sync_device_combo.setObjectName("SyncDeviceCombo")
        self._sync_device_combo.setProperty("role", "lane-chip")
        self._sync_device_combo.setFont(mono_font(8))
        self._sync_device_combo.setMaximumWidth(180)
        self._sync_device_combo.setToolTip(
            "Audio input carrying the LTC/SMPTE signal")
        self._sync_device_combo.currentIndexChanged.connect(
            self._on_sync_device_selected)
        hbox.addWidget(self._sync_device_combo)
        # ARM CHASE from the busk surface (the same shell arm/disarm
        # the Structure tab drives).
        self._arm_chase_btn = QPushButton("ARM")
        self._arm_chase_btn.setCheckable(True)
        self._arm_chase_btn.setProperty("role", "output-select")
        self._arm_chase_btn.setFont(mono_font(8, QFont.Weight.Medium))
        self._arm_chase_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._arm_chase_btn.setToolTip(
            "Follow incoming SMPTE timecode (songs with an SMPTE "
            "trigger fire at their start time)")
        self._arm_chase_btn.toggled.connect(self._on_arm_chase_toggled)
        hbox.addWidget(self._arm_chase_btn)
        hbox.addSpacing(8)
        self._seed_sync_device_combo()
        self._refresh_output_status()

        # Tempo cluster (right end): a BPM readout + TAP + RESET. This is
        # the reference tempo for the rate-based controls (strobe rate, the
        # rudiment "1/4"); this pass only surfaces and stores it.
        hbox.addWidget(MicroLabel("Tempo", point_size=8, tracking_em=0.12))
        # The BPM is the live reference number: it wears the LED-readout
        # treatment (#TimeReadout - bold mono, readout green on its dark
        # well), same voice as the transport timecodes.
        self._bpm_display = QLabel(f"{self.state.bpm:.1f} BPM")
        self._bpm_display.setObjectName("TimeReadout")
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
        self._tap_reset_btn.setToolTip(
            f"Reset the tempo to {DEFAULT_LIVE_BPM:.0f} BPM and clear "
            "the tap history")
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
        """RESET: back to the default tempo and a clean tap history.
        The first pass only cleared the tap history and kept the BPM,
        which read as a dead button (bench feedback 2026-07-13) - the
        readout snaps to the default now, and running engine slots
        rescale to it like any tempo change."""
        self._tap_bpm.reset()
        self.state.set_bpm(DEFAULT_LIVE_BPM)

    # -- engine-status chips (OUT / SYNC) ---------------------------------

    def set_status_arbiter(self, arbiter) -> None:
        """Wire the shared OutputArbiter as the OUT chip's source
        (gui.py calls this when the arbiter is created; None reads
        OFF). Display-only - the tab never drives the arbiter."""
        self._status_arbiter = arbiter
        self._last_frames_sent = None
        self._refresh_output_status()

    def _universe_plugins(self) -> Dict[int, str]:
        """{config universe id: configured output plugin} from the
        Setup/Universes tab (Universe.output['plugin'])."""
        plugins: Dict[int, str] = {}
        for uid, universe in (getattr(self.config, "universes", {})
                              or {}).items():
            output = getattr(universe, "output", None) or {}
            plugins[int(uid)] = output.get("plugin", "E1.31")
        return plugins

    def _refresh_output_status(self) -> None:
        """Poll the arbiter and restyle the OUT chip. Honesty rule:
        the chip shows what is actually on the wire - the native path
        streams ArtNet only; universes configured for E1.31/DMX USB
        get a * marker and a tooltip note (those settings are honoured
        by the QLC+ export, not by native output yet)."""
        chip = getattr(self, "_out_chip", None)
        if chip is None:
            return
        arbiter = self._status_arbiter
        status = arbiter.status() if arbiter is not None else None
        plugins = self._universe_plugins()

        if status is None or not status["running"]:
            self._last_frames_sent = None
            chip.setText("OUT OFF")
            self._set_chip_state(chip, False)
            chip.setToolTip(
                "No DMX is being sent · enable ArtNet output (topbar "
                "chip) to stream the merged look to the rig and the "
                "visualizer")
            return

        frames = status["frames_sent"]
        # Solid dot while the frame counter advances between polls;
        # hollow if the loop stalls (counter frozen).
        active = frames != self._last_frames_sent
        self._last_frames_sent = frames
        mapping = status["universe_mapping"]
        mixed = any(p != "ArtNet" for p in plugins.values())
        dot = "●" if active else "○"
        chip.setText(f"{dot} ARTNET · {len(mapping)}U"
                     + ("*" if mixed else ""))
        lines = [f"U{uid} -> ArtNet universe {wire}"
                 + (f" · configured {plugins[uid]}"
                    if plugins.get(uid, "ArtNet") != "ArtNet" else "")
                 for uid, wire in sorted(mapping.items())]
        if mixed:
            lines.append(
                "* some universes are configured for E1.31 / DMX USB - "
                "native output is ArtNet-only for now; those settings "
                "are honoured in the QLC+ export")
        chip.setToolTip("\n".join(lines))
        self._set_chip_state(chip, True)

    def set_sync_status(self, source: str, state: str = "",
                        label: str = "") -> None:
        """SYNC chip source (docs/ltc-plan.md phase 3). ``source`` is
        "int" (internal TAP, the default) or "ltc" with the chase's
        state ("locked" / "freewheel" / "no_signal") and the last
        received timecode label - shown INLINE in the #TimeReadout
        next to the chip (2026-07-22). Display-only; the shell drives
        this from the LTC service's signals."""
        chip = self._sync_chip
        if source == "ltc":
            text = {"locked": "SYNC LTC",
                    "freewheel": "SYNC LTC · FW",
                    "no_signal": "SYNC LTC · NO SIG"}.get(
                        state, "SYNC LTC")
            chip.setText(text)
            tip = "Chasing incoming SMPTE timecode"
            if label:
                tip += f" · last {label}"
            if state == "freewheel":
                tip += " · signal lost, freewheeling"
            elif state == "no_signal":
                tip += " · no signal"
            chip.setToolTip(tip)
            self._set_chip_state(chip, state == "locked")
            self._sync_tc_label.setText(label or "--:--:--:--")
            self._sync_tc_label.show()
        else:
            chip.setText("SYNC INT")
            chip.setToolTip(
                "Tempo reference: internal (TAP). External sync - MIDI "
                "clock, MTC, LTC - arrives with the sync engine and "
                "will slave the clock shown here")
            self._set_chip_state(chip, True)
            self._sync_tc_label.clear()
            self._sync_tc_label.hide()

    def _on_arm_chase_toggled(self, checked: bool) -> None:
        self.chase_arm_requested.emit(bool(checked))

    def set_chase_armed(self, armed: bool) -> None:
        """The shell reflects the ACTUAL chase state here (arming can
        fail; disarm can come from the timeline's STOP or the
        Structure tab's chip)."""
        btn = self._arm_chase_btn
        btn.blockSignals(True)
        btn.setChecked(armed)
        btn.setText("CHASING" if armed else "ARM")
        btn.blockSignals(False)

    def _seed_sync_device_combo(self) -> None:
        """Cheap pre-enumeration state: Default input plus the
        persisted device (so the project's choice reads correctly
        before the device list is ever enumerated)."""
        combo = self._sync_device_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Default input", "")
        persisted = getattr(getattr(self.config, "setlist", None),
                            "sync_device", "") or ""
        if persisted:
            combo.addItem(persisted, persisted)
            combo.setCurrentIndex(1)
        combo.blockSignals(False)

    def refresh_sync_devices(self) -> None:
        """Enumerate the audio inputs into the combo (once per
        session; called on tab activation - enumeration is not free).
        Keeps the persisted selection, appending it verbatim when the
        enumeration no longer lists it (unplugged interface: the
        choice must survive a venue where the box is not attached)."""
        if getattr(self, "_sync_devices_loaded", False):
            self._select_persisted_sync_device()
            return
        combo = self._sync_device_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Default input", "")
        try:
            from audio.device_manager import DeviceManager
            for dev in DeviceManager().enumerate_input_devices():
                combo.addItem(dev.display_name or dev.name, dev.name)
            self._sync_devices_loaded = True
        except Exception:
            pass    # enumeration failed: default input only
        combo.blockSignals(False)
        self._select_persisted_sync_device()

    def _select_persisted_sync_device(self) -> None:
        combo = self._sync_device_combo
        persisted = getattr(getattr(self.config, "setlist", None),
                            "sync_device", "") or ""
        combo.blockSignals(True)
        index = combo.findData(persisted)
        if index < 0 and persisted:
            combo.addItem(persisted, persisted)
            index = combo.count() - 1
        combo.setCurrentIndex(max(0, index))
        combo.blockSignals(False)

    def _on_sync_device_selected(self, index: int) -> None:
        value = self._sync_device_combo.itemData(index) or ""
        setlist = getattr(self.config, "setlist", None)
        if setlist is None or setlist.sync_device == value:
            return
        setlist.sync_device = value

    def on_tab_activated(self) -> None:
        """Shell hook (gui._on_tab_changed): the device list is
        enumerated the first time the busk surface is actually shown."""
        self.refresh_sync_devices()

    @staticmethod
    def _set_chip_state(chip: QLabel, on: bool) -> None:
        state = "on" if on else "off"
        if chip.property("state") != state:
            chip.setProperty("state", state)
            style = chip.style()
            if style:
                style.unpolish(chip)
                style.polish(chip)

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
        # 720p floor (2026-07-18): the pool grids DEMAND ~1128x624 as
        # their layout minimum, which propagates through the tab stack
        # into the WINDOW minimum (1462x1020) - Windows enforces that,
        # so the app could not fit a 1280x720 display at all. An
        # explicit minimum overrides the layout hint per axis
        # (qSmartMinSize): the pools compress below their preferred
        # size instead of pinning the window, and the squeezed render
        # is pinned by tests/visual/test_720p_layout.py goldens.
        # 200 (was 220) since the riff pools scroll (2026-07-22): a
        # lower floor stays usable, and the LIVE tab is the window
        # height driver - Linux CI needs the headroom.
        host.setMinimumSize(600, 200)
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

    @staticmethod
    def _pool_scroller(grid_host: QWidget) -> QScrollArea:
        """Wrap a pool grid in a vertical scroller (2026-07-22): a
        long library made the fixed grid overflow its column - cells
        painting over each other and the category headers. The scroll
        area's minimum is a few rows, so the pools keep squeezing at
        720p instead of demanding their content height."""
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroller.setWidget(grid_host)
        scroller.setMinimumHeight(60)
        # The viewport must keep the pool's themed background - a bare
        # QScrollArea paints the platform base color.
        scroller.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget "
            "{ background: transparent; }")
        return scroller

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
        # POSITION PALETTES: two subsections - PRESETS (targets computed
        # from the stage setup, utils/position_presets.py) on top, MARKS
        # (one cell per config.spots spike mark, authored on the Stage
        # tab) below. Header + both grids live in one section widget so
        # the movers-only gating can grey the whole pool (setEnabled,
        # like the effects pool) without touching the MOVEMENT SHAPES
        # placeholders below.
        section = QWidget()
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(0)
        # Tag kept short ("Movers only", not "Applies to: movers") - the
        # narrow five-column header truncates longer tags silently.
        section_layout.addWidget(self._pool_header(
            "Position palettes", "Movers only", tag_accent=True))
        section_layout.addWidget(self._pool_header("Presets"))
        preset_host = QWidget()
        preset_grid = QGridLayout(preset_host)
        preset_grid.setContentsMargins(14, 0, 14, 6)
        preset_grid.setSpacing(6)
        self._preset_grid = preset_grid
        section_layout.addWidget(preset_host)
        section_layout.addWidget(self._pool_header("Marks"))
        marks_host = QWidget()
        marks_grid = QGridLayout(marks_host)
        marks_grid.setContentsMargins(14, 0, 14, 10)
        marks_grid.setSpacing(6)
        self._marks_grid = marks_grid
        section_layout.addWidget(marks_host)
        self._position_section = section
        layout.addWidget(section)
        self._populate_position_pool()

        # MOVEMENT SHAPES: the 10 registry rudiments as real cells
        # (movers-only gated like the position section above). The
        # touched shape loops on every selected mover group, anchored
        # at the group's held position (CENTRE when none is held).
        shapes_section = QWidget()
        shapes_section_layout = QVBoxLayout(shapes_section)
        shapes_section_layout.setContentsMargins(0, 0, 0, 0)
        shapes_section_layout.setSpacing(0)
        shapes_section_layout.addWidget(
            self._pool_header("Movement shapes", "Movers only",
                              tag_accent=True))
        # Orbit SIZE chips (S/M/L, meters): physical radius around the
        # anchor - a running shape restages to the new size live.
        size_row = QWidget()
        size_box = QHBoxLayout(size_row)
        size_box.setContentsMargins(14, 0, 14, 6)
        size_box.setSpacing(6)
        size_box.addWidget(MicroLabel("Size", point_size=7,
                                      tracking_em=0.12))
        self._shape_size_buttons = []
        for label, meters in SHAPE_SIZES:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setProperty("role", "output-select")
            btn.setFont(mono_font(8, QFont.Weight.Medium))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"Orbit radius {meters:g} m around the "
                           "held position")
            btn.clicked.connect(
                lambda _checked=False, m=meters:
                self.state.set_shape_size(m))
            size_box.addWidget(btn)
            self._shape_size_buttons.append((btn, meters))
        size_box.addStretch(1)
        shapes_section_layout.addWidget(size_row)
        # STAGGER fader: 0 = the group's heads trace in unison, 100 =
        # evenly fanned around the whole cycle. A running shape
        # restages live as the fader moves.
        stagger_row = QWidget()
        stagger_box = QHBoxLayout(stagger_row)
        stagger_box.setContentsMargins(14, 0, 14, 6)
        stagger_box.setSpacing(6)
        stagger_box.addWidget(MicroLabel("Stagger", point_size=7,
                                         tracking_em=0.12))
        self._stagger_slider = _RateSlider()
        self._stagger_slider.setToolTip(
            "Spread the heads around the shape's cycle · 0 moves them "
            "in unison, 100 fans them evenly")
        self._stagger_slider.value_changed.connect(
            self.state.set_shape_stagger)
        stagger_box.addWidget(self._stagger_slider, 1)
        shapes_section_layout.addWidget(stagger_row)
        shapes_host = QWidget()
        shape_grid = QGridLayout(shapes_host)
        shape_grid.setContentsMargins(14, 0, 14, 12)
        shape_grid.setSpacing(6)
        shape_columns = 2
        for i, (shape_id, label) in enumerate(MOVEMENT_SHAPES):
            cell = _LibraryCell(shape_id, label)
            cell.setToolTip(
                f"{label} · loops on the selected mover groups, "
                "anchored at each group's held position (CENTRE when "
                "none is held) · touch again to release")
            cell.clicked.connect(self._on_shape_touched)
            self._movement_cells[shape_id] = cell
            shape_grid.addWidget(cell, i // shape_columns,
                                 i % shape_columns)
        for col in range(shape_columns):
            shape_grid.setColumnStretch(col, 1)
        shapes_section_layout.addWidget(shapes_host)
        self._shapes_section = shapes_section
        layout.addWidget(shapes_section)
        layout.addStretch(1)
        return pool

    def _on_shape_touched(self, shape_id: str) -> None:
        """Apply/release a movement shape on the selected groups
        (per-group, the effects pattern; the binder only drives the
        mover groups among them). Fire-only - no QUEUE latch."""
        if not self.state.stage_shape(shape_id):
            self._flash_programmer_warning(
                "NO MOVER GROUP SELECTED · SHAPES RUN ON SELECTED MOVERS")
        else:
            self._clear_programmer_warning()

    def _add_position_cell(self, grid: QGridLayout, index: int,
                           position_id: str, label: str, tag: str,
                           tip: str) -> None:
        cell = _LibraryCell(position_id, label, tag=tag)
        cell.setToolTip(tip)
        cell.clicked.connect(self._on_position_touched)
        self._position_cells[position_id] = cell
        self._position_labels[position_id] = label
        grid.addWidget(cell, index // 2, index % 2)

    def _populate_position_pool(self) -> None:
        """Rebuild both POSITION PALETTES grids: PRESETS from
        compute_presets (five geometry presets plus one per matching
        placed stage element), MARKS from config.spots (config order,
        stage coordinates as a small mono tag, an honest empty state
        when the stage has no marks yet)."""
        self._clear_grid(self._preset_grid)
        self._clear_grid(self._marks_grid)
        self._position_cells = {}
        self._position_labels = {}
        self._current_positions_fingerprint = self._positions_fingerprint()

        for i, preset in enumerate(compute_presets(self.config)):
            if preset.kind == KIND_POINT:
                x, y, z = preset.point
                where = f"target {x:.1f} / {y:.1f} / {z:.1f} m"
            else:
                where = "each mover derives its own target"
            self._add_position_cell(
                self._preset_grid, i, preset.preset_id, preset.label,
                preset.tag,
                f"{preset.label} · computed from the stage setup · "
                f"{where} · touch to point the selected movers at it")
        for col in range(2):
            self._preset_grid.setColumnStretch(col, 1)

        spots = getattr(self.config, "spots", {}) or {}
        if not spots:
            self._marks_grid.addWidget(
                self._marker("No marks yet · add spike marks on the "
                             "Stage tab"),
                0, 0, 1, 2)
            return
        for i, (name, spot) in enumerate(spots.items()):
            self._add_position_cell(
                self._marks_grid, i, mark_id(name), name,
                f"{spot.x:.1f} · {spot.y:.1f}",
                f"{name} · stage {spot.x:.1f} / {spot.y:.1f} / "
                f"{spot.z:.1f} m · touch to point the selected movers "
                "at it")
        for col in range(2):
            self._marks_grid.setColumnStretch(col, 1)

    def _positions_fingerprint(self) -> tuple:
        """What the POSITION pool renders from: the spike-mark set, the
        preset-relevant stage elements (id + kind, catalog-matching
        kinds only) and the stage dimensions (AUDIENCE / FAN OUT tags
        and targets depend on them)."""
        spots = getattr(self.config, "spots", {}) or {}
        return (tuple(spots.keys()),
                tuple(element_preset_ids(self.config)),
                (getattr(self.config, "stage_width", None),
                 getattr(self.config, "stage_height", None)))

    def _rebuild_positions(self) -> None:
        """Rebuild the POSITION PALETTES pool when its config inputs
        change; prune a staged position whose mark or element is gone
        (positions are config-bound, unlike effect/scene)."""
        if self._positions_fingerprint() == \
                self._current_positions_fingerprint:
            return
        spots = getattr(self.config, "spots", {}) or {}
        self.state.update_from_config(
            list(self.config.groups.keys()), spots.keys(),
            element_preset_ids(self.config))
        self._populate_position_pool()

    def _selection_has_movers(self) -> bool:
        """Whether any selected group has mover (pan/tilt) fixtures -
        the movers-only gate for the POSITION PALETTES pool."""
        return any(
            _group_has_movers(self.config.groups[name])
            for name in self.state.selected if name in self.config.groups)

    def _build_intensity_pool(self) -> QWidget:
        pool, layout = self._pool_shell()
        # Curated dimmer-only riffs from the library's "intensity"
        # category (riffs/intensity/, bundled) on the engine's own
        # concurrent slot: a dimmer pattern under a colour riff.
        # Selection-scoped like the EFFECTS pool.
        layout.addWidget(self._pool_header("Intensity FX",
                                           "Selection", tag_accent=True))
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(14, 0, 14, 8)
        grid.setSpacing(6)
        grid.setRowStretch(999, 1)      # content packs to the top
        self._intensity_grid = grid
        self._intensity_grid_host = grid_host
        layout.addWidget(self._pool_scroller(grid_host), 1)
        self._populate_intensity_pool()
        return pool

    def _populate_intensity_pool(self) -> None:
        self._clear_grid(self._intensity_grid)
        self._intensity_cells = {}
        library = self._resolve_effect_library()
        riffs = [r for r in (library.get_all_riffs() if library else [])
                 if r.category == INTENSITY_CATEGORY]
        if not riffs:
            self._intensity_grid.addWidget(
                self._marker("No intensity FX · bundled riffs missing"),
                0, 0, 1, 2)
            return
        columns = 2
        for i, riff in enumerate(riffs):
            key = f"{riff.category}/{riff.name}"
            cell = _LibraryCell(key, _display_name(riff.name))
            cell.setToolTip(f"{_display_name(riff.name)} · "
                            f"{riff.description} · "
                            "dimmer-only, loops on the selected groups "
                            "· touch again to release")
            cell.clicked.connect(self._on_intensity_touched)
            self._intensity_cells[key] = cell
            self._intensity_grid.addWidget(cell, i // columns,
                                           i % columns)
        for col in range(columns):
            self._intensity_grid.setColumnStretch(col, 1)

    def _on_intensity_touched(self, key: str) -> None:
        """Apply/release an intensity FX on the selected groups
        (per-group, the effects pattern - each group's dimmer pattern
        runs under its colour riff). Fire-only like shapes."""
        if not self.state.stage_intensity(key):
            self._flash_programmer_warning(
                "NO GROUP SELECTED · INTENSITY FX RUN ON SELECTED GROUPS")
        else:
            self._clear_programmer_warning()

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
        grid.setRowStretch(999, 1)      # content packs to the top
        self._effects_grid = grid
        layout.addWidget(self._pool_scroller(grid_host), 1)
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
        grid.setRowStretch(999, 1)      # content packs to the top
        self._scenes_grid = grid
        layout.addWidget(self._pool_scroller(grid_host), 1)
        self._populate_scenes_pool()
        return pool

    @staticmethod
    def _clear_grid(grid: QGridLayout) -> None:
        while grid.count():
            item = grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Detach immediately: deleteLater alone leaves the
                # widget parented and PAINTING until the event loop
                # runs - a repopulate could show the old empty-state
                # marker ghosting behind the new cells (exposed by the
                # category headers, same lesson as _clear_light_lanes).
                widget.hide()
                widget.setParent(None)
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
        """Rebuild the EFFECTS pool GROUPED BY RIFF CATEGORY
        (2026-07-22): one small header per category (the POSITION
        pool's PRESETS/MARKS subsection precedent) over a 2-col grid
        of its riffs. Cells keep their "category/name" keys."""
        self._clear_grid(self._effects_grid)
        self._effect_cells = {}
        library = self._resolve_effect_library()
        riffs = [r for r in (library.get_all_riffs()
                             if library is not None else [])
                 if r.category != INTENSITY_CATEGORY]
        if not riffs:
            self._effects_grid.addWidget(
                self._marker("No effects yet · save riffs from the timeline"),
                0, 0, 1, 2)
            return
        columns = 2
        by_category: Dict[str, list] = {}
        for riff in riffs:                    # get_all_riffs is sorted
            by_category.setdefault(riff.category, []).append(riff)
        grid_row = 0
        for category in sorted(by_category):
            header = MicroLabel(_display_name(category), point_size=7,
                                tracking_em=0.12)
            self._effects_grid.addWidget(header, grid_row, 0, 1, columns)
            grid_row += 1
            for i, riff in enumerate(by_category[category]):
                key = f"{riff.category}/{riff.name}"
                cell = _LibraryCell(key, _display_name(riff.name))
                cell.clicked.connect(self._on_effect_touched)
                self._effect_cells[key] = cell
                self._effects_grid.addWidget(cell,
                                             grid_row + i // columns,
                                             i % columns)
            grid_row += (len(by_category[category]) + columns - 1) \
                // columns
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
            cell = _LibraryCell(key, _display_name(scene.name),
                                chip_color=chip)
            cell.clicked.connect(self._on_scene_touched)
            self._scene_cells[key] = cell
            self._scenes_grid.addWidget(cell, i // columns, i % columns)
        for col in range(columns):
            self._scenes_grid.setColumnStretch(col, 1)

    def scene_for_key(self, key: Optional[str]):
        """The Scene behind a "category/name" pool key, or None. The
        busk output layer (utils/artnet/live_layer.py) resolves the
        active LiveState.scene through this."""
        if not key:
            return None
        return self._resolve_scene_library().scenes.get(key)

    def riff_for_key(self, key: Optional[str]):
        """The Riff behind a "category/name" pool key, or None. The
        live engine binders (utils/artnet/live_engine.py) resolve the
        per-group LiveState.effects keys and LiveState.intensity
        through this."""
        if not key:
            return None
        return self._resolve_effect_library().riffs.get(key)

    def set_effect_library(self, library) -> None:
        """Inject the shared RiffLibrary and rebuild the EFFECTS pool
        AND the INTENSITY FX pool (same library, different category)."""
        self._effect_library = library if library is not None \
            else self._empty_riff_library()
        self._populate_effects_pool()
        self._populate_intensity_pool()
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
        if not self.state.stage_colour(colour_id):
            self._flash_programmer_warning(
                "NO GROUP SELECTED · PICK GROUPS, THEN TOUCH A COLOUR")
        else:
            self._clear_programmer_warning()

    def _on_effect_touched(self, key: str) -> None:
        """Latched QUEUE stages the effect in next_up (cell stays
        inactive); unlatched applies it to the SELECTED groups (the
        positions pattern - each group runs its own riff, and it keeps
        running after deselection)."""
        if self._queue_latch_btn.isChecked():
            self.state.enqueue("effect", key, self._key_name(key))
            return
        if not self.state.stage_effect(key):
            self._flash_programmer_warning(
                "NO GROUP SELECTED · PICK GROUPS, THEN TOUCH AN EFFECT")
        else:
            self._clear_programmer_warning()

    def _on_scene_touched(self, key: str) -> None:
        """Latched QUEUE stages the scene in next_up; unlatched fires."""
        if self._queue_latch_btn.isChecked():
            self.state.enqueue("scene", key, self._key_name(key))
        else:
            self.state.set_scene(key)

    def _on_position_touched(self, position_id: str) -> None:
        """Apply/toggle a preset or spike mark on the selected groups
        (per-group, like colours). Fire-only - the QUEUE latch covers
        EFFECTS/SCENES cells; positions are not playbacks. The busk
        output layer aims each group's movers at its applied target."""
        if not self.state.stage_position(
                position_id, self._position_labels.get(position_id)):
            self._flash_programmer_warning(
                "NO GROUP SELECTED · PICK GROUPS, THEN TOUCH A POSITION")
        else:
            self._clear_programmer_warning()

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
        # Transient no-op feedback: a palette touch with nothing
        # selected changes no output; instead of silence the bar shows
        # a warning until the timer runs out (or real state replaces
        # it - _refresh_programmer prefers the warning while active).
        self._programmer_warning = ""
        self._programmer_warning_timer = QTimer(self)
        self._programmer_warning_timer.setSingleShot(True)
        self._programmer_warning_timer.timeout.connect(
            self._clear_programmer_warning)
        return bar

    def _flash_programmer_warning(self, text: str,
                                  duration_ms: int = 2500) -> None:
        self._programmer_warning = text
        self._programmer_warning_timer.start(duration_ms)
        self._refresh_programmer()

    def _clear_programmer_warning(self) -> None:
        self._programmer_warning = ""
        self._programmer_warning_timer.stop()
        self._refresh_programmer()

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

        # Quiet red outline until latched, full destructive fill while
        # armed (destructive-outline:checked) - a kill switch must show
        # its state, and the always-filled "destructive" role reads
        # identical checked and unchecked.
        dbo = QPushButton("DBO")
        dbo.setCheckable(True)
        dbo.setProperty("role", "destructive-outline")
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

        # Seed/prune the state's per-group data for the new group set
        # (spot names + element preset ids passed along so the position
        # prune stays exact).
        self.state.update_from_config(
            group_names, (getattr(self.config, "spots", {}) or {}).keys(),
            element_preset_ids(self.config))

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
            # Tile readout: "EFFECT · DIM INTENSITY" (the riff-like
            # per-group runners; positions/colours read on stage).
            parts = []
            if name in state.effects:
                parts.append(_display_name(
                    state.effects[name].split("/")[-1]))
            if name in state.intensities:
                parts.append("DIM " + _display_name(
                    state.intensities[name].split("/")[-1]))
            tile.set_running_effect(" · ".join(parts))

        active_ids = state.active_colour_ids()
        for colour_id, swatch in self._colour_swatches.items():
            swatch.set_active(colour_id in active_ids)

        # EFFECTS and INTENSITY FX: per-group. The pools grey with no
        # selection (STAGING targets the selection; running keys keep
        # running) and outline the keys held by any selected group.
        # SCENES: whole-rig, always enabled.
        self._effects_pool.setEnabled(bool(state.selected))
        active_effects = state.active_effect_keys()
        for key, cell in self._effect_cells.items():
            cell.set_active(key in active_effects)
        self._intensity_pool.setEnabled(bool(state.selected))
        active_intensities = state.active_intensity_keys()
        for key, cell in self._intensity_cells.items():
            cell.set_active(key in active_intensities)
        for key, cell in self._scene_cells.items():
            cell.set_active(key == state.scene)

        # POSITION PALETTES: movers-only. Grey the section when the
        # selection holds no mover groups; outline the ids applied to
        # any selected group (selection-scoped, like the colour pool).
        self._position_section.setEnabled(self._selection_has_movers())
        active_positions = state.active_position_ids()
        for name, cell in self._position_cells.items():
            cell.set_active(name in active_positions)

        # MOVEMENT SHAPES: same movers-only gate; per-group like
        # effects, so outline the selection's held shapes.
        self._shapes_section.setEnabled(self._selection_has_movers())
        active_shapes = state.active_shape_keys()
        for shape_id, cell in self._movement_cells.items():
            cell.set_active(shape_id in active_shapes)
        for btn, meters in self._shape_size_buttons:
            self._sync_toggle(btn, abs(state.shape_size - meters) < 1e-9)
        self._stagger_slider.set_value(state.shape_stagger)

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
        songs = getattr(self.config, "songs", {}) or {}
        name = next(iter(songs), None)
        row, hbox = self._row_shell()
        self._pinned_show_label, self._pinned_show_marker = self._row_text(
            hbox, name if name else "SHOW",
            "Show mode · pinned · no engine yet")
        return row

    def _make_running_row(self, index: int, record: dict) -> QWidget:
        row, hbox = self._row_shell()
        tag = "FX" if record["kind"] == "effect" else "SCENE"
        groups = record.get("groups") or ()
        if groups:
            tag += " · " + " + ".join(groups)
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
        if self._programmer_warning \
                and self._programmer_warning_timer.isActive():
            self._programmer_label.setText(self._programmer_warning)
            return
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
        # FX lists the selection's running riffs; with no selection,
        # everything held (mirrors the POS branch below).
        effect_keys = state.active_effect_keys() if state.selected \
            else set(state.effects.values())
        if effect_keys:
            fx_labels = sorted(self._key_name(k).upper()
                               for k in effect_keys)
            text += f" · FX: {' · '.join(fx_labels)}"
        if state.scene:
            text += f" · SCENE: {self._key_name(state.scene).upper()}"
        shape_ids = state.active_shape_keys() if state.selected \
            else set(state.shapes.values())
        if shape_ids:
            shape_labels = sorted(
                dict(MOVEMENT_SHAPES).get(s, s).upper()
                for s in shape_ids)
            text += f" · SHAPE: {' · '.join(shape_labels)}"
        intensity_keys = state.active_intensity_keys() if state.selected \
            else set(state.intensities.values())
        if intensity_keys:
            dim_labels = sorted(self._key_name(k).upper()
                                for k in intensity_keys)
            text += f" · DIM: {' · '.join(dim_labels)}"
        # POS shows the selection's applied targets; with no selection,
        # everything held (mirrors the colour HELD branch). Display
        # labels ("CROSS", "DS CENTRE"), not raw namespaced ids; fall
        # back to stripping the namespace for ids applied without a
        # label (legacy callers).
        position_ids = state.active_position_ids() if state.selected \
            else set(state.positions.values())
        if position_ids:
            labels = sorted(
                (state.position_labels.get(p) or p.split(":")[-1]).upper()
                for p in position_ids)
            text += f" · POS: {' · '.join(labels)}"
        self._programmer_label.setText(text)

    @staticmethod
    def _key_name(key: Optional[str]) -> str:
        """The display name from a "category/name" library key
        (underscores read as spaces, see _display_name)."""
        if not key:
            return "-"
        return _display_name(key.split("/")[-1])

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
            for cell in list(self._movement_cells.values()) \
                    + list(self._intensity_cells.values()):
                cell._restyle()
            for cell in list(self._effect_cells.values()) + \
                    list(self._scene_cells.values()) + \
                    list(self._position_cells.values()):
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
