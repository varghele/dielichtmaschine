# gui/dialogs/orientation_dialog.py
# 3D Orientation Dialog for setting fixture orientation

import math
from typing import List, Optional, Dict, Any

import moderngl
import glm
import numpy as np

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QDoubleSpinBox, QPushButton,
    QCheckBox, QWidget, QSizePolicy
)
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtGui import QSurfaceFormat
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from utils.fixture_capabilities import Chassis, chassis_from_legacy_type
from utils.geometry import GeometryBuilder


class OrientationPreviewWidget(QOpenGLWidget):
    """
    3D preview widget showing fixture orientation with gimbal rings.
    Uses ModernGL for rendering.
    """

    # Signal emitted when orientation changes from ring dragging
    orientation_changed = pyqtSignal(float, float, float)  # yaw, pitch, roll

    def __init__(self, parent=None):
        # Set OpenGL format before creating widget
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setDepthBufferSize(24)
        fmt.setSamples(4)
        QSurfaceFormat.setDefaultFormat(fmt)

        super().__init__(parent)

        self.ctx: Optional[moderngl.Context] = None

        # Orientation values
        self.mounting = "hanging"
        self.yaw = 0.0
        self.pitch = 0.0
        self.roll = 0.0

        # Fixture type for rendering (default to MH). ``self.chassis`` is the
        # chassis-keyed view; ``fixture_type`` is kept for sub-variant cues
        # (SUNSTRIP vs BAR, WASH vs PAR) within a single chassis branch.
        self.fixture_type = "MH"
        self.chassis: Chassis = Chassis.MOVING_YOKE
        self.segment_count = 8  # Default segment count for bars/sunstrips

        # Default colors and dimensions (will be set properly when geometry is created)
        self.body_color = (0.15, 0.15, 0.18)
        self.yoke_color = (0.15, 0.15, 0.18)
        self.front_depth = 0.2

        # Moving head specific dimensions (defaults)
        self.mh_base_height = 0.08
        self.mh_yoke_height = 0.2
        self.mh_head_height = 0.18
        self.mh_head_depth = 0.1

        # Camera parameters
        self.camera_distance = 4.0
        self.camera_azimuth = 45.0
        self.camera_elevation = 25.0

        # Mouse tracking
        self.last_mouse_pos = None
        self.mouse_button = None
        self.setMouseTracking(True)

        # Ring dragging state
        self.dragging_ring = None  # 'yaw', 'pitch', 'roll', or None
        self.drag_start_angle = 0.0

        # Render resources (all VAOs initialized to None)
        self.fixture_program = None
        self.fixture_vao = None
        self.segment_vao = None
        self.lamp_vao = None
        self.lens_vao = None
        self.base_vao = None
        self.yoke_vao = None
        self.head_vao = None
        self.indicator_vao = None
        self.ring_program = None
        self.ring_vao = None
        self.floor_program = None
        self.floor_vao = None
        self.wall_program = None
        self.wall_vao = None
        self.axes_vao = None
        self.handle_vao = None

        # Render timer
        self.render_timer = QTimer()
        self.render_timer.timeout.connect(self.update)
        self.render_timer.start(33)  # ~30 FPS

        # Compact-friendly minimum so the preview can sit comfortably inside
        # the Stage tab's right-hand splitter without forcing the whole
        # column wide. The dialog wrapper still sets a 500x550 dialog min.
        self.setMinimumSize(180, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def initializeGL(self):
        """Initialize OpenGL context and resources."""
        try:
            self.ctx = moderngl.create_context(standalone=False)
            self.ctx.enable(moderngl.DEPTH_TEST)
            self.ctx.enable(moderngl.BLEND)
            self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

            self._create_fixture_geometry()
            self._create_floor_geometry()
            self._create_axes_geometry()
            self._create_ring_geometry()
            self._create_handle_geometry()

        except Exception as e:
            print(f"Failed to initialize OrientationPreviewWidget: {e}")
            import traceback
            traceback.print_exc()

    def _create_fixture_geometry(self):
        """Create fixture body geometry based on fixture type."""
        # Shader for fixture body with emissive support (like visualizer)
        vertex_shader = """
            #version 330
            uniform mat4 mvp;
            uniform mat4 model;
            in vec3 in_position;
            in vec3 in_normal;
            out vec3 v_normal;
            out vec3 v_world_pos;
            void main() {
                gl_Position = mvp * vec4(in_position, 1.0);
                v_normal = mat3(model) * in_normal;
                v_world_pos = vec3(model * vec4(in_position, 1.0));
            }
        """
        fragment_shader = """
            #version 330
            uniform vec3 base_color;
            uniform vec3 emissive_color;
            uniform float emissive_strength;
            in vec3 v_normal;
            in vec3 v_world_pos;
            out vec4 fragColor;
            void main() {
                vec3 light_dir = normalize(vec3(0.5, 1.0, 0.3));
                float diff = max(dot(normalize(v_normal), light_dir), 0.0);
                vec3 ambient = base_color * 0.3;
                vec3 diffuse = base_color * diff * 0.7;
                vec3 emissive = emissive_color * emissive_strength;
                vec3 final_color = ambient + diffuse + emissive;
                fragColor = vec4(final_color, 1.0);
            }
        """
        self.fixture_program = self.ctx.program(
            vertex_shader=vertex_shader,
            fragment_shader=fragment_shader
        )

        # Create geometry based on fixture type
        self._update_fixture_geometry()

    def set_fixture_type(self, fixture_type: str, segment_count: int = 8):
        """Update the fixture type and recreate geometry."""
        if fixture_type != self.fixture_type or segment_count != self.segment_count:
            self.fixture_type = fixture_type
            self.chassis = chassis_from_legacy_type(fixture_type)
            self.segment_count = segment_count
            if self.ctx:
                self._update_fixture_geometry()
            self.update()

    def _release_fixture_vaos(self):
        """Release all fixture-related VAOs."""
        vao_attrs = ['fixture_vao', 'indicator_vao', 'segment_vao', 'lens_vao',
                     'base_vao', 'yoke_vao', 'head_vao', 'lamp_vao']
        for attr in vao_attrs:
            if hasattr(self, attr):
                vao = getattr(self, attr)
                if vao:
                    try:
                        vao.release()
                    except:
                        pass
                setattr(self, attr, None)

    def _update_fixture_geometry(self):
        """Create/update fixture geometry based on the current chassis.

        Dispatches on :class:`Chassis` (Phase C). Within Chassis.BAR /
        Chassis.PAR we still consult ``fixture_type`` for sub-variant
        visuals (SUNSTRIP, WASH) where the existing code has a
        dedicated mesh — keeps visual fidelity without re-introducing
        a 6-string dispatch at the top level.
        """
        self._release_fixture_vaos()

        if self.chassis is Chassis.MOVING_YOKE:
            self._create_moving_head_geometry()
        elif self.chassis is Chassis.PAR:
            if self.fixture_type == "WASH":
                self._create_wash_geometry()
            else:
                self._create_par_geometry()
        elif self.chassis is Chassis.BAR:
            if self.fixture_type == "SUNSTRIP":
                self._create_sunstrip_geometry()
            else:
                self._create_led_bar_geometry()
        elif self.chassis is Chassis.PANEL:
            # Closest existing mesh — a flat-faced bar. Phase D may
            # add a dedicated W×H pixel-matrix preview.
            self._create_led_bar_geometry()
        else:
            # SCANNER / EFFECT / PARTICLE / LASER / OTHER — placeholder
            # until each gets a dedicated preview mesh.
            self._create_moving_head_geometry()

    def _create_led_bar_geometry(self):
        """Create LED Bar geometry with body and LED segments (like visualizer)."""
        # Physical dimensions (scaled for preview)
        width = 0.6
        height = 0.08
        depth = 0.1

        # Body color (dark metal)
        self.body_color = (0.15, 0.15, 0.18)

        # Create bar body
        body_verts, body_norms = GeometryBuilder.create_box(width, height, depth)
        vbo = self.ctx.buffer(body_verts.tobytes())
        nbo = self.ctx.buffer(body_norms.tobytes())
        self.fixture_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(vbo, '3f', 'in_position'), (nbo, '3f', 'in_normal')]
        )

        # Create LED segment geometry (emitter surfaces on front)
        segment_width = (width * 0.9) / self.segment_count
        segment_height = height * 0.6
        segment_depth = 0.015

        segment_verts = []
        segment_norms = []
        start_x = -width * 0.45 + segment_width / 2

        for i in range(self.segment_count):
            x_offset = start_x + i * segment_width
            verts, norms = GeometryBuilder.create_box(
                segment_width * 0.85,
                segment_height,
                segment_depth,
                center=(x_offset, 0, depth / 2 + segment_depth / 2)
            )
            segment_verts.extend(verts.tolist())
            segment_norms.extend(norms.tolist())

        segment_verts = np.array(segment_verts, dtype='f4')
        segment_norms = np.array(segment_norms, dtype='f4')
        seg_vbo = self.ctx.buffer(segment_verts.tobytes())
        seg_nbo = self.ctx.buffer(segment_norms.tobytes())
        self.segment_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(seg_vbo, '3f', 'in_position'), (seg_nbo, '3f', 'in_normal')]
        )

        # Create front indicator
        self._create_front_indicator(depth / 2 + segment_depth + 0.01, height * 0.4)

        # Create coordinate axes on top of fixture (matching visualizer)
        self._create_bar_coordinate_axes(depth / 2 + 0.01, width)

        self.front_depth = depth / 2 + segment_depth

    def _create_sunstrip_geometry(self):
        """Create Sunstrip geometry with body and lamp bulbs (matching visualizer).

        Uses Z-up coordinate system per reference.md:
        - Bar extends along X axis
        - Lamps face +Z direction (up)
        """
        # Physical dimensions
        width = 0.6   # X dimension (bar length)
        height = 0.06  # Y dimension (toward audience)
        depth = 0.08   # Z dimension (up)

        self.body_color = (0.12, 0.12, 0.15)

        # Create bar body
        body_verts, body_norms = GeometryBuilder.create_box(width, height, depth)
        vbo = self.ctx.buffer(body_verts.tobytes())
        nbo = self.ctx.buffer(body_norms.tobytes())
        self.fixture_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(vbo, '3f', 'in_position'), (nbo, '3f', 'in_normal')]
        )

        # Create lamp bulbs (cylinders) - lamps face +Z (up) per reference.md
        lamp_radius = min(width / self.segment_count * 0.35, 0.025)
        lamp_height = 0.02

        lamp_verts = []
        lamp_norms = []
        spacing = width * 0.9 / self.segment_count
        start_x = -width * 0.45 + spacing / 2

        for i in range(self.segment_count):
            x_offset = start_x + i * spacing
            # Create cylinder (Y-oriented by default), then rotate to face +Z
            verts_raw, norms_raw = GeometryBuilder.create_cylinder(
                lamp_radius, lamp_height, segments=12,
                center=(0, 0, 0)
            )
            # Rotate -90° around X to point +Z, then translate to lamp position
            # Rotation: (x, y, z) -> (x, -z, y)
            for j in range(0, len(verts_raw), 3):
                x, y, z = verts_raw[j], verts_raw[j+1], verts_raw[j+2]
                new_x = x + x_offset
                new_y = -z
                new_z = y + depth / 2 + lamp_height / 2
                lamp_verts.extend([new_x, new_y, new_z])
            for j in range(0, len(norms_raw), 3):
                nx, ny, nz = norms_raw[j], norms_raw[j+1], norms_raw[j+2]
                lamp_norms.extend([nx, -nz, ny])

        lamp_verts = np.array(lamp_verts, dtype='f4')
        lamp_norms = np.array(lamp_norms, dtype='f4')
        lamp_vbo = self.ctx.buffer(lamp_verts.tobytes())
        lamp_nbo = self.ctx.buffer(lamp_norms.tobytes())
        self.lamp_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(lamp_vbo, '3f', 'in_position'), (lamp_nbo, '3f', 'in_normal')]
        )

        # Create coordinate axes on top of fixture (matching visualizer)
        self._create_bar_coordinate_axes(depth / 2 + 0.01, width)

        self.front_depth = depth / 2

    def _create_par_geometry(self):
        """Create PAR can geometry (cylinder with lens) matching visualizer.

        Uses Z-up coordinate system per reference.md:
        - Cylindrical body extends along Z axis
        - Lens/beam faces +Z direction
        """
        radius = 0.1
        depth = 0.2

        self.body_color = (0.1, 0.1, 0.12)

        # Create body cylinder - rotate from Y-oriented to Z-oriented
        body_verts_raw, body_norms_raw = GeometryBuilder.create_cylinder(radius, depth, segments=24)

        # Rotate -90° around X: (x, y, z) -> (x, -z, y)
        body_verts = []
        body_norms = []
        for i in range(0, len(body_verts_raw), 3):
            x, y, z = body_verts_raw[i], body_verts_raw[i+1], body_verts_raw[i+2]
            body_verts.extend([x, -z, y])
        for i in range(0, len(body_norms_raw), 3):
            nx, ny, nz = body_norms_raw[i], body_norms_raw[i+1], body_norms_raw[i+2]
            body_norms.extend([nx, -nz, ny])

        body_verts = np.array(body_verts, dtype='f4')
        body_norms = np.array(body_norms, dtype='f4')
        vbo = self.ctx.buffer(body_verts.tobytes())
        nbo = self.ctx.buffer(body_norms.tobytes())
        self.fixture_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(vbo, '3f', 'in_position'), (nbo, '3f', 'in_normal')]
        )

        # Create lens (front face at +Z)
        lens_verts_raw, lens_norms_raw = GeometryBuilder.create_cylinder(
            radius * 0.85, 0.02, segments=24,
            center=(0, 0, 0)
        )

        # Rotate -90° around X and translate to +Z face
        lens_verts = []
        lens_norms = []
        for i in range(0, len(lens_verts_raw), 3):
            x, y, z = lens_verts_raw[i], lens_verts_raw[i+1], lens_verts_raw[i+2]
            lens_verts.extend([x, -z, y + depth / 2 + 0.01])
        for i in range(0, len(lens_norms_raw), 3):
            nx, ny, nz = lens_norms_raw[i], lens_norms_raw[i+1], lens_norms_raw[i+2]
            lens_norms.extend([nx, -nz, ny])

        lens_verts = np.array(lens_verts, dtype='f4')
        lens_norms = np.array(lens_norms, dtype='f4')
        lens_vbo = self.ctx.buffer(lens_verts.tobytes())
        lens_nbo = self.ctx.buffer(lens_norms.tobytes())
        self.lens_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(lens_vbo, '3f', 'in_position'), (lens_nbo, '3f', 'in_normal')]
        )

        # Create coordinate axes on top of fixture
        self._create_par_coordinate_axes(depth / 2 + 0.01)

        self.front_depth = depth / 2
        self.par_radius = radius
        self.par_depth = depth

    def _create_wash_geometry(self):
        """Create Wash fixture geometry (box with lens panel) matching visualizer exactly.

        Uses Z-up coordinate system per reference.md:
        - Body lies in X-Y plane
        - Lens/beam faces +Z direction
        """
        width = 0.25
        height = 0.15
        depth = 0.18

        self.body_color = (0.12, 0.12, 0.15)

        # Create main body (same as visualizer)
        body_verts, body_norms = GeometryBuilder.create_box(width, height, depth)
        vbo = self.ctx.buffer(body_verts.tobytes())
        nbo = self.ctx.buffer(body_norms.tobytes())
        self.fixture_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(vbo, '3f', 'in_position'), (nbo, '3f', 'in_normal')]
        )

        # Create lens/front emitter (on +Z face, same as visualizer)
        lens_width = width * 0.85
        lens_height = height * 0.85
        lens_depth = 0.02

        lens_verts, lens_norms = GeometryBuilder.create_box(
            lens_width, lens_height, lens_depth,
            center=(0, 0, depth / 2 + lens_depth / 2)
        )
        lens_vbo = self.ctx.buffer(lens_verts.tobytes())
        lens_nbo = self.ctx.buffer(lens_norms.tobytes())
        self.lens_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(lens_vbo, '3f', 'in_position'), (lens_nbo, '3f', 'in_normal')]
        )

        # Create coordinate axes (same position as visualizer: depth/2 + 0.01)
        self._create_wash_coordinate_axes(depth / 2 + 0.01)

        self.front_depth = depth / 2 + lens_depth

    def _create_moving_head_geometry(self):
        """Create Moving Head geometry (base, yoke, head, lens) matching visualizer exactly.

        Uses Z-up coordinate system matching the visualizer:
        - X-Y plane: horizontal (base plate)
        - Z: vertical (up)
        - At Pan=0, Tilt=0: beam points +X

        See reference.md for full coordinate system documentation.
        """
        # Use same proportions as visualizer (scaled for dialog)
        # Simulating a fixture with width=0.3, depth=0.3, height=0.4
        width = 0.3
        depth = 0.3
        height = 0.4

        base_size = min(width, depth)
        base_thickness = height * 0.15  # Thickness in Z direction (up)

        yoke_thickness = base_size * 0.15  # Thickness of yoke arms
        yoke_height = height * 0.5  # Height in Z direction (up)
        yoke_depth = base_size * 0.8  # Depth along X (forward direction at Pan=0)

        # Head dimensions in local space (before pan/tilt):
        # X = forward/back (toward lens), Y = left/right (tilt axis), Z = up/down
        head_size_x = base_size * 0.5  # Forward/back dimension
        head_size_y = base_size * 0.7  # Left/right dimension (tilt axis)
        head_size_z = height * 0.45  # Up/down dimension

        self.body_color = (0.1, 0.1, 0.12)
        self.yoke_color = (0.15, 0.15, 0.18)

        # Create base (rectangular box in X-Y plane, Z is thickness/up)
        base_verts, base_norms = GeometryBuilder.create_box(
            base_size, base_size, base_thickness,
            center=(0, 0, base_thickness / 2)
        )
        base_vbo = self.ctx.buffer(base_verts.tobytes())
        base_nbo = self.ctx.buffer(base_norms.tobytes())
        self.base_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(base_vbo, '3f', 'in_position'), (base_nbo, '3f', 'in_normal')]
        )

        # Create coordinate axes on base for debugging orientation (matching visualizer)
        axis_origin_z = base_thickness + 0.01
        axis_length = 0.4  # Same as visualizer: 40cm axes for visibility
        axis_thickness = 0.008  # Same as visualizer
        arrow_length = 0.06  # Arrow head length
        arrow_width = 0.04  # Arrow head width

        # X-AXIS (Red) - pointing along +X (beam direction at Pan=0, Tilt=0)
        x_shaft_verts, x_shaft_norms = GeometryBuilder.create_box(
            axis_length, axis_thickness, axis_thickness,
            center=(axis_length / 2, 0, axis_origin_z)
        )
        arrow_tip_x = axis_length + arrow_length
        arrow_base_x = axis_length
        x_arrow_verts = np.array([
            # 4 triangular faces of pyramid pointing +X
            arrow_base_x, -arrow_width/2, axis_origin_z - arrow_width/2,
            arrow_base_x, arrow_width/2, axis_origin_z - arrow_width/2,
            arrow_tip_x, 0, axis_origin_z,

            arrow_base_x, arrow_width/2, axis_origin_z + arrow_width/2,
            arrow_base_x, -arrow_width/2, axis_origin_z + arrow_width/2,
            arrow_tip_x, 0, axis_origin_z,

            arrow_base_x, -arrow_width/2, axis_origin_z + arrow_width/2,
            arrow_base_x, -arrow_width/2, axis_origin_z - arrow_width/2,
            arrow_tip_x, 0, axis_origin_z,

            arrow_base_x, arrow_width/2, axis_origin_z - arrow_width/2,
            arrow_base_x, arrow_width/2, axis_origin_z + arrow_width/2,
            arrow_tip_x, 0, axis_origin_z,
        ], dtype='f4')
        x_arrow_norms = np.array([0, -1, 0] * 3 + [0, 1, 0] * 3 + [0, 0, -1] * 3 + [0, 0, 1] * 3, dtype='f4')
        x_axis_verts = np.concatenate([x_shaft_verts, x_arrow_verts])
        x_axis_norms = np.concatenate([x_shaft_norms, x_arrow_norms])

        x_axis_vbo = self.ctx.buffer(x_axis_verts.tobytes())
        x_axis_nbo = self.ctx.buffer(x_axis_norms.tobytes())
        self.mh_x_axis_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(x_axis_vbo, '3f', 'in_position'), (x_axis_nbo, '3f', 'in_normal')]
        )

        # Y-AXIS (Blue) - pointing along +Y (toward audience)
        y_shaft_verts, y_shaft_norms = GeometryBuilder.create_box(
            axis_thickness, axis_length, axis_thickness,
            center=(0, axis_length / 2, axis_origin_z)
        )
        arrow_tip_y = axis_length + arrow_length
        arrow_base_y = axis_length
        y_arrow_verts = np.array([
            # 4 triangular faces of pyramid pointing +Y
            -arrow_width/2, arrow_base_y, axis_origin_z - arrow_width/2,
            arrow_width/2, arrow_base_y, axis_origin_z - arrow_width/2,
            0, arrow_tip_y, axis_origin_z,

            arrow_width/2, arrow_base_y, axis_origin_z + arrow_width/2,
            -arrow_width/2, arrow_base_y, axis_origin_z + arrow_width/2,
            0, arrow_tip_y, axis_origin_z,

            -arrow_width/2, arrow_base_y, axis_origin_z + arrow_width/2,
            -arrow_width/2, arrow_base_y, axis_origin_z - arrow_width/2,
            0, arrow_tip_y, axis_origin_z,

            arrow_width/2, arrow_base_y, axis_origin_z - arrow_width/2,
            arrow_width/2, arrow_base_y, axis_origin_z + arrow_width/2,
            0, arrow_tip_y, axis_origin_z,
        ], dtype='f4')
        y_arrow_norms = np.array([0, 0, -1] * 3 + [0, 0, 1] * 3 + [-1, 0, 0] * 3 + [1, 0, 0] * 3, dtype='f4')
        y_axis_verts = np.concatenate([y_shaft_verts, y_arrow_verts])
        y_axis_norms = np.concatenate([y_shaft_norms, y_arrow_norms])

        y_axis_vbo = self.ctx.buffer(y_axis_verts.tobytes())
        y_axis_nbo = self.ctx.buffer(y_axis_norms.tobytes())
        self.mh_y_axis_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(y_axis_vbo, '3f', 'in_position'), (y_axis_nbo, '3f', 'in_normal')]
        )

        # Z-AXIS (Green) - pointing along +Z (up)
        z_shaft_verts, z_shaft_norms = GeometryBuilder.create_box(
            axis_thickness, axis_thickness, axis_length,
            center=(0, 0, axis_origin_z + axis_length / 2)
        )
        arrow_tip_z = axis_origin_z + axis_length + arrow_length
        arrow_base_z = axis_origin_z + axis_length
        z_arrow_verts = np.array([
            # 4 triangular faces of pyramid pointing +Z (up)
            -arrow_width/2, -arrow_width/2, arrow_base_z,
            arrow_width/2, -arrow_width/2, arrow_base_z,
            0, 0, arrow_tip_z,

            arrow_width/2, arrow_width/2, arrow_base_z,
            -arrow_width/2, arrow_width/2, arrow_base_z,
            0, 0, arrow_tip_z,

            -arrow_width/2, arrow_width/2, arrow_base_z,
            -arrow_width/2, -arrow_width/2, arrow_base_z,
            0, 0, arrow_tip_z,

            arrow_width/2, -arrow_width/2, arrow_base_z,
            arrow_width/2, arrow_width/2, arrow_base_z,
            0, 0, arrow_tip_z,
        ], dtype='f4')
        z_arrow_norms = np.array([0, -1, 0] * 3 + [0, 1, 0] * 3 + [-1, 0, 0] * 3 + [1, 0, 0] * 3, dtype='f4')
        z_axis_verts = np.concatenate([z_shaft_verts, z_arrow_verts])
        z_axis_norms = np.concatenate([z_shaft_norms, z_arrow_norms])

        z_axis_vbo = self.ctx.buffer(z_axis_verts.tobytes())
        z_axis_nbo = self.ctx.buffer(z_axis_norms.tobytes())
        self.mh_z_axis_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(z_axis_vbo, '3f', 'in_position'), (z_axis_nbo, '3f', 'in_normal')]
        )

        # Create indicator triangle on base
        indicator_size = base_size * 0.25
        indicator_z = base_thickness + 0.005
        indicator_x = base_size / 2 * 0.7

        indicator_verts = np.array([
            indicator_x + indicator_size * 0.4, 0, indicator_z,
            indicator_x - indicator_size * 0.2, -indicator_size * 0.35, indicator_z,
            indicator_x - indicator_size * 0.2, indicator_size * 0.35, indicator_z,
        ], dtype='f4')
        indicator_norms = np.array([0, 0, 1, 0, 0, 1, 0, 0, 1], dtype='f4')

        indicator_vbo = self.ctx.buffer(indicator_verts.tobytes())
        indicator_nbo = self.ctx.buffer(indicator_norms.tobytes())
        self.indicator_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(indicator_vbo, '3f', 'in_position'), (indicator_nbo, '3f', 'in_normal')]
        )

        # Create yoke arms (two pieces extending up in Z, on +Y and -Y sides)
        # At Pan=0, head faces +X and tilts around Y axis
        # So yoke arms are positioned on ±Y to allow tilting
        yoke_z = base_thickness + yoke_height / 2
        left_yoke_verts, left_yoke_norms = GeometryBuilder.create_box(
            yoke_depth, yoke_thickness, yoke_height,  # X, Y, Z dimensions
            center=(0, -head_size_y / 2 - yoke_thickness / 2, yoke_z)
        )
        right_yoke_verts, right_yoke_norms = GeometryBuilder.create_box(
            yoke_depth, yoke_thickness, yoke_height,  # X, Y, Z dimensions
            center=(0, head_size_y / 2 + yoke_thickness / 2, yoke_z)
        )
        yoke_verts = np.concatenate([left_yoke_verts, right_yoke_verts])
        yoke_norms = np.concatenate([left_yoke_norms, right_yoke_norms])

        yoke_vbo = self.ctx.buffer(yoke_verts.tobytes())
        yoke_nbo = self.ctx.buffer(yoke_norms.tobytes())
        self.yoke_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(yoke_vbo, '3f', 'in_position'), (yoke_nbo, '3f', 'in_normal')]
        )

        # Create head (box, will be rotated for tilt around Y-axis)
        # Head created at origin, transformed during render
        # Lens faces +X direction at default position
        head_verts, head_norms = GeometryBuilder.create_box(
            head_size_x, head_size_y, head_size_z
        )
        head_vbo = self.ctx.buffer(head_verts.tobytes())
        head_nbo = self.ctx.buffer(head_norms.tobytes())
        self.head_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(head_vbo, '3f', 'in_position'), (head_nbo, '3f', 'in_normal')]
        )

        # Create lens (cylinder facing +X direction)
        lens_radius = min(head_size_y, head_size_z) * 0.35
        lens_depth = 0.02

        # Create cylinder (Y-oriented by default)
        lens_verts_raw, lens_norms_raw = GeometryBuilder.create_cylinder(
            lens_radius, lens_depth, segments=24,
            center=(0, 0, 0)
        )

        # Rotate lens to face +X (cylinder Y-axis -> X-axis)
        # Rotation -90° around Z: (x, y, z) -> (y, -x, z)
        lens_verts = []
        lens_norms = []
        for i in range(0, len(lens_verts_raw), 3):
            x, y, z = lens_verts_raw[i], lens_verts_raw[i+1], lens_verts_raw[i+2]
            # Rotate -90° around Z, then offset to +X face of head
            new_x = y + head_size_x / 2 + lens_depth / 2
            new_y = -x
            new_z = z
            lens_verts.extend([new_x, new_y, new_z])

        for i in range(0, len(lens_norms_raw), 3):
            nx, ny, nz = lens_norms_raw[i], lens_norms_raw[i+1], lens_norms_raw[i+2]
            lens_norms.extend([ny, -nx, nz])

        lens_verts = np.array(lens_verts, dtype='f4')
        lens_norms = np.array(lens_norms, dtype='f4')

        lens_vbo = self.ctx.buffer(lens_verts.tobytes())
        lens_nbo = self.ctx.buffer(lens_norms.tobytes())
        self.lens_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(lens_vbo, '3f', 'in_position'), (lens_nbo, '3f', 'in_normal')]
        )

        # Store dimensions for positioning (Z-up coordinate system)
        self.mh_base_thickness = base_thickness  # Height of base in Z
        self.mh_yoke_height = yoke_height  # Height of yoke in Z direction
        self.mh_head_size_x = head_size_x  # Head size along X (beam direction)
        self.mh_head_size_y = head_size_y  # Head size along Y (tilt axis)
        self.mh_head_size_z = head_size_z  # Head size along Z (up/down)
        self.front_depth = head_size_x / 2

    def _create_front_indicator(self, z_pos: float, size: float):
        """Create a front indicator triangle at the given Z position."""
        indicator_verts = np.array([
            0, size * 0.8, z_pos,
            -size * 0.6, -size * 0.4, z_pos,
            size * 0.6, -size * 0.4, z_pos,
        ], dtype='f4')
        indicator_norms = np.array([0, 0, 1, 0, 0, 1, 0, 0, 1], dtype='f4')

        indicator_vbo = self.ctx.buffer(indicator_verts.tobytes())
        indicator_nbo = self.ctx.buffer(indicator_norms.tobytes())
        self.indicator_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(indicator_vbo, '3f', 'in_position'), (indicator_nbo, '3f', 'in_normal')]
        )

    def _create_bar_coordinate_axes(self, axis_origin_z: float, bar_width: float):
        """Create coordinate axes for bar fixtures (Sunstrip, LED Bar).

        Args:
            axis_origin_z: Z position for axis origin (top of fixture)
            bar_width: Width of bar to scale axes appropriately
        """
        axis_length = max(bar_width, 0.3) + 0.1
        axis_thickness = 0.008
        arrow_length = 0.06
        arrow_width = 0.04

        # X-AXIS (Red) - pointing along +X
        x_shaft_verts, x_shaft_norms = GeometryBuilder.create_box(
            axis_length, axis_thickness, axis_thickness,
            center=(axis_length / 2, 0, axis_origin_z)
        )
        arrow_tip_x = axis_length + arrow_length
        arrow_base_x = axis_length
        x_arrow_verts = np.array([
            arrow_base_x, -arrow_width/2, axis_origin_z - arrow_width/2,
            arrow_base_x, arrow_width/2, axis_origin_z - arrow_width/2,
            arrow_tip_x, 0, axis_origin_z,
            arrow_base_x, arrow_width/2, axis_origin_z + arrow_width/2,
            arrow_base_x, -arrow_width/2, axis_origin_z + arrow_width/2,
            arrow_tip_x, 0, axis_origin_z,
            arrow_base_x, -arrow_width/2, axis_origin_z + arrow_width/2,
            arrow_base_x, -arrow_width/2, axis_origin_z - arrow_width/2,
            arrow_tip_x, 0, axis_origin_z,
            arrow_base_x, arrow_width/2, axis_origin_z - arrow_width/2,
            arrow_base_x, arrow_width/2, axis_origin_z + arrow_width/2,
            arrow_tip_x, 0, axis_origin_z,
        ], dtype='f4')
        x_arrow_norms = np.array([0, 0, -1] * 3 + [0, 0, 1] * 3 + [0, -1, 0] * 3 + [0, 1, 0] * 3, dtype='f4')
        x_axis_verts = np.concatenate([x_shaft_verts, x_arrow_verts])
        x_axis_norms = np.concatenate([x_shaft_norms, x_arrow_norms])

        x_axis_vbo = self.ctx.buffer(x_axis_verts.tobytes())
        x_axis_nbo = self.ctx.buffer(x_axis_norms.tobytes())
        self.bar_x_axis_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(x_axis_vbo, '3f', 'in_position'), (x_axis_nbo, '3f', 'in_normal')]
        )

        # Y-AXIS (Blue) - pointing along +Y
        y_shaft_verts, y_shaft_norms = GeometryBuilder.create_box(
            axis_thickness, axis_length, axis_thickness,
            center=(0, axis_length / 2, axis_origin_z)
        )
        arrow_tip_y = axis_length + arrow_length
        arrow_base_y = axis_length
        y_arrow_verts = np.array([
            -arrow_width/2, arrow_base_y, axis_origin_z - arrow_width/2,
            arrow_width/2, arrow_base_y, axis_origin_z - arrow_width/2,
            0, arrow_tip_y, axis_origin_z,
            arrow_width/2, arrow_base_y, axis_origin_z + arrow_width/2,
            -arrow_width/2, arrow_base_y, axis_origin_z + arrow_width/2,
            0, arrow_tip_y, axis_origin_z,
            -arrow_width/2, arrow_base_y, axis_origin_z + arrow_width/2,
            -arrow_width/2, arrow_base_y, axis_origin_z - arrow_width/2,
            0, arrow_tip_y, axis_origin_z,
            arrow_width/2, arrow_base_y, axis_origin_z - arrow_width/2,
            arrow_width/2, arrow_base_y, axis_origin_z + arrow_width/2,
            0, arrow_tip_y, axis_origin_z,
        ], dtype='f4')
        y_arrow_norms = np.array([0, 0, -1] * 3 + [0, 0, 1] * 3 + [-1, 0, 0] * 3 + [1, 0, 0] * 3, dtype='f4')
        y_axis_verts = np.concatenate([y_shaft_verts, y_arrow_verts])
        y_axis_norms = np.concatenate([y_shaft_norms, y_arrow_norms])

        y_axis_vbo = self.ctx.buffer(y_axis_verts.tobytes())
        y_axis_nbo = self.ctx.buffer(y_axis_norms.tobytes())
        self.bar_y_axis_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(y_axis_vbo, '3f', 'in_position'), (y_axis_nbo, '3f', 'in_normal')]
        )

        # Z-AXIS (Green) - pointing along +Z (up)
        z_shaft_verts, z_shaft_norms = GeometryBuilder.create_box(
            axis_thickness, axis_thickness, axis_length,
            center=(0, 0, axis_origin_z + axis_length / 2)
        )
        arrow_tip_z = axis_origin_z + axis_length + arrow_length
        arrow_base_z = axis_origin_z + axis_length
        z_arrow_verts = np.array([
            -arrow_width/2, -arrow_width/2, arrow_base_z,
            arrow_width/2, -arrow_width/2, arrow_base_z,
            0, 0, arrow_tip_z,
            arrow_width/2, arrow_width/2, arrow_base_z,
            -arrow_width/2, arrow_width/2, arrow_base_z,
            0, 0, arrow_tip_z,
            -arrow_width/2, arrow_width/2, arrow_base_z,
            -arrow_width/2, -arrow_width/2, arrow_base_z,
            0, 0, arrow_tip_z,
            arrow_width/2, -arrow_width/2, arrow_base_z,
            arrow_width/2, arrow_width/2, arrow_base_z,
            0, 0, arrow_tip_z,
        ], dtype='f4')
        z_arrow_norms = np.array([0, -1, 0] * 3 + [0, 1, 0] * 3 + [-1, 0, 0] * 3 + [1, 0, 0] * 3, dtype='f4')
        z_axis_verts = np.concatenate([z_shaft_verts, z_arrow_verts])
        z_axis_norms = np.concatenate([z_shaft_norms, z_arrow_norms])

        z_axis_vbo = self.ctx.buffer(z_axis_verts.tobytes())
        z_axis_nbo = self.ctx.buffer(z_axis_norms.tobytes())
        self.bar_z_axis_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(z_axis_vbo, '3f', 'in_position'), (z_axis_nbo, '3f', 'in_normal')]
        )

    def _create_par_coordinate_axes(self, axis_origin_z: float):
        """Create coordinate axes for PAR fixture.

        Args:
            axis_origin_z: Z position for axis origin (top of fixture)
        """
        axis_length = 0.4
        axis_thickness = 0.008
        arrow_length = 0.06
        arrow_width = 0.04

        # X-AXIS (Red)
        x_shaft_verts, x_shaft_norms = GeometryBuilder.create_box(
            axis_length, axis_thickness, axis_thickness,
            center=(axis_length / 2, 0, axis_origin_z)
        )
        arrow_tip_x = axis_length + arrow_length
        arrow_base_x = axis_length
        x_arrow_verts = np.array([
            arrow_base_x, -arrow_width/2, axis_origin_z - arrow_width/2,
            arrow_base_x, arrow_width/2, axis_origin_z - arrow_width/2,
            arrow_tip_x, 0, axis_origin_z,
            arrow_base_x, arrow_width/2, axis_origin_z + arrow_width/2,
            arrow_base_x, -arrow_width/2, axis_origin_z + arrow_width/2,
            arrow_tip_x, 0, axis_origin_z,
            arrow_base_x, -arrow_width/2, axis_origin_z + arrow_width/2,
            arrow_base_x, -arrow_width/2, axis_origin_z - arrow_width/2,
            arrow_tip_x, 0, axis_origin_z,
            arrow_base_x, arrow_width/2, axis_origin_z - arrow_width/2,
            arrow_base_x, arrow_width/2, axis_origin_z + arrow_width/2,
            arrow_tip_x, 0, axis_origin_z,
        ], dtype='f4')
        x_arrow_norms = np.array([0, 0, -1] * 3 + [0, 0, 1] * 3 + [0, -1, 0] * 3 + [0, 1, 0] * 3, dtype='f4')
        x_axis_verts = np.concatenate([x_shaft_verts, x_arrow_verts])
        x_axis_norms = np.concatenate([x_shaft_norms, x_arrow_norms])

        x_axis_vbo = self.ctx.buffer(x_axis_verts.tobytes())
        x_axis_nbo = self.ctx.buffer(x_axis_norms.tobytes())
        self.par_x_axis_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(x_axis_vbo, '3f', 'in_position'), (x_axis_nbo, '3f', 'in_normal')]
        )

        # Y-AXIS (Blue)
        y_shaft_verts, y_shaft_norms = GeometryBuilder.create_box(
            axis_thickness, axis_length, axis_thickness,
            center=(0, axis_length / 2, axis_origin_z)
        )
        arrow_tip_y = axis_length + arrow_length
        arrow_base_y = axis_length
        y_arrow_verts = np.array([
            -arrow_width/2, arrow_base_y, axis_origin_z - arrow_width/2,
            arrow_width/2, arrow_base_y, axis_origin_z - arrow_width/2,
            0, arrow_tip_y, axis_origin_z,
            arrow_width/2, arrow_base_y, axis_origin_z + arrow_width/2,
            -arrow_width/2, arrow_base_y, axis_origin_z + arrow_width/2,
            0, arrow_tip_y, axis_origin_z,
            -arrow_width/2, arrow_base_y, axis_origin_z + arrow_width/2,
            -arrow_width/2, arrow_base_y, axis_origin_z - arrow_width/2,
            0, arrow_tip_y, axis_origin_z,
            arrow_width/2, arrow_base_y, axis_origin_z - arrow_width/2,
            arrow_width/2, arrow_base_y, axis_origin_z + arrow_width/2,
            0, arrow_tip_y, axis_origin_z,
        ], dtype='f4')
        y_arrow_norms = np.array([0, 0, -1] * 3 + [0, 0, 1] * 3 + [-1, 0, 0] * 3 + [1, 0, 0] * 3, dtype='f4')
        y_axis_verts = np.concatenate([y_shaft_verts, y_arrow_verts])
        y_axis_norms = np.concatenate([y_shaft_norms, y_arrow_norms])

        y_axis_vbo = self.ctx.buffer(y_axis_verts.tobytes())
        y_axis_nbo = self.ctx.buffer(y_axis_norms.tobytes())
        self.par_y_axis_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(y_axis_vbo, '3f', 'in_position'), (y_axis_nbo, '3f', 'in_normal')]
        )

        # Z-AXIS (Green)
        z_shaft_verts, z_shaft_norms = GeometryBuilder.create_box(
            axis_thickness, axis_thickness, axis_length,
            center=(0, 0, axis_origin_z + axis_length / 2)
        )
        arrow_tip_z = axis_origin_z + axis_length + arrow_length
        arrow_base_z = axis_origin_z + axis_length
        z_arrow_verts = np.array([
            -arrow_width/2, -arrow_width/2, arrow_base_z,
            arrow_width/2, -arrow_width/2, arrow_base_z,
            0, 0, arrow_tip_z,
            arrow_width/2, arrow_width/2, arrow_base_z,
            -arrow_width/2, arrow_width/2, arrow_base_z,
            0, 0, arrow_tip_z,
            -arrow_width/2, arrow_width/2, arrow_base_z,
            -arrow_width/2, -arrow_width/2, arrow_base_z,
            0, 0, arrow_tip_z,
            arrow_width/2, -arrow_width/2, arrow_base_z,
            arrow_width/2, arrow_width/2, arrow_base_z,
            0, 0, arrow_tip_z,
        ], dtype='f4')
        z_arrow_norms = np.array([0, -1, 0] * 3 + [0, 1, 0] * 3 + [-1, 0, 0] * 3 + [1, 0, 0] * 3, dtype='f4')
        z_axis_verts = np.concatenate([z_shaft_verts, z_arrow_verts])
        z_axis_norms = np.concatenate([z_shaft_norms, z_arrow_norms])

        z_axis_vbo = self.ctx.buffer(z_axis_verts.tobytes())
        z_axis_nbo = self.ctx.buffer(z_axis_norms.tobytes())
        self.par_z_axis_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(z_axis_vbo, '3f', 'in_position'), (z_axis_nbo, '3f', 'in_normal')]
        )

    def _create_wash_coordinate_axes(self, axis_origin_z: float):
        """Create coordinate axes for Wash fixture.

        Args:
            axis_origin_z: Z position for axis origin (top of fixture)
        """
        axis_length = 0.4
        axis_thickness = 0.008
        arrow_length = 0.06
        arrow_width = 0.04

        # X-AXIS (Red)
        x_shaft_verts, x_shaft_norms = GeometryBuilder.create_box(
            axis_length, axis_thickness, axis_thickness,
            center=(axis_length / 2, 0, axis_origin_z)
        )
        arrow_tip_x = axis_length + arrow_length
        arrow_base_x = axis_length
        x_arrow_verts = np.array([
            arrow_base_x, -arrow_width/2, axis_origin_z - arrow_width/2,
            arrow_base_x, arrow_width/2, axis_origin_z - arrow_width/2,
            arrow_tip_x, 0, axis_origin_z,
            arrow_base_x, arrow_width/2, axis_origin_z + arrow_width/2,
            arrow_base_x, -arrow_width/2, axis_origin_z + arrow_width/2,
            arrow_tip_x, 0, axis_origin_z,
            arrow_base_x, -arrow_width/2, axis_origin_z + arrow_width/2,
            arrow_base_x, -arrow_width/2, axis_origin_z - arrow_width/2,
            arrow_tip_x, 0, axis_origin_z,
            arrow_base_x, arrow_width/2, axis_origin_z - arrow_width/2,
            arrow_base_x, arrow_width/2, axis_origin_z + arrow_width/2,
            arrow_tip_x, 0, axis_origin_z,
        ], dtype='f4')
        x_arrow_norms = np.array([0, 0, -1] * 3 + [0, 0, 1] * 3 + [0, -1, 0] * 3 + [0, 1, 0] * 3, dtype='f4')
        x_axis_verts = np.concatenate([x_shaft_verts, x_arrow_verts])
        x_axis_norms = np.concatenate([x_shaft_norms, x_arrow_norms])

        x_axis_vbo = self.ctx.buffer(x_axis_verts.tobytes())
        x_axis_nbo = self.ctx.buffer(x_axis_norms.tobytes())
        self.wash_x_axis_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(x_axis_vbo, '3f', 'in_position'), (x_axis_nbo, '3f', 'in_normal')]
        )

        # Y-AXIS (Blue)
        y_shaft_verts, y_shaft_norms = GeometryBuilder.create_box(
            axis_thickness, axis_length, axis_thickness,
            center=(0, axis_length / 2, axis_origin_z)
        )
        arrow_tip_y = axis_length + arrow_length
        arrow_base_y = axis_length
        y_arrow_verts = np.array([
            -arrow_width/2, arrow_base_y, axis_origin_z - arrow_width/2,
            arrow_width/2, arrow_base_y, axis_origin_z - arrow_width/2,
            0, arrow_tip_y, axis_origin_z,
            arrow_width/2, arrow_base_y, axis_origin_z + arrow_width/2,
            -arrow_width/2, arrow_base_y, axis_origin_z + arrow_width/2,
            0, arrow_tip_y, axis_origin_z,
            -arrow_width/2, arrow_base_y, axis_origin_z + arrow_width/2,
            -arrow_width/2, arrow_base_y, axis_origin_z - arrow_width/2,
            0, arrow_tip_y, axis_origin_z,
            arrow_width/2, arrow_base_y, axis_origin_z - arrow_width/2,
            arrow_width/2, arrow_base_y, axis_origin_z + arrow_width/2,
            0, arrow_tip_y, axis_origin_z,
        ], dtype='f4')
        y_arrow_norms = np.array([0, 0, -1] * 3 + [0, 0, 1] * 3 + [-1, 0, 0] * 3 + [1, 0, 0] * 3, dtype='f4')
        y_axis_verts = np.concatenate([y_shaft_verts, y_arrow_verts])
        y_axis_norms = np.concatenate([y_shaft_norms, y_arrow_norms])

        y_axis_vbo = self.ctx.buffer(y_axis_verts.tobytes())
        y_axis_nbo = self.ctx.buffer(y_axis_norms.tobytes())
        self.wash_y_axis_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(y_axis_vbo, '3f', 'in_position'), (y_axis_nbo, '3f', 'in_normal')]
        )

        # Z-AXIS (Green)
        z_shaft_verts, z_shaft_norms = GeometryBuilder.create_box(
            axis_thickness, axis_thickness, axis_length,
            center=(0, 0, axis_origin_z + axis_length / 2)
        )
        arrow_tip_z = axis_origin_z + axis_length + arrow_length
        arrow_base_z = axis_origin_z + axis_length
        z_arrow_verts = np.array([
            -arrow_width/2, -arrow_width/2, arrow_base_z,
            arrow_width/2, -arrow_width/2, arrow_base_z,
            0, 0, arrow_tip_z,
            arrow_width/2, arrow_width/2, arrow_base_z,
            -arrow_width/2, arrow_width/2, arrow_base_z,
            0, 0, arrow_tip_z,
            -arrow_width/2, arrow_width/2, arrow_base_z,
            -arrow_width/2, -arrow_width/2, arrow_base_z,
            0, 0, arrow_tip_z,
            arrow_width/2, -arrow_width/2, arrow_base_z,
            arrow_width/2, arrow_width/2, arrow_base_z,
            0, 0, arrow_tip_z,
        ], dtype='f4')
        z_arrow_norms = np.array([0, -1, 0] * 3 + [0, 1, 0] * 3 + [-1, 0, 0] * 3 + [1, 0, 0] * 3, dtype='f4')
        z_axis_verts = np.concatenate([z_shaft_verts, z_arrow_verts])
        z_axis_norms = np.concatenate([z_shaft_norms, z_arrow_norms])

        z_axis_vbo = self.ctx.buffer(z_axis_verts.tobytes())
        z_axis_nbo = self.ctx.buffer(z_axis_norms.tobytes())
        self.wash_z_axis_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(z_axis_vbo, '3f', 'in_position'), (z_axis_nbo, '3f', 'in_normal')]
        )

    def _create_floor_geometry(self):
        """Create floor grid and back wall geometry."""
        vertex_shader = """
            #version 330
            uniform mat4 mvp;
            in vec3 in_position;
            in vec3 in_color;
            out vec3 v_color;
            void main() {
                gl_Position = mvp * vec4(in_position, 1.0);
                v_color = in_color;
            }
        """
        fragment_shader = """
            #version 330
            in vec3 v_color;
            out vec4 fragColor;
            void main() {
                fragColor = vec4(v_color, 0.5);
            }
        """
        self.floor_program = self.ctx.program(
            vertex_shader=vertex_shader,
            fragment_shader=fragment_shader
        )

        # Create floor grid lines
        vertices = []
        colors = []
        grid_size = 2.0
        grid_step = 0.5

        # Grid lines (gray)
        x = -grid_size
        while x <= grid_size + 0.01:
            vertices.extend([[x, 0, -grid_size], [x, 0, grid_size]])
            colors.extend([[0.4, 0.4, 0.4], [0.4, 0.4, 0.4]])
            vertices.extend([[-grid_size, 0, x], [grid_size, 0, x]])
            colors.extend([[0.4, 0.4, 0.4], [0.4, 0.4, 0.4]])
            x += grid_step

        vertices = np.array(vertices, dtype='f4').flatten()
        colors = np.array(colors, dtype='f4').flatten()

        vbo = self.ctx.buffer(vertices)
        cbo = self.ctx.buffer(colors)

        self.floor_vao = self.ctx.vertex_array(
            self.floor_program,
            [(vbo, '3f', 'in_position'), (cbo, '3f', 'in_color')]
        )
        self.floor_vertex_count = len(vertices) // 3

        # Create back wall (behind the fixture at z=-2)
        wall_shader_vert = """
            #version 330
            uniform mat4 mvp;
            in vec3 in_position;
            void main() {
                gl_Position = mvp * vec4(in_position, 1.0);
            }
        """
        wall_shader_frag = """
            #version 330
            out vec4 fragColor;
            void main() {
                fragColor = vec4(0.25, 0.25, 0.3, 0.6);
            }
        """
        self.wall_program = self.ctx.program(
            vertex_shader=wall_shader_vert,
            fragment_shader=wall_shader_frag
        )

        # Back wall quad (at z = -2, spanning x and y)
        wall_size = 2.0
        wall_height = 3.0
        wall_z = -2.0
        wall_verts = [
            [-wall_size, 0, wall_z], [wall_size, 0, wall_z],
            [wall_size, wall_height, wall_z], [-wall_size, wall_height, wall_z]
        ]
        wall_indices = [0, 1, 2, 0, 2, 3]

        wall_verts = np.array(wall_verts, dtype='f4').flatten()
        wall_indices = np.array(wall_indices, dtype='i4')

        wall_vbo = self.ctx.buffer(wall_verts)
        wall_ibo = self.ctx.buffer(wall_indices)

        self.wall_vao = self.ctx.vertex_array(
            self.wall_program,
            [(wall_vbo, '3f', 'in_position')],
            wall_ibo
        )

    def _create_axes_geometry(self):
        """Create coordinate axes geometry."""
        # Reuse floor program
        vertices = [
            # X axis (red)
            [0, 0, 0], [1, 0, 0],
            # Y axis (green)
            [0, 0, 0], [0, 1, 0],
            # Z axis (blue)
            [0, 0, 0], [0, 0, 1],
        ]
        colors = [
            [1, 0.3, 0.3], [1, 0.3, 0.3],  # Red
            [0.3, 1, 0.3], [0.3, 1, 0.3],  # Green
            [0.3, 0.3, 1], [0.3, 0.3, 1],  # Blue
        ]

        vertices = np.array(vertices, dtype='f4').flatten()
        colors = np.array(colors, dtype='f4').flatten()

        vbo = self.ctx.buffer(vertices)
        cbo = self.ctx.buffer(colors)

        self.axes_vao = self.ctx.vertex_array(
            self.floor_program,
            [(vbo, '3f', 'in_position'), (cbo, '3f', 'in_color')]
        )

    def _create_ring_geometry(self):
        """Create gimbal ring geometry."""
        # Create circle vertices for rings
        segments = 64
        self.ring_vertices = []
        for i in range(segments + 1):
            angle = 2 * math.pi * i / segments
            self.ring_vertices.append([math.cos(angle), math.sin(angle), 0])

        vertices = np.array(self.ring_vertices, dtype='f4').flatten()
        vbo = self.ctx.buffer(vertices)

        # Simple line program for rings
        vertex_shader = """
            #version 330
            uniform mat4 mvp;
            uniform mat4 ring_transform;
            in vec3 in_position;
            void main() {
                gl_Position = mvp * ring_transform * vec4(in_position, 1.0);
            }
        """
        fragment_shader = """
            #version 330
            uniform vec3 ring_color;
            out vec4 fragColor;
            void main() {
                fragColor = vec4(ring_color, 1.0);
            }
        """
        self.ring_program = self.ctx.program(
            vertex_shader=vertex_shader,
            fragment_shader=fragment_shader
        )

        self.ring_vao = self.ctx.vertex_array(
            self.ring_program,
            [(vbo, '3f', 'in_position')]
        )
        self.ring_vertex_count = segments + 1

    def _create_handle_geometry(self):
        """Create handle geometry (small boxes) for ring dragging."""
        # Create a small box for the handle
        handle_size = 0.06

        # Box vertices (centered at origin)
        s = handle_size / 2
        vertices = []
        normals = []

        # Front face
        vertices.extend([[-s, -s, s], [s, -s, s], [s, s, s], [-s, -s, s], [s, s, s], [-s, s, s]])
        normals.extend([[0, 0, 1]] * 6)
        # Back face
        vertices.extend([[s, -s, -s], [-s, -s, -s], [-s, s, -s], [s, -s, -s], [-s, s, -s], [s, s, -s]])
        normals.extend([[0, 0, -1]] * 6)
        # Top face
        vertices.extend([[-s, s, s], [s, s, s], [s, s, -s], [-s, s, s], [s, s, -s], [-s, s, -s]])
        normals.extend([[0, 1, 0]] * 6)
        # Bottom face
        vertices.extend([[-s, -s, -s], [s, -s, -s], [s, -s, s], [-s, -s, -s], [s, -s, s], [-s, -s, s]])
        normals.extend([[0, -1, 0]] * 6)
        # Right face
        vertices.extend([[s, -s, s], [s, -s, -s], [s, s, -s], [s, -s, s], [s, s, -s], [s, s, s]])
        normals.extend([[1, 0, 0]] * 6)
        # Left face
        vertices.extend([[-s, -s, -s], [-s, -s, s], [-s, s, s], [-s, -s, -s], [-s, s, s], [-s, s, -s]])
        normals.extend([[-1, 0, 0]] * 6)

        vertices = np.array(vertices, dtype='f4').flatten()
        normals = np.array(normals, dtype='f4').flatten()

        self.handle_vbo = self.ctx.buffer(vertices)
        self.handle_nbo = self.ctx.buffer(normals)
        self.handle_vao = self.ctx.vertex_array(
            self.fixture_program,
            [(self.handle_vbo, '3f', 'in_position'), (self.handle_nbo, '3f', 'in_normal')]
        )
        self.handle_vertex_count = len(vertices) // 3

    def set_orientation(self, mounting: str, yaw: float, pitch: float, roll: float):
        """Update the displayed orientation."""
        self.mounting = mounting
        self.yaw = yaw
        self.pitch = pitch
        self.roll = roll
        self.update()

    def get_fixture_transform(self) -> glm.mat4:
        """Get the fixture transformation matrix based on current orientation.

        Uses absolute yaw/pitch/roll values directly - no base rotation added.
        The preset values already contain the complete orientation.
        """
        # Start with identity
        transform = glm.mat4(1.0)

        # Apply rotations in order: Yaw (Y) -> Pitch (X) -> Roll (Z)
        # yaw, pitch, roll are now absolute world-space values

        # Apply yaw (rotation around Y axis - world up)
        transform = glm.rotate(transform, glm.radians(self.yaw), glm.vec3(0, 1, 0))
        # Apply pitch (rotation around X axis after yaw)
        transform = glm.rotate(transform, glm.radians(self.pitch), glm.vec3(1, 0, 0))
        # Apply roll (rotation around Z axis after pitch)
        transform = glm.rotate(transform, glm.radians(self.roll), glm.vec3(0, 0, 1))

        return transform

    def get_view_projection(self) -> glm.mat4:
        """Get the view-projection matrix."""
        # Camera position from spherical coordinates
        azimuth_rad = math.radians(self.camera_azimuth)
        elevation_rad = math.radians(self.camera_elevation)

        x = self.camera_distance * math.cos(elevation_rad) * math.sin(azimuth_rad)
        y = self.camera_distance * math.sin(elevation_rad)
        z = self.camera_distance * math.cos(elevation_rad) * math.cos(azimuth_rad)

        eye = glm.vec3(x, y, z)
        target = glm.vec3(0, 0.5, 0)  # Look at fixture center
        up = glm.vec3(0, 1, 0)

        view = glm.lookAt(eye, target, up)

        aspect = self.width() / max(self.height(), 1)
        projection = glm.perspective(glm.radians(45.0), aspect, 0.1, 100.0)

        return projection * view

    def resizeGL(self, width: int, height: int):
        """Handle resize."""
        pass  # Viewport set in paintGL

    def paintGL(self):
        """Render the scene."""
        if not self.ctx:
            return

        # Bind Qt's FBO
        qt_fbo_id = self.defaultFramebufferObject()
        self.ctx.fbo = self.ctx.detect_framebuffer(qt_fbo_id)
        self.ctx.fbo.use()
        self.ctx.viewport = (0, 0, self.width(), self.height())

        # Clear
        self.ctx.fbo.clear(0.15, 0.15, 0.18, 1.0)

        mvp = self.get_view_projection()
        fixture_transform = self.get_fixture_transform()

        # Render back wall first (behind everything)
        if hasattr(self, 'wall_vao') and self.wall_vao and self.wall_program:
            self.wall_program['mvp'].write(np.array(mvp.to_list(), dtype='f4').flatten().tobytes())
            self.wall_vao.render()

        # Render floor grid
        if self.floor_vao and self.floor_program:
            self.floor_program['mvp'].write(np.array(mvp.to_list(), dtype='f4').flatten().tobytes())
            self.floor_vao.render(moderngl.LINES)

        # Render gimbal rings
        self._render_gimbal_rings(mvp, fixture_transform)

        # Render fixture based on chassis (with sub-variant by fixture_type
        # within Chassis.BAR / Chassis.PAR — keeps SUNSTRIP / WASH visuals).
        if self.chassis is Chassis.MOVING_YOKE:
            self._render_moving_head(mvp, fixture_transform)
        elif self.chassis is Chassis.PAR:
            if self.fixture_type == "WASH":
                self._render_wash(mvp, fixture_transform)
            else:
                self._render_par(mvp, fixture_transform)
        elif self.chassis is Chassis.BAR:
            if self.fixture_type == "SUNSTRIP":
                self._render_sunstrip(mvp, fixture_transform)
            else:
                self._render_led_bar(mvp, fixture_transform)
        elif self.chassis is Chassis.PANEL:
            self._render_led_bar(mvp, fixture_transform)
        else:
            self._render_moving_head(mvp, fixture_transform)

        # Render beam direction indicator (cone pointing in Z direction)
        self._render_beam_indicator(mvp, fixture_transform)

    def _write_mvp_uniforms(self, mvp: glm.mat4, model: glm.mat4):
        """Helper to write MVP and model matrices to shader."""
        mvp_bytes = np.array([x for col in mvp.to_list() for x in col], dtype='f4').tobytes()
        model_bytes = np.array([x for col in model.to_list() for x in col], dtype='f4').tobytes()
        self.fixture_program['mvp'].write(mvp_bytes)
        self.fixture_program['model'].write(model_bytes)

    def _render_moving_head(self, mvp: glm.mat4, fixture_transform: glm.mat4):
        """Render moving head fixture (like visualizer).

        Uses Z-up coordinate system:
        - Base plate in X-Y plane, Z is up
        - Head positioned in Z direction (above base and yoke)
        - Lens faces +X direction
        """
        if not self.fixture_program:
            return

        body_color = self.body_color
        yoke_color = self.yoke_color

        # Render base
        if self.base_vao:
            base_mvp = mvp * fixture_transform
            self._write_mvp_uniforms(base_mvp, fixture_transform)
            self.fixture_program['base_color'].value = body_color
            self.fixture_program['emissive_color'].value = (0.0, 0.0, 0.0)
            self.fixture_program['emissive_strength'].value = 0.0
            self.base_vao.render()

        # Render indicator on base (red triangle)
        if self.indicator_vao:
            self.fixture_program['base_color'].value = (0.9, 0.2, 0.2)
            self.indicator_vao.render()

        # Render coordinate axes (X=Red, Y=Blue, Z=Green)
        if hasattr(self, 'mh_x_axis_vao') and self.mh_x_axis_vao:
            self.fixture_program['base_color'].value = (0.9, 0.2, 0.2)  # Red
            self.mh_x_axis_vao.render()
        if hasattr(self, 'mh_y_axis_vao') and self.mh_y_axis_vao:
            self.fixture_program['base_color'].value = (0.2, 0.4, 0.9)  # Blue
            self.mh_y_axis_vao.render()
        if hasattr(self, 'mh_z_axis_vao') and self.mh_z_axis_vao:
            self.fixture_program['base_color'].value = (0.2, 0.8, 0.2)  # Green
            self.mh_z_axis_vao.render()

        # Render yoke
        if self.yoke_vao:
            self.fixture_program['base_color'].value = yoke_color
            self.yoke_vao.render()

        # Render head (positioned in Z direction)
        if self.head_vao:
            # Head is positioned at yoke height (Z direction)
            base_thickness = getattr(self, 'mh_base_thickness', 0.04)
            yoke_height = getattr(self, 'mh_yoke_height', 0.2)
            head_z = base_thickness + yoke_height / 2
            head_translate = glm.translate(glm.mat4(1.0), glm.vec3(0, 0, head_z))
            head_model = fixture_transform * head_translate
            head_mvp = mvp * head_model

            self._write_mvp_uniforms(head_mvp, head_model)
            self.fixture_program['base_color'].value = body_color
            self.head_vao.render()

            # Render lens with emissive (white glow)
            if self.lens_vao:
                self.fixture_program['base_color'].value = (0.2, 0.2, 0.2)
                self.fixture_program['emissive_color'].value = (1.0, 1.0, 1.0)
                self.fixture_program['emissive_strength'].value = 0.5
                self.lens_vao.render()

    def _render_par(self, mvp: glm.mat4, fixture_transform: glm.mat4):
        """Render PAR can fixture.

        Geometry already has lens facing +Z per reference.md.
        No additional rotation needed.
        """
        if not self.fixture_program:
            return

        body_color = self.body_color
        fixture_mvp = mvp * fixture_transform

        self._write_mvp_uniforms(fixture_mvp, fixture_transform)
        self.fixture_program['base_color'].value = body_color
        self.fixture_program['emissive_color'].value = (0.0, 0.0, 0.0)
        self.fixture_program['emissive_strength'].value = 0.0

        if self.fixture_vao:
            self.fixture_vao.render()

        # Render coordinate axes (X=Red, Y=Blue, Z=Green)
        if hasattr(self, 'par_x_axis_vao') and self.par_x_axis_vao:
            self.fixture_program['base_color'].value = (0.9, 0.2, 0.2)
            self.par_x_axis_vao.render()
        if hasattr(self, 'par_y_axis_vao') and self.par_y_axis_vao:
            self.fixture_program['base_color'].value = (0.2, 0.4, 0.9)
            self.par_y_axis_vao.render()
        if hasattr(self, 'par_z_axis_vao') and self.par_z_axis_vao:
            self.fixture_program['base_color'].value = (0.2, 0.8, 0.2)
            self.par_z_axis_vao.render()

        # Render lens with emissive
        if self.lens_vao:
            self.fixture_program['base_color'].value = (0.15, 0.15, 0.15)
            self.fixture_program['emissive_color'].value = (1.0, 0.9, 0.8)
            self.fixture_program['emissive_strength'].value = 0.4
            self.lens_vao.render()

    def _render_led_bar(self, mvp: glm.mat4, fixture_transform: glm.mat4):
        """Render LED bar fixture with segments."""
        if not self.fixture_program:
            return

        body_color = self.body_color
        fixture_mvp = mvp * fixture_transform

        self._write_mvp_uniforms(fixture_mvp, fixture_transform)
        self.fixture_program['base_color'].value = body_color
        self.fixture_program['emissive_color'].value = (0.0, 0.0, 0.0)
        self.fixture_program['emissive_strength'].value = 0.0

        # Render body
        if self.fixture_vao:
            self.fixture_vao.render()

        # Render LED segments with emissive color
        if self.segment_vao:
            self.fixture_program['base_color'].value = (0.1, 0.1, 0.1)
            self.fixture_program['emissive_color'].value = (0.8, 0.9, 1.0)
            self.fixture_program['emissive_strength'].value = 0.6
            self.segment_vao.render()

        # Render front indicator
        if self.indicator_vao:
            self.fixture_program['base_color'].value = (0.9, 0.2, 0.2)
            self.fixture_program['emissive_color'].value = (0.0, 0.0, 0.0)
            self.fixture_program['emissive_strength'].value = 0.0
            self.indicator_vao.render()

        # Render coordinate axes (X=Red, Y=Blue, Z=Green)
        if hasattr(self, 'bar_x_axis_vao') and self.bar_x_axis_vao:
            self.fixture_program['base_color'].value = (0.9, 0.2, 0.2)
            self.bar_x_axis_vao.render()
        if hasattr(self, 'bar_y_axis_vao') and self.bar_y_axis_vao:
            self.fixture_program['base_color'].value = (0.2, 0.4, 0.9)
            self.bar_y_axis_vao.render()
        if hasattr(self, 'bar_z_axis_vao') and self.bar_z_axis_vao:
            self.fixture_program['base_color'].value = (0.2, 0.8, 0.2)
            self.bar_z_axis_vao.render()

    def _render_sunstrip(self, mvp: glm.mat4, fixture_transform: glm.mat4):
        """Render sunstrip fixture with lamp bulbs.

        Lamps face +Z (up) per reference.md.
        """
        if not self.fixture_program:
            return

        body_color = self.body_color
        fixture_mvp = mvp * fixture_transform

        self._write_mvp_uniforms(fixture_mvp, fixture_transform)
        self.fixture_program['base_color'].value = body_color
        self.fixture_program['emissive_color'].value = (0.0, 0.0, 0.0)
        self.fixture_program['emissive_strength'].value = 0.0

        # Render body
        if self.fixture_vao:
            self.fixture_vao.render()

        # Render coordinate axes (X=Red, Y=Blue, Z=Green)
        if hasattr(self, 'bar_x_axis_vao') and self.bar_x_axis_vao:
            self.fixture_program['base_color'].value = (0.9, 0.2, 0.2)
            self.bar_x_axis_vao.render()
        if hasattr(self, 'bar_y_axis_vao') and self.bar_y_axis_vao:
            self.fixture_program['base_color'].value = (0.2, 0.4, 0.9)
            self.bar_y_axis_vao.render()
        if hasattr(self, 'bar_z_axis_vao') and self.bar_z_axis_vao:
            self.fixture_program['base_color'].value = (0.2, 0.8, 0.2)
            self.bar_z_axis_vao.render()

        # Render lamp bulbs with warm white emissive
        if self.lamp_vao:
            self.fixture_program['base_color'].value = (0.9, 0.85, 0.7)
            self.fixture_program['emissive_color'].value = (1.0, 0.85, 0.6)
            self.fixture_program['emissive_strength'].value = 0.8
            self.lamp_vao.render()

    def _render_wash(self, mvp: glm.mat4, fixture_transform: glm.mat4):
        """Render wash fixture.

        Lens faces +Z (up) per reference.md.
        """
        if not self.fixture_program:
            return

        body_color = self.body_color
        fixture_mvp = mvp * fixture_transform

        self._write_mvp_uniforms(fixture_mvp, fixture_transform)
        self.fixture_program['base_color'].value = body_color
        self.fixture_program['emissive_color'].value = (0.0, 0.0, 0.0)
        self.fixture_program['emissive_strength'].value = 0.0

        # Render body
        if self.fixture_vao:
            self.fixture_vao.render()

        # Render coordinate axes (X=Red, Y=Blue, Z=Green)
        if hasattr(self, 'wash_x_axis_vao') and self.wash_x_axis_vao:
            self.fixture_program['base_color'].value = (0.9, 0.2, 0.2)
            self.wash_x_axis_vao.render()
        if hasattr(self, 'wash_y_axis_vao') and self.wash_y_axis_vao:
            self.fixture_program['base_color'].value = (0.2, 0.4, 0.9)
            self.wash_y_axis_vao.render()
        if hasattr(self, 'wash_z_axis_vao') and self.wash_z_axis_vao:
            self.fixture_program['base_color'].value = (0.2, 0.8, 0.2)
            self.wash_z_axis_vao.render()

        # Render lens with emissive color
        if self.lens_vao:
            self.fixture_program['base_color'].value = (0.15, 0.15, 0.15)
            self.fixture_program['emissive_color'].value = (0.9, 0.95, 1.0)
            self.fixture_program['emissive_strength'].value = 0.5
            self.lens_vao.render()

    def _render_gimbal_rings(self, mvp: glm.mat4, fixture_transform: glm.mat4):
        """Render the gimbal rings around the fixture with handles."""
        if not self.ring_vao or not self.ring_program:
            return

        ring_radius = 0.6

        # Helper to write matrix to ring program
        def write_ring_mvp(m):
            mvp_bytes = np.array([x for col in m.to_list() for x in col], dtype='f4').tobytes()
            self.ring_program['mvp'].write(mvp_bytes)

        def write_ring_transform(m):
            t_bytes = np.array([x for col in m.to_list() for x in col], dtype='f4').tobytes()
            self.ring_program['ring_transform'].write(t_bytes)

        # Yaw ring (blue) - around Y axis
        yaw_transform = glm.scale(glm.mat4(1.0), glm.vec3(ring_radius))
        yaw_transform = glm.rotate(glm.mat4(1.0), glm.radians(90), glm.vec3(1, 0, 0)) * yaw_transform
        write_ring_mvp(mvp)
        write_ring_transform(yaw_transform)
        self.ring_program['ring_color'].value = (0.3, 0.3, 1.0)
        self.ctx.line_width = 2.0
        self.ring_vao.render(moderngl.LINE_STRIP)

        # Pitch ring (green) - around X axis after yaw
        pitch_base = glm.rotate(glm.mat4(1.0), glm.radians(self.yaw), glm.vec3(0, 1, 0))
        pitch_transform = pitch_base * glm.rotate(glm.mat4(1.0), glm.radians(90), glm.vec3(0, 1, 0))
        pitch_transform = pitch_transform * glm.scale(glm.mat4(1.0), glm.vec3(ring_radius * 0.9))
        write_ring_transform(pitch_transform)
        self.ring_program['ring_color'].value = (0.3, 1.0, 0.3)
        self.ring_vao.render(moderngl.LINE_STRIP)

        # Roll ring (red) - around Z axis after yaw and pitch
        roll_transform = fixture_transform * glm.scale(glm.mat4(1.0), glm.vec3(ring_radius * 0.8))
        write_ring_transform(roll_transform)
        self.ring_program['ring_color'].value = (1.0, 0.3, 0.3)
        self.ring_vao.render(moderngl.LINE_STRIP)

        # Render handles on each ring
        self._render_ring_handles(mvp, fixture_transform, ring_radius)

    def _render_ring_handles(self, mvp: glm.mat4, fixture_transform: glm.mat4, ring_radius: float):
        """Render draggable handles on each gimbal ring that rotate with the ring."""
        if not self.handle_vao or not self.fixture_program:
            return

        # Reset emissive for handles
        self.fixture_program['emissive_color'].value = (0.0, 0.0, 0.0)
        self.fixture_program['emissive_strength'].value = 0.0

        # Yaw handle (blue) - rotates around Y axis with current yaw
        # The yaw ring is horizontal (XZ plane), handle starts at front and rotates with yaw
        yaw_angle_rad = math.radians(self.yaw)
        yaw_handle_pos = glm.vec3(
            ring_radius * math.sin(yaw_angle_rad),
            0,
            ring_radius * math.cos(yaw_angle_rad)
        )
        yaw_handle_transform = glm.translate(glm.mat4(1.0), yaw_handle_pos)
        yaw_handle_mvp = mvp * yaw_handle_transform
        self._write_mvp_uniforms(yaw_handle_mvp, yaw_handle_transform)
        self.fixture_program['base_color'].value = (0.4, 0.4, 1.0)
        self.handle_vao.render()

        # Pitch handle (green) - on pitch ring which is rotated by yaw, handle rotates with pitch
        # Pitch ring is vertical (YZ plane after yaw rotation), handle moves with pitch angle
        pitch_ring_radius = ring_radius * 0.9
        pitch_angle_rad = math.radians(self.pitch)
        # Handle position in pitch ring's local space (ring is in YZ plane)
        pitch_handle_local = glm.vec3(
            0,
            pitch_ring_radius * math.cos(pitch_angle_rad),
            pitch_ring_radius * math.sin(pitch_angle_rad)
        )
        # Apply yaw rotation to get world position
        pitch_ring_base = glm.rotate(glm.mat4(1.0), glm.radians(self.yaw), glm.vec3(0, 1, 0))
        pitch_handle_transform = pitch_ring_base * glm.translate(glm.mat4(1.0), pitch_handle_local)
        pitch_handle_mvp = mvp * pitch_handle_transform
        self._write_mvp_uniforms(pitch_handle_mvp, pitch_handle_transform)
        self.fixture_program['base_color'].value = (0.4, 1.0, 0.4)
        self.handle_vao.render()

        # Roll handle (red) - on roll ring which follows full orientation, handle rotates with roll
        roll_ring_radius = ring_radius * 0.8
        roll_angle_rad = math.radians(self.roll)
        # Handle position in roll ring's local space (ring is in XY plane after all rotations)
        roll_handle_local = glm.vec3(
            roll_ring_radius * math.cos(roll_angle_rad),
            roll_ring_radius * math.sin(roll_angle_rad),
            0
        )
        roll_handle_transform = fixture_transform * glm.translate(glm.mat4(1.0), roll_handle_local)
        roll_handle_mvp = mvp * roll_handle_transform
        self._write_mvp_uniforms(roll_handle_mvp, roll_handle_transform)
        self.fixture_program['base_color'].value = (1.0, 0.4, 0.4)
        self.handle_vao.render()

    def _render_beam_indicator(self, mvp: glm.mat4, fixture_transform: glm.mat4):
        """Render a line showing beam direction."""
        if not self.axes_vao or not self.floor_program:
            return

        # Transform for beam direction (local Z axis)
        beam_transform = fixture_transform * glm.scale(glm.mat4(1.0), glm.vec3(0.8))
        beam_mvp = mvp * beam_transform

        self.floor_program['mvp'].write(np.array(beam_mvp.to_list(), dtype='f4').flatten().tobytes())

        # Only render Z axis (beam direction) with yellow color
        vertices = np.array([[0, 0, 0], [0, 0, 1]], dtype='f4').flatten()
        colors = np.array([[1, 1, 0], [1, 1, 0]], dtype='f4').flatten()

        vbo = self.ctx.buffer(vertices)
        cbo = self.ctx.buffer(colors)

        beam_vao = self.ctx.vertex_array(
            self.floor_program,
            [(vbo, '3f', 'in_position'), (cbo, '3f', 'in_color')]
        )
        self.ctx.line_width = 3.0
        beam_vao.render(moderngl.LINES)
        beam_vao.release()
        vbo.release()
        cbo.release()

    def _get_ring_at_position(self, pos) -> Optional[str]:
        """
        Detect which ring (if any) is at the given screen position.
        Returns 'yaw', 'pitch', 'roll', or None.
        """
        if not self.ctx:
            return None

        # Get normalized device coordinates
        x = (2.0 * pos.x() / self.width()) - 1.0
        y = 1.0 - (2.0 * pos.y() / self.height())

        # Get view-projection matrix for unprojecting
        vp = self.get_view_projection()
        vp_inv = glm.inverse(vp)

        # Create ray from camera through the click point
        near_point = vp_inv * glm.vec4(x, y, -1.0, 1.0)
        far_point = vp_inv * glm.vec4(x, y, 1.0, 1.0)

        near_point = glm.vec3(near_point) / near_point.w
        far_point = glm.vec3(far_point) / far_point.w

        ray_dir = glm.normalize(far_point - near_point)
        ray_origin = near_point

        # Check each ring for intersection (approximate with torus check)
        ring_radius = 0.6
        ring_thickness = 0.08  # How close to ring counts as hit

        # Yaw ring (blue) - horizontal ring around Y axis at y=0
        dist_to_yaw = self._distance_to_ring(ray_origin, ray_dir, glm.vec3(0, 1, 0), ring_radius)
        if dist_to_yaw < ring_thickness:
            return 'yaw'

        # Pitch ring (green) - rotated based on current yaw
        pitch_axis = glm.vec3(math.cos(math.radians(self.yaw)), 0, -math.sin(math.radians(self.yaw)))
        dist_to_pitch = self._distance_to_ring(ray_origin, ray_dir, pitch_axis, ring_radius * 0.9)
        if dist_to_pitch < ring_thickness:
            return 'pitch'

        # Roll ring (red) - follows full fixture orientation
        fixture_transform = self.get_fixture_transform()
        roll_axis = glm.vec3(fixture_transform * glm.vec4(0, 0, 1, 0))
        dist_to_roll = self._distance_to_ring(ray_origin, ray_dir, roll_axis, ring_radius * 0.8)
        if dist_to_roll < ring_thickness:
            return 'roll'

        return None

    def _distance_to_ring(self, ray_origin: glm.vec3, ray_dir: glm.vec3,
                          ring_normal: glm.vec3, ring_radius: float) -> float:
        """Calculate approximate distance from ray to ring."""
        # Find where ray intersects the plane of the ring
        denom = glm.dot(ring_normal, ray_dir)
        if abs(denom) < 0.001:
            return float('inf')

        t = -glm.dot(ring_normal, ray_origin) / denom
        if t < 0:
            return float('inf')

        # Point on plane
        point = ray_origin + ray_dir * t

        # Distance from point to ring (distance from circle in plane)
        dist_from_center = glm.length(point)
        return abs(dist_from_center - ring_radius)

    def mousePressEvent(self, event):
        """Handle mouse press for camera control or ring dragging."""
        self.last_mouse_pos = event.position()
        self.mouse_button = event.button()

        if event.button() == Qt.MouseButton.LeftButton:
            # Check if clicking on a ring
            ring = self._get_ring_at_position(event.position())
            if ring:
                self.dragging_ring = ring
                self.drag_start_angle = getattr(self, ring, 0.0)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            else:
                self.dragging_ring = None

    def mouseReleaseEvent(self, event):
        """Handle mouse release."""
        if self.dragging_ring:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self.last_mouse_pos = None
        self.mouse_button = None
        self.dragging_ring = None

    def mouseMoveEvent(self, event):
        """Handle mouse move for camera orbit or ring dragging."""
        if self.last_mouse_pos is None:
            # Update cursor when hovering over rings
            ring = self._get_ring_at_position(event.position())
            if ring:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        pos = event.position()
        delta_x = pos.x() - self.last_mouse_pos.x()
        delta_y = pos.y() - self.last_mouse_pos.y()

        if self.dragging_ring:
            # Ring dragging - use horizontal mouse movement for angle change
            angle_delta = delta_x * 0.5  # Sensitivity

            if self.dragging_ring == 'yaw':
                self.yaw = max(-180, min(180, self.yaw + angle_delta))
            elif self.dragging_ring == 'pitch':
                self.pitch = max(-90, min(90, self.pitch + angle_delta))
            elif self.dragging_ring == 'roll':
                self.roll = max(-180, min(180, self.roll + angle_delta))

            # Emit signal to update spin boxes
            self.orientation_changed.emit(self.yaw, self.pitch, self.roll)

        elif self.mouse_button == Qt.MouseButton.LeftButton:
            # Orbit camera
            self.camera_azimuth -= delta_x * 0.5
            self.camera_elevation += delta_y * 0.5
            self.camera_elevation = max(5, min(85, self.camera_elevation))

        elif self.mouse_button == Qt.MouseButton.RightButton:
            # Zoom
            self.camera_distance += delta_y * 0.02
            self.camera_distance = max(2, min(10, self.camera_distance))

        self.last_mouse_pos = pos
        self.update()

    def wheelEvent(self, event):
        """Handle scroll for zoom."""
        delta = event.angleDelta().y() / 120.0
        self.camera_distance -= delta * 0.3
        self.camera_distance = max(2, min(10, self.camera_distance))
        self.update()

    def cleanup(self):
        """Release resources."""
        self.render_timer.stop()
        # Release fixture VAOs
        self._release_fixture_vaos()
        if self.ctx:
            self.ctx.release()
            self.ctx = None


