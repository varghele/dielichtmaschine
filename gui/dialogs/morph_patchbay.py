# gui/dialogs/morph_patchbay.py
"""The morph patchbay (v1.5b phase 4, mockup 15-morph-patch-flow-6d).

Left column: the source show's lanes, lane-level rows by default,
expandable to their four sublane streams. Right column: the target
config's groups with capability chips. Wires are cubic curves in the
middle canvas, coloured per source lane; a dashed wire is a lane-level
patch that fans out to several sublanes at once. Capability vocabulary
is the locked 1:1 mapping: INTENSITY / COLOUR / POSITION / BEAM ==
dimmer / colour / movement / special.

Interaction contract (kept deliberately testable - every mutation is a
plain method on the widget; painting only reads):

- Wiring: click a source chip, then a target capability chip. While a
  wire is pending, incompatible target chips are disabled - only the
  matching capability docks (the mockup's core rule). Clicking the
  pending chip again cancels. A collapsed lane row wires the whole
  lane: every sublane the lane carries that the target renders.
- POSITION on a lane with no movement content shows as a ghost chip;
  wiring it creates a ``regenerate`` edge (strategy ``manual`` until
  changed) - the design's "movement onto groups that had none" path.
- Edges: each target row lists its incoming edges as chips; the wire
  colour matches the source lane. Right-click an edge chip for mode
  (copy / copy+transform / regenerate + strategy), transforms
  (phase_offset amount, mirror, intensity_scale factor, spatial_subset
  selector), priority and delete. Fan-in priority uses the menu's
  "Priority +" / "Priority -" pair instead of drag-reorder: the edge
  chips wrap in a flow, so a drag order would be ambiguous to read
  and to test; the +/- pair maps 1:1 onto MorphEdge.priority. An edge
  carrying transforms wears the mockup's filter marker.
- Lock: the padlock button per target row round-trips
  plan.protected_target_lanes (re-morph leaves the lane untouched).
- AUTO-SUGGEST prefills edges by source lane primary-group
  lighting_role first, capability overlap second (design doc 8). It
  only ever ADDS edges the user can delete - manual-first stands.
- The checker strip at the bottom shows live per-group coverage from
  utils/morph/checker (worst case across songs); 0% on a capability
  the group has renders as a red gap chip.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtSignal

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


class LaneInfo:
    """Display metadata for one distinct source lane (by lane_id)."""

    def __init__(self, lane_id: str, name: str, song: str, colour: str,
                 content: Dict[str, int]):
        self.lane_id = lane_id
        self.name = name
        self.song = song
        self.colour = colour
        self.content = content       # sublane -> block count (0 omitted)


def _lane_catalog(source_config) -> List[LaneInfo]:
    """Every distinct lane across the setlist, in song order."""
    infos: List[LaneInfo] = []
    seen = set()
    multi = len(source_config.songs) > 1
    for song_name, song in source_config.songs.items():
        if not song.timeline_data:
            continue
        for lane in song.timeline_data.lanes:
            if lane.lane_id in seen:
                continue
            seen.add(lane.lane_id)
            content = {}
            for sublane, attr in SUBLANE_ATTRS.items():
                count = sum(len(getattr(lb, attr))
                            for lb in lane.light_blocks)
                if count:
                    content[sublane] = count
            name = lane.name
            if multi:
                name = f"{song_name} · {lane.name}"
            infos.append(LaneInfo(
                lane.lane_id, name, song_name,
                LANE_COLOURS[len(infos) % len(LANE_COLOURS)], content))
    return infos


class EdgeCanvas(QtWidgets.QWidget):
    """Dumb wire painter: asks the patchbay for curves, draws them."""

    def __init__(self, patchbay: "MorphPatchbay"):
        super().__init__(patchbay._board)
        self._patchbay = patchbay
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        width = self.width()
        for curve in self._patchbay.edge_curves():
            y1, y2, colour, dashed = curve
            pen = QtGui.QPen(QtGui.QColor(colour), 2.0)
            if dashed:
                pen.setStyle(Qt.PenStyle.DashLine)
                pen.setWidthF(1.5)
            painter.setPen(pen)
            path = QtGui.QPainterPath()
            path.moveTo(0.0, float(y1))
            path.cubicTo(width * 0.45, float(y1),
                         width * 0.55, float(y2), float(width), float(y2))
            painter.drawPath(path)
        painter.end()


class MorphPatchbay(QtWidgets.QWidget):
    """The routing editor. Owns a MorphPlan and mutates ONLY the plan
    (and its protected_target_lanes); configs are read-only here."""

    changed = pyqtSignal()

    def __init__(self, source_config, target_config,
                 plan: Optional[MorphPlan] = None, parent=None):
        super().__init__(parent)
        self.source_config = source_config
        self.target_config = target_config
        self.plan = plan if plan is not None else MorphPlan()

        self._lanes = _lane_catalog(source_config)
        self._lanes_by_id = {info.lane_id: info for info in self._lanes}
        self._caps = group_capabilities(target_config)
        self._expanded: set = set()
        #: (lane_id, target_group) pairs wired as one lane-level patch
        self._lane_patches: set = set()
        self._pending: Optional[Tuple[str, Optional[str]]] = None
        self._source_anchors: Dict[Tuple[str, Optional[str]],
                                   QtWidgets.QWidget] = {}
        self._target_anchors: Dict[str, QtWidgets.QWidget] = {}
        self._build_ui()
        self._derive_lane_patches()
        self._rebuild_rows()

    # ── model operations (tests drive these directly) ────────────────────

    def lane_content(self, lane_id: str) -> Dict[str, int]:
        info = self._lanes_by_id.get(lane_id)
        return dict(info.content) if info else {}

    def edge(self, edge_id: str) -> Optional[MorphEdge]:
        for e in self.plan.edges:
            if e.edge_id == edge_id:
                return e
        return None

    def can_dock(self, lane_id: str, sublane: str,
                 target_group: str) -> bool:
        """Capability gating: the target group must render the sublane,
        and the lane must carry it (POSITION alone may be empty - that
        is the regenerate path)."""
        if sublane not in self._caps.get(target_group, set()):
            return False
        content = self.lane_content(lane_id)
        if sublane == "movement":
            return True          # empty movement wires as regenerate
        return bool(content.get(sublane))

    def add_edge(self, lane_id: str, sublane: str, target_group: str,
                 mode: Optional[str] = None) -> Optional[MorphEdge]:
        """One wire; returns None (adds nothing) when the dock is
        incompatible or the identical edge already exists."""
        if not self.can_dock(lane_id, sublane, target_group):
            return None
        for e in self.plan.edges:
            if (e.source_lane_id == lane_id and e.sublane == sublane
                    and e.target_group == target_group):
                return None
        info = self._lanes_by_id[lane_id]
        if mode is None:
            if sublane == "movement" and not info.content.get("movement"):
                mode = "regenerate"
            else:
                mode = "copy"
        edge = MorphEdge(source_lane_id=lane_id,
                         source_lane_name=info.name, sublane=sublane,
                         target_group=target_group, mode=mode)
        self.plan.edges.append(edge)
        self._notify()
        return edge

    def add_lane_patch(self, lane_id: str,
                       target_group: str) -> List[MorphEdge]:
        """Lane-level wire: every sublane the lane carries that the
        target renders, marked as one dashed fan-out."""
        added = []
        content = self.lane_content(lane_id)
        for sublane in SUBLANE_ORDER:
            if not content.get(sublane):
                continue
            edge = self.add_edge(lane_id, sublane, target_group)
            if edge is not None:
                added.append(edge)
        if len(added) >= 2:
            self._lane_patches.add((lane_id, target_group))
            self._notify()
        return added

    def remove_edge(self, edge_id: str) -> bool:
        edge = self.edge(edge_id)
        if edge is None:
            return False
        self.plan.edges.remove(edge)
        pair = (edge.source_lane_id, edge.target_group)
        if pair in self._lane_patches and not any(
                e.source_lane_id == pair[0] and e.target_group == pair[1]
                for e in self.plan.edges):
            self._lane_patches.discard(pair)
        self._notify()
        return True

    def set_edge_mode(self, edge_id: str, mode: str,
                      strategy: str = "manual") -> None:
        edge = self.edge(edge_id)
        if edge is None:
            return
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
        edge.transforms = [t for t in edge.transforms
                           if t.get("type") != kind]
        if not edge.transforms and edge.mode == "copy_transform":
            edge.mode = "copy"
        self._notify()

    def bump_priority(self, edge_id: str, delta: int) -> None:
        edge = self.edge(edge_id)
        if edge is None:
            return
        edge.priority = max(0, edge.priority + delta)
        self._notify()

    def set_lock(self, target_group: str, locked: bool) -> None:
        """Round-trips plan.protected_target_lanes (design doc 5.5)."""
        protected = set(self.plan.protected_target_lanes)
        if locked:
            protected.add(target_group)
        else:
            protected.discard(target_group)
        self.plan.protected_target_lanes = sorted(protected)
        self._notify()

    def is_locked(self, target_group: str) -> bool:
        return target_group in self.plan.protected_target_lanes

    def is_lane_patch(self, lane_id: str, target_group: str) -> bool:
        return (lane_id, target_group) in self._lane_patches

    def set_expanded(self, lane_id: str, expanded: bool) -> None:
        if expanded:
            self._expanded.add(lane_id)
        else:
            self._expanded.discard(lane_id)
        self._rebuild_rows()

    def auto_suggest(self) -> List[MorphEdge]:
        """Prefill: for each source lane pick the best target group by
        (same lighting_role, capability overlap, name) and wire every
        compatible sublane. Adds only; never edits or removes."""
        added: List[MorphEdge] = []
        for info in self._lanes:
            if not info.content:
                continue
            role = self._lane_role(info)
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
                continue
            candidates.sort()
            best = candidates[0][2]
            for sublane in SUBLANE_ORDER:
                if info.content.get(sublane):
                    edge = self.add_edge(info.lane_id, sublane, best)
                    if edge is not None:
                        added.append(edge)
        if added:
            self._notify()
        return added

    def _lane_role(self, info: LaneInfo) -> str:
        for song in self.source_config.songs.values():
            if not song.timeline_data:
                continue
            for lane in song.timeline_data.lanes:
                if lane.lane_id != info.lane_id:
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
        self._lane_patches.clear()
        self._derive_lane_patches()
        self._rebuild_rows()
        self.changed.emit()

    def _derive_lane_patches(self) -> None:
        """A loaded plan carries no widget state: any (lane, target)
        pair wired on 2+ sublanes reads as a lane-level patch."""
        pairs: Dict[Tuple[str, str], set] = {}
        for edge in self.plan.edges:
            pairs.setdefault(
                (edge.source_lane_id, edge.target_group),
                set()).add(edge.sublane)
        for pair, sublanes in pairs.items():
            if len(sublanes) >= 2:
                self._lane_patches.add(pair)

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
        self.hint_label = QtWidgets.QLabel(
            "Click a source chip, then a matching target capability. "
            "Solid = 1:1 · dashed = lane patch.")
        header.addWidget(self.hint_label, 1)
        self.suggest_btn = QtWidgets.QPushButton("Auto-suggest")
        self.suggest_btn.setToolTip(
            "Prefill edges by lighting role and capability overlap. "
            "Only adds wires - delete any you do not want.")
        self.suggest_btn.clicked.connect(self.auto_suggest)
        header.addWidget(self.suggest_btn)
        layout.addLayout(header)

        self._board = QtWidgets.QWidget()
        board_layout = QtWidgets.QHBoxLayout(self._board)
        board_layout.setContentsMargins(0, 0, 0, 0)
        board_layout.setSpacing(0)

        self._source_column = QtWidgets.QVBoxLayout()
        self._source_column.setSpacing(8)
        source_holder = QtWidgets.QWidget()
        source_holder.setLayout(self._source_column)
        source_holder.setFixedWidth(280)

        self._canvas = EdgeCanvas(self)
        self._canvas.setMinimumWidth(160)

        self._target_column = QtWidgets.QVBoxLayout()
        self._target_column.setSpacing(8)
        target_holder = QtWidgets.QWidget()
        target_holder.setLayout(self._target_column)
        target_holder.setFixedWidth(320)

        board_layout.addWidget(source_holder)
        board_layout.addWidget(self._canvas, 1)
        board_layout.addWidget(target_holder)

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

    def _chip(self, text: str, colour: str = "",
              ghost: bool = False) -> QtWidgets.QToolButton:
        chip = QtWidgets.QToolButton()
        chip.setText(text)
        chip.setCheckable(True)
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        border = colour or "#3a3a3a"
        style = (f"QToolButton {{ border: 1px solid {border};"
                 f" padding: 2px 8px; }}"
                 f" QToolButton:checked {{ background: {border}; }}"
                 f" QToolButton:disabled {{ color: #5c6068;"
                 f" border-color: #2d2d2d; }}")
        if ghost:
            style = style.replace("1px solid", "1px dashed")
        chip.setStyleSheet(style)
        return chip

    def _row_frame(self, colour: str) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setStyleSheet(
            f"QFrame {{ border: 1px solid #2d2d2d;"
            f" border-left: 3px solid {colour}; }}"
            f" QLabel {{ border: none; }}")
        frame.setMinimumHeight(ROW_HEIGHT)
        return frame

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

        for info in self._lanes:
            self._source_column.addWidget(self._build_source_row(info))
        self._source_column.addStretch(1)

        for group in self.target_config.groups:
            self._target_column.addWidget(self._build_target_row(group))
        self._target_column.addStretch(1)

        self._refresh_gating()
        self._refresh_checker()
        self._canvas.update()

    def _build_source_row(self, info: LaneInfo) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout(holder)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(4)

        frame = self._row_frame(info.colour)
        row = QtWidgets.QHBoxLayout(frame)
        row.setContentsMargins(8, 4, 8, 4)
        expand = QtWidgets.QToolButton()
        expand.setText("-" if info.lane_id in self._expanded else "+")
        expand.setToolTip("Expand to the four sublane streams")
        expand.clicked.connect(
            lambda _=False, lid=info.lane_id:
            self.set_expanded(lid, lid not in self._expanded))
        row.addWidget(expand)
        name = QtWidgets.QLabel(info.name)
        row.addWidget(name, 1)

        if info.lane_id in self._expanded:
            # Expanded: the lane header is not wireable; each sublane
            # stream gets its own chip row + anchor.
            for sublane in SUBLANE_ORDER:
                has_content = bool(info.content.get(sublane))
                if not has_content and sublane != "movement":
                    continue
                sub = self._row_frame(info.colour)
                sub_row = QtWidgets.QHBoxLayout(sub)
                sub_row.setContentsMargins(24, 4, 8, 4)
                count = info.content.get(sublane, 0)
                sub_row.addWidget(QtWidgets.QLabel(
                    f"{count}x" if count else "empty"))
                sub_row.addStretch(1)
                chip = self._chip(SUBLANE_LABELS[sublane], info.colour,
                                  ghost=not has_content)
                if not has_content:
                    chip.setToolTip(
                        "No movement authored - wiring this creates a "
                        "REGENERATE edge")
                chip.clicked.connect(
                    lambda _=False, lid=info.lane_id, s=sublane:
                    self._chip_clicked(lid, s))
                self._register_chip((info.lane_id, sublane), chip)
                sub_row.addWidget(chip)
                self._source_anchors[(info.lane_id, sublane)] = sub
                vbox.addWidget(sub)
        else:
            chip = self._chip("LANE", info.colour)
            chip.setToolTip(
                "Wire the whole lane: every stream it carries that the "
                "target renders (dashed fan-out)")
            chip.clicked.connect(
                lambda _=False, lid=info.lane_id:
                self._chip_clicked(lid, None))
            self._register_chip((info.lane_id, None), chip)
            row.addWidget(chip)
            self._source_anchors[(info.lane_id, None)] = frame

        vbox.insertWidget(0, frame)
        return holder

    def _build_target_row(self, group: str) -> QtWidgets.QWidget:
        colour = "#8d9299"
        for edge in self.plan.edges:
            if edge.target_group == group:
                info = self._lanes_by_id.get(edge.source_lane_id)
                if info:
                    colour = info.colour
                break
        frame = self._row_frame(colour)
        vbox = QtWidgets.QVBoxLayout(frame)
        vbox.setContentsMargins(8, 4, 8, 4)
        vbox.setSpacing(4)

        row = QtWidgets.QHBoxLayout()
        lock = QtWidgets.QToolButton()
        lock.setCheckable(True)
        lock.setChecked(self.is_locked(group))
        lock.setText("LOCK")
        lock.setToolTip(
            "Protect this target lane: re-morph leaves it untouched")
        lock.toggled.connect(
            lambda checked, g=group: self.set_lock(g, checked))
        row.addWidget(lock)

        for sublane in SUBLANE_ORDER:
            if sublane not in self._caps.get(group, set()):
                continue
            chip = self._chip(SUBLANE_LABELS[sublane], colour)
            chip.setCheckable(False)
            chip.clicked.connect(
                lambda _=False, g=group, s=sublane:
                self._target_chip_clicked(g, s))
            self._register_target_chip(group, sublane, chip)
            row.addWidget(chip)

        row.addStretch(1)
        fixtures = getattr(self.target_config.groups.get(group),
                           "fixtures", [])
        row.addWidget(QtWidgets.QLabel(f"{group} {len(fixtures)}x"))
        vbox.addLayout(row)

        edges_here = [e for e in self.plan.edges if e.target_group == group]
        if edges_here:
            edge_row = QtWidgets.QHBoxLayout()
            edge_row.setSpacing(4)
            for edge in sorted(edges_here, key=lambda e: -e.priority):
                edge_row.addWidget(self._build_edge_chip(edge))
            edge_row.addStretch(1)
            vbox.addLayout(edge_row)

        self._target_anchors[group] = frame
        return frame

    def _build_edge_chip(self, edge: MorphEdge) -> QtWidgets.QToolButton:
        info = self._lanes_by_id.get(edge.source_lane_id)
        colour = info.colour if info else "#8d9299"
        text = f"{edge.source_lane_name} · {SUBLANE_LABELS[edge.sublane]}"
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
        return chip

    # ── wiring interaction ───────────────────────────────────────────────

    def _register_chip(self, key, chip) -> None:
        chip.setProperty("wire_key", key)
        if self._pending == key:
            chip.setChecked(True)

    def _register_target_chip(self, group, sublane, chip) -> None:
        chip.setProperty("target_key", (group, sublane))

    def _chip_clicked(self, lane_id: str, sublane: Optional[str]) -> None:
        key = (lane_id, sublane)
        if self._pending == key:
            self._pending = None
        else:
            self._pending = key
        self._refresh_gating()
        self._sync_pending_checks()

    def _target_chip_clicked(self, group: str, sublane: str) -> None:
        if self._pending is None:
            self.hint_label.setText("Click a source chip first.")
            return
        lane_id, pending_sublane = self._pending
        if pending_sublane is None:
            self.add_lane_patch(lane_id, group)
        else:
            if pending_sublane != sublane:
                return               # gated: only matching capability docks
            self.add_edge(lane_id, pending_sublane, group)
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
        """While a wire is pending, disable every target chip that
        cannot dock it (the visible half of capability gating)."""
        pending = self._pending
        for chip in self._board.findChildren(QtWidgets.QToolButton):
            key = chip.property("target_key")
            if key is None:
                continue
            group, sublane = key
            if pending is None:
                chip.setEnabled(True)
                continue
            lane_id, pending_sublane = pending
            if pending_sublane is None:
                content = self.lane_content(lane_id)
                chip.setEnabled(bool(content.get(sublane)))
            else:
                chip.setEnabled(sublane == pending_sublane and
                                self.can_dock(lane_id, sublane, group))
        if pending is None:
            self.hint_label.setText(
                "Click a source chip, then a matching target capability. "
                "Solid = 1:1 · dashed = lane patch.")
        else:
            lane_id, sublane = pending
            info = self._lanes_by_id.get(lane_id)
            what = SUBLANE_LABELS.get(sublane, "LANE")
            self.hint_label.setText(
                f"Wiring {info.name if info else '?'} · {what} - click a "
                f"matching target capability (incompatible chips are "
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
            info = self._lanes_by_id.get(edge.source_lane_id)
            if info is None:
                continue
            anchor = self._source_anchors.get(
                (edge.source_lane_id, edge.sublane))
            if anchor is None:
                anchor = self._source_anchors.get(
                    (edge.source_lane_id, None))
            target = self._target_anchors.get(edge.target_group)
            if anchor is None or target is None:
                continue
            dashed = self.is_lane_patch(edge.source_lane_id,
                                        edge.target_group)
            y1 = self._anchor_y(anchor)
            y2 = self._anchor_y(target)
            curves.append((y1, y2, info.colour, dashed))
        return curves

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
