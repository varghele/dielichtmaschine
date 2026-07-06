"""Chassis geometry registry for the composable fixture renderer.

Phase B established the single-mesh registry (``_BUILDERS`` + ``build_chassis_mesh``)
covering all nine ``Chassis`` enum values. Phase C refines :class:`Chassis.MOVING_YOKE`
into a compound base + yoke + head + lens that animates with pan/tilt, mirroring
the existing :class:`MovingHeadRenderer` visuals.

Layout:
- :data:`_BUILDERS` — mesh builders for every Chassis (Phase B; still used by tests
  and by :class:`StaticChassisGeometry`).
- :class:`ChassisGeometry` — abstract base.
- :class:`StaticChassisGeometry` — one mesh, one draw, one VAO. Used for everything
  except moving heads.
- :class:`MovingYokeChassisGeometry` — animated base/yoke/head/lens for moving heads.
  Mirrors :meth:`MovingHeadRenderer._create_geometry` proportions.
- :func:`make_chassis_geometry` — factory keyed off :class:`Chassis`.

Phase D / Phase E may add :class:`ScannerChassisGeometry` (mirror), particle/laser,
etc. without touching components, emitters, or beams.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import glm
import moderngl
import numpy as np

from utils.fixture_capabilities import CellArray, Chassis
from utils.geometry import GeometryBuilder
from visualizer.renderer.gl_state import set_depth_mask
from visualizer.renderer.shaders import (
    FIXTURE_FRAGMENT_SHADER,
    FIXTURE_VERTEX_SHADER,
)


# ---------------------------------------------------------------------------
# Body color presets
# ---------------------------------------------------------------------------


DARK_METAL = (0.15, 0.15, 0.18)
LIGHT_METAL = (0.25, 0.25, 0.28)
PLACEHOLDER = (0.35, 0.30, 0.30)
YOKE_COLOR = (0.20, 0.20, 0.23)  # slightly lighter than DARK_METAL so yoke arms read against base
LENS_OFF_COLOR = (0.20, 0.20, 0.20)

# Axis colors for the MOVING_YOKE debug overlay (red / blue / green).
AXIS_X_COLOR = (0.9, 0.2, 0.2)
AXIS_Y_COLOR = (0.2, 0.4, 0.9)
AXIS_Z_COLOR = (0.2, 0.8, 0.2)


_BODY_COLORS: Dict[Chassis, Tuple[float, float, float]] = {
    Chassis.PAR: DARK_METAL,
    Chassis.BAR: DARK_METAL,
    Chassis.PANEL: DARK_METAL,
    Chassis.MOVING_YOKE: DARK_METAL,
    Chassis.SCANNER: DARK_METAL,
    Chassis.EFFECT: DARK_METAL,
    Chassis.PARTICLE: LIGHT_METAL,
    Chassis.LASER: LIGHT_METAL,
    Chassis.OTHER: PLACEHOLDER,
}


def get_body_color(chassis: Chassis) -> Tuple[float, float, float]:
    return _BODY_COLORS.get(chassis, DARK_METAL)


# ---------------------------------------------------------------------------
# Single-mesh registry (Phase B API — still used by tests and StaticChassisGeometry)
# ---------------------------------------------------------------------------


MeshBuilder = Callable[[float, float, float], Tuple[np.ndarray, np.ndarray]]


def _build_par(width: float, height: float, depth: float):
    radius = max(width, height) / 2.0
    return GeometryBuilder.create_cylinder(radius=radius, height=depth, segments=24)


def _build_bar(width: float, height: float, depth: float):
    return GeometryBuilder.create_box(width, height, depth)


def _build_panel(width: float, height: float, depth: float):
    return GeometryBuilder.create_box(width, height, max(depth, 0.05))


def _build_moving_yoke(width: float, height: float, depth: float):
    """Single-box approximation. The real animated chassis is :class:`MovingYokeChassisGeometry`;
    this is the legacy single-mesh entry that ``build_chassis_mesh`` returns for
    code paths that just want a representative shape (e.g. unit tests)."""
    return GeometryBuilder.create_box(width, height, depth)


def _build_scanner(width: float, height: float, depth: float):
    return GeometryBuilder.create_box(width, height, depth)


def _build_effect(width: float, height: float, depth: float):
    return GeometryBuilder.create_box(width, height, depth)


def _build_particle(width: float, height: float, depth: float):
    return GeometryBuilder.create_box(width, height, depth)


def _build_laser(width: float, height: float, depth: float):
    return GeometryBuilder.create_box(width, height, depth)


def _build_other(width: float, height: float, depth: float):
    return GeometryBuilder.create_box(width, height, depth)


_BUILDERS: Dict[Chassis, MeshBuilder] = {
    Chassis.PAR: _build_par,
    Chassis.BAR: _build_bar,
    Chassis.PANEL: _build_panel,
    Chassis.MOVING_YOKE: _build_moving_yoke,
    Chassis.SCANNER: _build_scanner,
    Chassis.EFFECT: _build_effect,
    Chassis.PARTICLE: _build_particle,
    Chassis.LASER: _build_laser,
    Chassis.OTHER: _build_other,
}


def build_chassis_mesh(
    chassis: Chassis,
    body_dims_m: Tuple[float, float, float],
) -> Tuple[np.ndarray, np.ndarray]:
    """Build a single-mesh approximation for a chassis (no GL).

    Returns ``(vertices, normals)``. For :class:`Chassis.MOVING_YOKE` this
    is a representative box; the GL renderer uses the compound
    :class:`MovingYokeChassisGeometry` instead.
    """
    builder = _BUILDERS.get(chassis, _build_other)
    return builder(*body_dims_m)


# ---------------------------------------------------------------------------
# Render state — passed to ChassisGeometry.render()
# ---------------------------------------------------------------------------


@dataclass
class ChassisRenderState:
    """Per-frame inputs to :meth:`ChassisGeometry.render`.

    Fields are ignored by chassis subclasses that don't use them
    (a static chassis ignores ``pan_deg``; a moving yoke uses both
    ``pan_deg`` and ``tilt_deg`` plus the lens emissive).

    ``cell_emissives`` carries premultiplied per-cell ``(r, g, b)``
    emissive values for bar / sunstrip / matrix chassis with a
    :class:`CellArray` emitter. Order matches ``CellArrayRunner.cell_states``
    (row-major). ``None`` means "no per-cell emitter geometry" — the chassis
    just uses ``emissive_color`` for any unified emitter / lens surface.
    """
    pan_deg: float = 0.0
    tilt_deg: float = 0.0
    emissive_color: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    emissive_strength: float = 0.0
    cell_emissives: Optional[List[Tuple[float, float, float]]] = None


_DEFAULT_STATE = ChassisRenderState()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mat4_bytes(m: glm.mat4) -> bytes:
    return np.array([x for col in m.to_list() for x in col], dtype='f4').tobytes()


# ---------------------------------------------------------------------------
# ABC + concrete chassis classes
# ---------------------------------------------------------------------------


class ChassisGeometry(ABC):
    """One chassis body, with its own GL program + VAOs.

    Subclasses own all GPU resources for one fixture's body.
    :meth:`render` is called once per frame, before the beam is rendered
    by the :class:`FixtureRenderer`.
    """

    @abstractmethod
    def render(
        self,
        mvp: glm.mat4,
        model: glm.mat4,
        state: ChassisRenderState = _DEFAULT_STATE,
    ) -> None:
        ...

    @abstractmethod
    def release(self) -> None:
        ...

    def beam_origin_transform(
        self,
        pan_deg: float = 0.0,
        tilt_deg: float = 0.0,
    ) -> glm.mat4:
        """Local transform from chassis origin to the beam's emission point.

        The beam cone is built along +Z (``GeometryBuilder.create_beam_cone``
        convention). This transform places the cone at the fixture's
        light-emission point and orients it along its outgoing direction.

        Default (static chassis): identity — cone emerges from origin
        along local +Z. For typical hanging mounts (pitch=90°) this maps
        to world -Y (down), which matches PAR / BAR / WASH expectations.

        :class:`MovingYokeChassisGeometry` overrides to incorporate
        pan + head translation + tilt + lens offset + 90° rotation so
        the cone emerges from the lens along the head's local +X.
        """
        return glm.mat4(1.0)


class StaticChassisGeometry(ChassisGeometry):
    """One-mesh chassis: PAR / BAR / PANEL / EFFECT / PARTICLE / LASER / OTHER / SCANNER.

    Ignores ``state.pan_deg`` / ``state.tilt_deg`` (no internal articulation).
    Uses ``state.emissive_color`` to optionally tint the body.
    """

    def __init__(
        self,
        ctx: moderngl.Context,
        chassis: Chassis,
        body_dims_m: Tuple[float, float, float],
    ):
        self.ctx = ctx
        self.chassis = chassis
        self.body_dims_m = body_dims_m

        verts, norms = build_chassis_mesh(chassis, body_dims_m)
        self._vertex_count = len(verts) // 3

        self.program = ctx.program(
            vertex_shader=FIXTURE_VERTEX_SHADER,
            fragment_shader=FIXTURE_FRAGMENT_SHADER,
        )
        self.vbo = ctx.buffer(verts.tobytes())
        self.nbo = ctx.buffer(norms.tobytes())
        self.vao = ctx.vertex_array(
            self.program,
            [
                (self.vbo, '3f', 'in_position'),
                (self.nbo, '3f', 'in_normal'),
            ],
        )

    def render(
        self,
        mvp: glm.mat4,
        model: glm.mat4,
        state: ChassisRenderState = _DEFAULT_STATE,
    ) -> None:
        # Make sure depth writes are on — beams/floor projections explicitly
        # turn them off via the real glDepthMask helper, and assigning
        # ``ctx.depth_mask = True`` doesn't restore them in moderngl 5.11.
        self.ctx.disable(moderngl.BLEND)
        set_depth_mask(True)

        self.program['mvp'].write(_mat4_bytes(mvp * model))
        self.program['model'].write(_mat4_bytes(model))
        self.program['base_color'].value = get_body_color(self.chassis)
        self.program['emissive_color'].value = state.emissive_color
        self.program['emissive_strength'].value = float(state.emissive_strength)
        self.vao.render(moderngl.TRIANGLES)

    def release(self) -> None:
        if self.vao:
            self.vao.release()
        if self.vbo:
            self.vbo.release()
        if self.nbo:
            self.nbo.release()
        if self.program:
            self.program.release()


class MovingYokeChassisGeometry(ChassisGeometry):
    """Compound moving-head chassis: base + yoke + head + lens + debug axes.

    Local frame is Z-up to match :class:`MovingHeadRenderer`:
    - X-Y plane is horizontal (base plate footprint)
    - Z is vertical (up)
    - At pan=0 / tilt=0, beam points +X
    - Pan rotates the yoke (and head) around Z
    - Tilt rotates the head (and lens) around the yoke's local Y after pan

    The lens is rendered with ``state.emissive_color`` so its visible color
    follows the beam's RGB × dimmer.

    A red/blue/green X/Y/Z axis triad is drawn on the base for orientation
    feedback (matches the legacy :class:`MovingHeadRenderer`). Disable
    globally by setting ``MovingYokeChassisGeometry.show_axes = False``.
    """

    show_axes: bool = True
    AXIS_LENGTH = 0.4
    AXIS_THICKNESS = 0.008
    ARROW_LENGTH = 0.06
    ARROW_WIDTH = 0.04

    def __init__(
        self,
        ctx: moderngl.Context,
        body_dims_m: Tuple[float, float, float],
    ):
        self.ctx = ctx
        self.body_dims_m = body_dims_m
        width, height, depth = body_dims_m

        # Proportions copied from MovingHeadRenderer._create_geometry.
        base_size = min(width, depth)
        base_thickness = height * 0.15

        yoke_thickness = base_size * 0.15
        yoke_height = height * 0.5
        yoke_depth = base_size * 0.8

        head_size_x = base_size * 0.5
        head_size_y = base_size * 0.7
        head_size_z = height * 0.45

        self.base_thickness = base_thickness
        self.yoke_height = yoke_height
        self.head_size_x = head_size_x

        self.program = ctx.program(
            vertex_shader=FIXTURE_VERTEX_SHADER,
            fragment_shader=FIXTURE_FRAGMENT_SHADER,
        )

        # --- base ---
        base_verts, base_norms = GeometryBuilder.create_box(
            base_size, base_size, base_thickness,
            center=(0, 0, base_thickness / 2),
        )
        self._base_vbo = ctx.buffer(base_verts.tobytes())
        self._base_nbo = ctx.buffer(base_norms.tobytes())
        self._base_vao = ctx.vertex_array(
            self.program,
            [(self._base_vbo, '3f', 'in_position'), (self._base_nbo, '3f', 'in_normal')],
        )

        # --- yoke (two arms, ±Y of head) ---
        yoke_z = base_thickness + yoke_height / 2
        left_verts, left_norms = GeometryBuilder.create_box(
            yoke_depth, yoke_thickness, yoke_height,
            center=(0, -head_size_y / 2 - yoke_thickness / 2, yoke_z),
        )
        right_verts, right_norms = GeometryBuilder.create_box(
            yoke_depth, yoke_thickness, yoke_height,
            center=(0, head_size_y / 2 + yoke_thickness / 2, yoke_z),
        )
        yoke_verts = np.concatenate([left_verts, right_verts])
        yoke_norms = np.concatenate([left_norms, right_norms])
        self._yoke_vbo = ctx.buffer(yoke_verts.tobytes())
        self._yoke_nbo = ctx.buffer(yoke_norms.tobytes())
        self._yoke_vao = ctx.vertex_array(
            self.program,
            [(self._yoke_vbo, '3f', 'in_position'), (self._yoke_nbo, '3f', 'in_normal')],
        )

        # --- head (created at origin; transformed during render) ---
        head_verts, head_norms = GeometryBuilder.create_box(
            head_size_x, head_size_y, head_size_z,
        )
        self._head_vbo = ctx.buffer(head_verts.tobytes())
        self._head_nbo = ctx.buffer(head_norms.tobytes())
        self._head_vao = ctx.vertex_array(
            self.program,
            [(self._head_vbo, '3f', 'in_position'), (self._head_nbo, '3f', 'in_normal')],
        )

        # --- lens (cylinder rotated to face +X, attached to head front) ---
        lens_radius = min(head_size_y, head_size_z) * 0.35
        lens_depth = 0.02
        self._lens_radius = lens_radius
        self.lens_depth = lens_depth
        self.head_size_x = head_size_x

        lens_verts_raw, lens_norms_raw = GeometryBuilder.create_cylinder(
            lens_radius, lens_depth, segments=24, center=(0, 0, 0),
        )
        # Rotate cylinder (Y-aligned by default) to face +X, then translate to head front.
        lens_verts = []
        lens_norms = []
        for i in range(0, len(lens_verts_raw), 3):
            x, y, z = lens_verts_raw[i], lens_verts_raw[i + 1], lens_verts_raw[i + 2]
            new_x = y + head_size_x / 2 + lens_depth / 2
            new_y = -x
            new_z = z
            lens_verts.extend([new_x, new_y, new_z])
        for i in range(0, len(lens_norms_raw), 3):
            nx, ny, nz = lens_norms_raw[i], lens_norms_raw[i + 1], lens_norms_raw[i + 2]
            lens_norms.extend([ny, -nx, nz])
        lens_verts = np.array(lens_verts, dtype='f4')
        lens_norms = np.array(lens_norms, dtype='f4')

        self._lens_vbo = ctx.buffer(lens_verts.tobytes())
        self._lens_nbo = ctx.buffer(lens_norms.tobytes())
        self._lens_vao = ctx.vertex_array(
            self.program,
            [(self._lens_vbo, '3f', 'in_position'), (self._lens_nbo, '3f', 'in_normal')],
        )

        # --- coordinate axes on top of the base (debug overlay) ---
        axis_origin_z = base_thickness + 0.01
        self._axis_x_vao, self._axis_x_vbo, self._axis_x_nbo = self._build_axis_vao(
            ctx, 'x', axis_origin_z,
        )
        self._axis_y_vao, self._axis_y_vbo, self._axis_y_nbo = self._build_axis_vao(
            ctx, 'y', axis_origin_z,
        )
        self._axis_z_vao, self._axis_z_vbo, self._axis_z_nbo = self._build_axis_vao(
            ctx, 'z', axis_origin_z,
        )

    def _build_axis_vao(
        self,
        ctx: moderngl.Context,
        axis: str,
        origin_z: float,
    ) -> Tuple[moderngl.VertexArray, moderngl.Buffer, moderngl.Buffer]:
        """Build one axis (shaft + pyramid arrow head) pointing along +X / +Y / +Z.

        Mirrors the legacy ``MovingHeadRenderer._create_geometry`` axis blocks.
        """
        L = self.AXIS_LENGTH
        T = self.AXIS_THICKNESS
        AL = self.ARROW_LENGTH
        AW = self.ARROW_WIDTH

        if axis == 'x':
            shaft_verts, shaft_norms = GeometryBuilder.create_box(
                L, T, T, center=(L / 2, 0, origin_z),
            )
            arrow_tip = (L + AL, 0.0, origin_z)
            arrow_base_x = L
            arrow_verts = np.array([
                # 4 triangular faces of pyramid pointing +X
                arrow_base_x, -AW / 2, origin_z - AW / 2,
                arrow_base_x,  AW / 2, origin_z - AW / 2,
                *arrow_tip,

                arrow_base_x,  AW / 2, origin_z + AW / 2,
                arrow_base_x, -AW / 2, origin_z + AW / 2,
                *arrow_tip,

                arrow_base_x, -AW / 2, origin_z + AW / 2,
                arrow_base_x, -AW / 2, origin_z - AW / 2,
                *arrow_tip,

                arrow_base_x,  AW / 2, origin_z - AW / 2,
                arrow_base_x,  AW / 2, origin_z + AW / 2,
                *arrow_tip,
            ], dtype='f4')
            arrow_norms = np.array([0, -1, 0] * 3 + [0, 1, 0] * 3 + [0, 0, -1] * 3 + [0, 0, 1] * 3, dtype='f4')
        elif axis == 'y':
            shaft_verts, shaft_norms = GeometryBuilder.create_box(
                T, L, T, center=(0, L / 2, origin_z),
            )
            arrow_tip = (0.0, L + AL, origin_z)
            arrow_base_y = L
            arrow_verts = np.array([
                -AW / 2, arrow_base_y, origin_z - AW / 2,
                 AW / 2, arrow_base_y, origin_z - AW / 2,
                *arrow_tip,

                 AW / 2, arrow_base_y, origin_z + AW / 2,
                -AW / 2, arrow_base_y, origin_z + AW / 2,
                *arrow_tip,

                -AW / 2, arrow_base_y, origin_z + AW / 2,
                -AW / 2, arrow_base_y, origin_z - AW / 2,
                *arrow_tip,

                 AW / 2, arrow_base_y, origin_z - AW / 2,
                 AW / 2, arrow_base_y, origin_z + AW / 2,
                *arrow_tip,
            ], dtype='f4')
            arrow_norms = np.array([0, 0, -1] * 3 + [0, 0, 1] * 3 + [-1, 0, 0] * 3 + [1, 0, 0] * 3, dtype='f4')
        else:  # 'z'
            shaft_verts, shaft_norms = GeometryBuilder.create_box(
                T, T, L, center=(0, 0, origin_z + L / 2),
            )
            arrow_tip = (0.0, 0.0, origin_z + L + AL)
            arrow_base_z = origin_z + L
            arrow_verts = np.array([
                -AW / 2, -AW / 2, arrow_base_z,
                 AW / 2, -AW / 2, arrow_base_z,
                *arrow_tip,

                 AW / 2,  AW / 2, arrow_base_z,
                -AW / 2,  AW / 2, arrow_base_z,
                *arrow_tip,

                -AW / 2,  AW / 2, arrow_base_z,
                -AW / 2, -AW / 2, arrow_base_z,
                *arrow_tip,

                 AW / 2, -AW / 2, arrow_base_z,
                 AW / 2,  AW / 2, arrow_base_z,
                *arrow_tip,
            ], dtype='f4')
            arrow_norms = np.array([0, -1, 0] * 3 + [0, 1, 0] * 3 + [-1, 0, 0] * 3 + [1, 0, 0] * 3, dtype='f4')

        verts = np.concatenate([shaft_verts, arrow_verts])
        norms = np.concatenate([shaft_norms, arrow_norms])

        vbo = ctx.buffer(verts.tobytes())
        nbo = ctx.buffer(norms.tobytes())
        vao = ctx.vertex_array(
            self.program,
            [(vbo, '3f', 'in_position'), (nbo, '3f', 'in_normal')],
        )
        return vao, vbo, nbo

    def render(
        self,
        mvp: glm.mat4,
        model: glm.mat4,
        state: ChassisRenderState = _DEFAULT_STATE,
    ) -> None:
        # Make sure incidental blend state from a previous fixture's beam doesn't bleed in.
        # (The legacy MovingHeadRenderer did the same defensively.)
        self.ctx.disable(moderngl.BLEND)
        set_depth_mask(True)

        # --- base (no rotation) ---
        self.program['mvp'].write(_mat4_bytes(mvp * model))
        self.program['model'].write(_mat4_bytes(model))
        self.program['base_color'].value = get_body_color(Chassis.MOVING_YOKE)
        self.program['emissive_color'].value = (0.0, 0.0, 0.0)
        self.program['emissive_strength'].value = 0.0
        self._base_vao.render(moderngl.TRIANGLES)

        # --- coordinate axes on the base (debug overlay; same MVP as base) ---
        if self.show_axes:
            self.program['base_color'].value = AXIS_X_COLOR
            self._axis_x_vao.render(moderngl.TRIANGLES)
            self.program['base_color'].value = AXIS_Y_COLOR
            self._axis_y_vao.render(moderngl.TRIANGLES)
            self.program['base_color'].value = AXIS_Z_COLOR
            self._axis_z_vao.render(moderngl.TRIANGLES)

        # --- yoke (pan around Z) ---
        pan_rotation = glm.rotate(glm.mat4(1.0), glm.radians(state.pan_deg), glm.vec3(0, 0, 1))
        yoke_model = model * pan_rotation
        self.program['mvp'].write(_mat4_bytes(mvp * yoke_model))
        self.program['model'].write(_mat4_bytes(yoke_model))
        self.program['base_color'].value = YOKE_COLOR
        self._yoke_vao.render(moderngl.TRIANGLES)

        # --- head (pan + lift to yoke height + tilt around local Y) ---
        head_translate = glm.translate(glm.mat4(1.0), glm.vec3(0, 0, self.base_thickness + self.yoke_height / 2))
        # Negative tilt around Y goes from +X (forward) toward +Z (up) as tilt increases.
        tilt_rotation = glm.rotate(glm.mat4(1.0), glm.radians(-state.tilt_deg), glm.vec3(0, 1, 0))
        head_model = model * pan_rotation * head_translate * tilt_rotation

        self.program['mvp'].write(_mat4_bytes(mvp * head_model))
        self.program['model'].write(_mat4_bytes(head_model))
        self.program['base_color'].value = get_body_color(Chassis.MOVING_YOKE)
        self.program['emissive_color'].value = (0.0, 0.0, 0.0)
        self.program['emissive_strength'].value = 0.0
        self._head_vao.render(moderngl.TRIANGLES)

        # --- lens (same head transform, but emissive follows beam color × dimmer) ---
        self.program['base_color'].value = LENS_OFF_COLOR
        self.program['emissive_color'].value = state.emissive_color
        self.program['emissive_strength'].value = float(state.emissive_strength)
        self._lens_vao.render(moderngl.TRIANGLES)

    def head_offset_local(self) -> glm.vec3:
        """Local-frame offset (Z-up) from the chassis origin to the head pivot.

        Beam emissions originate at this point, transformed through the
        same pan/tilt that the head goes through. Useful for the
        FixtureRenderer when computing the beam's local transform —
        currently the EmitterRunner builds its own head offset, but this
        getter gives a consistent answer.
        """
        return glm.vec3(0.0, 0.0, self.base_thickness + self.yoke_height / 2)

    def lens_world_pos(
        self,
        fixture_model: glm.mat4,
        pan_deg: float,
        tilt_deg: float,
    ) -> glm.vec3:
        """World position of the lens center, given chassis transform and pan/tilt.

        Applies the same pan + head_translate + tilt chain that
        :meth:`render` uses internally, then offsets along the head's
        local +X to the lens center. Result is in the same world space
        as ``fixture_model``.
        """
        pan_mat = glm.rotate(glm.mat4(1.0), glm.radians(pan_deg), glm.vec3(0, 0, 1))
        head_translate = glm.translate(
            glm.mat4(1.0),
            glm.vec3(0, 0, self.base_thickness + self.yoke_height / 2),
        )
        tilt_mat = glm.rotate(glm.mat4(1.0), glm.radians(-tilt_deg), glm.vec3(0, 1, 0))
        head_model = fixture_model * pan_mat * head_translate * tilt_mat
        lens_local = glm.vec3(self.head_size_x / 2 + self.lens_depth, 0.0, 0.0)
        return glm.vec3(head_model * glm.vec4(lens_local, 1.0))

    def beam_origin_transform(
        self,
        pan_deg: float = 0.0,
        tilt_deg: float = 0.0,
    ) -> glm.mat4:
        """Beam emission transform: pan × head_translate × tilt × lens_offset × cone_rotation.

        Mirrors :meth:`MovingHeadRenderer._render_single_beam`:
        ``beam_model = head_model * beam_offset * beam_rotation``,
        where ``head_model = base_model * pan_rotation * head_translate * tilt_rotation``.

        Applied to a cone vertex (cone built along +Z), the chain:
        1. Rotates 90° around Y → cone now points along +X (head's forward)
        2. Translates along +X to the lens center
        3. Rotates around Y for tilt (around the head's pivot)
        4. Translates up by head pivot Z
        5. Rotates around Z for pan
        ...then the fixture's model matrix places everything in world space.
        """
        pan_mat = glm.rotate(glm.mat4(1.0), glm.radians(pan_deg), glm.vec3(0, 0, 1))
        head_translate = glm.translate(
            glm.mat4(1.0),
            glm.vec3(0, 0, self.base_thickness + self.yoke_height / 2),
        )
        tilt_mat = glm.rotate(glm.mat4(1.0), glm.radians(-tilt_deg), glm.vec3(0, 1, 0))
        lens_offset = glm.translate(
            glm.mat4(1.0),
            glm.vec3(self.head_size_x / 2 + self.lens_depth, 0, 0),
        )
        cone_rotation = glm.rotate(glm.mat4(1.0), glm.radians(90.0), glm.vec3(0, 1, 0))
        return pan_mat * head_translate * tilt_mat * lens_offset * cone_rotation

    def release(self) -> None:
        for vao in (
            self._base_vao, self._yoke_vao, self._head_vao, self._lens_vao,
            self._axis_x_vao, self._axis_y_vao, self._axis_z_vao,
        ):
            if vao:
                vao.release()
        for buf in (
            self._base_vbo, self._base_nbo,
            self._yoke_vbo, self._yoke_nbo,
            self._head_vbo, self._head_nbo,
            self._lens_vbo, self._lens_nbo,
            self._axis_x_vbo, self._axis_x_nbo,
            self._axis_y_vbo, self._axis_y_nbo,
            self._axis_z_vbo, self._axis_z_nbo,
        ):
            if buf:
                buf.release()
        if self.program:
            self.program.release()


# ---------------------------------------------------------------------------
# PixelBarChassisGeometry — body box + per-cell visible emitter slabs
# ---------------------------------------------------------------------------


class PixelBarChassisGeometry(ChassisGeometry):
    """Bar / panel chassis with one visible RGBW emitter slab per cell.

    Mirrors the legacy :class:`PixelBarRenderer._create_geometry` visual:
    a dark body box, with thin colored slabs sitting on the front face,
    one per cell. Each slab lights up with that cell's premultiplied
    emissive (read from :attr:`ChassisRenderState.cell_emissives`, which
    the :class:`FixtureRenderer` populates from the
    :class:`CellArrayRunner`'s per-cell state).
    """

    BODY_COLOR = (0.15, 0.15, 0.18)
    SLAB_BASE_COLOR = (0.1, 0.1, 0.1)
    SLAB_DEPTH = 0.01
    # Slabs cover this fraction of each cell's width × the bar's height.
    SLAB_WIDTH_FRACTION = 0.85
    SLAB_HEIGHT_FRACTION = 0.6

    def __init__(
        self,
        ctx: moderngl.Context,
        body_dims_m: Tuple[float, float, float],
        emitter: CellArray,
    ):
        self.ctx = ctx
        self.body_dims_m = body_dims_m
        self.emitter = emitter

        self.program = ctx.program(
            vertex_shader=FIXTURE_VERTEX_SHADER,
            fragment_shader=FIXTURE_FRAGMENT_SHADER,
        )

        width, height, depth = body_dims_m
        body_verts, body_norms = GeometryBuilder.create_box(width, height, depth)
        self._body_vbo = ctx.buffer(body_verts.tobytes())
        self._body_nbo = ctx.buffer(body_norms.tobytes())
        self._body_vao = ctx.vertex_array(
            self.program,
            [(self._body_vbo, '3f', 'in_position'), (self._body_nbo, '3f', 'in_normal')],
        )

        span_w = width * 0.9
        span_h = height * 0.9
        cell_w = span_w / max(1, emitter.width)
        cell_h = span_h / max(1, emitter.height)
        slab_w = cell_w * self.SLAB_WIDTH_FRACTION
        slab_h = (
            cell_h * self.SLAB_WIDTH_FRACTION
            if emitter.height > 1
            else height * self.SLAB_HEIGHT_FRACTION
        )
        slab_z = depth / 2.0 + self.SLAB_DEPTH / 2.0
        start_x = -span_w / 2.0 + cell_w / 2.0
        start_y = -span_h / 2.0 + cell_h / 2.0

        self._slab_vaos: list[moderngl.VertexArray] = []
        self._slab_vbos: list[moderngl.Buffer] = []
        self._slab_nbos: list[moderngl.Buffer] = []
        for row in range(emitter.height):
            for col in range(emitter.width):
                cx = start_x + col * cell_w
                cy = start_y + row * cell_h if emitter.height > 1 else 0.0
                verts, norms = GeometryBuilder.create_box(
                    slab_w, slab_h, self.SLAB_DEPTH,
                    center=(cx, cy, slab_z),
                )
                vbo = ctx.buffer(verts.tobytes())
                nbo = ctx.buffer(norms.tobytes())
                vao = ctx.vertex_array(
                    self.program,
                    [(vbo, '3f', 'in_position'), (nbo, '3f', 'in_normal')],
                )
                self._slab_vbos.append(vbo)
                self._slab_nbos.append(nbo)
                self._slab_vaos.append(vao)

    def render(
        self,
        mvp: glm.mat4,
        model: glm.mat4,
        state: ChassisRenderState = _DEFAULT_STATE,
    ) -> None:
        self.ctx.disable(moderngl.BLEND)
        set_depth_mask(True)

        self.program['mvp'].write(_mat4_bytes(mvp * model))
        self.program['model'].write(_mat4_bytes(model))

        # Body — unlit dark housing.
        self.program['base_color'].value = self.BODY_COLOR
        self.program['emissive_color'].value = (0.0, 0.0, 0.0)
        self.program['emissive_strength'].value = 0.0
        self._body_vao.render(moderngl.TRIANGLES)

        # Slabs — one per cell, lit by per-cell emissive.
        self.program['base_color'].value = self.SLAB_BASE_COLOR
        emissives = state.cell_emissives
        for i, vao in enumerate(self._slab_vaos):
            if emissives is not None and i < len(emissives):
                er, eg, eb = emissives[i]
                # Treat the largest channel as overall intensity so an off
                # cell (all-zero emissive) stays at SLAB_BASE_COLOR ambient.
                strength = max(er, eg, eb)
                self.program['emissive_color'].value = (er, eg, eb)
                self.program['emissive_strength'].value = float(strength)
            else:
                self.program['emissive_color'].value = (0.0, 0.0, 0.0)
                self.program['emissive_strength'].value = 0.0
            vao.render(moderngl.TRIANGLES)

    def release(self) -> None:
        for vao in (self._body_vao, *self._slab_vaos):
            if vao:
                vao.release()
        for buf in (
            self._body_vbo, self._body_nbo,
            *self._slab_vbos, *self._slab_nbos,
        ):
            if buf:
                buf.release()
        if self.program:
            self.program.release()


# ---------------------------------------------------------------------------
# SunstripChassisGeometry — body box + per-cell lamp bulbs (cylinders)
# ---------------------------------------------------------------------------


class SunstripChassisGeometry(ChassisGeometry):
    """Sunstrip-style chassis: a dark bar body with small cylindrical lamp
    bulbs protruding from the front face, one per cell. Each lamp glows
    warm-white at the cell's per-cell dimmer.

    Mirrors the legacy :class:`SunstripRenderer._create_geometry`.
    """

    BODY_COLOR = (0.12, 0.12, 0.15)
    LAMP_BASE_COLOR = (0.9, 0.85, 0.7)
    # Warm-white preserved from legacy WARM_WHITE_COLOR.
    LAMP_EMISSIVE = (1.0, 0.85, 0.6)
    LAMP_HEIGHT = 0.02

    def __init__(
        self,
        ctx: moderngl.Context,
        body_dims_m: Tuple[float, float, float],
        emitter: CellArray,
    ):
        self.ctx = ctx
        self.body_dims_m = body_dims_m
        self.emitter = emitter

        self.program = ctx.program(
            vertex_shader=FIXTURE_VERTEX_SHADER,
            fragment_shader=FIXTURE_FRAGMENT_SHADER,
        )

        width, height, depth = body_dims_m
        body_verts, body_norms = GeometryBuilder.create_box(width, height, depth)
        self._body_vbo = ctx.buffer(body_verts.tobytes())
        self._body_nbo = ctx.buffer(body_norms.tobytes())
        self._body_vao = ctx.vertex_array(
            self.program,
            [(self._body_vbo, '3f', 'in_position'), (self._body_nbo, '3f', 'in_normal')],
        )

        n_lamps = max(1, emitter.width)
        # Lamp radius — bound to cell width but capped at 3 cm like legacy.
        lamp_radius = min(width * 0.9 / n_lamps * 0.35, 0.03)
        self.lamp_radius = lamp_radius

        # GeometryBuilder.create_cylinder is Y-axis aligned; rotate so it
        # points +Z (lamp protrudes from front face), then translate to its
        # cell position. (Same rotation as legacy SunstripRenderer.)
        span = width * 0.9
        cell_w = span / n_lamps
        start_x = -span / 2.0 + cell_w / 2.0
        lamp_z = depth / 2.0 + self.LAMP_HEIGHT / 2.0

        self._lamp_vaos: list[moderngl.VertexArray] = []
        self._lamp_vbos: list[moderngl.Buffer] = []
        self._lamp_nbos: list[moderngl.Buffer] = []
        for i in range(n_lamps):
            x_offset = start_x + i * cell_w
            raw_v, raw_n = GeometryBuilder.create_cylinder(
                lamp_radius, self.LAMP_HEIGHT, segments=12, center=(0, 0, 0),
            )
            verts = []
            norms = []
            # (x, y, z) → (x, -z, y) then translate to (x_offset, 0, lamp_z)
            for j in range(0, len(raw_v), 3):
                x, y, z = raw_v[j], raw_v[j + 1], raw_v[j + 2]
                verts.extend([x + x_offset, -z, y + lamp_z])
            for j in range(0, len(raw_n), 3):
                nx, ny, nz = raw_n[j], raw_n[j + 1], raw_n[j + 2]
                norms.extend([nx, -nz, ny])
            vbo = ctx.buffer(np.array(verts, dtype='f4').tobytes())
            nbo = ctx.buffer(np.array(norms, dtype='f4').tobytes())
            vao = ctx.vertex_array(
                self.program,
                [(vbo, '3f', 'in_position'), (nbo, '3f', 'in_normal')],
            )
            self._lamp_vbos.append(vbo)
            self._lamp_nbos.append(nbo)
            self._lamp_vaos.append(vao)

    def render(
        self,
        mvp: glm.mat4,
        model: glm.mat4,
        state: ChassisRenderState = _DEFAULT_STATE,
    ) -> None:
        self.ctx.disable(moderngl.BLEND)
        set_depth_mask(True)

        self.program['mvp'].write(_mat4_bytes(mvp * model))
        self.program['model'].write(_mat4_bytes(model))

        # Body.
        self.program['base_color'].value = self.BODY_COLOR
        self.program['emissive_color'].value = (0.0, 0.0, 0.0)
        self.program['emissive_strength'].value = 0.0
        self._body_vao.render(moderngl.TRIANGLES)

        # Lamps — warm-white emissive scaled by per-cell brightness.
        self.program['base_color'].value = self.LAMP_BASE_COLOR
        emissives = state.cell_emissives
        for i, vao in enumerate(self._lamp_vaos):
            if emissives is not None and i < len(emissives):
                # Use the brightest channel as dimmer-equivalent. Sunstrip
                # cells are warm-white, so dimmer ≈ max(rgb).
                er, eg, eb = emissives[i]
                dimmer = max(er, eg, eb)
            else:
                dimmer = 0.0
            if dimmer > 0.01:
                self.program['emissive_color'].value = (
                    self.LAMP_EMISSIVE[0] * dimmer,
                    self.LAMP_EMISSIVE[1] * dimmer,
                    self.LAMP_EMISSIVE[2] * dimmer,
                )
                self.program['emissive_strength'].value = 1.5
            else:
                self.program['emissive_color'].value = (0.0, 0.0, 0.0)
                self.program['emissive_strength'].value = 0.0
            vao.render(moderngl.TRIANGLES)

    def release(self) -> None:
        for vao in (self._body_vao, *self._lamp_vaos):
            if vao:
                vao.release()
        for buf in (
            self._body_vbo, self._body_nbo,
            *self._lamp_vbos, *self._lamp_nbos,
        ):
            if buf:
                buf.release()
        if self.program:
            self.program.release()


# ---------------------------------------------------------------------------
# PARChassisGeometry — cylinder body + visible lens slab on the front face
# ---------------------------------------------------------------------------


class PARChassisGeometry(ChassisGeometry):
    """PAR / wash chassis with a visible lens slab on the front.

    Replaces the bare cylinder body that ``StaticChassisGeometry`` drew for
    :class:`Chassis.PAR`. The lens slab lights up with the chassis-wide
    emissive (color × dimmer), the way the legacy
    :class:`WashRenderer._create_geometry` shows a coloured lens panel on
    Wild Wash / Retro Flat Par fixtures.
    """

    BODY_COLOR = (0.12, 0.12, 0.15)
    LENS_BASE_COLOR = (0.15, 0.15, 0.15)
    LENS_DEPTH = 0.02
    LENS_FACE_FRACTION = 0.85

    def __init__(
        self,
        ctx: moderngl.Context,
        body_dims_m: Tuple[float, float, float],
    ):
        self.ctx = ctx
        self.body_dims_m = body_dims_m

        self.program = ctx.program(
            vertex_shader=FIXTURE_VERTEX_SHADER,
            fragment_shader=FIXTURE_FRAGMENT_SHADER,
        )

        width, height, depth = body_dims_m
        radius = max(width, height) / 2.0

        body_verts, body_norms = GeometryBuilder.create_cylinder(
            radius=radius, height=depth, segments=24,
        )
        self._body_vbo = ctx.buffer(body_verts.tobytes())
        self._body_nbo = ctx.buffer(body_norms.tobytes())
        self._body_vao = ctx.vertex_array(
            self.program,
            [(self._body_vbo, '3f', 'in_position'), (self._body_nbo, '3f', 'in_normal')],
        )

        lens_w = width * self.LENS_FACE_FRACTION
        lens_h = height * self.LENS_FACE_FRACTION
        lens_z = depth / 2.0 + self.LENS_DEPTH / 2.0
        lens_verts, lens_norms = GeometryBuilder.create_box(
            lens_w, lens_h, self.LENS_DEPTH, center=(0, 0, lens_z),
        )
        self._lens_vbo = ctx.buffer(lens_verts.tobytes())
        self._lens_nbo = ctx.buffer(lens_norms.tobytes())
        self._lens_vao = ctx.vertex_array(
            self.program,
            [(self._lens_vbo, '3f', 'in_position'), (self._lens_nbo, '3f', 'in_normal')],
        )

    def render(
        self,
        mvp: glm.mat4,
        model: glm.mat4,
        state: ChassisRenderState = _DEFAULT_STATE,
    ) -> None:
        self.ctx.disable(moderngl.BLEND)
        set_depth_mask(True)

        self.program['mvp'].write(_mat4_bytes(mvp * model))
        self.program['model'].write(_mat4_bytes(model))

        # Body — unlit.
        self.program['base_color'].value = self.BODY_COLOR
        self.program['emissive_color'].value = (0.0, 0.0, 0.0)
        self.program['emissive_strength'].value = 0.0
        self._body_vao.render(moderngl.TRIANGLES)

        # Lens — emissive from chassis-wide colour × dimmer.
        self.program['base_color'].value = self.LENS_BASE_COLOR
        self.program['emissive_color'].value = state.emissive_color
        self.program['emissive_strength'].value = float(state.emissive_strength)
        self._lens_vao.render(moderngl.TRIANGLES)

    def release(self) -> None:
        for vao in (self._body_vao, self._lens_vao):
            if vao:
                vao.release()
        for buf in (
            self._body_vbo, self._body_nbo,
            self._lens_vbo, self._lens_nbo,
        ):
            if buf:
                buf.release()
        if self.program:
            self.program.release()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def _cellarray_has_color(emitter: CellArray) -> bool:
    return any(
        c.red_channel is not None
        or c.green_channel is not None
        or c.blue_channel is not None
        for c in emitter.cells
    )


def make_chassis_geometry(
    ctx: moderngl.Context,
    chassis: Chassis,
    body_dims_m: Tuple[float, float, float],
    emitter: Optional[object] = None,
    gdtf_source: Optional[Tuple[str, object, str]] = None,
) -> ChassisGeometry:
    """Construct the right :class:`ChassisGeometry` for a fixture.

    ``emitter`` is the :class:`FixtureCapabilities.emitter` value — used to
    pick a cell-aware chassis (visible per-cell slabs / lamps) when the
    fixture has a :class:`CellArray`. ``None`` falls back to the legacy
    static / moving-yoke choice.

    ``gdtf_source`` is ``(gdtf_path, GdtfData, mode_name)`` for
    GDTF-sourced fixtures: try the mesh-backed chassis first and fall
    back to the procedural ladder below on any failure (missing models,
    bake rejects, degenerate trees — wild files, see
    docs/gdtf-coverage-note.md).
    """
    if gdtf_source is not None:
        try:
            from visualizer.renderer.gdtf_mesh_chassis import GdtfMeshChassisGeometry
            gdtf_path, gdtf_data, mode_name = gdtf_source
            return GdtfMeshChassisGeometry(ctx, gdtf_path, gdtf_data, mode_name)
        except Exception as e:
            print(f"GDTF mesh chassis unavailable, procedural fallback: {e}")
    if chassis is Chassis.MOVING_YOKE:
        return MovingYokeChassisGeometry(ctx, body_dims_m)
    if isinstance(emitter, CellArray) and chassis in (Chassis.BAR, Chassis.PANEL):
        if _cellarray_has_color(emitter):
            return PixelBarChassisGeometry(ctx, body_dims_m, emitter)
        return SunstripChassisGeometry(ctx, body_dims_m, emitter)
    if chassis is Chassis.PAR:
        return PARChassisGeometry(ctx, body_dims_m)
    return StaticChassisGeometry(ctx, chassis, body_dims_m)