class OrientationPanel(QWidget):
    """Embeddable orientation editor — preview + presets + fine adjustment.

    Shared by the legacy ``OrientationDialog`` (which wraps it with Cancel/
    Apply buttons) and the Stage tab's persistent inline panel (which uses
    it directly and writes through on accept). Calling code can re-bind the
    panel to a different fixture selection via :meth:`set_fixtures`.

    Emits :attr:`values_changed` whenever the user changes any orientation
    value via spinbox edits, gimbal drag, or preset clicks. Inline embedders
    (Stage tab) listen on this signal to push the new values back to the
    selected fixtures live; the modal dialog ignores it and writes back on
    Apply only.
    """

    values_changed = pyqtSignal()

    # Mounting preset definitions
    PRESETS = {
        'hanging': {'label': 'Hanging', 'tooltip': 'Fixture hanging from truss, beam pointing down'},
        'standing': {'label': 'Standing', 'tooltip': 'Fixture on floor, beam pointing up'},
        'wall_left': {'label': 'Wall-L', 'tooltip': 'Mounted on stage-left wall'},
        'wall_right': {'label': 'Wall-R', 'tooltip': 'Mounted on stage-right wall'},
        'wall_back': {'label': 'Wall-Back', 'tooltip': 'Mounted on back wall, beam toward audience'},
        'wall_front': {'label': 'Wall-Front', 'tooltip': 'Mounted facing audience, beam toward back'},
        'custom': {'label': 'Custom', 'tooltip': 'Custom orientation (manually adjusted)'},
    }

    # Absolute orientation values for each preset (yaw, pitch, roll)
    # These are the actual world-space angles, not relative adjustments
    PRESET_VALUES = {
        'hanging': (0.0, 90.0, 0.0),      # Beam pointing down (-Z world)
        'standing': (0.0, -90.0, 0.0),    # Beam pointing up (+Z world)
        'wall_left': (-90.0, 0.0, 0.0),   # Beam pointing stage-right (+X world)
        'wall_right': (90.0, 0.0, 0.0),   # Beam pointing stage-left (-X world)
        'wall_back': (0.0, 0.0, 0.0),     # Beam pointing toward audience (-Y world)
        'wall_front': (180.0, 0.0, 0.0),  # Beam pointing toward back (+Y world)
        'custom': None,  # No predefined values for custom
    }

    def __init__(self, fixtures: List, config=None, parent=None):
        """
        Args:
            fixtures: List of FixtureItem objects to configure (may be empty
                      when constructed by an inline embedder; call
                      :meth:`set_fixtures` later).
            config: Configuration object for group lookups
            parent: Parent widget
        """
        super().__init__(parent)
        self.fixtures = fixtures
        self.config = config

        self._setup_ui()
        self._connect_signals()
        if fixtures:
            self._load_initial_values()
        else:
            # Inline embedders (Stage tab) start with no selection.
            self._set_inputs_enabled(False)

    def _setup_ui(self):
        """Set up the panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Info label — kept as an instance attribute so set_fixtures can
        # update it when the embedder re-binds the panel to a new selection.
        self.info_label = QLabel(self._format_info_text(self.fixtures))
        self.info_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(self.info_label)

        # 3D Preview. Kept as an instance attribute so an embedder can hide
        # it: the Stage tab already shows a live 3D visualizer at the top of
        # the same column, so a second preview here is redundant and only
        # steals vertical space from the presets and fine-adjustment
        # controls. The standalone modal keeps it visible.
        self.preview_group = QGroupBox("3D Preview")
        preview_layout = QVBoxLayout(self.preview_group)
        # The theme's QGroupBox only reserves top padding for the title, so
        # the GL widget would otherwise render flush against (and appear to
        # overlap) the border. Inset it. Top margin 0 because the theme
        # already adds 8px padding-top; that balances the 8px bottom margin
        # so the preview has equal top and bottom insets.
        preview_layout.setContentsMargins(8, 0, 8, 8)
        self.preview_widget = OrientationPreviewWidget()
        preview_layout.addWidget(self.preview_widget)
        layout.addWidget(self.preview_group, stretch=1)

        # Presets + Fine Adjustment live side-by-side in one row to share
        # vertical space with the 3D preview above. Otherwise the panel
        # would either consume most of the right-column height or
        # squeeze the preview down to nothing.
        body_row = QHBoxLayout()
        body_row.setSpacing(6)

        # Presets — 6 mounting presets in a 3 rows x 2 cols block, with
        # Custom on a 4th row spanning both columns. Custom is the
        # "this doesn't match a preset" indicator and reads naturally
        # as a wide bottom button.
        presets_group = QGroupBox("Presets")
        presets_layout = QGridLayout(presets_group)
        presets_layout.setHorizontalSpacing(4)
        presets_layout.setVerticalSpacing(4)

        # Order intentional: mounting pairs read top-to-bottom.
        named_presets = ["hanging", "standing", "wall_left", "wall_right",
                         "wall_back", "wall_front"]
        self.preset_buttons = {}
        for index, preset_id in enumerate(named_presets):
            preset_info = self.PRESETS[preset_id]
            btn = QPushButton(preset_info['label'])
            btn.setToolTip(preset_info['tooltip'])
            btn.setCheckable(True)
            btn.setMaximumWidth(84)
            # Trim the theme's 14px horizontal button padding so the longest
            # labels ("Wall-Front") fit the narrow two-column preset grid
            # without clipping.
            btn.setStyleSheet("padding: 5px 3px;")
            btn.clicked.connect(lambda checked, p=preset_id: self._on_preset_clicked(p))
            row, col = divmod(index, 2)
            presets_layout.addWidget(btn, row, col)
            self.preset_buttons[preset_id] = btn

        custom_btn = QPushButton(self.PRESETS['custom']['label'])
        custom_btn.setToolTip(self.PRESETS['custom']['tooltip'])
        custom_btn.setCheckable(True)
        custom_btn.clicked.connect(lambda checked: self._on_preset_clicked('custom'))
        # Span both columns at the bottom — visually marks Custom as the
        # "no match" state, distinct from the 6 named presets above it.
        presets_layout.addWidget(custom_btn, 3, 0, 1, 2)
        self.preset_buttons['custom'] = custom_btn

        body_row.addWidget(presets_group)

        # Fine adjustment — single QGridLayout so all four axis rows share
        # the same column widths (label / spinbox / +90 button / stretch).
        # Earlier per-row QHBoxLayouts let columns drift between rows,
        # especially the Z-Height row that has no +90 button.
        # Apply-to-group lives at the bottom of this same grid spanning
        # every column, so the panel reads as a single block instead of
        # leaving an orphan checkbox below.
        adjust_group = QGroupBox("Fine Adjustment")
        adjust_layout = QGridLayout(adjust_group)
        adjust_layout.setHorizontalSpacing(4)
        adjust_layout.setVerticalSpacing(4)

        def _add_axis_row(row_index, label_text, spin, rotate_btn=None):
            label = QLabel(label_text)
            label.setStyleSheet("font-weight: bold;")
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            adjust_layout.addWidget(label, row_index, 0)
            # Cap width tightly: the spinbox min-size-hint (arrows + suffix)
            # otherwise drives this group past the two-column budget for the
            # Stage tab's right inspector. 64px still shows "-180°".
            spin.setMaximumWidth(64)
            spin.setMinimumWidth(1)
            adjust_layout.addWidget(spin, row_index, 1)
            if rotate_btn is not None:
                # Override the theme's default 6px/14px button padding so the
                # +90° text fits inside the narrow button without clipping.
                rotate_btn.setMinimumWidth(1)
                rotate_btn.setMaximumWidth(46)
                rotate_btn.setStyleSheet(rotate_btn.styleSheet() + " padding: 4px 2px;")
                adjust_layout.addWidget(rotate_btn, row_index, 2)

        # Yaw
        self.yaw_spin = QDoubleSpinBox()
        self.yaw_spin.setRange(-180, 180)
        self.yaw_spin.setSuffix("°")
        self.yaw_spin.setSingleStep(5)
        self.yaw_spin.setToolTip("Rotation around vertical axis (blue ring)")
        self.yaw_90_btn = QPushButton("+90°")
        self.yaw_90_btn.setToolTip("Rotate yaw by +90°")
        self.yaw_90_btn.setStyleSheet(
            "background-color: #4466CC; color: white; font-weight: bold; "
            "padding: 4px 6px;"
        )
        self.yaw_90_btn.clicked.connect(lambda: self._rotate_by_90('yaw'))
        _add_axis_row(0, "Yaw:", self.yaw_spin, self.yaw_90_btn)

        # Pitch
        self.pitch_spin = QDoubleSpinBox()
        self.pitch_spin.setRange(-90, 90)
        self.pitch_spin.setSuffix("°")
        self.pitch_spin.setSingleStep(5)
        self.pitch_spin.setToolTip("Tilt angle (green ring)")
        self.pitch_90_btn = QPushButton("+90°")
        self.pitch_90_btn.setToolTip("Rotate pitch by +90°")
        self.pitch_90_btn.setStyleSheet(
            "background-color: #44AA44; color: white; font-weight: bold; "
            "padding: 4px 6px;"
        )
        self.pitch_90_btn.clicked.connect(lambda: self._rotate_by_90('pitch'))
        _add_axis_row(1, "Pitch:", self.pitch_spin, self.pitch_90_btn)

        # Roll
        self.roll_spin = QDoubleSpinBox()
        self.roll_spin.setRange(-180, 180)
        self.roll_spin.setSuffix("°")
        self.roll_spin.setSingleStep(5)
        self.roll_spin.setToolTip("Rotation around beam axis (red ring)")
        self.roll_90_btn = QPushButton("+90°")
        self.roll_90_btn.setToolTip("Rotate roll by +90°")
        self.roll_90_btn.setStyleSheet(
            "background-color: #CC4444; color: white; font-weight: bold; "
            "padding: 4px 6px;"
        )
        self.roll_90_btn.clicked.connect(lambda: self._rotate_by_90('roll'))
        _add_axis_row(2, "Roll:", self.roll_spin, self.roll_90_btn)

        # Z-height (no rotate button — column 2 stays empty for that row)
        self.z_spin = QDoubleSpinBox()
        self.z_spin.setRange(0, 50)
        self.z_spin.setSuffix(" m")
        self.z_spin.setSingleStep(0.1)
        self.z_spin.setDecimals(2)
        self.z_spin.setToolTip("Height above stage floor")
        _add_axis_row(3, "Z-Height:", self.z_spin)

        # Trailing stretch column absorbs any leftover horizontal space so
        # spinboxes don't get pushed wide and rows align cell-for-cell.
        adjust_layout.setColumnStretch(0, 0)
        adjust_layout.setColumnStretch(1, 0)
        adjust_layout.setColumnStretch(2, 0)
        adjust_layout.setColumnStretch(3, 1)

        body_row.addWidget(adjust_group)

        # Two sub-panels only in the horizontal strip. A former third
        # column (Group Defaults) pushed the body past the inspector width
        # so the preset buttons ran off the right edge and needed a
        # horizontal scrollbar to reach. Presets + Fine Adjustment fit the
        # right column; the apply-to-group control drops to its own row.
        layout.addLayout(body_row)

        # Group Defaults — a full-width row directly beneath the two
        # sub-panels. Below (rather than beside) it always has room for
        # the indicator and label, and reads naturally as "this applies to
        # the whole selection", which is what the checkbox does.
        group_defaults_group = QGroupBox("Group Defaults")
        gd_layout = QVBoxLayout(group_defaults_group)
        self.apply_to_group_checkbox = QCheckBox("Apply to group default")
        self.apply_to_group_checkbox.setToolTip(
            "If checked, also updates the group's default orientation"
        )
        gd_layout.addWidget(self.apply_to_group_checkbox)
        self._refresh_apply_to_group(self.fixtures)

        layout.addWidget(group_defaults_group)

    @staticmethod
    def _format_info_text(fixtures: list) -> str:
        if not fixtures:
            return "No fixture selected"
        if len(fixtures) == 1:
            return f"Fixture: {fixtures[0].fixture_name}"
        return f"Editing {len(fixtures)} fixtures"

    def _refresh_apply_to_group(self, fixtures: list) -> None:
        """Enable the apply-to-group checkbox only when every selected
        fixture belongs to the same group. Updates the label accordingly.

        ``FixtureItem`` instances (the StageView's graphics items) don't
        carry a ``group`` attribute directly; they only know their
        ``fixture_name``. Resolve via ``self.config`` so the checkbox
        actually becomes clickable when a grouped fixture is selected.
        """
        groups: set = set()
        for fx in fixtures:
            group_name = getattr(fx, "group", None)
            if not group_name and self.config is not None:
                fx_name = getattr(fx, "fixture_name", None) or getattr(fx, "name", None)
                if fx_name:
                    cf = next(
                        (cf for cf in self.config.fixtures if cf.name == fx_name),
                        None,
                    )
                    if cf is not None:
                        group_name = cf.group
            if group_name:
                groups.add(group_name)

        if len(groups) == 1:
            self.apply_to_group_checkbox.setEnabled(True)
            self.apply_to_group_checkbox.setText(
                f"Apply to group default ({next(iter(groups))})"
            )
        else:
            self.apply_to_group_checkbox.setEnabled(False)
            self.apply_to_group_checkbox.setChecked(False)
            self.apply_to_group_checkbox.setText("Apply to group default")

    def set_fixtures(self, fixtures: list) -> None:
        """Re-bind the panel to a new selection without rebuilding widgets.

        Refreshes the info label, the apply-to-group checkbox, and reloads
        the orientation spinboxes / preset selection from the first fixture.
        When ``fixtures`` is empty (typical for the Stage tab when nothing
        is selected on the 2D view), every input is disabled so values
        can't be changed accidentally and the panel reads "No fixture
        selected".
        """
        self.fixtures = fixtures
        self.info_label.setText(self._format_info_text(fixtures))
        self._refresh_apply_to_group(fixtures)
        self._set_inputs_enabled(bool(fixtures))
        if fixtures:
            self._load_initial_values()

    def _set_inputs_enabled(self, enabled: bool) -> None:
        """Toggle interactivity for every editing surface on the panel.

        The apply-to-group checkbox has its own enable rule (only when all
        selected fixtures share a group); ``_refresh_apply_to_group`` runs
        after this and may override the disabled state to keep that rule
        intact.
        """
        for spin in (self.yaw_spin, self.pitch_spin, self.roll_spin, self.z_spin):
            spin.setEnabled(enabled)
        for btn in (self.yaw_90_btn, self.pitch_90_btn, self.roll_90_btn):
            btn.setEnabled(enabled)
        for btn in self.preset_buttons.values():
            btn.setEnabled(enabled)
        if hasattr(self, "preview_widget") and self.preview_widget is not None:
            # Disabling the QOpenGLWidget greys it out and stops mouse interaction.
            self.preview_widget.setEnabled(enabled)
        if not enabled:
            # When we lose the binding, also clear any apply-to-group state
            # so reselecting a single-group selection re-enables the box
            # without carrying a stale checked state from elsewhere.
            self.apply_to_group_checkbox.setChecked(False)
            self.apply_to_group_checkbox.setEnabled(False)

    def _connect_signals(self):
        """Connect UI signals."""
        self.yaw_spin.valueChanged.connect(self._on_values_changed)
        self.pitch_spin.valueChanged.connect(self._on_values_changed)
        self.roll_spin.valueChanged.connect(self._on_values_changed)
        # Z-height edits don't reshape the gimbal, but inline embedders need
        # to know when the value changed so they can write it back.
        self.z_spin.valueChanged.connect(lambda _v: self.values_changed.emit())

        # Ticking "apply to group default" must take effect immediately in
        # the inline (Stage tab) path, which acts on values_changed. Without
        # this the box read as broken: the modal reads it at Apply time, but
        # inline nothing re-applied until some other value changed.
        # `clicked` (not `toggled`): fire only on real user interaction, so
        # the programmatic setChecked(False) that runs while re-binding the
        # panel to a new selection does not spuriously re-apply values.
        self.apply_to_group_checkbox.clicked.connect(
            lambda _checked: self.values_changed.emit())

        # Connect preview widget's ring drag signal to update spin boxes
        self.preview_widget.orientation_changed.connect(self._on_preview_orientation_changed)

    def _on_preview_orientation_changed(self, yaw: float, pitch: float, roll: float):
        """Handle orientation change from ring dragging in preview widget."""
        # Block signals to avoid feedback loop
        self.yaw_spin.blockSignals(True)
        self.pitch_spin.blockSignals(True)
        self.roll_spin.blockSignals(True)

        self.yaw_spin.setValue(yaw)
        self.pitch_spin.setValue(pitch)
        self.roll_spin.setValue(roll)

        self.yaw_spin.blockSignals(False)
        self.pitch_spin.blockSignals(False)
        self.roll_spin.blockSignals(False)

        # Check if values match a preset and update selection
        matched_preset = self._find_matching_preset(yaw, pitch, roll)
        self._update_preset_selection(matched_preset)

        self.values_changed.emit()

    def _load_initial_values(self):
        """Load initial values from the first fixture."""
        if not self.fixtures:
            return

        fixture = self.fixtures[0]

        # Get fixture type and segment count from layout
        fixture_type = getattr(fixture, 'fixture_type', 'MH')

        # Look up segment count from fixture file if manufacturer/model available
        segment_count = 8  # Default
        manufacturer = getattr(fixture, 'manufacturer', None)
        model = getattr(fixture, 'model', None)

        if manufacturer and model:
            from utils.fixture_utils import get_fixture_layout
            layout = get_fixture_layout(manufacturer, model)
            segment_count = layout.get('width', 1)

        # Set fixture type with segment count
        self.preview_widget.set_fixture_type(fixture_type, segment_count)

        # Get orientation values
        mounting = getattr(fixture, 'mounting', 'hanging')
        yaw = getattr(fixture, 'rotation_angle', 0.0)  # rotation_angle is yaw in 2D view
        pitch = getattr(fixture, 'pitch', 0.0)
        roll = getattr(fixture, 'roll', 0.0)
        z_height = getattr(fixture, 'z_height', 3.0)

        # Backward compatibility: if yaw/pitch/roll are all zero and mounting is set,
        # convert from old relative system to new absolute system
        if yaw == 0.0 and pitch == 0.0 and roll == 0.0 and mounting in self.PRESET_VALUES:
            preset_values = self.PRESET_VALUES.get(mounting)
            if preset_values:
                yaw, pitch, roll = preset_values

        # Block signals while setting values
        self.yaw_spin.blockSignals(True)
        self.pitch_spin.blockSignals(True)
        self.roll_spin.blockSignals(True)
        self.z_spin.blockSignals(True)

        self.yaw_spin.setValue(yaw)
        self.pitch_spin.setValue(pitch)
        self.roll_spin.setValue(roll)
        self.z_spin.setValue(z_height)

        self.yaw_spin.blockSignals(False)
        self.pitch_spin.blockSignals(False)
        self.roll_spin.blockSignals(False)
        self.z_spin.blockSignals(False)

        # Find which preset matches the values (or 'custom' if none)
        matched_preset = self._find_matching_preset(yaw, pitch, roll)
        self._update_preset_selection(matched_preset)

        # Update preview with absolute values
        self.preview_widget.set_orientation(matched_preset, yaw, pitch, roll)

    def _on_preset_clicked(self, preset_id: str):
        """Handle preset button click."""
        # Don't do anything special when clicking Custom - it's auto-selected
        if preset_id == 'custom':
            self._update_preset_selection(preset_id)
            return

        # Update button states
        self._update_preset_selection(preset_id)

        # Get the absolute values for this preset
        preset_values = self.PRESET_VALUES.get(preset_id, (0.0, 0.0, 0.0))
        yaw, pitch, roll = preset_values

        # Set spinboxes to actual preset values
        self.yaw_spin.blockSignals(True)
        self.pitch_spin.blockSignals(True)
        self.roll_spin.blockSignals(True)

        self.yaw_spin.setValue(yaw)
        self.pitch_spin.setValue(pitch)
        self.roll_spin.setValue(roll)

        self.yaw_spin.blockSignals(False)
        self.pitch_spin.blockSignals(False)
        self.roll_spin.blockSignals(False)

        # Update preview with absolute values
        self.preview_widget.set_orientation(preset_id, yaw, pitch, roll)

        self.values_changed.emit()

    def _update_preset_selection(self, preset_id: str):
        """Update preset button checked states."""
        for pid, btn in self.preset_buttons.items():
            btn.setChecked(pid == preset_id)

    def _on_values_changed(self):
        """Handle spin box value changes."""
        yaw = self.yaw_spin.value()
        pitch = self.pitch_spin.value()
        roll = self.roll_spin.value()

        # Check if current values match any preset
        matched_preset = self._find_matching_preset(yaw, pitch, roll)
        self._update_preset_selection(matched_preset)

        # Update preview with absolute values
        self.preview_widget.set_orientation(matched_preset, yaw, pitch, roll)

        self.values_changed.emit()

    def _find_matching_preset(self, yaw: float, pitch: float, roll: float) -> str:
        """Find which preset matches the given values, or 'custom' if none match."""
        tolerance = 0.1  # Small tolerance for floating point comparison

        for preset_id, values in self.PRESET_VALUES.items():
            if values is None:  # Skip 'custom' preset
                continue
            preset_yaw, preset_pitch, preset_roll = values
            if (abs(yaw - preset_yaw) < tolerance and
                abs(pitch - preset_pitch) < tolerance and
                abs(roll - preset_roll) < tolerance):
                return preset_id

        return 'custom'

    def _rotate_by_90(self, axis: str):
        """Rotate the specified axis by +90 degrees, wrapping to stay in valid range."""
        if axis == 'yaw':
            new_value = self.yaw_spin.value() + 90
            # Wrap to -180 to 180 range
            if new_value > 180:
                new_value -= 360
            self.yaw_spin.setValue(new_value)
        elif axis == 'pitch':
            new_value = self.pitch_spin.value() + 90
            # Wrap to -90 to 90 range
            if new_value > 90:
                new_value -= 180
            self.pitch_spin.setValue(new_value)
        elif axis == 'roll':
            new_value = self.roll_spin.value() + 90
            # Wrap to -180 to 180 range
            if new_value > 180:
                new_value -= 360
            self.roll_spin.setValue(new_value)

    def get_selected_mounting(self) -> str:
        """Get the selected mounting preset."""
        for pid, btn in self.preset_buttons.items():
            if btn.isChecked():
                return pid
        return 'hanging'

    def get_orientation_values(self) -> dict:
        """Get all orientation values as a dictionary."""
        return {
            'mounting': self.get_selected_mounting(),
            'yaw': self.yaw_spin.value(),
            'pitch': self.pitch_spin.value(),
            'roll': self.roll_spin.value(),
            'z_height': self.z_spin.value(),
            'apply_to_group': self.apply_to_group_checkbox.isChecked()
        }

    def cleanup(self) -> None:
        """Release GL resources owned by the preview widget. Called by the
        wrapping dialog on close, or by the inline embedder on tab cleanup."""
        if hasattr(self, "preview_widget") and self.preview_widget is not None:
            self.preview_widget.cleanup()


class OrientationDialog(QDialog):
    """Modal wrapper around :class:`OrientationPanel`.

    Adds Cancel / Apply buttons and standard QDialog accept/reject flow so
    existing call sites (``stage_tab._open_orientation_dialog``) keep working
    unchanged. Forwards ``get_selected_mounting`` / ``get_orientation_values``
    to the embedded panel.
    """

    # Re-export presets for any caller still reading them off the dialog.
    PRESETS = OrientationPanel.PRESETS
    PRESET_VALUES = OrientationPanel.PRESET_VALUES

    def __init__(self, fixtures: List, config=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set Orientation")
        self.setMinimumSize(500, 550)

        layout = QVBoxLayout(self)
        self.panel = OrientationPanel(fixtures, config, self)
        layout.addWidget(self.panel, stretch=1)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.apply_btn)

        layout.addLayout(button_layout)

    # ── Pass-throughs that preserve the dialog's existing public API ──

    def get_selected_mounting(self) -> str:
        return self.panel.get_selected_mounting()

    def get_orientation_values(self) -> dict:
        return self.panel.get_orientation_values()

    @property
    def fixtures(self):
        return self.panel.fixtures

    @property
    def preview_widget(self):
        return self.panel.preview_widget

    def closeEvent(self, event):
        self.panel.cleanup()
        super().closeEvent(event)
