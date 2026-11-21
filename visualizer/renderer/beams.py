"""Beam components for the composable fixture renderer (Phase B).

Each :class:`BeamComponent` owns its own GL program + VAO and knows how
to render one :class:`Emission` (volumetric beam, gobo modulation, etc.).
The :class:`FixtureRenderer` iterates the EmitterRunner's emissions and
calls ``render_emission`` once per emission.

Variants mirror the natural factoring of the existing renderers:
- :class:`GlowBeam` — short glow cone (PAR / wash fallback)
- :class:`CylindricalBeam` — stubby column (PAR canister)
- :class:`ConeBeam` — long narrow cone with gobo + focus modulation (MH)
- :class:`RectangularBeam` — wide rectangular volume (wash)

Phase B keeps the existing GLSL intact (shared via ``shaders.py``); Phase D
will swap callers from the old ``FixtureRenderer`` subclasses over to these.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Tuple

import glm
import moderngl
import numpy as np

from utils.geometry import GeometryBuilder
from visualizer.renderer.emitters import Emission
from visualizer.renderer.gl_state import set_depth_mask
from visualizer.renderer.shaders import (
    BEAM_FRAGMENT_SHADER,
    BEAM_VERTEX_SHADER,
    GOBO_BEAM_FRAGMENT_SHADER,
    GOBO_BEAM_VERTEX_SHADER,
)


# ---------------------------------------------------------------------------
# Modifiers — bundle of per-frame uniform inputs that some beam variants use
# ---------------------------------------------------------------------------


@dataclass
class BeamModifiers:
    """Per-frame uniform inputs that decorate a beam render.

    Variants ignore fields they don't care about (a GlowBeam ignores
    ``gobo_pattern``; a ConeBeam consumes it).
    """
    brightness_scale: float = 1.0
    gobo_pattern: int = 0
    gobo_rotation_rad: float = 0.0
    focus_sharpness: float = 1.0
    iris_opening: float = 1.0
    frost: float = 0.0
    zoom_angle_deg: Optional[float] = None  # overrides BeamShape default when set
    prism_active: bool = False
    prism_facets: int = 3


_DEFAULT_MODIFIERS = BeamModifiers()


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class BeamComponent(ABC):
    """Owns the GL resources for one beam shape. Renders one emission at a time."""

    def __init__(self, ctx: moderngl.Context):
        self.ctx = ctx
        self.program: Optional[moderngl.Program] = None
        self.vao: Optional[moderngl.VertexArray] = None
        self.vbo: Optional[moderngl.Buffer] = None
        self.abo: Optional[moderngl.Buffer] = None  # alpha buffer

    @abstractmethod
    def render_emission(
        self,
        mvp: glm.mat4,
        fixture_model: glm.mat4,
        emission: Emission,
        modifiers: BeamModifiers = _DEFAULT_MODIFIERS,
    ) -> None:
        """Render one emission."""

    def release(self) -> None:
        if self.vao:
            self.vao.release()
        if self.vbo:
            self.vbo.release()
        if self.abo:
            self.abo.release()
        if self.program:
            self.program.release()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _to_mvp_bytes(mvp: glm.mat4, fixture_model: glm.mat4, local: glm.mat4) -> bytes:
    """Compose chassis × local, then mvp × model, into 16 floats."""
    final_mvp = mvp * fixture_model * local
    return np.array(
        [x for col in final_mvp.to_list() for x in col],
        dtype='f4',
    ).tobytes()


def _setup_additive_blending(ctx: moderngl.Context) -> None:
    ctx.enable(moderngl.BLEND)
    ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE)
    # NB: ``ctx.depth_mask = False`` is a no-op in moderngl 5.11.x.
    # Use the real glDepthMask via ctypes so beams don't write depth
    # and occlude subsequent chassis draws (see gl_state.py).
    set_depth_mask(False)


def _restore_state(ctx: moderngl.Context) -> None:
    set_depth_mask(True)
    ctx.disable(moderngl.BLEND)


# ---------------------------------------------------------------------------
# GlowBeam — short glow cone (PAR / wash fallback)
# ---------------------------------------------------------------------------


class GlowBeam(BeamComponent):
    """Short glow cone, ~0.8m long with wide spread. The cheap fallback."""

    def __init__(
        self,
        ctx: moderngl.Context,
        length_m: float = 0.8,
        cone_angle_deg: float = 40.0,
    ):
        super().__init__(ctx)
        self.length_m = length_m
        self.cone_angle_deg = cone_angle_deg

        radius = length_m * math.tan(math.radians(cone_angle_deg / 2.0))
        verts, alphas = GeometryBuilder.create_beam_cone(radius, length_m, segments=16)

        self.program = ctx.program(
            vertex_shader=BEAM_VERTEX_SHADER,
            fragment_shader=BEAM_FRAGMENT_SHADER,
        )
        self.vbo = ctx.buffer(verts.tobytes())
        self.abo = ctx.buffer(alphas.tobytes())
        self.vao = ctx.vertex_array(
            self.program,
            [
                (self.vbo, '3f', 'in_position'),
                (self.abo, '1f', 'in_alpha'),
            ],
        )

    def render_emission(
        self,
        mvp: glm.mat4,
        fixture_model: glm.mat4,
        emission: Emission,
        modifiers: BeamModifiers = _DEFAULT_MODIFIERS,
    ) -> None:
        if emission.dimmer < 0.01:
            return
        mvp_bytes = _to_mvp_bytes(mvp, fixture_model, emission.local_transform)
        _setup_additive_blending(self.ctx)
        try:
            self.program['mvp'].write(mvp_bytes)
            self.program['beam_color'].value = emission.color
            self.program['beam_intensity'].value = emission.dimmer * modifiers.brightness_scale
            self.vao.render(moderngl.TRIANGLES)
        finally:
            _restore_state(self.ctx)


# ---------------------------------------------------------------------------
# CylindricalBeam — short cylindrical column (PAR canister)
# ---------------------------------------------------------------------------


class CylindricalBeam(BeamComponent):
    """Stubby cylindrical beam column. Mirrors ``PARRenderer._create_cylindrical_beam``."""

    def __init__(
        self,
        ctx: moderngl.Context,
        radius_m: float = 0.18,
        length_m: float = 1.2,
    ):
        super().__init__(ctx)
        self.radius_m = radius_m
        self.length_m = length_m

        verts, alphas = GeometryBuilder.create_beam_cylinder(radius_m, length_m, segments=20)

        self.program = ctx.program(
            vertex_shader=BEAM_VERTEX_SHADER,
            fragment_shader=BEAM_FRAGMENT_SHADER,
        )
        self.vbo = ctx.buffer(verts.tobytes())
        self.abo = ctx.buffer(alphas.tobytes())
        self.vao = ctx.vertex_array(
            self.program,
            [
                (self.vbo, '3f', 'in_position'),
                (self.abo, '1f', 'in_alpha'),
            ],
        )

    def render_emission(
        self,
        mvp: glm.mat4,
        fixture_model: glm.mat4,
        emission: Emission,
        modifiers: BeamModifiers = _DEFAULT_MODIFIERS,
    ) -> None:
        if emission.dimmer < 0.01:
            return
        mvp_bytes = _to_mvp_bytes(mvp, fixture_model, emission.local_transform)
        _setup_additive_blending(self.ctx)
        try:
            self.program['mvp'].write(mvp_bytes)
            self.program['beam_color'].value = emission.color
            self.program['beam_intensity'].value = emission.dimmer * modifiers.brightness_scale
            self.vao.render(moderngl.TRIANGLES)
        finally:
            _restore_state(self.ctx)


# ---------------------------------------------------------------------------
# ConeBeam — moving-head beam with gobo + focus modulation
# ---------------------------------------------------------------------------


class ConeBeam(BeamComponent):
    """Long narrow cone. Consumes gobo_pattern / gobo_rotation / focus_sharpness modifiers.

    When ``modifiers.prism_active`` is True, renders ``modifiers.prism_facets``
    beams arranged around the beam axis at uniform 360/N° offsets, each tilted
    outward by ``PRISM_TILT_DEG`` and at ``PRISM_INTENSITY_PER_FACET`` of the
    base intensity. Mirrors :meth:`MovingHeadRenderer._render_beam` legacy
    behavior (default 3 facets at 120°, 10° tilt, 40% intensity per facet).
    """

    PRISM_TILT_DEG = 10.0
    PRISM_INTENSITY_PER_FACET = 0.4

    def __init__(
        self,
        ctx: moderngl.Context,
        length_m: float = 6.0,
        cone_angle_deg: float = 15.0,
    ):
        super().__init__(ctx)
        self.length_m = length_m
        self.cone_angle_deg = cone_angle_deg

        radius = length_m * math.tan(math.radians(cone_angle_deg / 2.0))
        verts, alphas = GeometryBuilder.create_beam_cone(radius, length_m, segments=24)

        self.program = ctx.program(
            vertex_shader=GOBO_BEAM_VERTEX_SHADER,
            fragment_shader=GOBO_BEAM_FRAGMENT_SHADER,
        )
        self.vbo = ctx.buffer(verts.tobytes())
        self.abo = ctx.buffer(alphas.tobytes())
        self.vao = ctx.vertex_array(
            self.program,
            [
                (self.vbo, '3f', 'in_position'),
                (self.abo, '1f', 'in_alpha'),
            ],
        )

    def render_emission(
        self,
        mvp: glm.mat4,
        fixture_model: glm.mat4,
        emission: Emission,
        modifiers: BeamModifiers = _DEFAULT_MODIFIERS,
    ) -> None:
        if emission.dimmer < 0.01:
            return

        if modifiers.prism_active and modifiers.prism_facets > 1:
            self._render_prism_facets(mvp, fixture_model, emission, modifiers)
        else:
            self._render_one(
                mvp, fixture_model, emission.local_transform,
                emission, modifiers, intensity_scale=1.0,
            )

    def _render_one(
        self,
        mvp: glm.mat4,
        fixture_model: glm.mat4,
        local_transform: glm.mat4,
        emission: Emission,
        modifiers: BeamModifiers,
        intensity_scale: float,
    ) -> None:
        mvp_bytes = _to_mvp_bytes(mvp, fixture_model, local_transform)
        _setup_additive_blending(self.ctx)
        try:
            self.program['mvp'].write(mvp_bytes)
            self.program['beam_color'].value = emission.color
            self.program['beam_intensity'].value = (
                emission.dimmer * modifiers.brightness_scale * intensity_scale
            )
            self.program['gobo_pattern'].value = modifiers.gobo_pattern
            self.program['gobo_rotation'].value = modifiers.gobo_rotation_rad
            self.program['focus_sharpness'].value = modifiers.focus_sharpness
            self.vao.render(moderngl.TRIANGLES)
        finally:
            _restore_state(self.ctx)

    def _render_prism_facets(
        self,
        mvp: glm.mat4,
        fixture_model: glm.mat4,
        emission: Emission,
        modifiers: BeamModifiers,
    ) -> None:
        """Render N facet beams at evenly-spaced rotations around the beam axis.

        Beam cone is built along +Z, so:
        - rotation around the beam axis = rotation around local Z
        - outward tilt = rotation around local Y, applied first
        These are pre-multiplied into the emission's local_transform.
        """
        n = modifiers.prism_facets
        tilt_mat = glm.rotate(
            glm.mat4(1.0),
            glm.radians(self.PRISM_TILT_DEG),
            glm.vec3(0, 1, 0),
        )
        for i in range(n):
            offset_deg = (360.0 / n) * i
            rot_mat = glm.rotate(
                glm.mat4(1.0),
                glm.radians(offset_deg),
                glm.vec3(0, 0, 1),
            )
            local = emission.local_transform * rot_mat * tilt_mat
            self._render_one(
                mvp, fixture_model, local, emission, modifiers,
                intensity_scale=self.PRISM_INTENSITY_PER_FACET,
            )


# ---------------------------------------------------------------------------
# RectangularBeam — wash-style wide rectangular volume
# ---------------------------------------------------------------------------


class RectangularBeam(BeamComponent):
    """Wide rectangular beam volume (wash). Mirrors WashRenderer's rect beam."""

    def __init__(
        self,
        ctx: moderngl.Context,
        width_m: float = 0.8,
        height_m: float = 0.8,
        length_m: float = 2.0,
    ):
        super().__init__(ctx)
        self.width_m = width_m
        self.height_m = height_m
        self.length_m = length_m

        verts, alphas = GeometryBuilder.create_beam_box(width_m, height_m, length_m)

        self.program = ctx.program(
            vertex_shader=BEAM_VERTEX_SHADER,
            fragment_shader=BEAM_FRAGMENT_SHADER,
        )
        self.vbo = ctx.buffer(verts.tobytes())
        self.abo = ctx.buffer(alphas.tobytes())
        self.vao = ctx.vertex_array(
            self.program,
            [
                (self.vbo, '3f', 'in_position'),
                (self.abo, '1f', 'in_alpha'),
            ],
        )

    def render_emission(
        self,
        mvp: glm.mat4,
        fixture_model: glm.mat4,
        emission: Emission,
        modifiers: BeamModifiers = _DEFAULT_MODIFIERS,
    ) -> None:
        if emission.dimmer < 0.01:
            return
        mvp_bytes = _to_mvp_bytes(mvp, fixture_model, emission.local_transform)
        _setup_additive_blending(self.ctx)
        try:
            self.program['mvp'].write(mvp_bytes)
            self.program['beam_color'].value = emission.color
            self.program['beam_intensity'].value = emission.dimmer * modifiers.brightness_scale
            self.vao.render(moderngl.TRIANGLES)
        finally:
            _restore_state(self.ctx)


