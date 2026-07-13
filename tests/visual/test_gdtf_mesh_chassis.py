# tests/visual/test_gdtf_mesh_chassis.py
"""Real-GL smoke tests for the GDTF mesh chassis (plan Phase 3).

Synthetic case runs everywhere a GL context exists (GLB authored
in-test); the real-file case runs only where gdtf_fixtures/ holds the
local Share downloads (never committed).
"""
import glob
import os
import zipfile

import glm
import moderngl
import numpy as np
import pytest
import trimesh

from utils.gdtf_loader import parse_gdtf_file
from utils.gdtf_mesh import clear_mesh_cache

from tests.unit.test_gdtf_loader import SPOT_DESCRIPTION

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SIZE = 128


@pytest.fixture(scope="module")
def gl_context():
    try:
        ctx = moderngl.create_standalone_context()
    except Exception as e:
        pytest.skip(f"Could not create standalone GL context: {e}")
    yield ctx
    ctx.release()


@pytest.fixture()
def fbo(gl_context):
    color = gl_context.texture((SIZE, SIZE), 4)
    depth = gl_context.depth_renderbuffer((SIZE, SIZE))
    fb = gl_context.framebuffer(color_attachments=[color], depth_attachment=depth)
    yield fb
    fb.release()
    color.release()
    depth.release()


@pytest.fixture(autouse=True)
def _fresh_mesh_cache():
    from visualizer.renderer.gdtf_mesh_chassis import clear_gl_mesh_cache
    clear_mesh_cache()
    yield
    clear_gl_mesh_cache()
    clear_mesh_cache()


def test_instances_share_gl_buffers(gl_context, fbo, tmp_path):
    """N fixtures of one type share program + buffers; only VAOs are
    per instance, and releasing one instance leaves the other usable."""
    from visualizer.renderer.gdtf_mesh_chassis import GdtfMeshChassisGeometry

    defn = parse_gdtf_file(_spot_with_glb(tmp_path))
    a = GdtfMeshChassisGeometry(gl_context, defn.path, defn.gdtf, "Standard")
    b = GdtfMeshChassisGeometry(gl_context, defn.path, defn.gdtf, "Standard")
    try:
        assert a.program is b.program
        assert a.entries[0].shared is b.entries[0].shared
        assert a.entries[0].vao is not b.entries[0].vao
        a.release()
        fbo.use()
        gl_context.clear(0.0, 0.0, 0.0, 0.0)
        gl_context.enable(moderngl.DEPTH_TEST)
        b.render(_mvp(), glm.mat4(1.0))
        assert _rendered_pixels(fbo) > 50, "survivor renders after peer release"
    finally:
        b.release()


def _spot_with_glb(tmp_path):
    """The synthetic spot .gdtf, with a real GLB behind its BaseModel."""
    mesh = trimesh.creation.box(extents=(0.3, 0.25, 0.4))
    glb = trimesh.Scene(mesh).export(file_type="glb")
    path = os.path.join(str(tmp_path), "spot_mesh.gdtf")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("description.xml", SPOT_DESCRIPTION)
        z.writestr("models/gltf/base.glb", glb)
    return path


def _mvp():
    proj = glm.perspective(glm.radians(45.0), 1.0, 0.1, 50.0)
    view = glm.lookAt(glm.vec3(1.5, 1.2, 1.5), glm.vec3(0.0, 0.0, 0.2),
                      glm.vec3(0.0, 0.0, 1.0))
    return proj * view


def _rendered_pixels(fbo):
    data = np.frombuffer(fbo.read(components=4), dtype=np.uint8)
    return int((data.reshape(-1, 4)[:, :3].sum(axis=1) > 20).sum())


def test_mesh_chassis_renders_synthetic_spot(gl_context, fbo, tmp_path):
    from visualizer.renderer.gdtf_mesh_chassis import GdtfMeshChassisGeometry

    defn = parse_gdtf_file(_spot_with_glb(tmp_path))
    chassis = GdtfMeshChassisGeometry(gl_context, defn.path, defn.gdtf, "Standard")
    try:
        fbo.use()
        gl_context.clear(0.0, 0.0, 0.0, 0.0)
        gl_context.enable(moderngl.DEPTH_TEST)
        chassis.render(_mvp(), glm.mat4(1.0))
        assert _rendered_pixels(fbo) > 50, "mesh chassis must draw pixels"

        # Beam origin takes SOLVER-convention degrees (converted onto
        # the GDTF axes inside, see solver_to_gdtf_axes): home (0, 0)
        # emits along solver local +X; solver tilt +90 sends it to +Z.
        rest = chassis.beam_origin_transform(0.0, 0.0) * glm.vec4(0, 0, 1, 0)
        assert rest.x == pytest.approx(1.0, abs=1e-5)
        tilted = chassis.beam_origin_transform(0.0, 90.0) * glm.vec4(0, 0, 1, 0)
        assert tilted.z == pytest.approx(1.0, abs=1e-5)
    finally:
        chassis.release()


