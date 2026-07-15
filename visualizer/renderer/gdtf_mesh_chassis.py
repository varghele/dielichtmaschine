# visualizer/renderer/gdtf_mesh_chassis.py
"""Mesh-backed chassis for GDTF fixtures (plan Phase 3).

Renders the fixture body from the GDTF geometry tree: GLB-backed nodes
draw their baked mesh (utils/gdtf_mesh.py), modelless / 3DS-only nodes
fall back to a primitive box scaled to the Model dims - mixed rendering
per NODE, because wild files ship mixed formats (MagicBlade R: GLB head,
3DS yoke/base). Pan/tilt rotate whole subtrees at the GDTF Axis nodes
via the GL-free draw plan (gdtf_draw_plan.py).

Raises at construction when nothing is drawable; make_chassis_geometry
catches and falls back to the procedural chassis (the ladder in
docs/gdtf-integration-plan.md §6).

Renders in the opaque chassis pass; depth writes via gl_state.set_depth_mask
(gl-gotchas #1).
"""

from __future__ import annotations

import io
from typing import List, Optional, Tuple

import glm
import moderngl
import numpy as np

from utils.gdtf_data import GdtfData
from utils.gdtf_mesh import BakedMesh, load_glb_mesh
from utils.geometry import GeometryBuilder
from visualizer.renderer.chassis import ChassisGeometry
from visualizer.renderer.gdtf_draw_plan import (
    DrawItem,
    build_draw_plan,
    clamp_to_physical,
    physical_half_ranges,
    solver_to_gdtf_axes,
)
from visualizer.renderer.gl_state import set_depth_mask
from visualizer.renderer.shaders import (
    GDTF_MESH_FRAGMENT_SHADER,
    GDTF_MESH_VERTEX_SHADER,
)


def _np_to_glm(m: np.ndarray) -> glm.mat4:
    return glm.mat4(*np.asarray(m, dtype=np.float64).T.flatten())


def _box_as_baked(dims: Tuple[float, float, float]) -> BakedMesh:
    """Primitive fallback in the same interleaved layout as a GLB bake."""
    verts, norms = GeometryBuilder.create_box(*dims)
    positions = np.asarray(verts, dtype=np.float32).reshape(-1, 3)
    normals = np.asarray(norms, dtype=np.float32).reshape(-1, 3)
    uv = np.zeros((len(positions), 2), dtype=np.float32)
    return BakedMesh(
        vertex_data=np.hstack([positions, normals, uv]).astype(np.float32),
        indices=np.arange(len(positions), dtype=np.uint32),
        base_color=(0.28, 0.28, 0.30, 1.0),
        texture_png=None,
    )


# ---------------------------------------------------------------------------
# Shared GL resources: one program per context, one buffer/texture set per
# (context, archive, model). N instances of the same fixture type share
# everything except their (cheap) VAOs - per-fixture private buffers would
# not scale to the 60-fixture festival rig with real meshes. Shared
# resources live for the context's lifetime (bounded by distinct fixture
# types); clear_gl_mesh_cache() exists for explicit teardown.
# ---------------------------------------------------------------------------

_shared_programs: dict = {}     # id(ctx) -> Program
_shared_meshes: dict = {}       # (id(ctx), gdtf_path, mesh_key) -> _SharedMesh


class _SharedMesh:
    def __init__(self, ctx: moderngl.Context, baked: BakedMesh):
        self.base_color = baked.base_color[:3]
        self.vbo = ctx.buffer(baked.vertex_data.tobytes())
        self.ibo = ctx.buffer(baked.indices.tobytes())
        self.texture: Optional[moderngl.Texture] = None
        if baked.texture_png:
            from PIL import Image
            image = Image.open(io.BytesIO(baked.texture_png)).convert('RGBA')
            self.texture = ctx.texture(image.size, 4, image.tobytes())
            self.texture.build_mipmaps()

    def release(self):
        for res in (self.vbo, self.ibo, self.texture):
            if res is not None:
                res.release()


def _shared_program(ctx: moderngl.Context) -> moderngl.Program:
    program = _shared_programs.get(id(ctx))
    if program is None:
        program = ctx.program(vertex_shader=GDTF_MESH_VERTEX_SHADER,
                              fragment_shader=GDTF_MESH_FRAGMENT_SHADER)
        _shared_programs[id(ctx)] = program
    return program


def _shared_mesh(ctx: moderngl.Context, gdtf_path: str, mesh_key: str,
                 baked: BakedMesh) -> _SharedMesh:
    key = (id(ctx), gdtf_path, mesh_key)
    shared = _shared_meshes.get(key)
    if shared is None:
        shared = _SharedMesh(ctx, baked)
        _shared_meshes[key] = shared
    return shared


def clear_gl_mesh_cache() -> None:
    """Release all shared GL mesh resources (explicit teardown only)."""
    for shared in _shared_meshes.values():
        shared.release()
    _shared_meshes.clear()
    for program in _shared_programs.values():
        program.release()
    _shared_programs.clear()