# ---------------------------------------------------------------------------
# SegmentedRectBeam — one short rectangular-box glow per cell
# (pixel bar / LED bar; mirrors the legacy PixelBarRenderer / LEDBarRenderer)
# ---------------------------------------------------------------------------


class SegmentedRectBeam(BeamComponent):
    """Per-cell short rectangular box glow.

    Mirrors :meth:`PixelBarRenderer._create_segment_beams` / the matching
    LED bar code: a thin "wall of light" emerging from each cell's
    emitter slab. Width/height come from the cell footprint so the beam
    sits flush with the visible slab on the chassis front face.
    """

    def __init__(
        self,
        ctx: moderngl.Context,
        cell_width_m: float = 0.05,
        cell_height_m: float = 0.05,
        length_m: float = 0.3,
    ):
        super().__init__(ctx)
        self.cell_width_m = cell_width_m
        self.cell_height_m = cell_height_m
        self.length_m = length_m

        verts, alphas = GeometryBuilder.create_beam_box(
            cell_width_m, cell_height_m, length_m,
        )

        self.program = ctx.program(
            vertex_shader=BEAM_VERTEX_SHADER,
            fragment_shader=BEAM_FRAGMENT_SHADER,
        )
        self.vbo = ctx.buffer(verts.tobytes())
        self.abo = ctx.buffer(alphas.tobytes())
        self.vao = ctx.vertex_array(
            self.program,
            [
                (self.vbo, '3f', 'in_position'),
                (self.abo, '1f', 'in_alpha'),
            ],
        )

    def render_emission(
        self,
        mvp: glm.mat4,
        fixture_model: glm.mat4,
        emission: Emission,
        modifiers: BeamModifiers = _DEFAULT_MODIFIERS,
    ) -> None:
        if emission.dimmer < 0.01:
            return
        mvp_bytes = _to_mvp_bytes(mvp, fixture_model, emission.local_transform)
        _setup_additive_blending(self.ctx)
        try:
            self.program['mvp'].write(mvp_bytes)
            self.program['beam_color'].value = emission.color
            self.program['beam_intensity'].value = (
                emission.dimmer * modifiers.brightness_scale
            )
            self.vao.render(moderngl.TRIANGLES)
        finally:
            _restore_state(self.ctx)


