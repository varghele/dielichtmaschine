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
from visualizer.renderer.gdtf_draw_plan import DrawItem, build_draw_plan
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


class _DrawEntry:
    def __init__(self, item: DrawItem, baked: BakedMesh, ctx: moderngl.Context,
                 program: moderngl.Program):
        self.item = item
        self.base_color = baked.base_color[:3]
        self.vbo = ctx.buffer(baked.vertex_data.tobytes())
        self.ibo = ctx.buffer(baked.indices.tobytes())
        self.vao = ctx.vertex_array(
            program,
            [(self.vbo, '3f 3f 2f', 'in_position', 'in_normal', 'in_uv')],
            index_buffer=self.ibo,
        )
        self.texture: Optional[moderngl.Texture] = None
        if baked.texture_png:
            from PIL import Image
            image = Image.open(io.BytesIO(baked.texture_png)).convert('RGBA')
            self.texture = ctx.texture(image.size, 4, image.tobytes())
            self.texture.build_mipmaps()

    def release(self):
        for res in (self.vao, self.vbo, self.ibo, self.texture):
            if res is not None:
                res.release()


class GdtfMeshChassisGeometry(ChassisGeometry):
    """ChassisGeometry implementation backed by GDTF meshes."""

    def __init__(self, ctx: moderngl.Context, gdtf_path: str, gdtf: GdtfData,
                 mode_name: str):
        self.ctx = ctx
        self.program = ctx.program(
            vertex_shader=GDTF_MESH_VERTEX_SHADER,
            fragment_shader=GDTF_MESH_FRAGMENT_SHADER,
        )
        self.entries: List[_DrawEntry] = []
        self._beam_item: Optional[DrawItem] = None

        plan = build_draw_plan(gdtf, mode_name)
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
            if glb is not None:
                baked = load_glb_mesh(gdtf_path, glb, target_dims_m=dims)
            if baked is None:
                if max(dims) <= 0:
                    continue
                baked = _box_as_baked(dims)
            self.entries.append(_DrawEntry(item, baked, ctx, self.program))

        if not self.entries:
            self.program.release()
            raise ValueError(
                f"GDTF geometry tree of {gdtf_path} yields nothing drawable")

    def render(self, mvp: glm.mat4, model: glm.mat4, state=None) -> None:
        pan = float(getattr(state, 'pan_deg', 0.0) or 0.0)
        tilt = float(getattr(state, 'tilt_deg', 0.0) or 0.0)
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
        emitting along the node's -Z (GDTF convention)."""
        if self._beam_item is None:
            return glm.mat4(1.0)
        node = _np_to_glm(self._beam_item.compose(pan_deg, tilt_deg))
        flip = glm.rotate(glm.mat4(1.0), glm.radians(180.0),
                          glm.vec3(1.0, 0.0, 0.0))
        return node * flip

    def release(self) -> None:
        for entry in self.entries:
            entry.release()
        if self.program:
            self.program.release()
