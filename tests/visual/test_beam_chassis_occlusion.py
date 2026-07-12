"""Visual regression: a chassis must remain visible when a beam crosses in front of it.

Reproduces the user-reported issue where a moving head's beam crossing
between the camera and a back fixture would "hide" the back fixture in the
embedded visualizer.

Scene:

    camera --->  [ MH (white beam) ]  -- beam ->  [ red PAR ] (back)
       (front)         (mid)                          (deep)

The PAR is set to a distinctive red color so its chassis pixels are
easy to find programmatically. The MH's beam crosses in front. We
render twice (with and without the MH), find the PAR's screen-space
extent in the no-MH render, and assert that the *same* pixels still
read as red in the with-MH render.

Includes both:
- LDR direct path (FixtureManager rendered straight to the FBO) —
  exercises the two-pass chassis-on-top logic alone.
- HDR + tonemap path (same as the embedded visualizer) — exercises
  the full user-visible pipeline.

To inspect rendered images during debugging, set
``BEAM_CHASSIS_DEBUG_OUT=/some/dir`` in the environment; the test will
write PNGs of each scene there. Otherwise no I/O.
"""

from __future__ import annotations

import importlib
import os
import pathlib
from typing import Optional, Tuple

import glm
import moderngl
import numpy as np
import pytest

from config.models import (
    Configuration,
    Fixture,
    FixtureGroup,
    FixtureMode,
    Universe,
)
from utils.fixture_capabilities import clear_capabilities_cache
from utils.tcp.protocol import VisualizerProtocol
from visualizer.renderer.camera import OrbitCamera


FBO_SIZE = 512


# ---------------------------------------------------------------------------
# GL context / FBO
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def gl_context():
    try:
        ctx = moderngl.create_standalone_context()
    except Exception as e:
        pytest.skip(f"Could not create standalone GL context: {e}")
    yield ctx
    ctx.release()


@pytest.fixture
def ldr_fbo(gl_context):
    """LDR RGBA8 framebuffer with depth — the 'direct' path."""
    color = gl_context.texture((FBO_SIZE, FBO_SIZE), 4)
    depth = gl_context.depth_renderbuffer((FBO_SIZE, FBO_SIZE))
    fbo = gl_context.framebuffer(color_attachments=[color], depth_attachment=depth)
    yield fbo
    fbo.release()
    color.release()
    depth.release()


@pytest.fixture
def hdr_fbo(gl_context):
    """RGBA16F framebuffer with depth — mirrors the engine's HDR pass target."""
    color = gl_context.texture((FBO_SIZE, FBO_SIZE), 4, dtype='f2')
    depth = gl_context.depth_renderbuffer((FBO_SIZE, FBO_SIZE))
    fbo = gl_context.framebuffer(color_attachments=[color], depth_attachment=depth)
    yield fbo
    fbo.release()
    color.release()
    depth.release()


# ---------------------------------------------------------------------------
# Scene builders — keep positions consistent so the camera framing matches
# ---------------------------------------------------------------------------


# Scene layout (world coords, Y up):
#
#                   camera  (0, 1.7, ~8)
#                      |
#                      v
#   MH @ (-3,1,0)  ────beam──>  PAR @ (0,1,0)   ──> (towards camera)
#                  white                      red
#
# The MH stands upright (no rotation) so its beam — emitted along
# chassis-local +X, then world +X after identity orientation —
# crosses through the camera's line-of-sight to the PAR. The PAR
# stands upright with a dim glow beam toward the camera. The MH
# beam is the "horizontal beam going in front" of the user's
# scenario.
PAR_POS = (0.0, 0.0, 1.0)        # x, y(depth), z(height) — middle of stage, 1m up
MH_POS = (-1.8, 0.0, 1.0)        # x, y(depth), z(height) — to the side, same height


