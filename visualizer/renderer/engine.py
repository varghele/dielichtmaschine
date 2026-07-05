# visualizer/renderer/engine.py
# ModernGL render engine with PyQt6 integration

import time
import moderngl
from typing import Optional

from PyQt6.QtWidgets import QWidget
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QSurfaceFormat

from .camera import OrbitCamera
from .stage import StageRenderer
from .stage_planes import StagePlaneHighlight
from .gizmo import CoordinateGizmo
from .fixtures import FixtureManager
from .hdr import HDRPipeline


class RenderEngine(QOpenGLWidget):
    """
    ModernGL-based 3D render engine for PyQt6.

    Provides:
    - OpenGL context management
    - Orbit camera with mouse controls
    - Stage floor with grid
    - FPS counter
    - Window resize handling
    """

    def __init__(self, parent: Optional[QWidget] = None):
        """Initialize render engine."""
        # Set OpenGL format before creating widget
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setDepthBufferSize(24)
        fmt.setSamples(4)  # MSAA
        QSurfaceFormat.setDefaultFormat(fmt)

        super().__init__(parent)

        # ModernGL context (created in initializeGL)
        self.ctx: Optional[moderngl.Context] = None

        # Camera
        self.camera = OrbitCamera()

        # Renderers (created in initializeGL)
        self.stage_renderer: Optional[StageRenderer] = None
        self.stage_planes: Optional[StagePlaneHighlight] = None
        self.gizmo_renderer: Optional[CoordinateGizmo] = None
        self.fixture_manager: Optional[FixtureManager] = None
        self.hdr: Optional[HDRPipeline] = None

        # Stage dimensions
        self.stage_width = 10.0
        self.stage_height = 6.0  # depth

        # Pending state captured before initializeGL fires. QOpenGLWidget
        # only initialises GL the first time it is shown, so an embedded
        # visualizer hosted on an inactive tab silently drops fixture /
        # grid / DMX updates pushed at config-load time. We buffer them
        # here and flush in initializeGL so the preview is correct the
        # moment the user first activates the tab.
        self._pending_grid_size: Optional[float] = None
        self._pending_fixtures: Optional[list] = None
        self._pending_dmx: dict[int, bytes] = {}
        self._pending_plane_highlight: Optional[tuple] = None  # (name, rig_height)

        # Mouse tracking
        self.setMouseTracking(True)
        self.last_mouse_pos = None
        self.mouse_button = None

        # FPS counter
        self.fps = 0.0
        self.frame_count = 0
        self.fps_time = time.time()
        self.last_frame_time = time.time()
        self._first_frame = True  # Debug flag

        # Render timer (60 FPS target)
        self.render_timer = QTimer()
        self.render_timer.timeout.connect(self.update)
        self.render_timer.start(16)  # ~60 FPS

        # Enable keyboard focus
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def initializeGL(self):
        """Initialize OpenGL context and resources."""
        try:
            # Create ModernGL context from existing OpenGL context
            # standalone=False tells ModernGL to use the existing Qt context
            self.ctx = moderngl.create_context(standalone=False)

            # Get Qt's framebuffer object ID for rendering
            # QOpenGLWidget uses an FBO, not the default framebuffer
            self.qt_fbo_id = self.defaultFramebufferObject()
            print(f"Qt FBO ID: {self.qt_fbo_id}")

            # Enable depth testing
            self.ctx.enable(moderngl.DEPTH_TEST)

            # Enable blending for transparency
            self.ctx.enable(moderngl.BLEND)
            self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

            # Create stage renderer
            self.stage_renderer = StageRenderer(
                self.ctx,
                self.stage_width,
                self.stage_height
            )

            # Highlighted stage-plane overlay (driven by the Stage tab's
            # plane picker).
            self.stage_planes = StagePlaneHighlight(
                self.ctx,
                self.stage_width,
                self.stage_height
            )

            # Create coordinate gizmo
            self.gizmo_renderer = CoordinateGizmo(self.ctx)

            # Create fixture manager
            self.fixture_manager = FixtureManager(self.ctx)

            # HDR offscreen + tonemap pass so additive beam contributions
            # don't clip the framebuffer to flat white. Sized lazily in
            # paintGL from the current widget dimensions.
            self.hdr = HDRPipeline(self.ctx)

            # Set camera to fit stage
            self.camera.set_stage_size(self.stage_width, self.stage_height)

            # Flush any state pushed before this widget was first shown.
            self._flush_pending_state()

            print(f"OpenGL initialized: {self.ctx.info['GL_RENDERER']}")
            print(f"  Stage size: {self.stage_width}m x {self.stage_height}m")
            print(f"  Camera distance: {self.camera.distance}")
            print(f"  Camera position: {self.camera.get_position()}")

        except Exception as e:
            print(f"Failed to initialize OpenGL: {e}")
            import traceback
            traceback.print_exc()

    def resizeGL(self, width: int, height: int):
        """Handle window resize."""
        # Update camera aspect ratio
        if height > 0:
            self.camera.set_aspect(width / height)

        # Note: Viewport is set per-frame when binding the FBO

    def paintGL(self):
        """Render frame."""
        if not self.ctx:
            return

        # Debug: first frame info
        if self._first_frame:
            print(f"First frame rendering...")
            print(f"  Viewport: {self.ctx.viewport}")
            print(f"  Stage renderer: {self.stage_renderer is not None}")
            # Check for OpenGL errors
            try:
                error = self.ctx.error
                if error:
                    print(f"  OpenGL error: {error}")
            except:
                pass
            self._first_frame = False

        # Calculate FPS
        self._update_fps()

        # Resolve the Qt LDR FBO once so we can target it for the tonemap
        # and for LDR-only overlays (gizmo). Qt's FBO ID can change on
        # resize.
        qt_fbo_id = self.defaultFramebufferObject()
        qt_fbo = self.ctx.detect_framebuffer(qt_fbo_id)
        self.ctx.fbo = qt_fbo

        w, h = self.width(), self.height()
        self.ctx.viewport = (0, 0, w, h)

        # Get view-projection matrix
        mvp = self.camera.get_view_projection_matrix()

        # --- Scene pass: render to HDR offscreen ---
        if self.hdr is not None:
            self.hdr.resize(w, h)
            self.hdr.bind()
            self.ctx.viewport = (0, 0, w, h)
            self.hdr.clear(0.05, 0.05, 0.08, 1.0)

            if self.stage_renderer:
                self.stage_renderer.render(mvp)
            if self.fixture_manager:
                self.fixture_manager.render(mvp)
            # Plane highlight after fixtures: alpha-blends over the scene
            # while the depth test still lets chassis in front occlude it.
            if self.stage_planes:
                self.stage_planes.render(mvp)

            # --- Tonemap pass: HDR → Qt LDR FBO ---
            self.hdr.tonemap_to(qt_fbo)
            self.ctx.viewport = (0, 0, w, h)
        else:
            # Fallback path if HDR init failed: render direct to Qt FBO.
            qt_fbo.use()
            qt_fbo.clear(0.05, 0.05, 0.08, 1.0)
            if self.stage_renderer:
                self.stage_renderer.render(mvp)
            if self.fixture_manager:
                self.fixture_manager.render(mvp)
            if self.stage_planes:
                self.stage_planes.render(mvp)

        # Render coordinate gizmo last to the LDR FBO so the UI overlay
        # isn't affected by the tonemap curve.
        if self.gizmo_renderer:
            view_matrix = self.camera.get_view_matrix()
            self.gizmo_renderer.render(view_matrix, w, h)

    def _update_fps(self):
        """Update FPS counter."""
        self.frame_count += 1
        current_time = time.time()

        # Update FPS every second
        elapsed = current_time - self.fps_time
        if elapsed >= 1.0:
            self.fps = self.frame_count / elapsed
            self.frame_count = 0
            self.fps_time = current_time

        self.last_frame_time = current_time

    def get_fps(self) -> float:
        """Get current FPS."""
        return self.fps

    def set_stage_size(self, width: float, height: float):
        """
        Update stage dimensions.

        Args:
            width: Stage width in meters
            height: Stage depth in meters
        """
        print(f"RenderEngine: Updating stage size to {width}x{height}m")
        self.stage_width = width
        self.stage_height = height

        if self.stage_renderer:
            # Make sure we're in the right OpenGL context
            self.makeCurrent()
            self.stage_renderer.set_size(width, height)
            self.doneCurrent()

        if self.stage_planes:
            # GL-free: only marks geometry dirty for the next render.
            self.stage_planes.set_stage_size(width, height)

        self.camera.set_stage_size(width, height)
        print(f"RenderEngine: Stage size update complete")

    def set_highlighted_plane(self, name: Optional[str], rig_height: float = 3.0):
        """Highlight one face of the stage bounding cuboid (None clears).

        Args:
            name: One of Floor / Ceiling / Front / Back / Left / Right, or None
            rig_height: Cuboid ceiling height in meters (typically the
                tallest fixture's Z, min 3.0 — same rule as autogen's
                compute_stage_planes)
        """
        if self.stage_planes:
            # Setters are GL-free; the VBO rebuild happens inside render.
            self.stage_planes.set_rig_height(rig_height)
            self.stage_planes.set_highlight(name)
            self.update()
        else:
            self._pending_plane_highlight = (name, rig_height)

    def set_grid_size(self, grid_size: float):
        """
        Update grid spacing.

        Args:
            grid_size: Grid spacing in meters
        """
        if self.stage_renderer:
            # Make sure we're in the right OpenGL context
            self.makeCurrent()
            self.stage_renderer.set_grid_size(grid_size)
            self.doneCurrent()
            print(f"RenderEngine: Grid size updated to {grid_size}m")
        else:
            self._pending_grid_size = grid_size

    def update_fixtures(self, fixtures_data: list):
        """
        Update fixtures from TCP data.

        Args:
            fixtures_data: List of fixture dictionaries from TCP message
        """
        if self.fixture_manager:
            self.makeCurrent()
            self.fixture_manager.update_fixtures(fixtures_data)
            self.doneCurrent()
        else:
            self._pending_fixtures = fixtures_data

    def update_dmx(self, universe: int, dmx_data: bytes):
        """
        Update fixture DMX values from ArtNet data.

        Args:
            universe: Universe number
            dmx_data: 512 bytes of DMX data
        """
        if self.fixture_manager:
            self.fixture_manager.update_dmx(universe, dmx_data)
        else:
            self._pending_dmx[universe] = dmx_data

    def _flush_pending_state(self):
        """Apply state captured before initializeGL fired.

        Split out so unit tests can exercise the flush against mock
        renderers without needing a real OpenGL context.
        """
        if self._pending_grid_size is not None and self.stage_renderer:
            self.stage_renderer.set_grid_size(self._pending_grid_size)
            self._pending_grid_size = None
        if self._pending_fixtures is not None and self.fixture_manager:
            self.fixture_manager.update_fixtures(self._pending_fixtures)
            self._pending_fixtures = None
        if self.fixture_manager and self._pending_dmx:
            for uni, dmx in self._pending_dmx.items():
                self.fixture_manager.update_dmx(uni, dmx)
            self._pending_dmx.clear()
        if self._pending_plane_highlight is not None and self.stage_planes:
            name, rig_height = self._pending_plane_highlight
            self.stage_planes.set_rig_height(rig_height)
            self.stage_planes.set_highlight(name)
            self._pending_plane_highlight = None

    def reset_camera(self):
        """Reset camera to default position."""
        self.camera.reset()

    # --- Mouse Event Handlers ---

    def mousePressEvent(self, event):
        """Handle mouse button press."""
        self.last_mouse_pos = event.position()
        self.mouse_button = event.button()

    def mouseReleaseEvent(self, event):
        """Handle mouse button release."""
        self.last_mouse_pos = None
        self.mouse_button = None

    def mouseMoveEvent(self, event):
        """Handle mouse movement."""
        if self.last_mouse_pos is None:
            return

        pos = event.position()
        delta_x = pos.x() - self.last_mouse_pos.x()
        delta_y = pos.y() - self.last_mouse_pos.y()

        if self.mouse_button == Qt.MouseButton.LeftButton:
            # Orbit camera
            self.camera.orbit(delta_x, delta_y)

        elif self.mouse_button == Qt.MouseButton.RightButton:
            # Pan camera
            self.camera.pan(delta_x, delta_y)

        elif self.mouse_button == Qt.MouseButton.MiddleButton:
            # Also pan with middle button
            self.camera.pan(delta_x, delta_y)

        self.last_mouse_pos = pos

    def wheelEvent(self, event):
        """Handle mouse wheel scroll."""
        delta = event.angleDelta().y() / 120.0  # Normalize to +/- 1
        self.camera.zoom(delta)

    def keyPressEvent(self, event):
        """Handle key press."""
        if event.key() == Qt.Key.Key_Home:
            self.reset_camera()
        elif event.key() == Qt.Key.Key_R:
            self.reset_camera()

    # --- Cleanup ---

    def cleanup(self):
        """Release GPU resources."""
        if self.render_timer:
            self.render_timer.stop()

        if self.fixture_manager:
            self.fixture_manager.release()
            self.fixture_manager = None

        if self.stage_renderer:
            self.stage_renderer.release()
            self.stage_renderer = None

        if self.stage_planes:
            self.stage_planes.release()
            self.stage_planes = None

        if self.gizmo_renderer:
            self.gizmo_renderer.release()
            self.gizmo_renderer = None

        if self.hdr:
            self.hdr.release()
            self.hdr = None

        if self.ctx:
            self.ctx.release()
            self.ctx = None

    def closeEvent(self, event):
        """Handle widget close."""
        self.cleanup()
        super().closeEvent(event)
