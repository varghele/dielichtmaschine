# visualizer/renderer/gizmo.py
# Coordinate system gizmo for orientation reference

import numpy as np
import moderngl
import glm


class CoordinateGizmo:
    """
    Renders a small coordinate system gizmo in the corner of the viewport.

    Shows X (red), Y (green), Z (blue) axes with labels.
    The gizmo rotates with the camera to show current orientation.
    """

    # Vertex shader for axes
    AXIS_VERTEX_SHADER = """
    #version 330

    in vec3 in_position;
    in vec3 in_color;

    out vec3 v_color;

    uniform mat4 mvp;

    void main() {
        gl_Position = mvp * vec4(in_position, 1.0);
        v_color = in_color;
    }
    """

    AXIS_FRAGMENT_SHADER = """
    #version 330

    in vec3 v_color;

    out vec4 fragColor;

    void main() {
        fragColor = vec4(v_color, 1.0);
    }
    """

    # Vertex shader for text labels (rendered as quads)
    TEXT_VERTEX_SHADER = """
    #version 330

    in vec2 in_position;
    in vec2 in_texcoord;

    out vec2 v_texcoord;

    uniform vec2 offset;
    uniform vec2 scale;

    void main() {
        vec2 pos = in_position * scale + offset;
        gl_Position = vec4(pos, 0.0, 1.0);
        v_texcoord = in_texcoord;
    }
    """

    TEXT_FRAGMENT_SHADER = """
    #version 330

    in vec2 v_texcoord;

    out vec4 fragColor;

    uniform vec3 color;
    uniform sampler2D text_texture;

    void main() {
        float alpha = texture(text_texture, v_texcoord).r;
        fragColor = vec4(color, alpha);
    }
    """

    def __init__(self, ctx: moderngl.Context):
        """Initialize the gizmo renderer."""
        self.ctx = ctx

        # Gizmo size and position (in normalized device coordinates)
        self.size = 0.1  # Size of gizmo (NDC units)
        self.margin = 0.05  # Margin from corner

        # Axis colors matching stage grid convention:
        # X = Red (stage width, horizontal)
        # Y = Blue (stage depth, shown as "up" in 2D top-down view)
        # Z = Green (height above stage)
        self.x_color = (1.0, 0.3, 0.3)  # Red
        self.y_color = (0.3, 0.3, 1.0)  # Blue (depth)
        self.z_color = (0.3, 1.0, 0.3)  # Green (height)

        # Create shader
        self.axis_program = ctx.program(
            vertex_shader=self.AXIS_VERTEX_SHADER,
            fragment_shader=self.AXIS_FRAGMENT_SHADER
        )

        # Create axis geometry
        self._create_axes()

        # Create text rendering (simple approach using lines to draw letters)
        self._create_text_geometry()

    def _create_axes(self):
        """Create axis line geometry."""
        # Axis length in local space
        length = 1.0

        # Vertices: position (3) + color (3)
        # Note: We swap Y/Z colors to match stage convention
        # - X axis (red) = stage width
        # - Vertical axis uses z_color (green) = height (labeled Z)
        # - Depth axis uses y_color (blue) = stage depth (labeled Y)
        vertices = np.array([
            # X axis (red) - stage width
            0.0, 0.0, 0.0, *self.x_color,
            length, 0.0, 0.0, *self.x_color,
            # Vertical axis (green, labeled Z) - height
            0.0, 0.0, 0.0, *self.z_color,
            0.0, length, 0.0, *self.z_color,
            # Depth axis (blue, labeled Y) - stage depth
            0.0, 0.0, 0.0, *self.y_color,
            0.0, 0.0, length, *self.y_color,
        ], dtype='f4')

        self.axis_vbo = self.ctx.buffer(vertices.tobytes())
        self.axis_vao = self.ctx.vertex_array(
            self.axis_program,
            [(self.axis_vbo, '3f 3f', 'in_position', 'in_color')]
        )

    def _create_text_geometry(self):
        """Create geometry for axis labels (X, Y, Z drawn with lines)."""
        # We'll draw letters using line segments
        # Each letter is defined by a list of line segments in local space

        # Letter X (two diagonal lines)
        x_lines = [
            (-0.1, -0.15, 0.1, 0.15),  # Bottom-left to top-right
            (-0.1, 0.15, 0.1, -0.15),  # Top-left to bottom-right
        ]

        # Letter Y (three lines: two diagonals meeting at center, one down)
        y_lines = [
            (-0.1, 0.15, 0.0, 0.0),  # Top-left to center
            (0.1, 0.15, 0.0, 0.0),   # Top-right to center
            (0.0, 0.0, 0.0, -0.15),  # Center to bottom
        ]

        # Letter Z (three lines: top, diagonal, bottom)
        z_lines = [
            (-0.1, 0.15, 0.1, 0.15),   # Top horizontal
            (0.1, 0.15, -0.1, -0.15),  # Diagonal
            (-0.1, -0.15, 0.1, -0.15), # Bottom horizontal
        ]

        self.letter_data = {
            'X': x_lines,
            'Y': y_lines,
            'Z': z_lines
        }

        # Create VBOs for each letter
        self.letter_vbos = {}
        self.letter_vaos = {}

        for letter, lines in self.letter_data.items():
            vertices = []
            for x1, y1, x2, y2 in lines:
                vertices.extend([x1, y1, 0.0, 1.0, 1.0, 1.0])  # White color
                vertices.extend([x2, y2, 0.0, 1.0, 1.0, 1.0])

            vertex_array = np.array(vertices, dtype='f4')
            vbo = self.ctx.buffer(vertex_array.tobytes())
            vao = self.ctx.vertex_array(
                self.axis_program,
                [(vbo, '3f 3f', 'in_position', 'in_color')]
            )
            self.letter_vbos[letter] = vbo
            self.letter_vaos[letter] = vao

    def render(self, view_matrix: glm.mat4, viewport_width: int, viewport_height: int):
        """
        Render the coordinate gizmo.

        Args:
            view_matrix: Camera view matrix (rotation only, no translation)
            viewport_width: Viewport width in pixels
            viewport_height: Viewport height in pixels
        """
        # Calculate gizmo position in top-right corner
        aspect = viewport_width / viewport_height if viewport_height > 0 else 1.0

        # Position gizmo in top-right corner (NDC coordinates)
        gizmo_x = 1.0 - self.margin - self.size
        gizmo_y = 1.0 - self.margin - self.size

        # Create orthographic projection for the gizmo
        # Scale to fit in corner, maintaining aspect ratio
        ortho = glm.ortho(-aspect, aspect, -1.0, 1.0, -10.0, 10.0)

        # Extract rotation from view matrix (remove translation)
        rotation_only = glm.mat4(glm.mat3(view_matrix))

        # Create model matrix to position gizmo in corner
        model = glm.mat4(1.0)
        model = glm.translate(model, glm.vec3(gizmo_x * aspect, gizmo_y, 0.0))
        model = glm.scale(model, glm.vec3(self.size, self.size, self.size))

        # Combine matrices: projection * model * rotation
        mvp = ortho * model * rotation_only

        # Convert to bytes
        mvp_flat = []
        for col in mvp.to_list():
            mvp_flat.extend(col)
        mvp_bytes = np.array(mvp_flat, dtype='f4').tobytes()

        try:
            # Disable depth test for gizmo (always on top)
            self.ctx.disable(moderngl.DEPTH_TEST)

            # Render axes
            self.axis_program['mvp'].write(mvp_bytes)
            self.axis_vao.render(moderngl.LINES)

            # Render labels at end of each axis
            # Note: Stage uses X for width, Y for depth (shown as Z in 2D), Z for height
            # The 3D engine uses Y-up convention, so we swap labels to match stage view
            label_offset = 1.2  # Slightly beyond axis end
            label_scale = 0.3   # Scale for letters

            # X label (stage width) - stays the same
            x_pos = rotation_only * glm.vec4(label_offset, 0.0, 0.0, 1.0)
            self._render_label('X', x_pos, model, ortho, self.x_color, label_scale)

            # Z label on the vertical axis (height in 3D, labeled Z to match convention)
            y_pos = rotation_only * glm.vec4(0.0, label_offset, 0.0, 1.0)
            self._render_label('Z', y_pos, model, ortho, self.z_color, label_scale)

            # Y label on the depth axis (stage depth, labeled Y to match stage view)
            z_pos = rotation_only * glm.vec4(0.0, 0.0, label_offset, 1.0)
            self._render_label('Y', z_pos, model, ortho, self.y_color, label_scale)

        finally:
            # Always re-enable depth test
            self.ctx.enable(moderngl.DEPTH_TEST)

    def _render_label(self, letter: str, pos: glm.vec4, model: glm.mat4,
                      ortho: glm.mat4, color: tuple, scale: float):
        """Render a single letter label."""
        if letter not in self.letter_vaos:
            return

        # Create transform for the letter
        letter_model = glm.mat4(1.0)
        letter_model = glm.translate(letter_model, glm.vec3(
            model[3][0] + pos.x * self.size,
            model[3][1] + pos.y * self.size,
            0.0
        ))
        letter_model = glm.scale(letter_model, glm.vec3(scale * self.size, scale * self.size, 1.0))

        mvp = ortho * letter_model

        # Convert to bytes
        mvp_flat = []
        for col in mvp.to_list():
            mvp_flat.extend(col)
        mvp_bytes = np.array(mvp_flat, dtype='f4').tobytes()

        # Override color in vertex data by using uniform (but we're using vertex colors)
        # For simplicity, we'll just use the same white color for all labels
        self.axis_program['mvp'].write(mvp_bytes)
        self.letter_vaos[letter].render(moderngl.LINES)

    def release(self):
        """Release GPU resources."""
        self.axis_vbo.release()
        self.axis_vao.release()
        for vbo in self.letter_vbos.values():
            vbo.release()
        for vao in self.letter_vaos.values():
            vao.release()
        self.axis_program.release()
