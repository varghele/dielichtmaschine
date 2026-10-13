# gui/dialogs/morph_patchbay.py
"""The morph patchbay (v1.5b phase 4, mockup 15-morph-patch-flow-6d).

Left column: the source show's fixture GROUPS (one row per group
selector, e.g. "WASH" / "WASH:0"), expandable to their four sublane
streams. Group-keyed, not lane-keyed: lanes live inside a song, so
cataloguing them made the user redraw every wire once per song - a real
12-song gig needed 293 edges for 39 distinct wires (changed 2026-08-08;
design doc 5.2). Right column: the target config's groups with
capability chips. Wires are cubic curves in the middle canvas, coloured
per source group; a dashed wire is a group-level patch that fans out to
several sublanes at once. Capability vocabulary
is the locked 1:1 mapping: INTENSITY / COLOUR / POSITION / BEAM ==
dimmer / colour / movement / special.

Interaction contract (kept deliberately testable - every mutation is a
plain method on the widget; painting only reads):

- Wiring, two equivalent paths sharing one gate (``can_dock``):
  DRAG a source chip onto a target capability chip or target row (the
  mockup's ZIEHEN: QUELLE -> ZIEL), or CLICK a source chip, then a
  target capability chip. While a wire is pending (clicked or mid-
  drag), incompatible target chips are disabled - only the matching
  capability docks (the mockup's core rule). Clicking the pending chip
  again cancels. A collapsed group row wires the whole group: every
  sublane the lane carries that the target renders. Drops route
  through ``handle_wire_drop`` so tests drive them without synthetic
  mouse events.
- POSITION on a lane with no movement content shows as a ghost chip;
  wiring it creates a ``regenerate`` edge (strategy ``manual`` until
  changed) - the design's "movement onto groups that had none" path.
- Edges: each target row lists its incoming edges as chips in a
  wrapping flow; the wire colour matches the source lane. Right-click
  an edge chip for mode (copy / copy+transform / regenerate +
  strategy), transforms (phase_offset amount, mirror, intensity_scale
  factor, spatial_subset selector), priority and delete. Fan-in
  priority uses the menu's "Priority +" / "Priority -" pair instead of
  drag-reorder: chips wrap, so a drag order would be ambiguous to read
  and to test; the +/- pair maps 1:1 onto MorphEdge.priority. An edge
  carrying transforms wears the mockup's filter marker.
- Lock: the LOCK button per target row round-trips
  plan.protected_target_lanes (re-morph leaves the lane untouched).
- AUTO-SUGGEST prefills edges by source group
  lighting_role first, capability overlap second (design doc 8). It
  only ever ADDS edges the user can delete - manual-first stands.
- The checker strip at the bottom shows live per-group coverage from
  utils/morph/checker (worst case across songs); 0% on a capability
  the group has renders as a red gap chip.
"""

from __future__ import annotations

import contextlib
from typing import Dict, List, Optional, Tuple

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtSignal

from gui.widgets.flow_layout import FlowLayout
from utils.morph.checker import check, group_capabilities
from utils.morph.compile import SUBLANE_ATTRS
from utils.morph.plan import (MorphEdge, MorphPlan, REGENERATE_STRATEGIES,
                              TRANSFORM_TYPES)

#: data-model sublane -> UI capability label (decision 3, locked 1:1)
SUBLANE_LABELS = {
    "dimmer": "INTENSITY",
    "colour": "COLOUR",
    "movement": "POSITION",
    "special": "BEAM",
}
SUBLANE_ORDER = ("dimmer", "colour", "movement", "special")

#: wire colours per source lane, cycled (mockup 6d palette)
LANE_COLOURS = ("#d9a441", "#4ecbd4", "#c95fd0", "#6f9e4c",
                "#f0562e", "#8d9299")

SUBSET_SELECTORS = ("left-half", "right-half", "front-half", "back-half")

ROW_HEIGHT = 40
FILTER_MARK = "◐"   # the mockup's "capability filter active" glyph

#: drag payload: "<selector>\n<sublane>" ('' = whole lane)
WIRE_MIME = "application/x-lm-morph-wire"

#: drag payload for pulling an existing patch OUT: the edge id. Nothing
#: in the patchbay accepts it, on purpose - see _EdgeChipHolder.
UNPATCH_MIME = "application/x-lm-morph-unpatch"


def encode_wire_mime(selector: str,
                     sublane: Optional[str]) -> QtCore.QMimeData:
    mime = QtCore.QMimeData()
    mime.setData(WIRE_MIME, f"{selector}\n{sublane or ''}".encode("utf-8"))
    return mime


def decode_wire_mime(mime: QtCore.QMimeData
                     ) -> Optional[Tuple[str, Optional[str]]]:
    """(selector, sublane-or-None) from a wire drag, else None."""
    if not mime.hasFormat(WIRE_MIME):
        return None
    raw = bytes(mime.data(WIRE_MIME)).decode("utf-8")
    selector, _, sublane = raw.partition("\n")
    return selector, (sublane or None)


class SourceInfo:
    """Display metadata for one distinct source GROUP SELECTOR."""

    def __init__(self, selector: str, name: str, songs: List[str],
                 colour: str, content: Dict[str, int]):
        self.selector = selector     # "WASH" / "WASH:0" - the edge key
        self.name = name             # display label
        self.songs = songs           # songs whose lanes use this selector
        self.colour = colour
        self.content = content       # sublane -> block count (0 omitted)

    @property
    def song(self) -> str:
        """Back-compat single-song label; the rail shows the count."""
        return self.songs[0] if len(self.songs) == 1 else ""


def _source_catalog(source_config) -> List[SourceInfo]:
    """Every distinct GROUP SELECTOR the setlist's lanes target.

    Group-keyed, not lane-keyed (design doc 5.2): the same group recurs
    in every song, so one row here wires the whole setlist. Cataloguing
    lanes instead produced one row per song per lane - 58 rows and 293
    edges on a real 12-song gig that expresses 39 distinct wires.
    """
    content: Dict[str, Dict[str, int]] = {}
    songs: Dict[str, List[str]] = {}
    order: List[str] = []
    for song_name, song in source_config.songs.items():
        if not song.timeline_data:
            continue
        for lane in song.timeline_data.lanes:
            for selector in lane.fixture_targets:
                if selector not in content:
                    content[selector] = {}
                    songs[selector] = []
                    order.append(selector)
                if song_name not in songs[selector]:
                    songs[selector].append(song_name)
                for sublane, attr in SUBLANE_ATTRS.items():
                    count = sum(len(getattr(lb, attr))
                                for lb in lane.light_blocks)
                    if count:
                        content[selector][sublane] = \
                            content[selector].get(sublane, 0) + count
    infos: List[SourceInfo] = []
    for selector in order:
        used = songs[selector]
        label = selector
        if len(source_config.songs) > 1:
            label = f"{selector}  ({len(used)} song{'s' if len(used) != 1 else ''})"
        infos.append(SourceInfo(
            selector, label, used,
            LANE_COLOURS[len(infos) % len(LANE_COLOURS)],
            content[selector]))
    return infos