def test_mesh_chassis_matches_golden(gl_context, fbo, tmp_path):
    """Pixel-level pin of the mesh render path (per-platform golden,
    QLC_REGEN_GOLDENS=1 to regenerate after intended changes)."""
    from PyQt6.QtGui import QImage
    from tests.visual.harness import compare_to_golden
    from visualizer.renderer.gdtf_mesh_chassis import GdtfMeshChassisGeometry

    defn = parse_gdtf_file(_spot_with_glb(tmp_path))
    chassis = GdtfMeshChassisGeometry(gl_context, defn.path, defn.gdtf, "Standard")
    try:
        fbo.use()
        gl_context.clear(0.05, 0.05, 0.07, 1.0)
        gl_context.enable(moderngl.DEPTH_TEST)
        chassis.render(_mvp(), glm.mat4(1.0))
        data = np.frombuffer(fbo.read(components=4), dtype=np.uint8)
        data = data.reshape(SIZE, SIZE, 4)[::-1].copy()  # bottom-up FBO
        image = QImage(data.tobytes(), SIZE, SIZE, SIZE * 4,
                       QImage.Format.Format_RGBA8888)
        compare_to_golden(image, "gdtf_mesh_spot")
    finally:
        chassis.release()


def test_all_modelless_tree_raises(gl_context, tmp_path):
    """A GDTF whose nodes carry no models must NOT build a mesh chassis
    (make_chassis_geometry then falls back to the procedural ladder)."""
    from visualizer.renderer.gdtf_mesh_chassis import GdtfMeshChassisGeometry

    # Same description, but no GLB in the archive and models dims kept:
    # BaseModel still has dims, so the primitive-box fallback kicks in
    # instead -> chassis must build. Then strip models to force the raise.
    path = os.path.join(str(tmp_path), "no_mesh.gdtf")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("description.xml", SPOT_DESCRIPTION)
    defn = parse_gdtf_file(path)
    chassis = GdtfMeshChassisGeometry(gl_context, defn.path, defn.gdtf, "Standard")
    chassis.release()  # primitive fallback path builds fine

    defn.gdtf.models.clear()
    with pytest.raises(ValueError):
        GdtfMeshChassisGeometry(gl_context, defn.path, defn.gdtf, "Standard")


_MAGICBLADE = glob.glob(os.path.join(REPO_ROOT, "gdtf_fixtures",
                                     "Ayrton@MagicBlade R@*.gdtf"))


@pytest.mark.skipif(not _MAGICBLADE,
                    reason="local Share download not present (not committed)")
def test_real_magicblade_mesh_chassis(gl_context, fbo):
    from visualizer.renderer.gdtf_mesh_chassis import GdtfMeshChassisGeometry

    defn = parse_gdtf_file(_MAGICBLADE[0])
    chassis = GdtfMeshChassisGeometry(gl_context, defn.path, defn.gdtf, "Extended")
    try:
        assert chassis.entries, "GLB head + primitive yoke/base entries"
        fbo.use()
        gl_context.clear(0.0, 0.0, 0.0, 0.0)
        gl_context.enable(moderngl.DEPTH_TEST)
        chassis.render(_mvp(), glm.mat4(1.0))
        at_rest = _rendered_pixels(fbo)
        assert at_rest > 50

        # Pan must change the image (the bar rotates about Z).
        gl_context.clear(0.0, 0.0, 0.0, 0.0)
        class _S:  # minimal ChassisRenderState stand-in
            pan_deg, tilt_deg = 60.0, 30.0
            emissive_color, emissive_strength, cell_emissives = (0, 0, 0), 0.0, None
        chassis.render(_mvp(), glm.mat4(1.0), _S())
        assert _rendered_pixels(fbo) != at_rest
    finally:
        chassis.release()
