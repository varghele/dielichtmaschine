"""Emitter runners for the composable fixture renderer (Phase B).

A :class:`EmitterRunner` expands one logical fixture into one or more
:class:`Emission` instances per frame. Each Emission describes the local
transform, color, and dimmer for one emission point — the renderer iterates
the list, multiplies the local transform onto the chassis model matrix,
and calls the beam component's ``render()`` once per Emission.

The runners own per-cell / per-head DMX state. They implement
:class:`FixtureComponent` (so the FixtureRenderer can pass them DMX
updates uniformly), but unlike state-only components they also drive
the emission loop.

ParticlePlumeRunner and LaserVectorRunner are stubs — defined here so
the type hierarchy is complete; implementation deferred to v2.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Iterator, List, Optional, Tuple

import glm

from utils.fixture_capabilities import (
    CellArray,
    Emitter,
    LaserVector,
    MultiHead,
    ParticlePlume,
    PointEmitter,
)
from visualizer.renderer.components import (
    ColorComponent,
    DimmerComponent,
    FixtureComponent,
    MovementComponent,
    _read_dmx,
)


# ---------------------------------------------------------------------------
# Emission descriptor
# ---------------------------------------------------------------------------


@dataclass
class Emission:
    """One emission point produced by an EmitterRunner.

    ``local_transform`` is from the chassis origin. The renderer
    multiplies it onto the chassis model matrix before invoking the
    beam component.
    """
    local_transform: glm.mat4 = field(default_factory=lambda: glm.mat4(1.0))
    color: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    dimmer: float = 0.0
    # Per-head pan/tilt — used by ConeBeam-style beams that compute their
    # own beam direction. None when this emission has no movement.
    pan_deg: Optional[float] = None
    tilt_deg: Optional[float] = None


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class EmitterRunner(FixtureComponent):
    """Owns per-cell/per-head state. Yields Emissions for the current frame."""

    @abstractmethod
    def emissions(
        self,
        chassis_color: Optional[ColorComponent],
        chassis_dimmer: Optional[DimmerComponent],
    ) -> Iterator[Emission]:
        """Yield Emissions for this frame. ``chassis_color`` and
        ``chassis_dimmer`` are fallbacks for sub-emissions that don't
        carry their own color/dimmer (e.g. dimmer-only cells)."""


# ---------------------------------------------------------------------------
# PointEmitterRunner — single emission at the chassis origin
# ---------------------------------------------------------------------------


class PointEmitterRunner(EmitterRunner):
    """Single emission point at the chassis origin. PAR, wash, single-head MH, …

    ``beam_origin_xform_fn`` (if provided) returns the chassis-local
    transform that places the cone at the fixture's emission point and
    orients it along its outgoing direction. For moving heads this is
    pan × head_translate × tilt × lens_offset × cone_rotation; for static
    chassis it's typically identity (cone +Z is already correct).
    """

    def __init__(
        self,
        emitter: PointEmitter,
        movement: Optional[MovementComponent] = None,
        beam_origin_xform_fn: Optional[Callable[[float, float], glm.mat4]] = None,
    ):
        self.emitter = emitter
        self.movement = movement
        self.beam_origin_xform_fn = beam_origin_xform_fn

    def update_dmx(self, dmx_data: bytes, address: int) -> None:
        # PointEmitter has no per-cell state; chassis-level movement
        # component (if any) is owned + updated by the FixtureRenderer
        # directly, not by us. Nothing to do here.
        pass

    def emissions(
        self,
        chassis_color: Optional[ColorComponent],
        chassis_dimmer: Optional[DimmerComponent],
    ) -> Iterator[Emission]:
        color = chassis_color.rgb if chassis_color is not None else (1.0, 1.0, 1.0)
        dimmer = chassis_dimmer.normalized if chassis_dimmer is not None else 1.0

        pan = self.movement.pan_deg if self.movement is not None else 0.0
        tilt = self.movement.tilt_deg if self.movement is not None else 0.0
        if self.beam_origin_xform_fn is not None:
            local = self.beam_origin_xform_fn(pan, tilt)
        else:
            local = glm.mat4(1.0)

        yield Emission(
            local_transform=local,
            color=color,
            dimmer=dimmer,
            pan_deg=pan if self.movement is not None else None,
            tilt_deg=tilt if self.movement is not None else None,
        )


# ---------------------------------------------------------------------------
# CellArrayRunner — N independently-addressable cells (pixel bar / matrix / sunstrip)
# ---------------------------------------------------------------------------


@dataclass
class CellState:
    """DMX-derived state for one cell of a CellArrayRunner."""
    rgb: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    dimmer: float = 1.0          # 1.0 if cell has no per-cell dimmer
    has_color: bool = False      # True if any RGB(W) channels exist for this cell


class CellArrayRunner(EmitterRunner):
    """``W*H`` cells laid out in a rectangle. Each cell has its own DMX state."""

    def __init__(
        self,
        emitter: CellArray,
        body_dims_m: Tuple[float, float, float],
    ):
        self.emitter = emitter
        self.body_dims_m = body_dims_m
        self.cell_states: List[CellState] = [CellState() for _ in emitter.cells]
        self.cell_offsets: List[glm.vec3] = list(_compute_cell_offsets(emitter, body_dims_m))

    def update_dmx(self, dmx_data: bytes, address: int) -> None:
        for state, cell in zip(self.cell_states, self.emitter.cells):
            has_color = (
                cell.red_channel is not None
                or cell.green_channel is not None
                or cell.blue_channel is not None
            )
            state.has_color = has_color
            if has_color:
                r = _read_dmx(dmx_data, address, cell.red_channel) / 255.0
                g = _read_dmx(dmx_data, address, cell.green_channel) / 255.0
                b = _read_dmx(dmx_data, address, cell.blue_channel) / 255.0
                w = _read_dmx(dmx_data, address, cell.white_channel) / 255.0
                # White adds to all three additively (clamped).
                state.rgb = (min(1.0, r + w), min(1.0, g + w), min(1.0, b + w))
            else:
                state.rgb = (1.0, 1.0, 1.0)
            if cell.dimmer_channel is not None:
                state.dimmer = _read_dmx(dmx_data, address, cell.dimmer_channel) / 255.0
            else:
                state.dimmer = 1.0

    def emissions(
        self,
        chassis_color: Optional[ColorComponent],
        chassis_dimmer: Optional[DimmerComponent],
    ) -> Iterator[Emission]:
        master = chassis_dimmer.normalized if chassis_dimmer is not None else 1.0
        fallback_rgb = chassis_color.rgb if chassis_color is not None else (1.0, 1.0, 1.0)
        for state, offset in zip(self.cell_states, self.cell_offsets):
            color = state.rgb if state.has_color else fallback_rgb
            yield Emission(
                local_transform=glm.translate(glm.mat4(1.0), offset),
                color=color,
                dimmer=master * state.dimmer,
            )


def _compute_cell_offsets(
    emitter: CellArray,
    body_dims_m: Tuple[float, float, float],
) -> Iterator[glm.vec3]:
    """Evenly distribute cells across the chassis body footprint.

    Convention: cells laid out in the body's local X-Y plane (width = X,
    height = Y); Z stays at 0. Row-major matches CellArray.cells order.

    Cells span the inner 90% of the body so the legacy bar chassis (which
    drew per-cell slabs with a margin) and the composable cone offsets line
    up — important now that :class:`PixelBarChassisGeometry` and
    :class:`SunstripChassisGeometry` draw visible emitter slabs at these
    positions and the beam must emerge from the slab, not from the chassis
    edge.
    """
    if emitter.width <= 0 or emitter.height <= 0:
        yield glm.vec3(0.0, 0.0, 0.0)
        return

    body_w, body_h, body_d = body_dims_m
    span_w = body_w * 0.9
    span_h = body_h * 0.9
    cell_w = span_w / emitter.width
    cell_h = span_h / emitter.height
    start_x = -span_w / 2.0 + cell_w / 2.0
    start_y = -span_h / 2.0 + cell_h / 2.0
    # Cells emit from just above the body's front face so beams emerge from
    # the visible emitter slabs / lamp bulbs the chassis draws there.
    z = body_d / 2.0 + 0.005

    for row in range(emitter.height):
        for col in range(emitter.width):
            yield glm.vec3(
                start_x + col * cell_w,
                start_y + row * cell_h,
                z,
            )


# ---------------------------------------------------------------------------
# MultiHeadRunner — N heads with independent pan/tilt + color (moving-head bar, spider)
# ---------------------------------------------------------------------------


@dataclass
class HeadState:
    """DMX-derived state for one head of a MultiHeadRunner."""
    rgb: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    dimmer: float = 1.0
    pan_deg: float = 0.0
    tilt_deg: float = 0.0


class MultiHeadRunner(EmitterRunner):
    """N heads on one chassis, each with own pan/tilt + color/dimmer."""

    def __init__(self, emitter: MultiHead):
        self.emitter = emitter
        self.head_states: List[HeadState] = [HeadState() for _ in emitter.heads]

    def update_dmx(self, dmx_data: bytes, address: int) -> None:
        for state, head in zip(self.head_states, self.emitter.heads):
            if head.color_mixing is not None:
                ch = head.color_mixing.channels
                r = _read_dmx(dmx_data, address, ch.get('red')) / 255.0
                g = _read_dmx(dmx_data, address, ch.get('green')) / 255.0
                b = _read_dmx(dmx_data, address, ch.get('blue')) / 255.0
                w = _read_dmx(dmx_data, address, ch.get('white')) / 255.0
                state.rgb = (min(1.0, r + w), min(1.0, g + w), min(1.0, b + w))
            else:
                state.rgb = (1.0, 1.0, 1.0)
            if head.dimmer_channel is not None:
                state.dimmer = _read_dmx(dmx_data, address, head.dimmer_channel) / 255.0
            else:
                state.dimmer = 1.0
            if head.movement is not None:
                m = head.movement
                pan_coarse = _read_dmx(dmx_data, address, m.pan_channel)
                pan_fine = _read_dmx(dmx_data, address, m.pan_fine_channel)
                tilt_coarse = _read_dmx(dmx_data, address, m.tilt_channel)
                tilt_fine = _read_dmx(dmx_data, address, m.tilt_fine_channel)
                pan_combined = (pan_coarse * 256 + pan_fine) / 65535.0
                tilt_combined = (tilt_coarse * 256 + tilt_fine) / 65535.0
                state.pan_deg = (pan_combined - 0.5) * m.pan_max_deg
                state.tilt_deg = (tilt_combined - 0.5) * m.tilt_max_deg

    # 90° rotation around local Y that takes the beam cone (built along +Z by
    # GeometryBuilder.create_beam_cone) and points it along the head's local +X
    # — matching :meth:`MovingYokeChassisGeometry.beam_origin_transform`.
    _CONE_ROTATION_90Y = glm.rotate(glm.mat4(1.0), glm.radians(90.0), glm.vec3(0, 1, 0))

    def emissions(
        self,
        chassis_color: Optional[ColorComponent],
        chassis_dimmer: Optional[DimmerComponent],
    ) -> Iterator[Emission]:
        master = chassis_dimmer.normalized if chassis_dimmer is not None else 1.0
        for state, head in zip(self.head_states, self.emitter.heads):
            # Build per-head local transform:
            #   head_offset × pan × tilt × cone_rotation_90Y
            # Applied right-to-left: rotate cone +Z → +X, then tilt around Y,
            # then pan around Z, then translate to the head's slot along the
            # chassis. Matches the chassis-level chain in
            # MovingYokeChassisGeometry.beam_origin_transform, minus the
            # head_translate (heads in a multi-head bar share a flat chassis,
            # not a yoke-and-head compound).
            t = glm.translate(glm.mat4(1.0), glm.vec3(*head.offset_m))
            t = glm.rotate(t, glm.radians(state.pan_deg), glm.vec3(0, 0, 1))
            t = glm.rotate(t, glm.radians(-state.tilt_deg), glm.vec3(0, 1, 0))
            t = t * self._CONE_ROTATION_90Y
            yield Emission(
                local_transform=t,
                color=state.rgb,
                dimmer=master * state.dimmer,
                pan_deg=state.pan_deg if head.movement is not None else None,
                tilt_deg=state.tilt_deg if head.movement is not None else None,
            )


# ---------------------------------------------------------------------------
# v2 stubs — particle and laser emitters (deferred)
# ---------------------------------------------------------------------------


class ParticlePlumeRunner(EmitterRunner):
    """Hazer/smoke/fog particle emitter. v2 stub — yields a single point."""

    def __init__(self, emitter: ParticlePlume):
        self.emitter = emitter
        self._density = 0

    def update_dmx(self, dmx_data: bytes, address: int) -> None:
        self._density = _read_dmx(dmx_data, address, self.emitter.density_channel)

    def emissions(
        self,
        chassis_color: Optional[ColorComponent],
        chassis_dimmer: Optional[DimmerComponent],
    ) -> Iterator[Emission]:
        # Placeholder: emit a single dim point so the fixture is still visible.
        yield Emission(
            color=(0.7, 0.7, 0.7),
            dimmer=self._density / 255.0,
        )


class LaserVectorRunner(EmitterRunner):
    """ILDA-style laser. v2 stub."""

    def __init__(self, emitter: LaserVector):
        self.emitter = emitter

    def update_dmx(self, dmx_data: bytes, address: int) -> None:
        pass

    def emissions(
        self,
        chassis_color: Optional[ColorComponent],
        chassis_dimmer: Optional[DimmerComponent],
    ) -> Iterator[Emission]:
        yield Emission(color=(1.0, 0.0, 0.0), dimmer=1.0)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_emitter_runner(
    emitter: Emitter,
    body_dims_m: Tuple[float, float, float],
    chassis_movement: Optional[MovementComponent] = None,
    beam_origin_xform_fn: Optional[Callable[[float, float], glm.mat4]] = None,
) -> EmitterRunner:
    """Build the right EmitterRunner for an Emitter variant.

    ``chassis_movement`` is threaded into ``PointEmitterRunner`` so its
    Emissions can carry the chassis-level pan/tilt for ConeBeam to use.

    ``beam_origin_xform_fn`` is the chassis's beam-emission transform
    (returns chassis-local mat4 for ``(pan_deg, tilt_deg)``). For moving
    yokes this orients the cone along the head's local +X; for static
    chassis it's typically left as None (cone +Z is correct as built).
    """
    if isinstance(emitter, PointEmitter):
        return PointEmitterRunner(
            emitter,
            movement=chassis_movement,
            beam_origin_xform_fn=beam_origin_xform_fn,
        )
    if isinstance(emitter, CellArray):
        return CellArrayRunner(emitter, body_dims_m=body_dims_m)
    if isinstance(emitter, MultiHead):
        return MultiHeadRunner(emitter)
    if isinstance(emitter, ParticlePlume):
        return ParticlePlumeRunner(emitter)
    if isinstance(emitter, LaserVector):
        return LaserVectorRunner(emitter)
    raise TypeError(f"No EmitterRunner for emitter type {type(emitter).__name__}")