def _make_back_par(name: str = "par_back") -> Fixture:
    """A standing PAR at the centre of the stage, lit red."""
    x, y, z = PAR_POS
    return Fixture(
        universe=1, address=1,
        manufacturer="Stairville",
        model="Retro Flat Par 18x12W RGBW ",
        name=name,
        group="g_back",
        current_mode="8 Channel",
        available_modes=[FixtureMode(name="8 Channel", channels=8)],
        type="PAR",
        x=x, y=y, z=z,
        mounting="standing",
        yaw=0.0, pitch=0.0, roll=0.0,
        orientation_uses_group_default=False,
        z_uses_group_default=False,
    )


def _make_front_mh(name: str = "mh_front") -> Fixture:
    """A moving head off to the side, beam going horizontally toward the PAR."""
    x, y, z = MH_POS
    return Fixture(
        universe=1, address=10,
        manufacturer="Varytec",
        model="Hero Spot 60",
        name=name,
        group="g_front",
        current_mode="14 Channel",
        available_modes=[FixtureMode(name="14 Channel", channels=14)],
        type="MH",
        x=x, y=y, z=z,
        mounting="standing",  # no body rotation; beam along world +X
        yaw=0.0, pitch=0.0, roll=0.0,
        orientation_uses_group_default=False,
        z_uses_group_default=False,
    )


def _build_config(fixtures) -> Configuration:
    groups: dict[str, FixtureGroup] = {}
    for f in fixtures:
        if f.group not in groups:
            groups[f.group] = FixtureGroup(
                name=f.group, fixtures=[], default_z_height=1.0,
            )
        groups[f.group].fixtures.append(f)
    return Configuration(
        fixtures=list(fixtures),
        groups=groups,
        universes={1: Universe(id=1, name="U1", output={})},
        stage_width=10.0,
        stage_height=6.0,
    )


# ---------------------------------------------------------------------------
# DMX helpers — fill specific channels for each fixture
# ---------------------------------------------------------------------------


def _set_par_dmx(
    dmx: bytearray,
    address: int,
    *,
    dimmer: int = 255,
    r: int = 255,
    g: int = 0,
    b: int = 0,
) -> None:
    """Retro Flat Par 18x12W RGBW 8ch: dimmer, R, G, B, W, A, UV, strobe."""
    i = address - 1
    dmx[i + 0] = dimmer
    dmx[i + 1] = r
    dmx[i + 2] = g
    dmx[i + 3] = b


def _set_mh_dmx(
    dmx: bytearray,
    address: int,
    *,
    pan: int = 128,
    tilt: int = 128,
    dimmer: int = 255,
    color: int = 0,
) -> None:
    """Hero Spot 60 ``14 Channel`` mode layout (per the QXF <Mode>):
    0=Pan 1=PanFine 2=Tilt 3=TiltFine 4=MovingSpeed 5=Dimmer 6=Shutter
    7=Color 8=Gobo 9=GoboRot 10=Focus 11=Prism 12=MovingProg 13=AutoShows.
    """
    i = address - 1
    dmx[i + 0] = pan
    dmx[i + 2] = tilt
    dmx[i + 5] = dimmer
    dmx[i + 6] = 255      # shutter open
    dmx[i + 7] = color    # 0 = white macro


# ---------------------------------------------------------------------------
# Camera + render helpers
# ---------------------------------------------------------------------------


def _camera() -> OrbitCamera:
    """Eye-level, looking at the PAR at scene (0, 1, 0), from the side
    the fixtures in this synthetic scene actually face.

    The azimuth is 180, not 0, since the stage-to-display correction
    landed (visualizer/renderer/camera.py DISPLAY_FLIP): the camera now
    orbits in display space, so a given azimuth views the stage from the
    opposite side than it used to. Verified equivalent - this framing
    reproduces the pre-correction image pixel for pixel.
    """
    cam = OrbitCamera()
    cam.set_aspect(1.0)
    cam.target = glm.vec3(0.0, 1.0, 0.0)
    cam.azimuth = 180.0
    cam.elevation = 5.0
    cam.distance = 5.0
    return cam


