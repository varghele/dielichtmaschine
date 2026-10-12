"""GL smoke tests for untested visualizer renderer modules (v1.5.5, G10).

``visualizer/renderer/shaders.py``, ``gizmo.py`` and ``gl_state.py`` had
no test. With a standalone moderngl context (Mesa / the desktop driver;
the whole module skips where none can be created) these check that
every shader pair compiles and links with the uniforms its consumer
writes, that the axis gizmo builds, draws and releases cleanly, and that
``set_depth_mask`` really reaches ``glDepthMask`` (the moderngl 5.11
attribute it replaces is a silent no-op).

No pixels are compared: the gizmo test only checks that SOMETHING lit
up and that the GL error state stays clean.
"""

from __future__ import annotations

import ctypes

import numpy as np
import pytest

moderngl = pytest.importorskip("moderngl")
glm = pytest.importorskip("glm")

from visualizer.renderer import shaders as S


@pytest.fixture(scope="module")
def _gl_context():
    try:
        context = moderngl.create_standalone_context()
    except Exception as exc:  # pragma: no cover - environment-specific
        pytest.skip(f"no standalone GL context: {exc}")
    yield context
    context.release()


@pytest.fixture
def ctx(_gl_context):
    """The module context, made current for this test: raw ctypes GL
    calls act on whatever context is current, and under xdist another
    file's standalone context may have been created in between."""
    with _gl_context:
        yield _gl_context


# vertex constant, fragment constant, uniforms + attributes the consumer
# (beams.py / chassis.py / floor_projection.py / gdtf_mesh_chassis.py)
# writes by name.
PAIRS = [
    ("FIXTURE_VERTEX_SHADER", "FIXTURE_FRAGMENT_SHADER",
     {"mvp", "model", "base_color", "emissive_color", "emissive_strength",
      "in_position", "in_normal"}),
    ("GDTF_MESH_VERTEX_SHADER", "GDTF_MESH_FRAGMENT_SHADER",
     {"mvp", "model", "base_color", "emissive_color", "emissive_strength",
      "tex", "use_texture", "in_position", "in_normal", "in_uv"}),
    ("BEAM_VERTEX_SHADER", "BEAM_FRAGMENT_SHADER",
     {"mvp", "beam_color", "beam_intensity", "in_position", "in_alpha"}),
    ("GOBO_BEAM_VERTEX_SHADER", "GOBO_BEAM_FRAGMENT_SHADER",
     {"mvp", "beam_color", "beam_intensity", "gobo_pattern",
      "gobo_rotation", "focus_sharpness", "in_position", "in_alpha"}),
    ("FLOOR_PROJECTION_VERTEX_SHADER", "FLOOR_PROJECTION_FRAGMENT_SHADER",
     {"mvp", "projection_color", "projection_intensity", "distance_falloff",
      "in_position", "in_uv"}),
    ("FLOOR_PROJECTION_VERTEX_SHADER", "GOBO_FLOOR_PROJECTION_FRAGMENT_SHADER",
     {"mvp", "projection_color", "projection_intensity", "distance_falloff",
      "gobo_pattern", "gobo_rotation", "focus_sharpness",
      "in_position", "in_uv"}),
]


@pytest.mark.parametrize("vertex,fragment,members", PAIRS,
                         ids=[p[1] for p in PAIRS])
def test_shader_pair_links_with_consumer_uniforms(ctx, vertex, fragment, members):
    program = ctx.program(vertex_shader=getattr(S, vertex),
                          fragment_shader=getattr(S, fragment))
    try:
        missing = members - set(program._members)
        assert not missing, f"not active after linking: {sorted(missing)}"
    finally:
        program.release()


def test_every_shader_constant_is_covered():
    names = {n for n in dir(S) if n.endswith("_SHADER")}
    covered = {p[0] for p in PAIRS} | {p[1] for p in PAIRS}
    assert names == covered


def _gl_get_depth_writemask() -> int:
    from visualizer.renderer.gl_state import _load_gl_lib
    get = _load_gl_lib().glGetBooleanv
    get.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_ubyte)]
    get.restype = None
    value = ctypes.c_ubyte(2)
    get(0x0B72, ctypes.byref(value))   # GL_DEPTH_WRITEMASK
    return value.value


def test_set_depth_mask_reaches_gl(ctx):
    from visualizer.renderer.gl_state import set_depth_mask
    fbo = ctx.simple_framebuffer((8, 8))
    fbo.use()
    try:
        set_depth_mask(False)
        assert _gl_get_depth_writemask() == 0
        set_depth_mask(True)
        assert _gl_get_depth_writemask() == 1
    finally:
        set_depth_mask(True)
        fbo.release()


def _drain_gl_errors(ctx) -> None:
    """Clear pending GL error flags. The context is shared by the whole
    module, and ``ctx.error`` (glGetError) reports a flag left by ANY
    earlier call, so a check must start from a clean state."""
    seen = []
    for _ in range(16):  # glGetError returns one flag per call
        error = ctx.error
        if error == "GL_NO_ERROR":
            return
        seen.append(error)
    raise AssertionError(f"GL error flag does not clear: {seen[:4]}")


class TestGizmo:
    def test_builds_draws_and_releases(self, ctx):
        from visualizer.renderer.gizmo import CoordinateGizmo
        size = 96
        _drain_gl_errors(ctx)
        fbo = ctx.simple_framebuffer((size, size))
        assert ctx.error == "GL_NO_ERROR", "framebuffer create"
        fbo.use()
        assert ctx.error == "GL_NO_ERROR", "framebuffer use"
        fbo.clear(0.0, 0.0, 0.0, 1.0)
        assert ctx.error == "GL_NO_ERROR", "framebuffer clear"
        gizmo = CoordinateGizmo(ctx)
        try:
            assert ctx.error == "GL_NO_ERROR", "gizmo build"
            assert set(gizmo.letter_vaos) == {"X", "Y", "Z"}
            view = glm.lookAt(glm.vec3(3, 3, 3), glm.vec3(0), glm.vec3(0, 1, 0))
            gizmo.render(view, size, size)
            assert ctx.error == "GL_NO_ERROR", "gizmo render"
            pixels = np.frombuffer(fbo.read(components=3), dtype=np.uint8)
            assert (pixels.reshape(-1, 3).max(axis=1) > 0).any()
            # Degenerate viewport (minimised window) must not raise.
            gizmo.render(view, size, 0)
            assert ctx.error == "GL_NO_ERROR", "degenerate-viewport render"
        finally:
            gizmo.release()
            fbo.release()

    def test_render_restores_depth_test(self, ctx):
        from visualizer.renderer.gizmo import CoordinateGizmo
        fbo = ctx.simple_framebuffer((16, 16))
        fbo.use()
        gizmo = CoordinateGizmo(ctx)
        try:
            ctx.enable(moderngl.DEPTH_TEST)
            gizmo.render(glm.mat4(1.0), 16, 16)
            from visualizer.renderer.gl_state import _load_gl_lib
            is_enabled = _load_gl_lib().glIsEnabled
            is_enabled.argtypes = [ctypes.c_uint]
            is_enabled.restype = ctypes.c_ubyte
            assert is_enabled(0x0B71) == 1   # GL_DEPTH_TEST
        finally:
            gizmo.release()
            fbo.release()
