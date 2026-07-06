# utils/gdtf_data.py
"""GDTF-native data carried on FixtureDefinition (the "richer lane").

The GDTF import serves DMX channel semantics through the shared QLC
preset vocabulary (utils/gdtf_loader.py transpile), because for playback
and export the formats are equally expressive. Everything GDTF knows
*beyond* that - the geometry tree with per-node transforms, 3D model
references, beam photometrics, per-function physical values - lives
here, structurally, so consumers of the rich data never go through the
transpiled channel model:

- Phase 3 (mesh rendering) reads ``models`` + ``geometry_trees`` and
  pulls GLB bytes from the archive via ``GdtfModel.archive_paths``.
- v1.5a (stage-relative movement) reads Axis nodes and the physical
  pan/tilt ranges in ``channel_physical`` for inverse kinematics.

Pure dataclasses, no pygdtf dependency: built by the loader, consumed
anywhere. ``FixtureDefinition.gdtf`` is None for .qxf-sourced fixtures -
that asymmetry is the "GDTF primary, .qxf maintained" relationship made
structural.

Coordinate conventions (GDTF, DIN SPEC 15800): right-handed, Z-up,
origin at the center of the base plate, fixtures authored hanging.
``position`` matrices are relative to the parent node, NOT the root.
Beam nodes emit along -Z of their node. Do not mix with stage or
renderer frames; see docs/gdtf-integration-plan.md §5 Phase 3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

IDENTITY_MATRIX = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]


@dataclass
class GdtfBeam:
    """Photometrics of one <Beam> geometry node (emits along its -Z)."""
    name: str
    beam_angle: float           # degrees
    field_angle: float          # degrees
    luminous_flux: float        # lumens
    color_temperature: float    # Kelvin (0 if unspecified)
    beam_type: str              # 'Wash' | 'Spot' | 'None' | ... ('' if absent)
    power_consumption: float    # watts (0 if unspecified)


@dataclass
class GdtfModel:
    """One <Model>: dimensions the mesh scales to, plus archive files."""
    name: str
    length_m: float             # X extent, meters
    width_m: float              # Y extent, meters
    height_m: float             # Z extent, meters
    primitive_type: str         # fallback when no file: Cube/Cylinder/Base/Yoke/Head/...
    file: str                   # base name without extension ('' if none)
    archive_paths: List[str] = field(default_factory=list)
    """Paths inside the .gdtf zip matching this model's file, e.g.
    ['models/gltf/head.glb', 'models/3ds/head.3ds']. Empty when the
    model is primitive-only. Read the bytes via zipfile on
    FixtureDefinition.path."""

    def glb_path(self) -> Optional[str]:
        """The default-LOD GLB inside the archive, if any (spec-preferred
        format; low/high LOD variants live in gltf_low/ / gltf_high/)."""
        for p in self.archive_paths:
            if p.lower().startswith('models/gltf/') and p.lower().endswith('.glb'):
                return p
        return None


@dataclass
class GdtfGeometryNode:
    """One node of the geometry tree (kinematic chain + mesh placement)."""
    name: str
    node_type: str              # 'Geometry' | 'Axis' | 'Beam' | 'Reference' | other GDTF kinds
    model: Optional[str]        # GdtfModel name, None for modelless nodes
    position: List[List[float]] = field(default_factory=lambda: [row[:] for row in IDENTITY_MATRIX])
    """4x4 row-major transform relative to the PARENT node."""
    children: List['GdtfGeometryNode'] = field(default_factory=list)
    axis_attribute: Optional[str] = None
    """For Axis nodes: the GDTF attribute that drives it ('Pan'/'Tilt'),
    resolved from the DMX channels' Geometry links. None if undriven."""
    beam: Optional[GdtfBeam] = None
    """For Beam nodes: the photometrics."""
    reference_to: Optional[str] = None
    """For Reference nodes: name of the top-level geometry instanced here."""
    break_offsets: List[int] = field(default_factory=list)
    """For Reference nodes: per-break DMX base offsets (1-based)."""

    def iter_subtree(self) -> Iterator['GdtfGeometryNode']:
        yield self
        for child in self.children:
            yield from child.iter_subtree()


@dataclass
class GdtfChannelPhysical:
    """Physical value range of one DMX channel (full resolution, straight
    from the GDTF channel functions; the transpiled capability ranges are
    scaled to the coarse byte and lose this)."""
    mode: str                   # DMX mode name
    attribute: str              # GDTF attribute ('Pan', 'Zoom', ...)
    geometry: str               # geometry node the channel drives
    channel_index: int          # 0-based coarse index within the mode footprint
    physical_from: float
    physical_to: float


@dataclass
class GdtfData:
    """Everything GDTF-native on a FixtureDefinition (None for .qxf)."""
    fixture_type_id: Optional[str]
    data_version: str
    mode_root_geometry: Dict[str, str] = field(default_factory=dict)
    """DMX mode name -> name of the geometry subtree it instantiates."""
    models: Dict[str, GdtfModel] = field(default_factory=dict)
    geometry_trees: List[GdtfGeometryNode] = field(default_factory=list)
    channel_physical: List[GdtfChannelPhysical] = field(default_factory=list)

    def iter_nodes(self) -> Iterator[GdtfGeometryNode]:
        for root in self.geometry_trees:
            yield from root.iter_subtree()

    def find_node(self, name: str) -> Optional[GdtfGeometryNode]:
        return next((n for n in self.iter_nodes() if n.name == name), None)

    def beams(self) -> List[GdtfGeometryNode]:
        return [n for n in self.iter_nodes() if n.beam is not None]

    def axes(self) -> List[GdtfGeometryNode]:
        return [n for n in self.iter_nodes() if n.node_type == 'Axis']