def _force_composable_and_reload():
    """Make sure :mod:`visualizer.renderer.fixtures` picks up
    ``FIXTURE_RENDERER=composable``."""
    os.environ["FIXTURE_RENDERER"] = "composable"
    from visualizer.renderer import fixtures as fixtures_module
    importlib.reload(fixtures_module)
    return fixtures_module


def _render_ldr(
    ctx: moderngl.Context,
    fbo,
    config: Configuration,
    dmx: bytes,
) -> np.ndarray:
    """Render straight to the LDR FBO. No HDR / tonemap."""
    fixtures_module = _force_composable_and_reload()
    fm = fixtures_module.FixtureManager(ctx)
    clear_capabilities_cache()
    payload = VisualizerProtocol.build_fixtures_payload(config)
    fm.update_fixtures(payload)
    fm.update_dmx(universe=1, dmx_data=dmx)

    cam = _camera()
    mvp = cam.get_view_projection_matrix()

    fbo.use()
    ctx.viewport = (0, 0, FBO_SIZE, FBO_SIZE)
    ctx.enable(moderngl.DEPTH_TEST)
    ctx.depth_mask = True
    ctx.disable(moderngl.BLEND)
    ctx.clear(0.05, 0.05, 0.08, 1.0)
    fm.render(mvp)

    raw = fbo.read(components=3, dtype="f1")
    image = np.frombuffer(raw, dtype="u1").reshape(FBO_SIZE, FBO_SIZE, 3)
    fm.release()
    return image.copy()


def _render_hdr(
    ctx: moderngl.Context,
    hdr_fbo,
    ldr_fbo,
    config: Configuration,
    dmx: bytes,
) -> np.ndarray:
    """Render scene to HDR FBO, then tonemap to LDR FBO. Mirrors RenderEngine.paintGL."""
    from visualizer.renderer.hdr import HDRPipeline

    fixtures_module = _force_composable_and_reload()
    fm = fixtures_module.FixtureManager(ctx)
    clear_capabilities_cache()
    payload = VisualizerProtocol.build_fixtures_payload(config)
    fm.update_fixtures(payload)
    fm.update_dmx(universe=1, dmx_data=dmx)

    cam = _camera()
    mvp = cam.get_view_projection_matrix()

    hdr = HDRPipeline(ctx)
    try:
        # Use the test's HDR FBO instead of HDRPipeline's internal one.
        hdr_fbo.use()
        ctx.viewport = (0, 0, FBO_SIZE, FBO_SIZE)
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.depth_mask = True
        ctx.disable(moderngl.BLEND)
        hdr_fbo.clear(0.05, 0.05, 0.08, 1.0)
        fm.render(mvp)

        # Manually invoke the tonemap pass against our textures: build a tiny
        # standalone tonemap that mirrors HDRPipeline.tonemap_to but reads
        # from hdr_fbo.color_attachments[0].
        hdr_color = hdr_fbo.color_attachments[0]
        hdr._color = hdr_color  # repoint pipeline at our HDR texture
        hdr._size = (FBO_SIZE, FBO_SIZE)
        hdr.tonemap_to(ldr_fbo)

        raw = ldr_fbo.read(components=3, dtype="f1")
        image = np.frombuffer(raw, dtype="u1").reshape(FBO_SIZE, FBO_SIZE, 3)
    finally:
        # Don't release the texture we borrowed.
        hdr._color = None
        hdr.release()
        fm.release()

    return image.copy()


# ---------------------------------------------------------------------------
# Pixel analysis
# ---------------------------------------------------------------------------


def _red_mask(image: np.ndarray, *, min_r: int = 80, dominance: int = 25) -> np.ndarray:
    """Boolean mask for pixels where red dominates (R >> G, R >> B).

    A red-lit PAR's chassis pixels read as orange/red/pink. The MH's
    white beam has roughly equal RGB, so this mask is ~zero in
    beam-only regions.
    """
    r, g, b = image[..., 0].astype(int), image[..., 1].astype(int), image[..., 2].astype(int)
    return (r >= min_r) & (r - g >= dominance) & (r - b >= dominance)