# ---------------------------------------------------------------------------
# SegmentedCylinderBeam — one short cylindrical glow per cell (sunstrip)
# ---------------------------------------------------------------------------


class SegmentedCylinderBeam(BeamComponent):
    """Per-cell short cylindrical glow.

    Mirrors :meth:`SunstripRenderer._render_segment_beams`: each lamp gets
    a stubby cylindrical column of light extending from its bulb.
    """

    def __init__(
        self,
        ctx: moderngl.Context,
        radius_m: float = 0.025,
        length_m: float = 0.3,
    ):
        super().__init__(ctx)
        self.radius_m = radius_m
        self.length_m = length_m

        verts, alphas = GeometryBuilder.create_beam_cylinder(
            radius_m, length_m, segments=10,
        )

        self.program = ctx.program(
            vertex_shader=BEAM_VERTEX_SHADER,
            fragment_shader=BEAM_FRAGMENT_SHADER,
        )
        self.vbo = ctx.buffer(verts.tobytes())
        self.abo = ctx.buffer(alphas.tobytes())
        self.vao = ctx.vertex_array(
            self.program,
            [
                (self.vbo, '3f', 'in_position'),
                (self.abo, '1f', 'in_alpha'),
            ],
        )

    def render_emission(
        self,
        mvp: glm.mat4,
        fixture_model: glm.mat4,
        emission: Emission,
        modifiers: BeamModifiers = _DEFAULT_MODIFIERS,
    ) -> None:
        if emission.dimmer < 0.01:
            return
        mvp_bytes = _to_mvp_bytes(mvp, fixture_model, emission.local_transform)
        _setup_additive_blending(self.ctx)
        try:
            self.program['mvp'].write(mvp_bytes)
            self.program['beam_color'].value = emission.color
            self.program['beam_intensity'].value = (
                emission.dimmer * modifiers.brightness_scale
            )
            self.vao.render(moderngl.TRIANGLES)
        finally:
            _restore_state(self.ctx)