class EdgeCanvas(QtWidgets.QWidget):
    """Dumb wire painter: asks the patchbay for curves, draws them."""

    def __init__(self, patchbay: "MorphPatchbay"):
        super().__init__(patchbay._board)
        self._patchbay = patchbay
        # Clickable, unlike the in-flight overlay: clicking a wire is how
        # you select and then unpatch it. Focusable so Delete arrives.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        width = self.width()
        selected = self._patchbay.selected_edge_id
        for y1, y2, colour, dashed, edge_id in self._patchbay.edge_curves():
            is_selected = edge_id == selected
            pen = QtGui.QPen(QtGui.QColor(colour),
                             3.5 if is_selected else 2.0)
            if dashed:
                pen.setStyle(Qt.PenStyle.DashLine)
                pen.setWidthF(3.0 if is_selected else 1.5)
            painter.setPen(pen)
            path = self._patchbay.curve_path(y1, y2, width)
            painter.drawPath(path)
            if is_selected:
                # A halo, so the selected wire reads even where it
                # overlaps its neighbours.
                halo = QtGui.QPen(QtGui.QColor("#f4f1ea"), 1.0)
                halo.setStyle(Qt.PenStyle.DotLine)
                painter.setPen(halo)
                painter.drawPath(path)
        painter.end()

    def mousePressEvent(self, event):
        edge_id = self._patchbay.edge_at(event.position().toPoint())
        # A click on empty canvas clears the selection rather than
        # leaving a wire armed for the next Delete.
        self._patchbay.select_edge(edge_id)
        if edge_id is not None:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self._patchbay.remove_selected_edge():
                event.accept()
                return
        super().keyPressEvent(event)


class _WireOverlay(QtWidgets.QWidget):
    """Paints the cable that follows the cursor while a wire is in flight.

    A separate widget from EdgeCanvas on purpose. EdgeCanvas is a LAYOUT
    COLUMN between the source and target columns, so it can only paint in
    the gap; a cable that follows the cursor has to reach over the target
    column too. This one spans the whole board and paints nothing else,
    which keeps committed-wire painting (and its golden) untouched.
    """

    def __init__(self, patchbay: "MorphPatchbay"):
        super().__init__(patchbay._board)
        self._patchbay = patchbay
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        curve = self._patchbay.pending_curve()
        if curve is None:
            return
        x1, y1, x2, y2, colour = curve
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        pen = QtGui.QPen(QtGui.QColor(colour), 2.0)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        path = QtGui.QPainterPath()
        path.moveTo(x1, y1)
        # Same cubic shape as a committed wire, so the cable in flight
        # reads as the wire it is about to become.
        span = max(abs(x2 - x1), 1.0)
        path.cubicTo(x1 + span * 0.45, y1, x2 - span * 0.45, y2, x2, y2)
        painter.drawPath(path)
        # A blob on the free end: without it the cable looks like it ends
        # in nothing rather than in the cursor.
        painter.setBrush(QtGui.QBrush(QtGui.QColor(colour)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QtCore.QPointF(x2, y2), 4.0, 4.0)
        painter.end()


class _SourceChip(QtWidgets.QToolButton):
    """A wireable source chip: click sets the pending wire, dragging it
    carries the same key as a QDrag (both paths meet in the patchbay's
    gating)."""

    def __init__(self, patchbay: "MorphPatchbay",
                 key: Tuple[str, Optional[str]]):
        super().__init__()
        self._patchbay = patchbay
        self._key = key
        self._press_pos: Optional[QtCore.QPoint] = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._press_pos is not None
                and event.buttons() & Qt.MouseButton.LeftButton
                and (event.pos() - self._press_pos).manhattanLength()
                >= QtWidgets.QApplication.startDragDistance()):
            self._press_pos = None
            # Release the button's pressed state before the drag eats
            # the mouse-release, or the chip sticks visually pressed.
            self.setDown(False)
            drag = QtGui.QDrag(self)
            drag.setMimeData(encode_wire_mime(*self._key))
            self._patchbay.begin_wire_drag(self._key)
            try:
                drag.exec(Qt.DropAction.CopyAction)
            finally:
                self._patchbay.end_wire_drag()
            return
        super().mouseMoveEvent(event)


class _TargetChip(QtWidgets.QToolButton):
    """A target capability chip that accepts compatible wire drops."""

    def __init__(self, patchbay: "MorphPatchbay", group: str, sublane: str):
        super().__init__()
        self._patchbay = patchbay
        self._group = group
        self._sublane = sublane
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        wire = decode_wire_mime(event.mimeData())
        if wire is not None and self._patchbay.wire_drop_allowed(
                wire[0], wire[1], self._group, self._sublane):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        # Feeds the in-flight cable. This path is guaranteed to fire over
        # a target (where precision matters); the patchbay's cursor timer
        # covers the gaps in between. Only wire drags: accepting anything
        # would swallow an unpatch drag and turn it into a no-op.
        if decode_wire_mime(event.mimeData()) is None:
            event.ignore()
            return
        self._patchbay.report_drag_position(self, event.position().toPoint())
        event.acceptProposedAction()

    def dropEvent(self, event):
        wire = decode_wire_mime(event.mimeData())
        if wire is not None and self._patchbay.handle_wire_drop(
                wire[0], wire[1], self._group, self._sublane):
            event.acceptProposedAction()


class _TargetRowFrame(QtWidgets.QFrame):
    """A whole target row accepts drops too - dropping anywhere on the
    group docks the wire (lane drags fan out, stream drags dock their
    own capability)."""

    def __init__(self, patchbay: "MorphPatchbay", group: str):
        super().__init__()
        self._patchbay = patchbay
        self._group = group
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        wire = decode_wire_mime(event.mimeData())
        if wire is not None and self._patchbay.wire_drop_allowed(
                wire[0], wire[1], self._group, None):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if decode_wire_mime(event.mimeData()) is None:
            event.ignore()
            return
        self._patchbay.report_drag_position(self, event.position().toPoint())
        event.acceptProposedAction()

    def dropEvent(self, event):
        wire = decode_wire_mime(event.mimeData())
        if wire is not None and self._patchbay.handle_wire_drop(
                wire[0], wire[1], self._group, None):
            event.acceptProposedAction()


class _PlanEditCommand(QtGui.QUndoCommand):
    """Snapshot-based undo for the patch plan.

    Deliberately NOT a command class per mutation. The plan is a small
    document (a real 12-song gig is 39 edges) and the patchbay mutates it
    nine different ways; nine inverse operations would drift out of sync
    with them, while one snapshot pair cannot. Snapshots are plain data
    (edge dicts), so equality is free and a no-op edit pushes nothing.
    """

    def __init__(self, patchbay: "MorphPatchbay", text: str,
                 before, after):
        super().__init__(text)
        self._patchbay = patchbay
        self._before = before
        self._after = after
        # QUndoStack.push() calls redo() immediately, but the mutation
        # has already run by then - the first redo must not re-apply it.
        self._applied = True

    def redo(self):
        if self._applied:
            self._applied = False
            return
        self._patchbay._restore_snapshot(self._after)

    def undo(self):
        self._patchbay._restore_snapshot(self._before)