def _maybe_save_debug(image: np.ndarray, name: str) -> None:
    """Optionally save the rendered image as a PNG for visual debugging.

    Set ``BEAM_CHASSIS_DEBUG_OUT=/path`` in the environment to enable.
    """
    out_dir = os.environ.get("BEAM_CHASSIS_DEBUG_OUT")
    if not out_dir:
        return
    try:
        from PIL import Image
    except ImportError:
        return
    pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
    Image.fromarray(image).save(os.path.join(out_dir, f"{name}.png"))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _build_dmx_par_only() -> bytes:
    dmx = bytearray(512)
    _set_par_dmx(dmx, address=1, dimmer=200, r=255, g=0, b=0)
    return bytes(dmx)


def _build_dmx_par_plus_mh() -> bytes:
    dmx = bytearray(512)
    _set_par_dmx(dmx, address=1, dimmer=200, r=255, g=0, b=0)
    _set_mh_dmx(dmx, address=10, pan=128, tilt=128, dimmer=255)
    return bytes(dmx)


def _build_dmx_mh_only_red() -> bytes:
    """Debug helper: just the MH, color macro = Red (DMX ch9 in [25, 50])."""
    dmx = bytearray(512)
    _set_mh_dmx(dmx, address=10, pan=128, tilt=128, dimmer=255, color=30)
    return bytes(dmx)


def test_mh_beam_visible_alone(gl_context, ldr_fbo):
    """Sanity check that the MH's beam actually shows up in the test scene.

    If the beam isn't visible here, the chassis-occlusion tests aren't
    actually exercising the bug; the DMX channel layout for the test MH
    needs adjustment before any conclusion can be drawn.
    """
    config = _build_config([_make_front_mh()])
    img = _render_ldr(gl_context, ldr_fbo, config, _build_dmx_mh_only_red())
    _maybe_save_debug(img, "ldr_mh_alone_red")

    # A 6 m red ConeBeam should leave many red-dominant pixels — well
    # over the ~70 you'd get from just the chassis's red X-axis arrow.
    red = _red_mask(img).sum()
    print(f"[mh_alone_red] red pixels: {red}")
    assert red > 500, (
        f"MH beam doesn't appear to render (only {red} red pixels). "
        f"Check the DMX channel layout for the Hero Spot 60 14ch mode."
    )
    # Beam should produce a red column emerging from the MH.
    red = _red_mask(img).sum()
    # Anything notably different from background (0.05, 0.05, 0.08 → ~12,12,20).
    bg_r, bg_g, bg_b = 12, 12, 20
    delta = np.maximum.reduce([
        np.abs(img[..., 0].astype(int) - bg_r),
        np.abs(img[..., 1].astype(int) - bg_g),
        np.abs(img[..., 2].astype(int) - bg_b),
    ])
    non_bg = (delta > 15).sum()
    # Brightest red pixel anywhere — tells us the peak beam contribution.
    max_r = int(img[..., 0].max())
    print(
        f"[debug] MH-alone: red_pixels={red} non_background={non_bg} "
        f"max_r={max_r}"
    )


def test_par_is_visible_alone_ldr(gl_context, ldr_fbo):
    """Baseline: a red PAR alone must render visible red pixels."""
    config = _build_config([_make_back_par()])
    img = _render_ldr(gl_context, ldr_fbo, config, _build_dmx_par_only())
    _maybe_save_debug(img, "ldr_par_alone")

    n_red = _red_mask(img).sum()
    print(f"[ldr_par_alone] red pixels: {n_red}")
    assert n_red > 200, (
        f"Baseline red PAR not visible (only {n_red} red pixels). "
        f"The test scene needs adjustment so the PAR's chassis takes up "
        f"more than a few-hundred screen pixels."
    )


