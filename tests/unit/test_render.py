# tests/unit/test_render.py
"""Unit tests for offline rendering components."""

import os
import math
import pytest
from unittest.mock import patch, MagicMock

from utils.render.camera_presets import CAMERA_PRESETS, _compute_distance


class TestCameraPresets:

    def test_all_presets_exist(self):
        expected = ["Front", "Front-Left 45", "Front-Right 45", "Top-Down", "Wide"]
        for name in expected:
            assert name in CAMERA_PRESETS, f"Missing preset: {name}"

    def test_preset_has_description(self):
        for name, preset in CAMERA_PRESETS.items():
            assert 'description' in preset
            assert isinstance(preset['description'], str)

    def test_preset_has_get_params(self):
        for name, preset in CAMERA_PRESETS.items():
            assert 'get_params' in preset
            assert callable(preset['get_params'])

    def test_preset_returns_required_keys(self):
        for name, preset in CAMERA_PRESETS.items():
            params = preset['get_params'](10.0, 6.0)
            assert 'azimuth' in params
            assert 'elevation' in params
            assert 'distance' in params
            assert 'target' in params
            assert len(params['target']) == 3

    def test_compute_distance_scales_with_stage(self):
        small = _compute_distance(5.0, 3.0)
        large = _compute_distance(20.0, 12.0)
        assert large > small

    def test_compute_distance_minimum(self):
        assert _compute_distance(0.1, 0.1) >= 5.0

    def test_front_camera_centered(self):
        params = CAMERA_PRESETS["Front"]["get_params"](10.0, 6.0)
        assert params['azimuth'] == 0.0  # Centered
        assert params['elevation'] > 0  # Looking slightly down

    def test_top_down_high_elevation(self):
        params = CAMERA_PRESETS["Top-Down"]["get_params"](10.0, 6.0)
        assert params['elevation'] >= 80.0


class TestOfflineRendererInit:
    """Test OfflineRenderer initialization without actually rendering."""

    def test_import(self):
        from utils.render.offline_renderer import OfflineRenderer
        assert OfflineRenderer is not None

    def test_cancel_flag(self):
        from utils.render.offline_renderer import OfflineRenderer
        renderer = OfflineRenderer.__new__(OfflineRenderer)
        renderer._cancelled = False
        renderer.cancel()
        assert renderer._cancelled is True


class TestRenderModuleImports:
    """Verify all render module components can be imported."""

    def test_import_camera_presets(self):
        from utils.render.camera_presets import CAMERA_PRESETS
        assert len(CAMERA_PRESETS) >= 5

    def test_import_offline_renderer(self):
        from utils.render.offline_renderer import OfflineRenderer
        assert OfflineRenderer is not None

    def test_import_render_dialog(self):
        from gui.dialogs.render_dialog import RenderDialog, RenderWorker
        assert RenderDialog is not None
        assert RenderWorker is not None


class TestOfflineRendererGLContext:
    """Test that standalone GL context works (requires GPU)."""

    def test_standalone_context_creation(self):
        """Verify ModernGL standalone context can be created.

        Environment probe, not a code test: on a machine with no GL
        (a display-less CI runner - glcontext's Linux default is the
        X11 backend) it SKIPS, matching the visual tier's GL tests;
        offline rendering simply is not available there.
        """
        import moderngl
        try:
            ctx = moderngl.create_context(standalone=True)
        except Exception as e:
            pytest.skip(f"Could not create standalone GL context: {e}")
        assert ctx is not None

        # Create an FBO
        color = ctx.texture((64, 64), 3)
        depth = ctx.depth_renderbuffer((64, 64))
        fbo = ctx.framebuffer(color_attachments=[color], depth_attachment=depth)

        fbo.use()
        fbo.clear(0.0, 0.0, 0.0, 1.0)

        # Read pixels
        pixels = fbo.read(components=3)
        assert len(pixels) == 64 * 64 * 3

        fbo.release()
        color.release()
        depth.release()
        ctx.release()


class TestFFmpegAvailability:
    """Test that FFmpeg is available via imageio-ffmpeg."""

    def test_ffmpeg_binary_exists(self):
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        assert os.path.exists(ffmpeg_path)