class _DrawEntry:
    def __init__(self, item: DrawItem, shared: _SharedMesh,
                 ctx: moderngl.Context, program: moderngl.Program):
        self.item = item
        self.shared = shared
        self.vao = ctx.vertex_array(
            program,
            [(shared.vbo, '3f 3f 2f', 'in_position', 'in_normal', 'in_uv')],
            index_buffer=shared.ibo,
        )

    @property
    def base_color(self):
        return self.shared.base_color

    @property
    def texture(self):
        return self.shared.texture

    def release(self):
        # Only the per-instance VAO; buffers/textures are shared.
        if self.vao is not None:
            self.vao.release()


class GdtfMeshChassisGeometry(ChassisGeometry):
    """ChassisGeometry implementation backed by GDTF meshes."""

    def __init__(self, ctx: moderngl.Context, gdtf_path: str, gdtf: GdtfData,
                 mode_name: str):
        self.ctx = ctx
        self.program = _shared_program(ctx)
        self.entries: List[_DrawEntry] = []
        self._beam_item: Optional[DrawItem] = None

        plan = build_draw_plan(gdtf, mode_name)
        # Posture decides the solver-to-GDTF-axis conversion signs
        # (see solver_to_gdtf_axes); the physical ranges clamp the
        # converted angles like the wire does, so the rendered head
        # stops where the real head stops.
        self._flipped = bool(getattr(plan, 'flipped', False))
        self._pan_half, self._tilt_half = physical_half_ranges(
            gdtf, mode_name)
        for item in plan:
            if item.is_beam and self._beam_item is None:
                self._beam_item = item
            if not item.model_name:
                continue
            model = gdtf.models.get(item.model_name)
            if model is None:
                continue
            dims = (model.length_m, model.width_m, model.height_m)
            baked = None
            glb = model.glb_path()
            mesh_key = f'glb:{glb}'
            if glb is not None:
                baked = load_glb_mesh(gdtf_path, glb, target_dims_m=dims)
            if baked is None:
                if max(dims) <= 0:
                    continue
                baked = _box_as_baked(dims)
                mesh_key = f'box:{item.model_name}'
            shared = _shared_mesh(ctx, gdtf_path, mesh_key, baked)
            self.entries.append(_DrawEntry(item, shared, ctx, self.program))

        if not self.entries:
            raise ValueError(
                f"GDTF geometry tree of {gdtf_path} yields nothing drawable")

    def render(self, mvp: glm.mat4, model: glm.mat4, state=None) -> None:
        # state carries SOLVER-convention degrees (MovementComponent);
        # the chain rotates at the GDTF axes, a different yoke model.
        pan, tilt = solver_to_gdtf_axes(
            float(getattr(state, 'pan_deg', 0.0) or 0.0),
            float(getattr(state, 'tilt_deg', 0.0) or 0.0),
            self._flipped,
        )
        pan, tilt = clamp_to_physical(pan, tilt, self._pan_half,
                                      self._tilt_half)
        self.ctx.disable(moderngl.BLEND)
        set_depth_mask(True)
        for entry in self.entries:
            local = _np_to_glm(entry.item.compose(pan, tilt))
            self.program['mvp'].write(
                np.array([x for col in (mvp * model * local).to_list() for x in col],
                         dtype='f4').tobytes())
            self.program['model'].write(
                np.array([x for col in (model * local).to_list() for x in col],
                         dtype='f4').tobytes())
            self.program['base_color'].value = entry.base_color
            self.program['emissive_color'].value = getattr(
                state, 'emissive_color', (0.0, 0.0, 0.0)) if state else (0.0, 0.0, 0.0)
            self.program['emissive_strength'].value = 0.0
            if entry.texture is not None:
                entry.texture.use(location=0)
                self.program['tex'].value = 0
                self.program['use_texture'].value = True
            else:
                self.program['use_texture'].value = False
            entry.vao.render(moderngl.TRIANGLES)

    def beam_origin_transform(self, pan_deg: float = 0.0,
                              tilt_deg: float = 0.0) -> glm.mat4:
        """Place the beam cone (built along +Z) at the GDTF Beam node,
        emitting along the node's -Z (GDTF convention). Takes
        SOLVER-convention degrees, converted like :meth:`render` so the
        cone leaves through the same lens the head shows."""
        if self._beam_item is None:
            return glm.mat4(1.0)
        pan_deg, tilt_deg = solver_to_gdtf_axes(pan_deg, tilt_deg,
                                                self._flipped)
        pan_deg, tilt_deg = clamp_to_physical(pan_deg, tilt_deg,
                                              self._pan_half,
                                              self._tilt_half)
        node = _np_to_glm(self._beam_item.compose(pan_deg, tilt_deg))
        flip = glm.rotate(glm.mat4(1.0), glm.radians(180.0),
                          glm.vec3(1.0, 0.0, 0.0))
        return node * flip

    def release(self) -> None:
        # VAOs only; program and mesh buffers are shared per context
        # (see clear_gl_mesh_cache for explicit teardown).
        for entry in self.entries:
            entry.release()