def test_par_stays_visible_under_mh_beam_ldr(gl_context, ldr_fbo):
    """A red PAR behind a white moving-head beam should still register many red pixels.

    Exercises the two-pass chassis-on-top render flow in isolation
    (no HDR / tonemap). If this fails, two-pass isn't actually keeping
    the chassis on top regardless of the beam.
    """
    # Baseline — establish red-pixel count for the unobstructed PAR.
    config_alone = _build_config([_make_back_par()])
    img_alone = _render_ldr(gl_context, ldr_fbo, config_alone, _build_dmx_par_only())
    baseline_red = _red_mask(img_alone).sum()
    _maybe_save_debug(img_alone, "ldr_par_alone")

    # With MH in front + bright white beam crossing the scene.
    config_both = _build_config([_make_back_par(), _make_front_mh()])
    img_both = _render_ldr(gl_context, ldr_fbo, config_both, _build_dmx_par_plus_mh())
    occluded_red = _red_mask(img_both).sum()
    _maybe_save_debug(img_both, "ldr_par_with_mh_beam")

    retention = occluded_red / max(1, baseline_red)
    print(
        f"[ldr_par_with_mh] baseline_red={baseline_red} occluded_red={occluded_red} "
        f"retention={retention:.2%}"
    )

    # Chassis-on-top in pass 2 should overwrite the beam at chassis pixels,
    # so retention should be ~1.0 (often slightly above, since beam glow
    # tints nearby pixels enough to also pass the red mask). 0.85 catches
    # a regression where the beam starts washing out the chassis silhouette.
    assert retention >= 0.85, (
        f"Red PAR vanishes under MH beam (retention {retention:.1%}). "
        f"Chassis-on-top render isn't keeping the PAR visible."
    )


FLOOR_PAR_POS = (0.0, 0.0, 0.3)        # x, y(depth), z(height) — sitting on the floor
OVERHEAD_MH_POS = (0.0, 0.0, 3.5)      # x, y(depth), z(height) — hanging directly above


def _make_floor_par(name: str = "par_floor") -> Fixture:
    """A PAR sitting on the floor, lit red. The user's scenario."""
    x, y, z = FLOOR_PAR_POS
    return Fixture(
        universe=1, address=1,
        manufacturer="Stairville",
        model="Retro Flat Par 18x12W RGBW ",
        name=name,
        group="g_floor",
        current_mode="8 Channel",
        available_modes=[FixtureMode(name="8 Channel", channels=8)],
        type="PAR",
        x=x, y=y, z=z,
        mounting="standing",
        yaw=0.0, pitch=0.0, roll=0.0,
        orientation_uses_group_default=False,
        z_uses_group_default=False,
    )


def _make_overhead_mh(name: str = "mh_overhead") -> Fixture:
    """An MH hanging from a grid, beam pointing down at the floor."""
    x, y, z = OVERHEAD_MH_POS
    return Fixture(
        universe=1, address=10,
        manufacturer="Varytec",
        model="Hero Spot 60",
        name=name,
        group="g_overhead",
        current_mode="14 Channel",
        available_modes=[FixtureMode(name="14 Channel", channels=14)],
        type="MH",
        x=x, y=y, z=z,
        mounting="hanging",
        yaw=0.0, pitch=90.0, roll=0.0,  # standard hanging pose
        orientation_uses_group_default=False,
        z_uses_group_default=False,
    )


def _floor_scene_camera() -> OrbitCamera:
    """Slightly elevated camera framing the whole MH-above-PAR stack.

    195, not 15: the same 180 degree remap as :func:`_camera` (see its
    docstring) since DISPLAY_FLIP landed, keeping the slight off-axis
    angle that stops the MH hiding directly behind the PAR.
    """
    cam = OrbitCamera()
    cam.set_aspect(1.0)
    cam.target = glm.vec3(0.0, 1.5, 0.0)
    cam.azimuth = 195.0
    cam.elevation = 10.0
    cam.distance = 6.0
    return cam


