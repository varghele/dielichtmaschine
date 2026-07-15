"""Composable FixtureRenderer (Phase B).

Composes :class:`utils.fixture_capabilities.FixtureCapabilities` into a
:class:`ChassisGeometry` + a list of :class:`FixtureComponent`s + a
:class:`BeamComponent` + an :class:`EmitterRunner`.

The renderer is not yet wired into ``FixtureManager`` — Phase D does
that. Phase B's job is just to make sure the composition produces a
correct, callable renderer for every supported fixture archetype.

Layout (rendered per frame in ``render(mvp)``):

1. ``get_model_matrix()`` — chassis position + yaw/pitch/roll
2. ``chassis.render(mvp, model)`` — body mesh
3. ``emitter_runner.emissions()`` → list of :class:`Emission`s
4. for each emission: ``beam.render_emission(mvp, model, emission, modifiers)``
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import glm
import moderngl

from utils.fixture_capabilities import (
    CellArray,
    Chassis,
    FixtureCapabilities,
    MultiHead,
    PointEmitter,
)
from visualizer.renderer.beams import (
    BeamComponent,
    BeamModifiers,
    ConeBeam,
    CylindricalBeam,
    GlowBeam,
    RectangularBeam,
    SegmentedBeam,
    SegmentedCylinderBeam,
    SegmentedRectBeam,
)
from visualizer.renderer.chassis import (
    ChassisGeometry,
    ChassisRenderState,
    MovingYokeChassisGeometry,
    make_chassis_geometry,
)
from visualizer.renderer.floor_projection import FloorProjectionComponent
from visualizer.renderer.components import (
    ColorComponent,
    DimmerComponent,
    FixtureComponent,
    FocusComponent,
    FrostComponent,
    GoboComponent,
    IrisComponent,
    MovementComponent,
    PrismComponent,
    StrobeComponent,
    ZoomComponent,
)
from visualizer.renderer.emitters import (
    CellArrayRunner,
    EmitterRunner,
    create_emitter_runner,
)


# ---------------------------------------------------------------------------
# Beam selection
# ---------------------------------------------------------------------------


def _select_beam(
    ctx: moderngl.Context,
    capabilities: FixtureCapabilities,
) -> BeamComponent:
    """Pick the right BeamComponent variant for a fixture's capabilities.

    Decision tree (matches the legacy renderers' beam shapes):
    - MultiHead emitter / single moving head → ConeBeam (long cone with gobo).
    - BAR/PANEL with RGB cells (pixel bar / LED bar / matrix) →
      SegmentedRectBeam (short rectangular per-cell glow).
    - BAR/PANEL with dimmer-only cells (sunstrip) →
      SegmentedCylinderBeam (short cylindrical per-cell column).
    - BAR/PANEL with no cells, no optics → RectangularBeam (wash bar).
    - PAR with no optics (LED wash / flat par) → short RectangularBeam
      sized to the body (matches legacy WashRenderer rectangular glow).
    - PAR with optics → CylindricalBeam.
    - Otherwise → GlowBeam (cheap fallback).
    """
    chassis = capabilities.chassis
    emitter = capabilities.emitter
    has_movement = capabilities.movement is not None
    has_optics = capabilities.beam.has_optics
    has_cells = isinstance(emitter, CellArray)

    if isinstance(emitter, MultiHead) or has_movement:
        cone_angle = capabilities.beam.max_deg if has_optics else 15.0
        return ConeBeam(ctx, cone_angle_deg=cone_angle)

    if has_cells and chassis in (Chassis.BAR, Chassis.PANEL):
        body_w, body_h, _ = capabilities.body_dims_m
        n_cols = max(1, emitter.width)
        n_rows = max(1, emitter.height)
        cell_w = (body_w * 0.9) / n_cols
        cell_h = (
            (body_h * 0.9) / n_rows if n_rows > 1 else body_h * 0.6
        )
        if _cellarray_has_rgb(emitter):
            # PixelBar / LED Bar / matrix — rectangular box per cell.
            return SegmentedRectBeam(
                ctx,
                cell_width_m=cell_w * 0.85,
                cell_height_m=cell_h * 0.85,
                length_m=0.3,
            )
        # Sunstrip — cylindrical column per lamp.
        lamp_radius = min(cell_w * 0.35, 0.025)
        return SegmentedCylinderBeam(ctx, radius_m=lamp_radius, length_m=0.3)

    if chassis in (Chassis.BAR, Chassis.PANEL) and not has_optics:
        # Wash bar / video panel — wide short rectangular volume.
        w = capabilities.body_dims_m[0] * 0.6
        h = max(capabilities.body_dims_m[1] * 0.6, 0.3)
        return RectangularBeam(ctx, width_m=w, height_m=h, length_m=0.4)

    if chassis is Chassis.PAR and not has_optics:
        # LED wash / flat par — short rectangular glow sized to the body.
        body_w, body_h, _ = capabilities.body_dims_m
        return RectangularBeam(
            ctx,
            width_m=body_w * 0.7,
            height_m=body_h * 0.7,
            length_m=0.3,
        )

    if chassis is Chassis.PAR and has_optics:
        return CylindricalBeam(ctx)

    return GlowBeam(ctx)


def _cellarray_has_rgb(emitter: CellArray) -> bool:
    return any(
        c.red_channel is not None
        or c.green_channel is not None
        or c.blue_channel is not None
        for c in emitter.cells
    )


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


class FixtureRenderer:
    """Composable per-fixture renderer.

    Built from a :class:`FixtureCapabilities` plus runtime placement
    (position, orientation, universe/address) from ``fixture_data``.
    Owns its chassis mesh, beam GL resources, and a list of components
    that consume DMX.
    """

    def __init__(
        self,
        ctx: moderngl.Context,
        fixture_data: Dict[str, Any],
        capabilities: FixtureCapabilities,
    ):
        self.ctx = ctx
        self.capabilities = capabilities

        # --- placement / identity (same fields as legacy FixtureRenderer) ---
        self.name = fixture_data.get('name', 'Unknown')
        self.position = fixture_data.get('position', {'x': 0.0, 'y': 0.0, 'z': 0.0})

        orientation = fixture_data.get('orientation', {})
        self.mounting = orientation.get('mounting', 'hanging')
        self.yaw = orientation.get('yaw', 0.0)
        self.pitch = orientation.get('pitch', 0.0)
        self.roll = orientation.get('roll', 0.0)

        self.universe = fixture_data.get('universe', 1)
        self.address = fixture_data.get('address', 1)
        self.brightness_scale = 1.0

        # --- chassis geometry ---
        # Pass the emitter so a BAR/PANEL with a CellArray uses the
        # cell-aware chassis (visible emitter slabs / lamp bulbs), and a
        # PAR uses the lensed variant. GDTF-sourced fixtures try their
        # embedded 3D models first (QLC_GDTF_MESHES=0 disables).
        self.chassis_geom: ChassisGeometry = make_chassis_geometry(
            ctx, capabilities.chassis, capabilities.body_dims_m,
            emitter=capabilities.emitter,
            gdtf_source=self._resolve_gdtf_source(fixture_data, capabilities),
        )

        # --- state-only components (built only when the capability exists) ---
        self.movement: Optional[MovementComponent] = (
            MovementComponent(capabilities.movement) if capabilities.movement else None
        )
        self.color: Optional[ColorComponent] = (
            ColorComponent(mixing=capabilities.color_mixing, wheel=capabilities.color_wheel)
            if (capabilities.color_mixing or capabilities.color_wheel)
            else None
        )
        self.dimmer: Optional[DimmerComponent] = (
            DimmerComponent(capabilities.dimmer_channel)
            if capabilities.dimmer_channel is not None
            else None
        )
        self.strobe: Optional[StrobeComponent] = (
            StrobeComponent(capabilities.strobe_channel)
            if capabilities.strobe_channel is not None
            else None
        )
        self.gobo: Optional[GoboComponent] = (
            GoboComponent(capabilities.gobo_wheel) if capabilities.gobo_wheel else None
        )
        self.prism: Optional[PrismComponent] = (
            PrismComponent(capabilities.prism) if capabilities.prism else None
        )
        self.focus: Optional[FocusComponent] = (
            FocusComponent(capabilities.focus_channel)
            if capabilities.focus_channel is not None
            else None
        )
        self.iris: Optional[IrisComponent] = (
            IrisComponent(capabilities.iris_channel)
            if capabilities.iris_channel is not None
            else None
        )
        self.frost: Optional[FrostComponent] = (
            FrostComponent(capabilities.frost_channel)
            if capabilities.frost_channel is not None
            else None
        )
        self.zoom: Optional[ZoomComponent] = (
            ZoomComponent(capabilities.zoom_channel, capabilities.beam)
            if capabilities.zoom_channel is not None
            else None
        )

        # --- emitter runner ---
        # Thread the chassis's beam_origin_transform into the runner so the
        # cone (built along +Z) emerges at the right place and direction.
        # For moving yokes this incorporates pan/tilt + lens offset + 90°
        # rotation; for static chassis it's identity and the cone stays +Z.
        self.emitter_runner: EmitterRunner = create_emitter_runner(
            capabilities.emitter,
            body_dims_m=capabilities.body_dims_m,
            chassis_movement=self.movement,
            beam_origin_xform_fn=self.chassis_geom.beam_origin_transform,
        )

        # --- beam ---
        self.beam: BeamComponent = _select_beam(ctx, capabilities)

        # --- floor projection (MOVING_YOKE only — wash-style fixtures don't need a floor spot) ---
        self.floor_projection: Optional[FloorProjectionComponent] = (
            FloorProjectionComponent(ctx)
            if isinstance(self.chassis_geom, MovingYokeChassisGeometry)
            else None
        )

    # --- public API ---

    @property
    def components(self) -> List[FixtureComponent]:
        """Ordered list of non-None components. Useful for batch DMX updates / introspection."""
        result: List[FixtureComponent] = []
        for c in (
            self.movement,
            self.color,
            self.dimmer,
            self.strobe,
            self.gobo,
            self.prism,
            self.focus,
            self.iris,
            self.frost,
            self.zoom,
        ):
            if c is not None:
                result.append(c)
        result.append(self.emitter_runner)
        return result

    @staticmethod
    def _resolve_gdtf_source(fixture_data, capabilities):
        """(gdtf_path, GdtfData, mode_name) when this fixture's definition
        resolves to a GDTF with native geometry data; else None. Works in
        both the embedded (in-process) and standalone (TCP) visualizer -
        the library re-resolves from disk either way. QLC_GDTF_MESHES=0
        is the kill switch back to the procedural chassis."""
        import os
        if os.environ.get('QLC_GDTF_MESHES', '1') == '0':
            return None
        manufacturer = fixture_data.get('manufacturer')
        model = fixture_data.get('model')
        if not manufacturer or not model:
            return None
        try:
            from utils.fixture_library import get_definition
            defn = get_definition(manufacturer, model)
        except Exception:
            return None
        if defn is None or defn.gdtf is None:
            return None
        return (defn.path, defn.gdtf, capabilities.mode_name)

    def get_model_matrix(self) -> glm.mat4:
        """Chassis model matrix from position + yaw/pitch/roll.

        Uses the same convention as the legacy renderer: stage X→3D X,
        stage Y→3D Z, stage Z (height)→3D Y. Rotation order YXZ.
        """
        m = glm.mat4(1.0)
        p = self.position
        m = glm.translate(m, glm.vec3(p['x'], p['z'], p['y']))
        m = glm.rotate(m, glm.radians(self.yaw), glm.vec3(0, 1, 0))
        m = glm.rotate(m, glm.radians(self.pitch), glm.vec3(1, 0, 0))
        m = glm.rotate(m, glm.radians(self.roll), glm.vec3(0, 0, 1))
        return m

    def update_dmx(self, dmx_data: bytes) -> None:
        """Fan-out the DMX universe buffer to every component."""
        for c in self.components:
            c.update_dmx(dmx_data, self.address)

    def render(self, mvp: glm.mat4) -> None:
        """Render lighting (additive light volumes), then chassis (opaque on top).

        :class:`FixtureManager.render` calls :meth:`render_lighting` and
        :meth:`render_chassis` separately across all fixtures so chassis
        silhouettes stay readable underneath bright / overlapping beams.
        Direct callers (older tests) still get a self-contained render.
        """
        self.render_lighting(mvp)
        self.render_chassis(mvp)

    def render_lighting(self, mvp: glm.mat4) -> None:
        """Render additive light volumes: beam cones + floor projection.

        Depth-tested against whatever opaque geometry (stage, previously
        drawn chassis) sits in the depth buffer, but does NOT write depth
        itself — so later chassis draws can overwrite the additive
        contributions at their own silhouette pixels.
        """
        model = self.get_model_matrix()
        modifiers = self._build_modifiers()

        for emission in self.emitter_runner.emissions(self.color, self.dimmer):
            self.beam.render_emission(mvp, model, emission, modifiers)

        if self.floor_projection is not None:
            self._render_floor_projection(mvp, model, modifiers)

    def render_chassis(self, mvp: glm.mat4) -> None:
        """Render the opaque chassis body.

        Drawn AFTER lighting in the two-pass FixtureManager flow so the
        chassis silhouette always reads at its native color, even when
        sitting under additive beam contributions from other fixtures.
        """
        model = self.get_model_matrix()
        chassis_state = self._build_chassis_state()
        self.chassis_geom.render(mvp, model, chassis_state)

    def release(self) -> None:
        self.chassis_geom.release()
        self.beam.release()
        if self.floor_projection is not None:
            self.floor_projection.release()

    # --- internal ---

    # --- Floor projection (MOVING_YOKE only) ---

    def _render_floor_projection(
        self,
        mvp: glm.mat4,
        model: glm.mat4,
        modifiers: BeamModifiers,
    ) -> None:
        """Render the gobo+focus floor spot beneath a moving head.

        Mirrors the legacy :meth:`MovingHeadRenderer._render_floor_projection`,
        including prism dispatch (3 facets at 120° around the beam axis,
        ~10° outward tilt, 40% intensity each).
        """
        if not isinstance(self.chassis_geom, MovingYokeChassisGeometry):
            return
        if self.color is None or self.dimmer is None:
            return  # no visible output without color/dimmer
        if self.dimmer.normalized < 0.01:
            return

        pan_deg = self.movement.pan_deg if self.movement is not None else 0.0
        tilt_deg = self.movement.tilt_deg if self.movement is not None else 0.0
        lens_pos = self.chassis_geom.lens_world_pos(model, pan_deg, tilt_deg)

        beam_angle_deg = (
            self.zoom.current_angle_deg
            if self.zoom is not None
            else self.capabilities.beam.max_deg or 25.0
        )
        color = self.color.rgb
        dimmer = self.dimmer.normalized

        if modifiers.prism_active and modifiers.prism_facets > 1:
            n = modifiers.prism_facets
            tilt_per_facet = 10.0  # legacy outward tilt
            for i in range(n):
                offset_deg = (360.0 / n) * i
                facet_dir = self._compute_beam_dir_world(
                    pan_deg, tilt_deg,
                    prism_offset_deg=offset_deg,
                    prism_outward_tilt_deg=tilt_per_facet,
                )
                self.floor_projection.render(
                    mvp,
                    lens_world_pos=lens_pos,
                    beam_dir_world=facet_dir,
                    beam_angle_deg=beam_angle_deg,
                    color=color,
                    dimmer=dimmer,
                    gobo_pattern=modifiers.gobo_pattern,
                    gobo_rotation_rad=modifiers.gobo_rotation_rad,
                    focus_sharpness=modifiers.focus_sharpness,
                    brightness_scale=modifiers.brightness_scale,
                    intensity_scale=0.4,
                )
        else:
            beam_dir = self._compute_beam_dir_world(pan_deg, tilt_deg)
            self.floor_projection.render(
                mvp,
                lens_world_pos=lens_pos,
                beam_dir_world=beam_dir,
                beam_angle_deg=beam_angle_deg,
                color=color,
                dimmer=dimmer,
                gobo_pattern=modifiers.gobo_pattern,
                gobo_rotation_rad=modifiers.gobo_rotation_rad,
                focus_sharpness=modifiers.focus_sharpness,
                brightness_scale=modifiers.brightness_scale,
                intensity_scale=1.0,
            )

    def _compute_beam_dir_world(
        self,
        pan_deg: float,
        tilt_deg: float,
        *,
        prism_offset_deg: float = 0.0,
        prism_outward_tilt_deg: float = 0.0,
    ) -> glm.vec3:
        """Compute the beam direction in world (Y-up) coordinates.

        Mirrors the legacy :meth:`MovingHeadRenderer.get_beam_direction`
        chain: fixture orientation × pan × tilt × prism_rotation × prism_tilt
        applied to the chassis-local +X axis.
        """
        direction = glm.vec3(1, 0, 0)
        tilt_mat = glm.rotate(glm.mat4(1.0), glm.radians(-tilt_deg), glm.vec3(0, 1, 0))
        pan_mat = glm.rotate(glm.mat4(1.0), glm.radians(pan_deg), glm.vec3(0, 0, 1))
        fixture_mat = glm.mat4(1.0)
        fixture_mat = glm.rotate(fixture_mat, glm.radians(self.yaw), glm.vec3(0, 1, 0))
        fixture_mat = glm.rotate(fixture_mat, glm.radians(self.pitch), glm.vec3(1, 0, 0))
        fixture_mat = glm.rotate(fixture_mat, glm.radians(self.roll), glm.vec3(0, 0, 1))

        prism_rot_mat = glm.rotate(
            glm.mat4(1.0), glm.radians(prism_offset_deg), glm.vec3(1, 0, 0),
        )
        prism_tilt_mat = glm.rotate(
            glm.mat4(1.0), glm.radians(prism_outward_tilt_deg), glm.vec3(0, 1, 0),
        )

        final = fixture_mat * pan_mat * tilt_mat * prism_rot_mat * prism_tilt_mat
        return glm.normalize(glm.vec3(final * glm.vec4(direction, 0.0)))

    def _build_chassis_state(self) -> ChassisRenderState:
        """Build per-frame chassis inputs: pan/tilt for animated chassis,
        emissive for the lens (color × dimmer), and — for cell-based bar /
        sunstrip / matrix fixtures — premultiplied per-cell emissive that
        the chassis uses to light individual emitter slabs / lamp bulbs."""
        pan = self.movement.pan_deg if self.movement is not None else 0.0
        tilt = self.movement.tilt_deg if self.movement is not None else 0.0

        if self.color is not None and self.dimmer is not None:
            d = self.dimmer.normalized
            r, g, b = self.color.rgb
            emissive = (r * d, g * d, b * d)
            strength = self.brightness_scale
        elif self.color is not None:
            emissive = self.color.rgb
            strength = self.brightness_scale
        else:
            emissive = (0.0, 0.0, 0.0)
            strength = 0.0

        cell_emissives = None
        if isinstance(self.emitter_runner, CellArrayRunner):
            master = self.dimmer.normalized if self.dimmer is not None else 1.0
            fallback = self.color.rgb if self.color is not None else (1.0, 1.0, 1.0)
            cell_emissives = []
            for cs in self.emitter_runner.cell_states:
                rgb = cs.rgb if cs.has_color else fallback
                k = cs.dimmer * master
                cell_emissives.append((rgb[0] * k, rgb[1] * k, rgb[2] * k))

        return ChassisRenderState(
            pan_deg=pan,
            tilt_deg=tilt,
            emissive_color=emissive,
            emissive_strength=strength,
            cell_emissives=cell_emissives,
        )

    def _build_modifiers(self) -> BeamModifiers:
        """Bundle component state into the modifier struct passed to the beam.

        Focus sharpness uses the fixture's mounting height (Z position)
        as a rough projection distance — the legacy MovingHeadRenderer
        does the same as a fallback when the floor intersection isn't
        computed.
        """
        if self.focus is not None:
            projection_dist = max(0.5, float(self.position.get('z', 3.0)))
            focus_sharpness = self.focus.sharpness(projection_dist)
        else:
            focus_sharpness = 1.0

        return BeamModifiers(
            brightness_scale=self.brightness_scale,
            gobo_pattern=self.gobo.pattern_id if self.gobo is not None else 0,
            gobo_rotation_rad=self.gobo.rotation_rad if self.gobo is not None else 0.0,
            focus_sharpness=focus_sharpness,
            iris_opening=self.iris.opening if self.iris is not None else 1.0,
            frost=self.frost.diffusion if self.frost is not None else 0.0,
            zoom_angle_deg=(self.zoom.current_angle_deg if self.zoom is not None else None),
            prism_active=self.prism.is_active if self.prism is not None else False,
            prism_facets=self.prism.facets if self.prism is not None else 3,
        )
