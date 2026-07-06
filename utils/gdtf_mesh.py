# utils/gdtf_mesh.py
"""GLB mesh extraction + baking for GDTF fixture models (plan Phase 3).

Renderer-agnostic: numpy in, numpy out, no GL and no Qt, so the bake is
unit-testable headless. The visualizer uploads the baked arrays into
ModernGL buffers (interleaved position+normal+uv, indexed).

Reality checks baked in (from Share files, docs/gdtf-coverage-note.md):
- Fixtures ship mixed formats (e.g. MagicBlade R: yoke/base as 3DS only,
  head as GLB). Callers fall back per NODE, not per fixture.
- Mesh units in the wild are often millimeters; the GDTF spec scales
  meshes to the Model node's Length/Width/Height (meters). The bake
  fits the mesh bounding box to those dims per axis WITHOUT moving the
  pivot: geometry-node transforms and rotation axes reference the
  authored origin.
- A GLB may be a multi-node scene; nodes are flattened with their
  transforms. The first PBR material's base color and texture win
  (single-material chassis are the norm for fixture bodies).
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np


@dataclass
class BakedMesh:
    """GL-ready mesh data: interleaved float32 [x y z nx ny nz u v]."""
    vertex_data: np.ndarray          # (N, 8) float32
    indices: np.ndarray              # (M,) uint32
    base_color: Tuple[float, float, float, float]
    texture_png: Optional[bytes]     # baseColor texture as PNG bytes, or None

    @property
    def vertex_count(self) -> int:
        return len(self.vertex_data)

    @property
    def triangle_count(self) -> int:
        return len(self.indices) // 3


# (gdtf archive path, inner model path) -> BakedMesh or None (bake failure)
_bake_cache: Dict[Tuple[str, str], Optional[BakedMesh]] = {}


def clear_mesh_cache() -> None:
    _bake_cache.clear()


def load_glb_mesh(gdtf_path: str, archive_path: str,
                  target_dims_m: Optional[Tuple[float, float, float]] = None,
                  max_vertices: int = 60000) -> Optional[BakedMesh]:
    """Bake one GLB from inside a .gdtf archive. None on any failure
    (missing file, unparseable, degenerate, over the vertex cap) - the
    caller falls back to the procedural chassis for that node.

    target_dims_m: GDTF Model (Length, Width, Height) in meters; the
    mesh bounding box is fitted to it per axis, pivot preserved.
    """
    key = (gdtf_path, archive_path)
    if key in _bake_cache:
        return _bake_cache[key]
    baked = None
    try:
        baked = _bake(gdtf_path, archive_path, target_dims_m, max_vertices)
    except Exception as e:
        print(f"GDTF mesh bake failed ({archive_path} in {gdtf_path}): {e}")
    _bake_cache[key] = baked
    return baked


def _bake(gdtf_path, archive_path, target_dims_m, max_vertices):
    import trimesh

    with zipfile.ZipFile(gdtf_path) as archive:
        payload = archive.read(archive_path)
    scene = trimesh.load(io.BytesIO(payload), file_type='glb')

    meshes = []
    if isinstance(scene, trimesh.Scene):
        for node_name in scene.graph.nodes_geometry:
            transform, geom_name = scene.graph[node_name]
            geom = scene.geometry[geom_name]
            if not isinstance(geom, trimesh.Trimesh) or geom.is_empty:
                continue
            mesh = geom.copy()
            mesh.apply_transform(transform)
            meshes.append((mesh, geom))
    elif isinstance(scene, trimesh.Trimesh):
        meshes.append((scene, scene))
    if not meshes:
        return None

    total_vertices = sum(len(m.vertices) for m, _src in meshes)
    if total_vertices == 0 or total_vertices > max_vertices:
        print(f"GDTF mesh rejected ({archive_path}): {total_vertices} vertices "
              f"(cap {max_vertices})")
        return None

    # Material from the first mesh that has one
    base_color = (0.35, 0.35, 0.38, 1.0)
    texture_png = None
    for _mesh, src in meshes:
        material = getattr(getattr(src, 'visual', None), 'material', None)
        if material is None:
            continue
        factor = getattr(material, 'baseColorFactor', None)
        if factor is not None:
            f = np.asarray(factor, dtype=np.float64)
            if f.max() > 1.0:
                f = f / 255.0
            base_color = tuple(float(v) for v in (list(f) + [1.0])[:4])
        image = getattr(material, 'baseColorTexture', None)
        if image is not None:
            buf = io.BytesIO()
            image.convert('RGBA').save(buf, format='PNG')
            texture_png = buf.getvalue()
        break

    # Concatenate into one interleaved indexed buffer
    vertex_blocks, index_blocks, offset = [], [], 0
    for mesh, src in meshes:
        positions = np.asarray(mesh.vertices, dtype=np.float32)
        normals = np.asarray(mesh.vertex_normals, dtype=np.float32)
        uv = getattr(getattr(src, 'visual', None), 'uv', None)
        if uv is not None and len(uv) == len(positions):
            uv = np.asarray(uv, dtype=np.float32)
        else:
            uv = np.zeros((len(positions), 2), dtype=np.float32)
        vertex_blocks.append(np.hstack([positions, normals, uv]))
        index_blocks.append(np.asarray(mesh.faces, dtype=np.uint32).reshape(-1) + offset)
        offset += len(positions)

    vertex_data = np.vstack(vertex_blocks).astype(np.float32)
    indices = np.concatenate(index_blocks).astype(np.uint32)

    # Fit bounding box to the Model dims per axis, pivot preserved
    # (scale about the authored origin, never translate).
    if target_dims_m is not None:
        extents = (vertex_data[:, :3].max(axis=0)
                   - vertex_data[:, :3].min(axis=0))
        scale = np.ones(3, dtype=np.float32)
        for axis in range(3):
            if extents[axis] > 1e-9 and target_dims_m[axis] > 0:
                scale[axis] = target_dims_m[axis] / extents[axis]
        # Wild meshes are usually uniformly mis-scaled (mm vs m); apply
        # per-axis only when dims genuinely disagree, else keep uniform
        # to avoid skewing detail on slightly-off boxes.
        if scale.max() > 1e-9 and scale.max() / max(scale.min(), 1e-9) < 1.15:
            scale[:] = float(np.median(scale))
        vertex_data[:, :3] *= scale
        # Normals are direction data; renormalize after non-uniform scale.
        if not np.allclose(scale, scale[0]):
            n = vertex_data[:, 3:6] / scale
            lengths = np.linalg.norm(n, axis=1, keepdims=True)
            lengths[lengths < 1e-9] = 1.0
            vertex_data[:, 3:6] = n / lengths

    return BakedMesh(vertex_data=vertex_data, indices=indices,
                     base_color=base_color, texture_png=texture_png)