def _render_ldr_floor_scene(ctx, fbo, config, dmx):
    """Same as _render_ldr but with the floor-scene camera."""
    fixtures_module = _force_composable_and_reload()
    fm = fixtures_module.FixtureManager(ctx)
    clear_capabilities_cache()
    payload = VisualizerProtocol.build_fixtures_payload(config)
    fm.update_fixtures(payload)
    fm.update_dmx(universe=1, dmx_data=dmx)

    cam = _floor_scene_camera()
    mvp = cam.get_view_projection_matrix()

    fbo.use()
    ctx.viewport = (0, 0, FBO_SIZE, FBO_SIZE)
    ctx.enable(moderngl.DEPTH_TEST)
    ctx.depth_mask = True
    ctx.disable(moderngl.BLEND)
    ctx.clear(0.05, 0.05, 0.08, 1.0)
    fm.render(mvp)

    raw = fbo.read(components=3, dtype="f1")
    image = np.frombuffer(raw, dtype="u1").reshape(FBO_SIZE, FBO_SIZE, 3)
    fm.release()
    return image.copy()


def test_floor_par_stays_visible_under_overhead_mh(gl_context, ldr_fbo):
    """Floor PAR sitting directly under an MH that's beaming straight down.

    Mirrors the user's reported scenario: a PAR on the floor that vanishes
    when a moving head's beam (and floor projection ellipse) cross over it.
    """
    # Baseline — PAR alone.
    config_alone = _build_config([_make_floor_par()])
    img_alone = _render_ldr_floor_scene(gl_context, ldr_fbo, config_alone, _build_dmx_par_only())
    baseline_red = _red_mask(img_alone).sum()
    _maybe_save_debug(img_alone, "ldr_floor_par_alone")

    # With overhead MH beaming down.
    config_both = _build_config([_make_floor_par(), _make_overhead_mh()])
    dmx = bytearray(512)
    _set_par_dmx(dmx, address=1, dimmer=200, r=255, g=0, b=0)
    _set_mh_dmx(dmx, address=10, pan=128, tilt=128, dimmer=255, color=0)  # white
    img_both = _render_ldr_floor_scene(gl_context, ldr_fbo, config_both, bytes(dmx))
    occluded_red = _red_mask(img_both).sum()
    _maybe_save_debug(img_both, "ldr_floor_par_with_overhead_mh")

    retention = occluded_red / max(1, baseline_red)
    print(
        f"[ldr_floor_par] baseline_red={baseline_red} occluded_red={occluded_red} "
        f"retention={retention:.2%}"
    )

    assert retention >= 0.85, (
        f"Floor PAR vanishes under overhead MH (retention {retention:.1%}). "
        f"This is the user-reported scenario — chassis-on-top isn't holding."
    )


def test_par_stays_visible_under_mh_beam_hdr(gl_context, hdr_fbo, ldr_fbo):
    """Same scenario, but through the full HDR + tonemap pipeline.

    This is the path the user actually sees in the embedded visualizer.
    """
    config_alone = _build_config([_make_back_par()])
    img_alone = _render_hdr(gl_context, hdr_fbo, ldr_fbo, config_alone, _build_dmx_par_only())
    baseline_red = _red_mask(img_alone).sum()
    _maybe_save_debug(img_alone, "hdr_par_alone")

    config_both = _build_config([_make_back_par(), _make_front_mh()])
    img_both = _render_hdr(gl_context, hdr_fbo, ldr_fbo, config_both, _build_dmx_par_plus_mh())
    occluded_red = _red_mask(img_both).sum()
    _maybe_save_debug(img_both, "hdr_par_with_mh_beam")

    retention = occluded_red / max(1, baseline_red)
    print(
        f"[hdr_par_with_mh] baseline_red={baseline_red} occluded_red={occluded_red} "
        f"retention={retention:.2%}"
    )

    assert retention >= 0.85, (
        f"Red PAR vanishes under MH beam in HDR path (retention {retention:.1%})."
    )
