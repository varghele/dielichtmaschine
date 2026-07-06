# visualizer/renderer/gdtf_draw_plan.py
"""Pure (GL-free) draw plan for GDTF mesh chassis rendering.

Walks a GdtfData geometry tree into a flat list of drawable items, each
carrying its kinematic chain: the ordered per-node transforms from the
root down, with markers where the live pan / tilt rotations insert
(GDTF Axis nodes). The GL side (GdtfMeshChassisGeometry) composes the
chain per frame; this module is plain numpy so the chain math is
unit-testable headless.

GDTF conventions (docs/gdtf-integration-plan.md Phase 3): right-handed
Z-up, origin at the base plate, node Position matrices are relative to
the PARENT, pan axes are Z-aligned, tilt axes X-aligned, Beam nodes
emit along their local -Z. The chassis-local frame of the renderer is
also Z-up (visualizer/renderer/reference.md), so no global basis change
is needed; only the beam cone (built along +Z) needs a 180-degree flip
onto -Z at the Beam node.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from utils.gdtf_data import GdtfData, GdtfGeometryNode


@dataclass
class ChainStep:
    """One node on the path from root to the drawn node."""
    matrix: np.ndarray                 # 4x4 float64, relative to parent
    axis_attribute: Optional[str]      # 'Pan' | 'Tilt' | None
    """When set, the live rotation for that attribute applies AFTER this
    node's matrix (rotating everything below the axis node)."""


@dataclass
class DrawItem:
    """One drawable node: a model reference plus its kinematic chain."""
    node_name: str
    model_name: Optional[str]          # GdtfModel to draw (None: nothing)
    chain: List[ChainStep] = field(default_factory=list)
    is_beam: bool = False              # Beam node: light emission point

    def compose(self, pan_deg: float = 0.0, tilt_deg: float = 0.0) -> np.ndarray:
        """World-from-root transform with live pan/tilt applied."""
        m = np.eye(4)
        for step in self.chain:
            m = m @ step.matrix
            if step.axis_attribute == 'Pan':
                m = m @ _rot_z(pan_deg)
            elif step.axis_attribute == 'Tilt':
                m = m @ _rot_x(tilt_deg)
        return m


def _rot_z(deg: float) -> np.ndarray:
    r = np.radians(deg)
    c, s = np.cos(r), np.sin(r)
    m = np.eye(4)
    m[0, 0], m[0, 1], m[1, 0], m[1, 1] = c, -s, s, c
    return m


def _rot_x(deg: float) -> np.ndarray:
    r = np.radians(deg)
    c, s = np.cos(r), np.sin(r)
    m = np.eye(4)
    m[1, 1], m[1, 2], m[2, 1], m[2, 2] = c, -s, s, c
    return m


def _resolve_axis(node: GdtfGeometryNode) -> Optional[str]:
    """Axis attribution with a name-convention fallback for wild files
    whose Axis nodes are not linked from the DMX channels (seen on the
    MAC Aura Share file, docs/gdtf-coverage-note.md)."""
    if node.axis_attribute in ('Pan', 'Tilt'):
        return node.axis_attribute
    if node.node_type == 'Axis':
        name = node.name.lower()
        if 'yoke' in name or 'pan' in name:
            return 'Pan'
        if 'head' in name or 'tilt' in name:
            return 'Tilt'
    return None


def build_draw_plan(gdtf: GdtfData, mode_name: str) -> List[DrawItem]:
    """Flatten the geometry tree for one DMX mode into draw items.

    GeometryReference nodes are expanded by instancing the referenced
    top-level subtree at the reference's transform (one instance per
    reference node; DMX break offsets are the emitters' concern, not
    the chassis'). Nodes without a model still contribute their
    transform to children. Beam nodes become is_beam items.
    """
    roots_by_name = {t.name: t for t in gdtf.geometry_trees}
    root_name = gdtf.mode_root_geometry.get(mode_name)
    root = roots_by_name.get(root_name) if root_name else None
    if root is None and gdtf.geometry_trees:
        root = gdtf.geometry_trees[0]
    if root is None:
        return []

    items: List[DrawItem] = []

    def visit(node: GdtfGeometryNode, chain: List[ChainStep], depth: int) -> None:
        if depth > 16:   # wild-file cycle guard (reference loops)
            return
        step = ChainStep(
            matrix=np.asarray(node.position, dtype=np.float64),
            axis_attribute=_resolve_axis(node),
        )
        chain = chain + [step]
        if node.node_type == 'Reference' and node.reference_to:
            target = roots_by_name.get(node.reference_to)
            if target is not None:
                # Instance the referenced subtree under this transform;
                # keep the reference's own model (if any) as a fallback.
                visit_children_of = target
                items_before = len(items)
                visit(visit_children_of, chain[:-1] + [ChainStep(step.matrix, step.axis_attribute)], depth + 1)
                if len(items) == items_before and node.model:
                    items.append(DrawItem(node.name, node.model, chain))
                return
        if node.model or node.beam is not None:
            items.append(DrawItem(
                node_name=node.name,
                model_name=node.model,
                chain=chain,
                is_beam=node.beam is not None,
            ))
        for child in node.children:
            visit(child, chain, depth + 1)

    visit(root, [], 0)
    return items
