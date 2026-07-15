# tests/unit/test_display_frame.py
"""The stage-to-display correction (visualizer/renderer/camera.py
DISPLAY_FLIP): the 3D scene must be a FAITHFUL copy of the stage, not
its mirror image.

Renderers build geometry in the historical scene frame
stage (x, y, z) -> scene (x, z, y), which swaps two axes and is
therefore a reflection (determinant -1). DISPLAY_FLIP negates scene Z
at the view matrix, making the composed stage -> display map
(x, y, z) -> (x, z, -y): determinant +1, a proper rotation. GL-free.
"""

import glm
import pytest

from visualizer.renderer.camera import DISPLAY_FLIP, OrbitCamera

# The scene frame every renderer's model matrix builds in.
def scene(x, y, z):
    """stage -> scene (the historical, mirrored mapping)."""
    return glm.vec3(x, z, y)


def display(x, y, z):
    """stage -> display (what the camera actually sees)."""
    return glm.vec3(DISPLAY_FLIP * glm.vec4(scene(x, y, z), 1.0))


def _det3(a, b, c):
    return glm.determinant(glm.mat3(a, b, c))


class TestHandedness:
    def test_the_scene_frame_alone_is_a_reflection(self):
        # The bug: a two-axis swap mirrors the world (this is what made
        # floor text read backwards).
        assert _det3(scene(1, 0, 0), scene(0, 1, 0), scene(0, 0, 1)) \
            == pytest.approx(-1.0)

    def test_the_display_frame_is_a_proper_rotation(self):
        # The fix: determinant +1, so the picture is a faithful copy of
        # the stage - no mirror writing, no flipped left/right.
        assert _det3(display(1, 0, 0), display(0, 1, 0),
                     display(0, 0, 1)) == pytest.approx(1.0)


class TestAxisMeaning:
    def test_stage_axes_map_as_documented(self):
        assert display(1, 0, 0) == glm.vec3(1, 0, 0)     # X stays X
        assert display(0, 0, 1) == glm.vec3(0, 1, 0)     # height -> up
        assert display(0, 1, 0) == glm.vec3(0, 0, -1)    # upstage -> -Z

    def test_the_audience_is_at_positive_display_z(self):
        # Stage Y is NEGATIVE toward the audience.
        assert display(0, -4, 0).z > 0


class TestDefaultCamera:
    def test_default_camera_sits_on_the_audience_side(self):
        # Before the fix, azimuth 45 put the camera UPSTAGE - looking at
        # the band from behind, which is why beams aimed at the audience
        # appeared to fly toward "the back of the stage".
        camera = OrbitCamera()
        camera.set_stage_size(10.0, 6.0)
        assert camera.get_position().z > 0        # same side as the audience

    def test_upstage_renders_farther_than_downstage(self):
        camera = OrbitCamera()
        camera.set_stage_size(10.0, 6.0)
        eye = camera.get_position()
        downstage = display(0, -3, 0)             # audience edge
        upstage = display(0, 3, 0)                # back of the stage
        assert glm.distance(eye, downstage) < glm.distance(eye, upstage)


class TestViewMatrixCarriesTheFlip:
    def test_view_matrix_applies_the_correction(self):
        camera = OrbitCamera()
        # A scene-frame point run through the view matrix must equal the
        # same point flipped into display space and then viewed - i.e.
        # the correction rides the view matrix, so no renderer needs to
        # know about it (and no pan/tilt math changes).
        scene_point = glm.vec4(scene(2.0, -3.0, 1.0), 1.0)
        viewed = camera.get_view_matrix() * scene_point
        raw_view = glm.lookAt(camera.get_position(), camera.target,
                              glm.vec3(0, 1, 0))
        expected = raw_view * glm.vec4(display(2.0, -3.0, 1.0), 1.0)
        assert glm.distance(glm.vec3(viewed), glm.vec3(expected)) \
            == pytest.approx(0.0, abs=1e-5)