class _EdgeChipHolder(QtWidgets.QWidget):
    """One incoming edge: its chip plus the × that unpatches it."""

    UNPATCH_SIZE = 18

    def __init__(self, patchbay: "MorphPatchbay", edge_id: str):
        super().__init__()
        self._patchbay = patchbay
        self.edge_id = edge_id
        # Focusable so the edge can be reached and removed from the
        # keyboard, not only by hitting an 18px target with the mouse.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._press_pos: Optional[QtCore.QPoint] = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Drag the patch off its row to unplug it - the physical
        gesture. Nothing in the patchbay accepts this mime, so the drag
        always ends in IgnoreAction; that IS the signal that it was
        pulled out rather than dropped somewhere meaningful."""
        if (self._press_pos is None
                or not event.buttons() & Qt.MouseButton.LeftButton
                or (event.pos() - self._press_pos).manhattanLength()
                < QtWidgets.QApplication.startDragDistance()):
            super().mouseMoveEvent(event)
            return
        self._press_pos = None
        drag = QtGui.QDrag(self)
        mime = QtCore.QMimeData()
        mime.setData(UNPATCH_MIME, self.edge_id.encode("utf-8"))
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        action = drag.exec(Qt.DropAction.MoveAction)
        self._patchbay.finish_unpatch_drag(
            self.edge_id, action == Qt.DropAction.IgnoreAction)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._patchbay.remove_edge(self.edge_id)
            event.accept()
            return
        super().keyPressEvent(event)

    @staticmethod
    def make_unpatch_button(colour: str) -> QtWidgets.QToolButton:
        button = QtWidgets.QToolButton()
        button.setText("×")
        button.setAutoRaise(True)
        button.setFixedSize(_EdgeChipHolder.UNPATCH_SIZE,
                            _EdgeChipHolder.UNPATCH_SIZE)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            "QToolButton { border: none; background: transparent;"
            f" color: {colour}; font-size: 14px; padding: 0; }}"
            "QToolButton:hover { color: #e5484d; }")
        return button


class MorphPatchbay(QtWidgets.QWidget):
    """The routing editor. Owns a MorphPlan and mutates ONLY the plan
    (and its protected_target_lanes); configs are read-only here."""

    changed = pyqtSignal()

    HINT_IDLE = ("Drag a source chip onto a matching target capability, "
                 "or click source then target. "
                 "Solid = 1:1 · dashed = lane patch.")

    def __init__(self, source_config, target_config,
                 plan: Optional[MorphPlan] = None, parent=None):
        super().__init__(parent)
        self.source_config = source_config
        self.target_config = target_config
        self.plan = plan if plan is not None else MorphPlan()

        self._sources = _source_catalog(source_config)
        self._sources_by_selector = {info.selector: info for info in self._sources}
        self._caps = group_capabilities(target_config)
        self._expanded: set = set()
        #: (selector, target_group) pairs wired as one group-level patch
        self._group_patches: set = set()
        self._pending: Optional[Tuple[str, Optional[str]]] = None
        self._dragging = False
        #: free end of the cable in flight, in BOARD coordinates
        self._drag_point: Optional[QtCore.QPoint] = None
        self._drag_timer: Optional[QtCore.QTimer] = None
        self._overlay: Optional["_WireOverlay"] = None
        #: view state only - the wire the user clicked, armed for Delete
        self._selected_edge_id: Optional[str] = None
        #: the patchbay's OWN stack: Ctrl+Z here means "unpatch that
        #: again", never "undo a timeline edit" (the app stack is a
        #: different document).
        self.undo_stack = QtGui.QUndoStack(self)
        self._undo_depth = 0
        self._restoring = False
        self._source_anchors: Dict[Tuple[str, Optional[str]],
                                   QtWidgets.QWidget] = {}
        self._target_anchors: Dict[str, QtWidgets.QWidget] = {}
        self._build_ui()
        self._derive_group_patches()
        self._rebuild_rows()

    # ── model operations (tests drive these directly) ────────────────────

    def source_content(self, selector: str) -> Dict[str, int]:
        info = self._sources_by_selector.get(selector)
        return dict(info.content) if info else {}

    def edge(self, edge_id: str) -> Optional[MorphEdge]:
        for e in self.plan.edges:
            if e.edge_id == edge_id:
                return e
        return None

    def can_dock(self, selector: str, sublane: str,
                 target_group: str) -> bool:
        """Capability gating: the target group must render the sublane,
        and the lane must carry it (POSITION alone may be empty - that
        is the regenerate path)."""
        if sublane not in self._caps.get(target_group, set()):
            return False
        content = self.source_content(selector)
        if sublane == "movement":
            return True          # empty movement wires as regenerate
        return bool(content.get(sublane))

    def add_edge(self, selector: str, sublane: str, target_group: str,
                 mode: Optional[str] = None) -> Optional[MorphEdge]:
        """One wire; returns None (adds nothing) when the dock is
        incompatible or the identical edge already exists."""
        if not self.can_dock(selector, sublane, target_group):
            return None
        for e in self.plan.edges:
            if (e.source_group == selector and e.sublane == sublane
                    and e.target_group == target_group):
                return None
        info = self._sources_by_selector[selector]
        if mode is None:
            if sublane == "movement" and not info.content.get("movement"):
                mode = "regenerate"
            else:
                mode = "copy"
        edge = MorphEdge(source_group=selector, sublane=sublane,
                         target_group=target_group, mode=mode)
        with self._undoable(
                f"Patch {selector} · {SUBLANE_LABELS[sublane]} "
                f"-> {target_group}"):
            self.plan.edges.append(edge)
            self._notify()
        return edge

    def add_group_patch(self, selector: str,
                       target_group: str) -> List[MorphEdge]:
        """Lane-level wire: every sublane the lane carries that the
        target renders, marked as one dashed fan-out."""
        added = []
        content = self.source_content(selector)
        with self._undoable(f"Patch {selector} -> {target_group}"):
            for sublane in SUBLANE_ORDER:
                if not content.get(sublane):
                    continue
                edge = self.add_edge(selector, sublane, target_group)
                if edge is not None:
                    added.append(edge)
            if len(added) >= 2:
                self._group_patches.add((selector, target_group))
                self._notify()
        return added

    def remove_edge(self, edge_id: str) -> bool:
        edge = self.edge(edge_id)
        if edge is None:
            return False
        label = f"{edge.source_group} · {SUBLANE_LABELS[edge.sublane]}"
        with self._undoable(f"Unpatch {label}"):
            self.plan.edges.remove(edge)
            if self._selected_edge_id == edge_id:
                # However it went (×, Delete, menu), a selection pointing
                # at a gone edge would arm the next Delete at nothing.
                self._selected_edge_id = None
            pair = (edge.source_group, edge.target_group)
            if pair in self._group_patches and not any(
                    e.source_group == pair[0] and e.target_group == pair[1]
                    for e in self.plan.edges):
                self._group_patches.discard(pair)
            self._notify()
        return True

    def set_edge_mode(self, edge_id: str, mode: str,
                      strategy: str = "manual") -> None:
        edge = self.edge(edge_id)
        if edge is None:
            return
        with self._undoable(f"Set mode {mode}"):
            edge.mode = mode
            if mode == "regenerate":
                if strategy in REGENERATE_STRATEGIES:
                    edge.regenerate_strategy = strategy
            elif mode == "copy":
                edge.transforms = []
            self._notify()

    def set_transform(self, edge_id: str, kind: str, **params) -> None:
        """Add or replace one transform on the edge; flips the mode to
        copy_transform. Raises ValueError on unknown kinds or missing
        required parameters (same vocabulary the plan validates)."""
        if kind not in TRANSFORM_TYPES:
            raise ValueError(f"unknown transform '{kind}'")
        for required in TRANSFORM_TYPES[kind]:
            if required not in params:
                raise ValueError(f"transform '{kind}' needs '{required}'")
        edge = self.edge(edge_id)
        if edge is None:
            return
        with self._undoable(f"Set {kind}"):
            edge.transforms = [t for t in edge.transforms
                               if t.get("type") != kind]
            edge.transforms.append({"type": kind, **params})
            if edge.mode == "copy":
                edge.mode = "copy_transform"
            self._notify()

    def clear_transform(self, edge_id: str, kind: str) -> None:
        edge = self.edge(edge_id)
        if edge is None:
            return
        with self._undoable(f"Clear {kind}"):
            edge.transforms = [t for t in edge.transforms
                               if t.get("type") != kind]
            if not edge.transforms and edge.mode == "copy_transform":
                edge.mode = "copy"
            self._notify()

    def bump_priority(self, edge_id: str, delta: int) -> None:
        edge = self.edge(edge_id)
        if edge is None:
            return
        with self._undoable("Change priority"):
            edge.priority = max(0, edge.priority + delta)
            self._notify()

    def set_lock(self, target_group: str, locked: bool) -> None:
        """Round-trips plan.protected_target_lanes (design doc 5.5)."""
        protected = set(self.plan.protected_target_lanes)
        if locked:
            protected.add(target_group)
        else:
            protected.discard(target_group)
        with self._undoable(
                f"{'Lock' if locked else 'Unlock'} {target_group}"):
            self.plan.protected_target_lanes = sorted(protected)
            self._notify()

    def is_locked(self, target_group: str) -> bool:
        return target_group in self.plan.protected_target_lanes

    def is_group_patch(self, selector: str, target_group: str) -> bool:
        return (selector, target_group) in self._group_patches

    def set_expanded(self, selector: str, expanded: bool) -> None:
        if expanded:
            self._expanded.add(selector)
        else:
            self._expanded.discard(selector)
        self._rebuild_rows()

    def auto_suggest(self) -> List[MorphEdge]:
        """Prefill: for each source lane pick the best target group by
        (same lighting_role, capability overlap, name) and wire every
        compatible sublane. Adds only; never edits or removes."""
        added: List[MorphEdge] = []
        # One undo step for the whole prefill: suggesting 39 wires and
        # then pressing Ctrl+Z 39 times is not an undo.
        with self._undoable("Auto-suggest"):
            for info in self._sources:
                if not info.content:
                    continue
                best = self._suggest_target_for(info)
                if best is None:
                    continue
                for sublane in SUBLANE_ORDER:
                    if info.content.get(sublane):
                        edge = self.add_edge(info.selector, sublane, best)
                        if edge is not None:
                            added.append(edge)
            if added:
                self._notify()
        return added

    def _suggest_target_for(self, info: SourceInfo) -> Optional[str]:
        """Best target group for a source: same lighting_role first,
        capability overlap second, name third (design doc 8)."""
        role = self._source_role(info)
        candidates = []
        for group, caps in self._caps.items():
            overlap = len(set(info.content) & caps)
            if not overlap:
                continue
            target_role = getattr(
                self.target_config.groups.get(group), "lighting_role",
                "") or ""
            role_match = 1 if role and target_role == role else 0
            candidates.append((-role_match, -overlap, group))
        if not candidates:
            return None
        candidates.sort()
        return candidates[0][2]

    def _source_role(self, info: SourceInfo) -> str:
        for song in self.source_config.songs.values():
            if not song.timeline_data:
                continue
            for lane in song.timeline_data.lanes:
                if lane.lane_id != info.selector:
                    continue
                for target in lane.fixture_targets:
                    group = self.source_config.groups.get(
                        target.split(":")[0])
                    if group is not None:
                        return group.lighting_role or ""
        return ""

    def checker(self):
        return check(self.source_config, self.plan, self.target_config)

    def coverage_summary(self) -> List[Tuple[str, str, int, bool]]:
        """(target group, sublane, worst percent across songs, is_gap)
        for every touched group - the checker strip's data."""
        result = self.checker()
        worst: Dict[Tuple[str, str], float] = {}
        for row in result.coverage:
            key = (row.target_group, row.sublane)
            worst[key] = min(worst.get(key, 1.0), row.fraction)
        summary = []
        for (group, sublane), fraction in sorted(worst.items()):
            is_gap = fraction == 0.0 and \
                sublane in self._caps.get(group, set())
            summary.append((group, sublane, int(round(fraction * 100)),
                            is_gap))
        return summary

    def load_plan(self, plan: MorphPlan) -> None:
        """Adopt an existing plan (re-morph workflow)."""
        self.plan = plan
        self._group_patches.clear()
        self._derive_group_patches()
        self._rebuild_rows()
        self.changed.emit()

    def _derive_group_patches(self) -> None:
        """A loaded plan carries no widget state: any (lane, target)
        pair wired on 2+ sublanes reads as a group-level patch."""
        pairs: Dict[Tuple[str, str], set] = {}
        for edge in self.plan.edges:
            pairs.setdefault(
                (edge.source_group, edge.target_group),
                set()).add(edge.sublane)
        for pair, sublanes in pairs.items():
            if len(sublanes) >= 2:
                self._group_patches.add(pair)

    # ── drag-and-drop wiring (the drop half is plain methods) ────────────

    def wire_drop_allowed(self, selector: str, sublane: Optional[str],
                          target_group: str,
                          target_sublane: Optional[str]) -> bool:
        """Would this drop dock? Same gate for dragEnter and tests.
        ``sublane`` None = whole-lane drag; ``target_sublane`` None =
        dropped on the row rather than one capability chip."""
        if selector not in self._sources_by_selector:
            return False
        if sublane is None:
            content = self.source_content(selector)
            docks = [s for s in content
                     if s in self._caps.get(target_group, set())]
            if target_sublane is not None:
                return target_sublane in docks
            return bool(docks)
        if target_sublane is not None and target_sublane != sublane:
            return False
        return self.can_dock(selector, sublane, target_group)

    def handle_wire_drop(self, selector: str, sublane: Optional[str],
                         target_group: str,
                         target_sublane: Optional[str] = None) -> bool:
        """A wire dropped on a target: lane drags fan out (dashed lane
        patch), stream drags dock their capability. Returns True when
        at least one edge was added."""
        if not self.wire_drop_allowed(selector, sublane, target_group,
                                      target_sublane):
            return False
        if sublane is None:
            added = bool(self.add_group_patch(selector, target_group))
        else:
            added = self.add_edge(selector, sublane, target_group) \
                is not None
        if added:
            self._pending = None
        return added

    def begin_wire_drag(self, key: Tuple[str, Optional[str]]) -> None:
        """Gate targets while the drag is in flight - same visual
        language as a pending click - and start the cable following the
        cursor."""
        self._dragging = True
        self._pending = key
        self._start_drag_tracking()
        self._refresh_gating()
        self._sync_pending_checks()

    def end_wire_drag(self) -> None:
        self._dragging = False
        self._pending = None
        self._stop_drag_tracking()
        self._refresh_gating()
        self._sync_pending_checks()

    # ── the cable in flight ──────────────────────────────────────────────

    def set_drag_position(self, point: Optional[QtCore.QPoint]) -> None:
        """Move the cable's free end (BOARD coordinates), or clear it.

        The testable seam: tests call this directly instead of
        synthesizing drag events, the same way ``handle_wire_drop``
        stands in for a real drop."""
        self._drag_point = point
        if self._overlay is not None:
            self._overlay.update()

    def report_drag_position(self, widget: QtWidgets.QWidget,
                             point: QtCore.QPoint) -> None:
        """A drop target relaying a dragMoveEvent position in ITS own
        coordinates."""
        self.set_drag_position(widget.mapTo(self._board, point))

    def pending_curve(self):
        """(x1, y1, x2, y2, colour) for the cable in flight, else None.
        Board coordinates. Painting reads this; nothing else."""
        if self._pending is None or self._drag_point is None:
            return None
        info = self._sources_by_selector.get(self._pending[0])
        if info is None:
            return None
        anchor = self._source_anchors.get(self._pending)
        if anchor is None:
            return None
        start = anchor.mapTo(self._board, QtCore.QPoint(
            anchor.width(), anchor.height() // 2))
        return (float(start.x()), float(start.y()),
                float(self._drag_point.x()), float(self._drag_point.y()),
                info.colour)

    def _start_drag_tracking(self) -> None:
        """Poll the cursor for the duration of the drag.

        QDrag.exec runs its own event loop and the source widget stops
        getting mouse moves, while the overlay is mouse-transparent by
        necessity (an overlay that accepted drag events would swallow the
        drops meant for the chips underneath). Drop targets relay their
        own dragMoveEvent - this covers the gaps between them."""
        self.set_drag_position(
            self._board.mapFromGlobal(QtGui.QCursor.pos()))
        if self._drag_timer is None:
            self._drag_timer = QtCore.QTimer(self)
            self._drag_timer.setInterval(16)
            self._drag_timer.timeout.connect(self._poll_cursor)
        self._drag_timer.start()

    def _stop_drag_tracking(self) -> None:
        if self._drag_timer is not None:
            self._drag_timer.stop()
        self.set_drag_position(None)

    def _poll_cursor(self) -> None:
        if self._dragging:
            self.set_drag_position(
                self._board.mapFromGlobal(QtGui.QCursor.pos()))

    # ── UI scaffolding ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("PATCH · CAPABILITY TO CAPABILITY")
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        header.addWidget(title)
        self.hint_label = QtWidgets.QLabel(self.HINT_IDLE)
        header.addWidget(self.hint_label, 1)
        self.suggest_btn = QtWidgets.QPushButton("Auto-suggest")
        self.suggest_btn.setToolTip(
            "Prefill edges by lighting role and capability overlap. "
            "Only adds wires - delete any you do not want.")
        self.suggest_btn.clicked.connect(self.auto_suggest)
        header.addWidget(self.suggest_btn)

        # Sits next to Auto-suggest on purpose: prefilling 39 wires you
        # did not want is exactly when you need to start over.
        self.unpatch_all_btn = QtWidgets.QPushButton("Unpatch all")
        self.unpatch_all_btn.setToolTip(
            "Remove every patch in this plan and start over")
        self.unpatch_all_btn.clicked.connect(
            lambda _=False: self.confirm_and_clear(what="this plan"))
        header.addWidget(self.unpatch_all_btn)

        self.undo_btn = QtWidgets.QPushButton("Undo")
        self.undo_btn.clicked.connect(lambda _=False: self.undo())
        header.addWidget(self.undo_btn)
        self.redo_btn = QtWidgets.QPushButton("Redo")
        self.redo_btn.clicked.connect(lambda _=False: self.redo())
        header.addWidget(self.redo_btn)
        # Buttons are the reliable path; the shortcut is scoped to this
        # widget tree so it cannot fight the app-wide Ctrl+Z, which
        # belongs to a different document (the timeline).
        for keys, slot in (
                (QtGui.QKeySequence.StandardKey.Undo, self.undo),
                (QtGui.QKeySequence.StandardKey.Redo, self.redo)):
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(keys), self)
            shortcut.setContext(
                Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
        # A BOUND METHOD, not a lambda: PyQt tracks the receiver QObject
        # and drops the connection when this widget dies. A lambda has no
        # receiver, so it outlives the widget and fires into the deleted
        # QUndoStack (native crash at teardown, found 2026-08-08).
        self.undo_stack.indexChanged.connect(self._on_undo_index_changed)
        self._sync_undo_buttons()
        layout.addLayout(header)

        self._board = QtWidgets.QWidget()
        board_layout = QtWidgets.QHBoxLayout(self._board)
        board_layout.setContentsMargins(0, 0, 0, 0)
        board_layout.setSpacing(0)

        # Proportional columns (the fixed 280/320px of the dialog era
        # squeezed chips into elided slivers): the wire canvas takes the
        # slack but stays narrow enough that rows read as one board.
        self._source_column = QtWidgets.QVBoxLayout()
        self._source_column.setSpacing(8)
        source_holder = QtWidgets.QWidget()
        source_holder.setLayout(self._source_column)
        source_holder.setMinimumWidth(320)

        self._canvas = EdgeCanvas(self)
        self._canvas.setMinimumWidth(120)
        self._canvas.setMaximumWidth(360)

        self._target_column = QtWidgets.QVBoxLayout()
        self._target_column.setSpacing(8)
        target_holder = QtWidgets.QWidget()
        target_holder.setLayout(self._target_column)
        target_holder.setMinimumWidth(420)

        board_layout.addWidget(source_holder, 2)
        board_layout.addWidget(self._canvas, 1)
        board_layout.addWidget(target_holder, 3)

        # Spans the whole board (not a layout item) so the cable in
        # flight can reach across the target column to the cursor.
        self._overlay = _WireOverlay(self)
        self._overlay.setGeometry(self._board.rect())
        self._overlay.raise_()
        self._board.installEventFilter(self)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._board)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(scroll, 1)

        self.checker_label = QtWidgets.QLabel("")
        self.checker_label.setWordWrap(True)
        self.checker_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.checker_label)

    def _style_chip(self, chip: QtWidgets.QToolButton, text: str,
                    colour: str = "", ghost: bool = False) -> None:
        """Common chip look: never narrower than its own text (the
        dialog-era fixed columns elided chips into 'I..Y')."""
        chip.setText(text)
        chip.setCheckable(True)
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        metrics = QtGui.QFontMetrics(chip.font())
        chip.setMinimumWidth(metrics.horizontalAdvance(text) + 20)
        border = colour or "#3a3a3a"
        style = (f"QToolButton {{ border: 1px solid {border};"
                 f" background: transparent; padding: 2px 8px; }}"
                 f" QToolButton:checked {{ background: {border};"
                 f" color: #0e0e10; }}"
                 f" QToolButton:disabled {{ color: #5c6068;"
                 f" border-color: #2d2d2d; }}")
        if ghost:
            style = style.replace("1px solid", "1px dashed")
        chip.setStyleSheet(style)

    def _chip(self, text: str, colour: str = "",
              ghost: bool = False) -> QtWidgets.QToolButton:
        chip = QtWidgets.QToolButton()
        self._style_chip(chip, text, colour, ghost)
        return chip

    def _source_chip(self, key: Tuple[str, Optional[str]], text: str,
                     colour: str, ghost: bool = False) -> _SourceChip:
        chip = _SourceChip(self, key)
        self._style_chip(chip, text, colour, ghost)
        # The third scope: everything this source feeds, however many
        # targets it fans out to.
        chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        chip.customContextMenuRequested.connect(
            lambda pos, s=key[0], c=chip: self._source_menu(s, c, pos))
        return chip

    def _source_menu(self, selector: str, chip: QtWidgets.QWidget,
                     pos: QtCore.QPoint) -> None:
        menu = QtWidgets.QMenu(self)
        count = len(self.edges_matching(source_group=selector))
        action = menu.addAction(f"Unpatch everything from {selector}"
                                f" ({count})")
        action.setEnabled(bool(count))
        action.triggered.connect(
            lambda _=False: self.confirm_and_clear(source_group=selector,
                                                   what=selector))
        menu.exec(chip.mapToGlobal(pos))

    def _row_frame(self, colour: str,
                   frame: Optional[QtWidgets.QFrame] = None
                   ) -> QtWidgets.QFrame:
        if frame is None:
            frame = QtWidgets.QFrame()
        frame.setStyleSheet(
            f"QFrame {{ border: 1px solid #2d2d2d;"
            f" border-left: 3px solid {colour}; }}"
            f" QLabel {{ border: none; }}")
        frame.setMinimumHeight(ROW_HEIGHT)
        return frame

    def _name_label(self, text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        return label

    def _clear_column(self, column: QtWidgets.QVBoxLayout) -> None:
        while column.count():
            item = column.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _rebuild_rows(self) -> None:
        self._source_anchors.clear()
        self._target_anchors.clear()
        self._clear_column(self._source_column)
        self._clear_column(self._target_column)

        for info in self._sources:
            self._source_column.addWidget(self._build_source_row(info))
        self._source_column.addStretch(1)

        for group in self.target_config.groups:
            self._target_column.addWidget(self._build_target_row(group))
        self._target_column.addStretch(1)

        self._refresh_gating()
        self._refresh_checker()
        self._canvas.update()
        if self._overlay is not None:
            # Rebuilt rows are new children; the cable must stay on top.
            self._overlay.raise_()
            self._overlay.update()

    def _build_source_row(self, info: SourceInfo) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout(holder)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(4)

        frame = self._row_frame(info.colour)
        row = QtWidgets.QHBoxLayout(frame)
        row.setContentsMargins(8, 4, 8, 4)
        expanded = info.selector in self._expanded
        expand = QtWidgets.QToolButton()
        # A drawn arrow, not a text glyph: the dialog era used "+"/"-"
        # text, which rendered as an anonymous blank square.
        expand.setArrowType(Qt.ArrowType.DownArrow if expanded
                            else Qt.ArrowType.RightArrow)
        expand.setAutoRaise(True)
        expand.setFixedSize(22, 22)
        expand.setStyleSheet("QToolButton { border: none;"
                             " background: transparent; padding: 0; }")
        expand.setToolTip("Expand to the four sublane streams")
        expand.clicked.connect(
            lambda _=False, lid=info.selector:
            self.set_expanded(lid, lid not in self._expanded))
        row.addWidget(expand)
        row.addWidget(self._name_label(info.name), 1)

        if expanded:
            # Expanded: the lane header is not wireable; each sublane
            # stream gets its own chip row + anchor.
            for sublane in SUBLANE_ORDER:
                has_content = bool(info.content.get(sublane))
                if not has_content and sublane != "movement":
                    continue
                sub = self._row_frame(info.colour)
                sub_row = QtWidgets.QHBoxLayout(sub)
                sub_row.setContentsMargins(30, 4, 8, 4)
                count = info.content.get(sublane, 0)
                sub_row.addWidget(QtWidgets.QLabel(
                    f"{count}x" if count else "empty"))
                sub_row.addStretch(1)
                chip = self._source_chip(
                    (info.selector, sublane), SUBLANE_LABELS[sublane],
                    info.colour, ghost=not has_content)
                if not has_content:
                    chip.setToolTip(
                        "No movement authored - wiring this creates a "
                        "REGENERATE edge")
                chip.clicked.connect(
                    lambda _=False, lid=info.selector, s=sublane:
                    self._chip_clicked(lid, s))
                self._register_chip((info.selector, sublane), chip)
                sub_row.addWidget(chip)
                self._source_anchors[(info.selector, sublane)] = sub
                vbox.addWidget(sub)
        else:
            chip = self._source_chip((info.selector, None), "GROUP",
                                     info.colour)
            chip.setToolTip(
                "Wire the whole lane: every stream it carries that the "
                "target renders (dashed fan-out)")
            chip.clicked.connect(
                lambda _=False, lid=info.selector:
                self._chip_clicked(lid, None))
            self._register_chip((info.selector, None), chip)
            row.addWidget(chip)
            self._source_anchors[(info.selector, None)] = frame

        vbox.insertWidget(0, frame)
        return holder

    def _build_target_row(self, group: str) -> QtWidgets.QWidget:
        colour = "#8d9299"
        for edge in self.plan.edges:
            if edge.target_group == group:
                info = self._sources_by_selector.get(edge.source_group)
                if info:
                    colour = info.colour
                break
        frame = self._row_frame(colour, _TargetRowFrame(self, group))
        vbox = QtWidgets.QVBoxLayout(frame)
        vbox.setContentsMargins(8, 4, 8, 4)
        vbox.setSpacing(4)

        # Header: the group's NAME leads (the dialog era hid it clipped
        # behind the chips); wires anchor on this row.
        head = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(head)
        row.setContentsMargins(0, 0, 0, 0)
        fixtures = getattr(self.target_config.groups.get(group),
                           "fixtures", [])
        row.addWidget(self._name_label(group))
        row.addWidget(QtWidgets.QLabel(f"{len(fixtures)}x"))
        row.addStretch(1)
        lock = self._chip("LOCK", "#8d9299")
        lock.setChecked(self.is_locked(group))
        lock.setToolTip(
            "Protect this target lane: re-morph leaves it untouched")
        lock.toggled.connect(
            lambda checked, g=group: self.set_lock(g, checked))
        row.addWidget(lock)
        if any(e.target_group == group for e in self.plan.edges):
            clear = self._chip("UNPATCH", "#8d9299")
            clear.setCheckable(False)
            clear.setToolTip(f"Remove every patch feeding {group}")
            clear.setProperty("unpatch_target_group", group)
            clear.clicked.connect(
                lambda _=False, g=group: self.confirm_and_clear(
                    target_group=g, what=g))
            row.addWidget(clear)
        vbox.addWidget(head)

        chip_holder = QtWidgets.QWidget()
        chips = FlowLayout(chip_holder)
        for sublane in SUBLANE_ORDER:
            if sublane not in self._caps.get(group, set()):
                continue
            chip = _TargetChip(self, group, sublane)
            self._style_chip(chip, SUBLANE_LABELS[sublane], colour)
            chip.setCheckable(False)
            chip.clicked.connect(
                lambda _=False, g=group, s=sublane:
                self._target_chip_clicked(g, s))
            self._register_target_chip(group, sublane, chip)
            chips.addWidget(chip)
        vbox.addWidget(chip_holder)

        edges_here = [e for e in self.plan.edges if e.target_group == group]
        if edges_here:
            edge_holder = QtWidgets.QWidget()
            edge_flow = FlowLayout(edge_holder)
            for edge in sorted(edges_here, key=lambda e: -e.priority):
                edge_flow.addWidget(self._build_edge_chip(edge))
            vbox.addWidget(edge_holder)

        self._target_anchors[group] = head
        return frame

    def _build_edge_chip(self, edge: MorphEdge) -> QtWidgets.QWidget:
        """An edge chip plus its unpatch button.

        The × is always visible, not hover-revealed: removal lived only
        behind a right-click menu until 2026-08-08 and users reasonably
        concluded there was no way to un-patch at all. An affordance that
        appears on hover would not have fixed that.
        """
        info = self._sources_by_selector.get(edge.source_group)
        colour = info.colour if info else "#8d9299"
        text = f"{edge.source_group} · {SUBLANE_LABELS[edge.sublane]}"
        if edge.mode == "regenerate":
            text += f" · REGEN({edge.regenerate_strategy})"
        if edge.transforms:
            text += f" {FILTER_MARK}"
        if edge.priority:
            text += f" p{edge.priority}"
        chip = self._chip(text, colour)
        chip.setCheckable(False)
        chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        chip.customContextMenuRequested.connect(
            lambda pos, e=edge, c=chip: self._edge_menu(e, c, pos))
        chip.setToolTip("Right-click: mode, transforms, priority, delete")
        chip.setProperty("edge_id", edge.edge_id)

        unpatch = _EdgeChipHolder.make_unpatch_button(colour)
        unpatch.setToolTip(f"Unpatch {text}")
        unpatch.setProperty("unpatch_edge_id", edge.edge_id)
        unpatch.clicked.connect(
            lambda _=False, eid=edge.edge_id: self.remove_edge(eid))

        holder = _EdgeChipHolder(self, edge.edge_id)
        box = QtWidgets.QHBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        box.addWidget(chip)
        box.addWidget(unpatch)
        return holder

    # ── wiring interaction ───────────────────────────────────────────────

    def _register_chip(self, key, chip) -> None:
        chip.setProperty("wire_key", key)
        if self._pending == key:
            chip.setChecked(True)

    def _register_target_chip(self, group, sublane, chip) -> None:
        chip.setProperty("target_key", (group, sublane))

    def _chip_clicked(self, selector: str, sublane: Optional[str]) -> None:
        key = (selector, sublane)
        if self._pending == key:
            self._pending = None
        else:
            self._pending = key
        self._refresh_gating()
        self._sync_pending_checks()

    def _target_chip_clicked(self, group: str, sublane: str) -> None:
        if self._pending is None:
            self.hint_label.setText(
                "Click (or drag) a source chip first.")
            return
        selector, pending_sublane = self._pending
        if pending_sublane is None:
            self.add_group_patch(selector, group)
        else:
            if pending_sublane != sublane:
                return               # gated: only matching capability docks
            self.add_edge(selector, pending_sublane, group)
        self._pending = None
        self._refresh_gating()

    def _sync_pending_checks(self) -> None:
        for chip in self._board.findChildren(QtWidgets.QToolButton):
            key = chip.property("wire_key")
            if key is not None and chip.isCheckable():
                chip.setChecked(self._pending == tuple(key)
                                if isinstance(key, (list, tuple))
                                else False)

    def _refresh_gating(self) -> None:
        """While a wire is pending (clicked or dragged), disable every
        target chip that cannot dock it (the visible half of capability
        gating)."""
        pending = self._pending
        for chip in self._board.findChildren(QtWidgets.QToolButton):
            key = chip.property("target_key")
            if key is None:
                continue
            group, sublane = key
            if pending is None:
                chip.setEnabled(True)
                continue
            selector, pending_sublane = pending
            if pending_sublane is None:
                content = self.source_content(selector)
                chip.setEnabled(bool(content.get(sublane)))
            else:
                chip.setEnabled(sublane == pending_sublane and
                                self.can_dock(selector, sublane, group))
        if pending is None:
            self.hint_label.setText(self.HINT_IDLE)
        else:
            selector, sublane = pending
            info = self._sources_by_selector.get(selector)
            what = SUBLANE_LABELS.get(sublane, "GROUP")
            verb = "Drop on" if self._dragging else "Click"
            self.hint_label.setText(
                f"Wiring {info.name if info else '?'} · {what} - {verb} "
                f"a matching target capability (incompatible chips are "
                f"disabled).")
        self._canvas.update()

    def _edge_menu(self, edge: MorphEdge, chip: QtWidgets.QWidget,
                   pos: QtCore.QPoint) -> None:
        menu = QtWidgets.QMenu(self)

        mode_menu = menu.addMenu("Mode")
        for mode, label in (("copy", "Copy"),
                            ("copy_transform", "Copy + transform")):
            action = mode_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(edge.mode == mode)
            action.triggered.connect(
                lambda _=False, m=mode:
                self.set_edge_mode(edge.edge_id, m))
        if edge.sublane == "movement":
            regen_menu = mode_menu.addMenu("Regenerate")
            for strategy in REGENERATE_STRATEGIES:
                action = regen_menu.addAction(strategy)
                action.setCheckable(True)
                action.setChecked(edge.mode == "regenerate" and
                                  edge.regenerate_strategy == strategy)
                action.triggered.connect(
                    lambda _=False, s=strategy:
                    self.set_edge_mode(edge.edge_id, "regenerate", s))

        transform_menu = menu.addMenu("Transforms")
        current = {t.get("type") for t in edge.transforms}
        action = transform_menu.addAction("Phase offset...")
        action.setCheckable(True)
        action.setChecked("phase_offset" in current)
        action.triggered.connect(
            lambda _=False: self._ask_phase_offset(edge))
        action = transform_menu.addAction("Mirror")
        action.setCheckable(True)
        action.setChecked("mirror" in current)
        action.triggered.connect(
            lambda checked=False:
            self.set_transform(edge.edge_id, "mirror") if checked
            else self.clear_transform(edge.edge_id, "mirror"))
        action = transform_menu.addAction("Intensity scale...")
        action.setCheckable(True)
        action.setChecked("intensity_scale" in current)
        action.triggered.connect(
            lambda _=False: self._ask_intensity_scale(edge))
        subset_menu = transform_menu.addMenu("Spatial subset")
        none_action = subset_menu.addAction("(none)")
        none_action.triggered.connect(
            lambda _=False:
            self.clear_transform(edge.edge_id, "spatial_subset"))
        for selector in SUBSET_SELECTORS:
            action = subset_menu.addAction(selector)
            action.setCheckable(True)
            action.setChecked(any(
                t.get("type") == "spatial_subset"
                and t.get("selector") == selector
                for t in edge.transforms))
            action.triggered.connect(
                lambda _=False, s=selector:
                self.set_transform(edge.edge_id, "spatial_subset",
                                   selector=s))

        menu.addSeparator()
        up = menu.addAction("Priority +")
        up.triggered.connect(
            lambda _=False: self.bump_priority(edge.edge_id, +1))
        down = menu.addAction("Priority -")
        down.triggered.connect(
            lambda _=False: self.bump_priority(edge.edge_id, -1))
        menu.addSeparator()
        delete = menu.addAction("Delete edge")
        delete.triggered.connect(
            lambda _=False: self.remove_edge(edge.edge_id))
        menu.exec(chip.mapToGlobal(pos))

    def _ask_phase_offset(self, edge: MorphEdge) -> None:
        amount, ok = QtWidgets.QInputDialog.getDouble(
            self, "Phase offset", "Fraction of a cycle (0..1):",
            0.5, 0.0, 1.0, 3)
        if ok:
            self.set_transform(edge.edge_id, "phase_offset", amount=amount)

    def _ask_intensity_scale(self, edge: MorphEdge) -> None:
        factor, ok = QtWidgets.QInputDialog.getDouble(
            self, "Intensity scale", "Factor:", 0.8, 0.0, 4.0, 2)
        if ok:
            self.set_transform(edge.edge_id, "intensity_scale",
                               factor=factor)

    # ── painting data + refresh ──────────────────────────────────────────

    def edge_curves(self) -> List[Tuple[float, float, str, bool]]:
        """(source y, target y, colour, dashed) per plan edge, in canvas
        coordinates. Painting reads this; nothing else."""
        curves = []
        for edge in self.plan.edges:
            info = self._sources_by_selector.get(edge.source_group)
            if info is None:
                continue
            anchor = self._source_anchors.get(
                (edge.source_group, edge.sublane))
            if anchor is None:
                anchor = self._source_anchors.get(
                    (edge.source_group, None))
            target = self._target_anchors.get(edge.target_group)
            if anchor is None or target is None:
                continue
            dashed = self.is_group_patch(edge.source_group,
                                        edge.target_group)
            y1 = self._anchor_y(anchor)
            y2 = self._anchor_y(target)
            curves.append((y1, y2, info.colour, dashed, edge.edge_id))
        return curves

    @staticmethod
    def curve_path(y1: float, y2: float,
                   width: float) -> QtGui.QPainterPath:
        """The wire's shape. ONE definition, shared by the painter and
        the click hit-test - two copies would drift and clicks would
        stop landing on the line the user can see."""
        path = QtGui.QPainterPath()
        path.moveTo(0.0, float(y1))
        path.cubicTo(width * 0.45, float(y1),
                     width * 0.55, float(y2), float(width), float(y2))
        return path

    def edge_at(self, point: QtCore.QPoint,
                tolerance: float = 6.0) -> Optional[str]:
        """edge_id of the wire under a canvas-space point, else None."""
        width = float(self._canvas.width())
        for y1, y2, _colour, _dashed, edge_id in self.edge_curves():
            stroker = QtGui.QPainterPathStroker()
            stroker.setWidth(tolerance * 2.0)
            if stroker.createStroke(
                    self.curve_path(y1, y2, width)).contains(
                        QtCore.QPointF(point)):
                return edge_id
        return None

    def select_edge(self, edge_id: Optional[str]) -> None:
        """Select a wire (or clear with None). Selection is view state,
        never touches the plan."""
        if edge_id is not None and self.edge(edge_id) is None:
            return
        self._selected_edge_id = edge_id
        self._canvas.update()
        self.hint_label.setText(
            "Wire selected - press Delete to unpatch it."
            if edge_id else self.HINT_IDLE)

    @property
    def selected_edge_id(self) -> Optional[str]:
        return self._selected_edge_id

    # ── undo / redo ──────────────────────────────────────────────────────

    def _snapshot(self):
        """The plan's whole editable state as plain data.

        Serialized (not object references) so two snapshots compare with
        ``==`` and a mutation that changed nothing pushes no command."""
        return (
            [e.to_dict() for e in self.plan.edges],
            list(self.plan.protected_target_lanes),
            sorted(self._group_patches),
            {song: [e.to_dict() for e in edges]
             for song, edges in self.plan.song_overrides.items()},
        )

    def _restore_snapshot(self, snap) -> None:
        edges, protected, group_patches, overrides = snap
        # Mutate the SHARED plan object in place - the morph screen holds
        # the same instance (see MorphScreen.set_plan).
        self.plan.edges = [MorphEdge.from_dict(d) for d in edges]
        self.plan.protected_target_lanes = list(protected)
        self.plan.song_overrides = {
            song: [MorphEdge.from_dict(d) for d in raw]
            for song, raw in overrides.items()}
        self._group_patches = set(tuple(p) for p in group_patches)
        if self._selected_edge_id is not None and \
                self.edge(self._selected_edge_id) is None:
            self._selected_edge_id = None
        self._restoring = True
        try:
            self._notify()
        finally:
            self._restoring = False

    @contextlib.contextmanager
    def _undoable(self, text: str):
        """Record one undoable edit.

        Re-entrant by design: add_group_patch calls add_edge, and the
        whole fan-out has to undo as ONE step, not four."""
        if self._undo_depth or self._restoring:
            yield
            return
        before = self._snapshot()
        self._undo_depth += 1
        try:
            yield
        finally:
            self._undo_depth -= 1
        after = self._snapshot()
        if before != after:
            self.undo_stack.push(
                _PlanEditCommand(self, text, before, after))

    def _on_undo_index_changed(self, _index: int = 0) -> None:
        self._sync_undo_buttons()

    def _sync_undo_buttons(self) -> None:
        if getattr(self, "undo_btn", None) is None:
            return
        self.undo_btn.setEnabled(self.undo_stack.canUndo())
        self.redo_btn.setEnabled(self.undo_stack.canRedo())
        self.undo_btn.setToolTip(
            f"Undo {self.undo_stack.undoText()}"
            if self.undo_stack.canUndo() else "Nothing to undo")
        self.redo_btn.setToolTip(
            f"Redo {self.undo_stack.redoText()}"
            if self.undo_stack.canRedo() else "Nothing to redo")

    def can_undo(self) -> bool:
        return self.undo_stack.canUndo()

    def can_redo(self) -> bool:
        return self.undo_stack.canRedo()

    def undo(self) -> None:
        self.undo_stack.undo()

    def redo(self) -> None:
        self.undo_stack.redo()

    def edges_matching(self, source_group: Optional[str] = None,
                       target_group: Optional[str] = None) -> List[MorphEdge]:
        """Edges in a scope. Both None = the whole plan."""
        return [e for e in self.plan.edges
                if (source_group is None or e.source_group == source_group)
                and (target_group is None or e.target_group == target_group)]

    def clear_edges(self, source_group: Optional[str] = None,
                    target_group: Optional[str] = None) -> int:
        """Unpatch a whole scope at once; returns how many went.

        Pure model, no dialogs - the confirmation lives at the UI entry
        points so tests can drive this directly (QMessageBox is blocked
        in the suite, see tests/conftest)."""
        doomed = self.edges_matching(source_group, target_group)
        if not doomed:
            return 0
        doomed_ids = {e.edge_id for e in doomed}
        scope = target_group or source_group or "this plan"
        with self._undoable(f"Unpatch {len(doomed)} from {scope}"):
            self.plan.edges = [e for e in self.plan.edges
                               if e.edge_id not in doomed_ids]
            if self._selected_edge_id in doomed_ids:
                self._selected_edge_id = None
            # Drop any group-patch marker whose edges are all gone.
            for pair in list(self._group_patches):
                if not any(e.source_group == pair[0]
                           and e.target_group == pair[1]
                           for e in self.plan.edges):
                    self._group_patches.discard(pair)
            self._notify()
        return len(doomed)

    def confirm_and_clear(self, source_group: Optional[str] = None,
                          target_group: Optional[str] = None,
                          what: str = "every patch") -> int:
        """UI entry point: ask first when more than one wire would go.

        There is no undo in the patchbay, so a bulk removal that took one
        click to trigger should take one more to mean it."""
        doomed = self.edges_matching(source_group, target_group)
        if not doomed:
            self.hint_label.setText("Nothing patched there yet.")
            return 0
        if len(doomed) > 1:
            answer = QtWidgets.QMessageBox.question(
                self, "Unpatch",
                f"Remove {len(doomed)} patches from {what}?\n"
                f"This cannot be undone.",
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No)
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return 0
        return self.clear_edges(source_group, target_group)

    def finish_unpatch_drag(self, edge_id: str, pulled_out: bool) -> bool:
        """Resolve a patch dragged off its row.

        ``pulled_out`` is whether the drag ended unaccepted - i.e. the
        cable was pulled clear rather than dropped on something. Split
        out from the widget so the outcome is testable: QDrag.exec runs
        a platform loop that cannot be synthesized offscreen."""
        if not pulled_out:
            return False
        return self.remove_edge(edge_id)

    def remove_selected_edge(self) -> bool:
        if self._selected_edge_id is None:
            return False
        removed = self.remove_edge(self._selected_edge_id)
        self._selected_edge_id = None
        return removed

    def eventFilter(self, obj, event):
        """Keep the overlay covering the board as it resizes/scrolls."""
        if obj is self._board and event.type() in (
                QtCore.QEvent.Type.Resize, QtCore.QEvent.Type.Show):
            if self._overlay is not None:
                self._overlay.setGeometry(self._board.rect())
                self._overlay.raise_()
        return super().eventFilter(obj, event)

    def _anchor_y(self, widget: QtWidgets.QWidget) -> float:
        point = widget.mapTo(self._board,
                             QtCore.QPoint(0, widget.height() // 2))
        return float(point.y() - self._canvas.y())

    def _refresh_checker(self) -> None:
        parts = []
        for group, sublane, percent, is_gap in self.coverage_summary():
            label = f"{group} {SUBLANE_LABELS[sublane]} {percent}%"
            if is_gap:
                parts.append(f"<span style='color:#e5484d'>"
                             f"{label} GAP</span>")
            else:
                parts.append(label)
        self.checker_label.setText(
            " · ".join(parts) if parts
            else "No edges yet - nothing routed.")

    def _notify(self) -> None:
        self._rebuild_rows()
        self.changed.emit()
