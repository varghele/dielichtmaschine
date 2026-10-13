# visualizer/renderer/fixtures.py
# Fixture rendering for the 3D visualizer

import math
import os
import numpy as np
import moderngl
import glm
from typing import Dict, List, Any, Optional, Tuple
from abc import ABC, abstractmethod

from utils.geometry import GeometryBuilder


# ---------------------------------------------------------------------------
# Feature flag — Phase D fixture-rewrite cutover.
# ---------------------------------------------------------------------------
#
# Default is now the composable renderer
# (:mod:`visualizer.renderer.composable_fixtures`). Visual regression
# tests (tests/visual/test_fixture_renderer_parity.py) pass for all 6
# custom fixtures with the cone properly oriented along the head's local
# +X for moving yokes.
#
# Set ``FIXTURE_RENDERER=legacy`` in the environment to fall back to the
# original 6-subclass dispatch (kept available for parity comparison
# and rollback during the v1.0 transition).

FIXTURE_RENDERER_MODE = os.environ.get('FIXTURE_RENDERER', 'composable').lower()
USE_COMPOSABLE_RENDERER = FIXTURE_RENDERER_MODE == 'composable'


# Warm white color temperature (~2700K)
WARM_WHITE_COLOR = (1.0, 0.85, 0.6)  # RGB approximation of warm white


# Legacy-renderer shaders (FIXTURE_RENDERER=legacy). The composable
# renderer draws with visualizer/renderer/shaders.py; the two sets have
# diverged on purpose and are NOT kept in sync (see that module's header).

# Shared shader for fixture body rendering
FIXTURE_VERTEX_SHADER = """
#version 330

in vec3 in_position;
in vec3 in_normal;

out vec3 v_normal;
out vec3 v_position;

uniform mat4 mvp;
uniform mat4 model;

void main() {
    gl_Position = mvp * vec4(in_position, 1.0);
    v_normal = mat3(model) * in_normal;
    v_position = (model * vec4(in_position, 1.0)).xyz;
}
"""

FIXTURE_FRAGMENT_SHADER = """
#version 330

in vec3 v_normal;
in vec3 v_position;

out vec4 fragColor;

uniform vec3 base_color;
uniform vec3 emissive_color;
uniform float emissive_strength;

void main() {
    // Simple directional lighting
    vec3 light_dir = normalize(vec3(0.5, 1.0, 0.3));
    float diff = max(dot(normalize(v_normal), light_dir), 0.0);

    // Ambient + diffuse lighting on base color
    vec3 ambient = base_color * 0.3;
    vec3 diffuse = base_color * diff * 0.7;

    // Add emissive glow
    vec3 emissive = emissive_color * emissive_strength;

    vec3 final_color = ambient + diffuse + emissive;
    fragColor = vec4(final_color, 1.0);
}
"""

# Beam shader for volumetric light cone
BEAM_VERTEX_SHADER = """
#version 330

in vec3 in_position;
in float in_alpha;

out float v_alpha;

uniform mat4 mvp;

void main() {
    gl_Position = mvp * vec4(in_position, 1.0);
    v_alpha = in_alpha;
}
"""

# Beam vertex shader with position output for gobo support
GOBO_BEAM_VERTEX_SHADER = """
#version 330

in vec3 in_position;
in float in_alpha;

out float v_alpha;
out vec3 v_position;

uniform mat4 mvp;

void main() {
    gl_Position = mvp * vec4(in_position, 1.0);
    v_alpha = in_alpha;
    v_position = in_position;  // Pass local position to fragment shader
}
"""

BEAM_FRAGMENT_SHADER = """
#version 330

in float v_alpha;

out vec4 fragColor;

uniform vec3 beam_color;
uniform float beam_intensity;

void main() {
    // Fade out toward edges and along length
    float alpha = v_alpha * beam_intensity * 0.8;
    fragColor = vec4(beam_color, alpha);
}
"""

# Floor projection shader for spotlight effect
FLOOR_PROJECTION_VERTEX_SHADER = """
#version 330

in vec3 in_position;
in vec2 in_uv;

out vec2 v_uv;

uniform mat4 mvp;

void main() {
    gl_Position = mvp * vec4(in_position, 1.0);
    v_uv = in_uv;
}
"""

FLOOR_PROJECTION_FRAGMENT_SHADER = """
#version 330

in vec2 v_uv;

out vec4 fragColor;

uniform vec3 projection_color;
uniform float projection_intensity;
uniform float distance_falloff;

void main() {
    // Calculate distance from center (0.5, 0.5) in UV space
    vec2 centered = v_uv - vec2(0.5);
    float dist = length(centered) * 2.0;  // Normalize to 0-1 range

    // Soft gaussian-like falloff from center
    // Use smoothstep for soft edge transition
    float soft_edge = 1.0 - smoothstep(0.0, 1.0, dist);

    // Add extra softness with gaussian-like curve
    float gaussian = exp(-dist * dist * 1.5);

    // Combine for nice soft spotlight effect
    float alpha = soft_edge * gaussian * projection_intensity * distance_falloff;

    // Output with good visibility (alpha up to 0.9 for bright center)
    alpha = clamp(alpha, 0.0, 0.9);
    fragColor = vec4(projection_color, alpha);
}
"""

# Floor projection shader with gobo pattern support and focus-based blur
GOBO_FLOOR_PROJECTION_FRAGMENT_SHADER = """
#version 330

in vec2 v_uv;

out vec4 fragColor;

uniform vec3 projection_color;
uniform float projection_intensity;
uniform float distance_falloff;
uniform int gobo_pattern;      // 0=open, 1=dots, 2=star, 3=lines, 4=triangle, 5=cross, 6=breakup
uniform float gobo_rotation;   // Rotation angle in radians
uniform float focus_sharpness; // 0.0 = blurry, 1.0 = sharp (distance-based)

// Constants
const float PI = 3.14159265359;

// Rotate UV coordinates around center
vec2 rotate_uv(vec2 uv, float angle) {
    vec2 centered = uv - vec2(0.5);
    float c = cos(angle);
    float s = sin(angle);
    vec2 rotated = vec2(
        centered.x * c - centered.y * s,
        centered.x * s + centered.y * c
    );
    return rotated + vec2(0.5);
}

// Pattern 1: Dots (ring of circles) - with blur parameter
float gobo_dots(vec2 uv, float blur) {
    vec2 centered = uv - vec2(0.5);
    float angle = atan(centered.y, centered.x);
    float dist = length(centered) * 2.0;

    // Create 6 dots in a ring
    float dot_angle = mod(angle + PI, PI / 3.0) - PI / 6.0;
    float dot_dist = abs(dist - 0.5);  // Distance from ring at radius 0.25
    float angular_dist = abs(dot_angle) * dist;

    // Blur affects edge sharpness
    float edge = mix(0.05, 0.2, blur);
    float dot = smoothstep(0.15 + edge, 0.1 - edge, length(vec2(dot_dist, angular_dist)));
    return dot;
}

// Pattern 2: Star (6-pointed) - with blur parameter
float gobo_star(vec2 uv, float blur) {
    vec2 centered = uv - vec2(0.5);
    float angle = atan(centered.y, centered.x);
    float dist = length(centered) * 2.0;

    // Create 6-pointed star
    float star_angle = mod(angle + PI, PI / 3.0) - PI / 6.0;
    float star_radius = 0.3 + 0.2 * cos(star_angle * 6.0);

    float edge = mix(0.05, 0.15, blur);
    return smoothstep(star_radius + edge, star_radius - edge, dist);
}

// Pattern 3: Lines (parallel bars) - with blur parameter
float gobo_lines(vec2 uv, float blur) {
    // Create 5 parallel lines
    float line = mod(uv.x * 10.0, 2.0);
    float edge = mix(0.1, 0.4, blur);
    float mask = smoothstep(0.3 - edge, 0.5 + edge, line) * (1.0 - smoothstep(1.5 - edge, 1.7 + edge, line));

    // Circular mask
    vec2 centered = uv - vec2(0.5);
    float dist = length(centered) * 2.0;
    float circle_edge = mix(0.1, 0.3, blur);
    float circle = 1.0 - smoothstep(0.8 - circle_edge, 1.0 + circle_edge, dist);

    return mask * circle;
}

// Pattern 4: Triangle - with blur parameter
float gobo_triangle(vec2 uv, float blur) {
    vec2 centered = uv - vec2(0.5);

    // Equilateral triangle
    float d1 = centered.y + 0.3;
    float d2 = -0.866 * centered.x - 0.5 * centered.y + 0.3;
    float d3 = 0.866 * centered.x - 0.5 * centered.y + 0.3;

    float tri = min(min(d1, d2), d3);
    float edge = mix(0.02, 0.1, blur);
    return smoothstep(-edge, edge, tri);
}

// Pattern 5: Cross (plus sign) - with blur parameter
float gobo_cross(vec2 uv, float blur) {
    vec2 centered = abs(uv - vec2(0.5));

    // Cross shape - blur affects arm definition
    float arm_width = 0.1 + blur * 0.05;
    float arm_length = 0.35;

    float edge = mix(0.01, 0.1, blur);
    float h_arm = smoothstep(arm_width + edge, arm_width - edge, centered.y) *
                  smoothstep(arm_length + edge, arm_length - edge, centered.x);
    float v_arm = smoothstep(arm_width + edge, arm_width - edge, centered.x) *
                  smoothstep(arm_length + edge, arm_length - edge, centered.y);

    return max(h_arm, v_arm);
}

// Pattern 6: Breakup (random-ish pattern) - with blur parameter
float gobo_breakup(vec2 uv, float blur) {
    vec2 centered = uv - vec2(0.5);
    float dist = length(centered) * 2.0;

    // Create organic breakup pattern using multiple sine waves
    float angle = atan(centered.y, centered.x);
    float pattern = 0.5 + 0.5 * sin(angle * 7.0 + dist * 15.0);
    pattern *= 0.5 + 0.5 * sin(angle * 5.0 - dist * 10.0 + 1.0);
    pattern *= 0.5 + 0.5 * sin(angle * 3.0 + dist * 8.0 + 2.0);

    // Threshold - blur makes edges softer
    float low = mix(0.2, 0.35, blur);
    float high = mix(0.3, 0.45, blur);
    float threshold = smoothstep(low, high, pattern);

    // Circular mask
    float circle_edge = mix(0.1, 0.3, blur);
    float circle = 1.0 - smoothstep(0.7 - circle_edge, 0.9 + circle_edge, dist);

    return threshold * circle;
}

// Main gobo pattern selector with blur
float get_gobo_pattern(vec2 uv, int pattern, float blur) {
    if (pattern == 0) return 1.0;  // Open
    if (pattern == 1) return gobo_dots(uv, blur);
    if (pattern == 2) return gobo_star(uv, blur);
    if (pattern == 3) return gobo_lines(uv, blur);
    if (pattern == 4) return gobo_triangle(uv, blur);
    if (pattern == 5) return gobo_cross(uv, blur);
    return gobo_breakup(uv, blur);  // Pattern 6 or default
}

void main() {
    // Apply gobo rotation
    vec2 rotated_uv = rotate_uv(v_uv, gobo_rotation);

    // Calculate blur from focus_sharpness (inverted: sharpness 1 = blur 0)
    float blur = 1.0 - focus_sharpness;

    // Get gobo pattern mask with focus-based blur
    float gobo_mask = get_gobo_pattern(rotated_uv, gobo_pattern, blur);

    // Calculate distance from center
    vec2 centered = v_uv - vec2(0.5);
    float dist = length(centered) * 2.0;

    // Gaussian falloff - width affected by focus
    // Unfocused = wider, softer falloff; Focused = tighter, sharper
    float gaussian_width = mix(2.5, 1.0, focus_sharpness);  // 1.0 = tight, 2.5 = wide
    float gaussian = exp(-dist * dist * gaussian_width);

    // Edge softness also affected by focus
    float edge_start = mix(-0.2, 0.0, focus_sharpness);
    float edge_end = mix(1.2, 1.0, focus_sharpness);
    float soft_edge = 1.0 - smoothstep(edge_start, edge_end, dist);

    // Combine falloff with gobo pattern
    float alpha = soft_edge * gaussian * gobo_mask * projection_intensity * distance_falloff;

    // Output with good visibility
    alpha = clamp(alpha, 0.0, 0.9);
    fragColor = vec4(projection_color, alpha);
}
"""

# Beam shader with gobo pattern support
GOBO_BEAM_FRAGMENT_SHADER = """
#version 330

in float v_alpha;
in vec3 v_position;  // Local position for gobo projection

out vec4 fragColor;

uniform vec3 beam_color;
uniform float beam_intensity;
uniform int gobo_pattern;
uniform float gobo_rotation;
uniform float focus_sharpness;  // 0.0 = blurry, 1.0 = sharp (distance-based)

const float PI = 3.14159265359;

// Rotate 2D coordinates
vec2 rotate_2d(vec2 p, float angle) {
    float c = cos(angle);
    float s = sin(angle);
    return vec2(p.x * c - p.y * s, p.x * s + p.y * c);
}

// Gobo patterns for volumetric beam - returns 0.0 to 1.0
// 0.0 = dark area, 1.0 = bright area
// blur parameter widens smoothstep edges (0.0 = sharp, 1.0 = fully blurred)
float beam_gobo_pattern(vec2 uv, int pattern, float blur) {
    if (pattern == 0) return 1.0;  // Open - full brightness

    vec2 centered = uv;
    float dist = length(centered);
    float angle = atan(centered.y, centered.x);

    // Blur factor widens the smoothstep transition (min 0.02 for sharpest)
    float edge_blur = mix(0.02, 0.25, blur);

    if (pattern == 1) {
        // Dots - ring of 6 dots (creates shadow with bright dots)
        float dot_angle = mod(angle + PI, PI / 3.0) - PI / 6.0;
        float dots = smoothstep(0.25 + edge_blur, 0.15 - edge_blur, abs(dot_angle)) *
                     smoothstep(0.2 + edge_blur, 0.08 - edge_blur, abs(dist - 0.5));
        return dots;
    }
    if (pattern == 2) {
        // Star - 6-pointed star shape
        float star_radius = 0.35 + 0.2 * cos(angle * 6.0);
        float star = smoothstep(star_radius + 0.08 + edge_blur, star_radius - 0.08 - edge_blur, dist);
        return star;
    }
    if (pattern == 3) {
        // Lines - 6 radial lines
        float line_pattern = abs(sin(angle * 3.0));
        return smoothstep(0.3 - edge_blur, 0.5 + edge_blur, line_pattern);
    }
    if (pattern == 4) {
        // Triangle
        float d1 = centered.y + 0.35;
        float d2 = -0.866 * centered.x - 0.5 * centered.y + 0.35;
        float d3 = 0.866 * centered.x - 0.5 * centered.y + 0.35;
        float tri = smoothstep(-edge_blur, 0.06 + edge_blur, min(min(d1, d2), d3));
        return tri;
    }
    if (pattern == 5) {
        // Cross - 4 radial arms
        float cross_angle = mod(abs(angle), PI / 2.0);
        float cross = smoothstep(0.18 + edge_blur, 0.12 - edge_blur, min(cross_angle, PI / 2.0 - cross_angle));
        return cross;
    }
    // Breakup - organic interference pattern (blur reduces contrast)
    float breakup = 0.5 + 0.5 * sin(angle * 7.0 + dist * 10.0);
    breakup *= 0.5 + 0.5 * sin(angle * 5.0 - dist * 8.0);
    float blur_smooth = mix(0.25, 0.45, blur);
    return smoothstep(blur_smooth, 1.0 - blur_smooth, breakup);
}

void main() {
    // Calculate UV from position (beam extends along Z)
    // Use angular coordinates: divide XY by Z to get consistent projection along beam
    float z_pos = max(0.1, v_position.z);  // Avoid division by very small z

    // Angular coordinates - gives consistent gobo projection along beam length
    vec2 beam_uv = v_position.xy / z_pos * 2.0;

    // Apply gobo rotation
    beam_uv = rotate_2d(beam_uv, gobo_rotation);

    // Calculate blur from focus_sharpness (inverted: sharpness 1 = blur 0)
    float blur = 1.0 - focus_sharpness;

    // Get gobo pattern value (0.0 to 1.0) with focus-based blur
    float pattern_value = beam_gobo_pattern(beam_uv, gobo_pattern, blur);

    // Convert pattern to alpha modulation
    // Use a gentler curve: pattern_value of 0 -> 0.5 brightness, 1 -> 1.0 brightness
    // This keeps the beam visible while still showing the pattern
    float gobo_brightness = mix(0.5, 1.0, pattern_value);

    // Beam edge softness based on focus
    // v_alpha is 1.0 at center, 0.0 at edge
    // When unfocused, make edges softer (less contrast)
    float edge_softness = mix(0.15, 0.0, focus_sharpness);  // 0.0=sharp edge, 0.15=soft edge
    float edge_alpha = smoothstep(edge_softness, 1.0, v_alpha);
    float adjusted_alpha = mix(v_alpha, edge_alpha, 0.5);  // Blend original and adjusted

    // Base beam alpha
    float base_alpha = adjusted_alpha * beam_intensity * 0.3;

    // Apply gobo modulation - reduces contrast but keeps beam visible
    float alpha = base_alpha * gobo_brightness;

    fragColor = vec4(beam_color, alpha);
}
"""


class FixtureRenderer(ABC):
    """Base class for fixture renderers."""

    def __init__(self, ctx: moderngl.Context, fixture_data: Dict[str, Any]):
        """
        Initialize fixture renderer.

        Args:
            ctx: ModernGL context
            fixture_data: Fixture data from TCP message
        """
        self.ctx = ctx
        self.fixture_data = fixture_data

        # Extract common properties
        self.name = fixture_data.get('name', 'Unknown')
        self.position = fixture_data.get('position', {'x': 0, 'y': 0, 'z': 0})

        # Extract orientation (new format with mounting preset)
        orientation = fixture_data.get('orientation', {})
        self.mounting = orientation.get('mounting', 'hanging')
        self.yaw = orientation.get('yaw', 0.0)
        self.pitch = orientation.get('pitch', 0.0)
        self.roll = orientation.get('roll', 0.0)

        self.universe = fixture_data.get('universe', 1)
        self.address = fixture_data.get('address', 1)
        self.channel_mapping = fixture_data.get('channel_mapping', {})

        # Physical dimensions (in meters)
        physical = fixture_data.get('physical', {'width': 0.3, 'height': 0.3, 'depth': 0.2})
        self.width = physical.get('width', 0.3)
        self.height = physical.get('height', 0.3)
        self.depth = physical.get('depth', 0.2)

        # Layout for segmented fixtures
        layout = fixture_data.get('layout', {'width': 1, 'height': 1})
        self.segment_cols = layout.get('width', 1)
        self.segment_rows = layout.get('height', 1)

        # Beam properties
        self.beam_angle = fixture_data.get('beam_angle', 25.0)

        # Brightness scaling (set by FixtureManager based on lumen normalization)
        self.brightness_scale = 1.0

        # Current DMX state
        self.dmx_values: Dict[str, int] = {}
        self.segment_values: List[int] = []  # Per-segment DMX values

        # GPU resources (to be created by subclasses)
        self.program: Optional[moderngl.Program] = None
        self.vao: Optional[moderngl.VertexArray] = None
        self.vbo: Optional[moderngl.Buffer] = None
        self.nbo: Optional[moderngl.Buffer] = None

        # Beam resources (optional, created by _create_glow_beam)
        self.beam_program: Optional[moderngl.Program] = None
        self.beam_vao: Optional[moderngl.VertexArray] = None
        self.beam_vbo: Optional[moderngl.Buffer] = None
        self.beam_abo: Optional[moderngl.Buffer] = None
        self.beam_vertex_count: int = 0

    def get_model_matrix(self) -> glm.mat4:
        """Get the model transformation matrix for this fixture."""
        # Start with identity
        model = glm.mat4(1.0)

        # Translate to position
        # Note: In the visualizer, Y is up, so we map:
        # Stage X -> 3D X
        # Stage Y -> 3D Z (depth)
        # Stage Z (height) -> 3D Y (up)
        pos = self.position
        model = glm.translate(model, glm.vec3(pos['x'], pos['z'], pos['y']))

        # Use yaw/pitch/roll directly as absolute values
        # The orientation dialog sends complete orientation values that already
        # include the mounting preset rotation (e.g., hanging = pitch 90°)

        # Apply rotations in YXZ order (yaw-pitch-roll)
        # Yaw: rotation around Y axis (vertical/up axis in 3D space)
        model = glm.rotate(model, glm.radians(self.yaw), glm.vec3(0, 1, 0))

        # Pitch: rotation around X axis (tilt forward/backward)
        model = glm.rotate(model, glm.radians(self.pitch), glm.vec3(1, 0, 0))

        # Roll: rotation around Z axis (twist)
        model = glm.rotate(model, glm.radians(self.roll), glm.vec3(0, 0, 1))

        return model

    def update_dmx(self, dmx_data: bytes):
        """
        Update fixture state from DMX data.

        Args:
            dmx_data: 512 bytes of DMX data for the universe
        """
        # Convert channel mapping (string keys from JSON to int)
        # ch_num is 0-indexed (channel offset within fixture mode)
        # self.address is 1-indexed DMX address
        for ch_str, func in self.channel_mapping.items():
            try:
                ch_num = int(ch_str)
                # Calculate array index: (address - 1) converts to 0-indexed, + ch_num for offset
                index = (self.address - 1) + ch_num
                if 0 <= index < 512:
                    self.dmx_values[func] = dmx_data[index]
            except (ValueError, IndexError):
                pass

        # Also store raw DMX values for segment-based fixtures
        # (sunstrips, LED bars with per-segment control)
        self._update_segment_dmx(dmx_data)

    def _update_segment_dmx(self, dmx_data: bytes):
        """
        Update per-segment DMX values. Override in segment-based fixtures.

        Args:
            dmx_data: 512 bytes of DMX data
        """
        # Default: store raw channel values for segment count
        # Subclasses can override for specific behavior
        self.segment_values = []
        base_index = self.address - 1  # Convert to 0-indexed

        for i in range(self.segment_cols * self.segment_rows):
            if base_index + i < 512:
                self.segment_values.append(dmx_data[base_index + i])
            else:
                self.segment_values.append(0)

    def get_color(self) -> Tuple[float, float, float]:
        """Get current RGB color from DMX values (0-1 range)."""
        r = self.dmx_values.get('red', 0) / 255.0
        g = self.dmx_values.get('green', 0) / 255.0
        b = self.dmx_values.get('blue', 0) / 255.0
        return (r, g, b)

    def get_dimmer(self) -> float:
        """Get current dimmer value (0-1 range)."""
        # Default to 0 (off) when no DMX received, not 255
        return self.dmx_values.get('dimmer', 0) / 255.0

    def _create_glow_beam(self, beam_length: float = 0.8, beam_angle: float = 40.0):
        """
        Create a short glow beam for non-moving-head fixtures.

        Args:
            beam_length: Length of the beam in meters (default 0.8m - short glow)
            beam_angle: Beam spread angle in degrees (default 40 - wide spread)
        """
        # Create beam shader program
        self.beam_program = self.ctx.program(
            vertex_shader=BEAM_VERTEX_SHADER,
            fragment_shader=BEAM_FRAGMENT_SHADER
        )

        # Calculate beam radius at end based on angle
        beam_radius = beam_length * math.tan(math.radians(beam_angle / 2))

        beam_verts, beam_alphas = GeometryBuilder.create_beam_cone(
            beam_radius, beam_length, segments=16
        )

        self.beam_vbo = self.ctx.buffer(beam_verts.tobytes())
        self.beam_abo = self.ctx.buffer(beam_alphas.tobytes())

        self.beam_vao = self.ctx.vertex_array(
            self.beam_program,
            [
                (self.beam_vbo, '3f', 'in_position'),
                (self.beam_abo, '1f', 'in_alpha'),
            ]
        )
        self.beam_vertex_count = len(beam_verts) // 3

    def _render_glow_beam(self, mvp: glm.mat4, model: glm.mat4,
                          color: Tuple[float, float, float], dimmer: float,
                          beam_offset_z: float = 0.0):
        """
        Render a short glow beam.

        Args:
            mvp: View-projection matrix
            model: Model matrix for the fixture
            color: RGB color tuple (0-1 range)
            dimmer: Dimmer value (0-1 range)
            beam_offset_z: Offset along Z axis to position beam at lens
        """
        if not self.beam_vao or dimmer < 0.01:
            return

        try:
            # Offset beam to start at lens position
            beam_offset = glm.translate(glm.mat4(1.0), glm.vec3(0, 0, beam_offset_z))
            beam_model = model * beam_offset

            beam_mvp = mvp * beam_model
            mvp_bytes = np.array([x for col in beam_mvp.to_list() for x in col], dtype='f4').tobytes()

            # Enable additive blending
            self.ctx.enable(moderngl.BLEND)
            self.ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE)
            self.ctx.depth_mask = False

            self.beam_program['mvp'].write(mvp_bytes)
            self.beam_program['beam_color'].value = color
            self.beam_program['beam_intensity'].value = dimmer * self.brightness_scale

            self.beam_vao.render(moderngl.TRIANGLES)

            # Restore state
            self.ctx.depth_mask = True
            self.ctx.disable(moderngl.BLEND)

        except Exception as e:
            # Restore state on error
            try:
                self.ctx.depth_mask = True
                self.ctx.disable(moderngl.BLEND)
            except:
                pass

    @abstractmethod
    def render(self, mvp: glm.mat4):
        """Render the fixture."""
        pass

    def release(self):
        """Release GPU resources."""
        if self.vao:
            self.vao.release()
        if self.vbo:
            self.vbo.release()
        if self.nbo:
            self.nbo.release()
        if self.program:
            self.program.release()
        # Release beam resources
        if self.beam_vao:
            self.beam_vao.release()
        if self.beam_vbo:
            self.beam_vbo.release()
        if self.beam_abo:
            self.beam_abo.release()
        if self.beam_program:
            self.beam_program.release()


class LEDBarRenderer(FixtureRenderer):
    """Renderer for LED bar fixtures with RGBW segments."""

    # Body color (dark metal)
    BODY_COLOR = (0.15, 0.15, 0.18)

    def __init__(self, ctx: moderngl.Context, fixture_data: Dict[str, Any]):
        super().__init__(ctx, fixture_data)
        self._create_geometry()
        self._create_segment_beams()

    def _create_geometry(self):
        """Create bar body and segment geometry."""
        # Create shader program
        self.program = self.ctx.program(
            vertex_shader=FIXTURE_VERTEX_SHADER,
            fragment_shader=FIXTURE_FRAGMENT_SHADER
        )

        # Create bar body (housing)
        body_verts, body_norms = GeometryBuilder.create_box(
            self.width, self.height, self.depth
        )

        self.vbo = self.ctx.buffer(body_verts.tobytes())
        self.nbo = self.ctx.buffer(body_norms.tobytes())

        self.vao = self.ctx.vertex_array(
            self.program,
            [
                (self.vbo, '3f', 'in_position'),
                (self.nbo, '3f', 'in_normal'),
            ]
        )
        self.body_vertex_count = len(body_verts) // 3

        # Create segment geometry (lens/emitter surfaces)
        segment_width = (self.width * 0.9) / self.segment_cols
        segment_height = self.height * 0.6
        segment_depth = 0.01  # Thin emitter surface

        segment_verts = []
        segment_norms = []

        start_x = -self.width * 0.45 + segment_width / 2

        for i in range(self.segment_cols):
            x_offset = start_x + i * segment_width
            verts, norms = GeometryBuilder.create_box(
                segment_width * 0.85,
                segment_height,
                segment_depth,
                center=(x_offset, 0, self.depth / 2 + segment_depth / 2)
            )
            segment_verts.extend(verts)
            segment_norms.extend(norms)

        self.segment_vbo = self.ctx.buffer(np.array(segment_verts, dtype='f4').tobytes())
        self.segment_nbo = self.ctx.buffer(np.array(segment_norms, dtype='f4').tobytes())

        self.segment_vao = self.ctx.vertex_array(
            self.program,
            [
                (self.segment_vbo, '3f', 'in_position'),
                (self.segment_nbo, '3f', 'in_normal'),
            ]
        )
        self.segment_vertex_count = len(segment_verts) // 3
        self.vertices_per_segment = self.segment_vertex_count // self.segment_cols

        # Store segment dimensions for beam creation
        self.segment_width = segment_width
        self.segment_height = segment_height
        self.segment_start_x = start_x

        # Create coordinate axes for debugging orientation
        # For bar fixtures, make axes longer than bar width for visibility
        self._create_coordinate_axes(axis_origin_z=self.depth / 2 + 0.01)

    def _create_coordinate_axes(self, axis_origin_z: float):
        """Create coordinate axes for debugging fixture orientation.

        Args:
            axis_origin_z: Z position for axis origin (top of fixture)
        """
        # Axis length should exceed bar width for visibility
        axis_length = max(self.width, self.height) + 0.1  # Exceed bar dimensions
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

        self.x_axis_vbo = self.ctx.buffer(x_axis_verts.tobytes())
        self.x_axis_nbo = self.ctx.buffer(x_axis_norms.tobytes())
        self.x_axis_vao = self.ctx.vertex_array(
            self.program,
            [(self.x_axis_vbo, '3f', 'in_position'), (self.x_axis_nbo, '3f', 'in_normal')]
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

        self.y_axis_vbo = self.ctx.buffer(y_axis_verts.tobytes())
        self.y_axis_nbo = self.ctx.buffer(y_axis_norms.tobytes())
        self.y_axis_vao = self.ctx.vertex_array(
            self.program,
            [(self.y_axis_vbo, '3f', 'in_position'), (self.y_axis_nbo, '3f', 'in_normal')]
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

        self.z_axis_vbo = self.ctx.buffer(z_axis_verts.tobytes())
        self.z_axis_nbo = self.ctx.buffer(z_axis_norms.tobytes())
        self.z_axis_vao = self.ctx.vertex_array(
            self.program,
            [(self.z_axis_vbo, '3f', 'in_position'), (self.z_axis_nbo, '3f', 'in_normal')]
        )

    def _create_segment_beams(self):
        """Create per-segment rectangular beams."""
        self.beam_program = self.ctx.program(
            vertex_shader=BEAM_VERTEX_SHADER,
            fragment_shader=BEAM_FRAGMENT_SHADER
        )

        beam_length = 0.3  # Short glow near fixture face
        beam_width = self.segment_width * 0.7
        beam_height = self.segment_height * 0.7

        # Create beam geometry for all segments
        all_beam_verts = []
        all_beam_alphas = []

        for i in range(self.segment_cols):
            x_offset = self.segment_start_x + i * self.segment_width
            # Beams extend from front of segment (+Z direction)
            base_verts, base_alphas = GeometryBuilder.create_beam_box(
                beam_width, beam_height, beam_length
            )

            # Translate beam to segment position
            for j in range(0, len(base_verts), 3):
                x, y, z = base_verts[j], base_verts[j+1], base_verts[j+2]
                new_x = x + x_offset
                new_y = y  # Centered vertically
                new_z = z + self.depth / 2 + 0.02  # Start just in front of segment
                all_beam_verts.extend([new_x, new_y, new_z])

            all_beam_alphas.extend(base_alphas)

        self.segment_beam_vbo = self.ctx.buffer(np.array(all_beam_verts, dtype='f4').tobytes())
        self.segment_beam_abo = self.ctx.buffer(np.array(all_beam_alphas, dtype='f4').tobytes())

        self.segment_beam_vao = self.ctx.vertex_array(
            self.beam_program,
            [
                (self.segment_beam_vbo, '3f', 'in_position'),
                (self.segment_beam_abo, '1f', 'in_alpha'),
            ]
        )

        # Calculate vertices per beam
        single_beam_verts, _ = GeometryBuilder.create_beam_box(beam_width, beam_height, beam_length)
        self.vertices_per_beam = len(single_beam_verts) // 3

    def render(self, mvp: glm.mat4):
        """Render the LED bar."""
        # Reset OpenGL state to prevent transparency issues from previous beam rendering
        self.ctx.disable(moderngl.BLEND)
        self.ctx.depth_mask = True

        model = self.get_model_matrix()
        final_mvp = mvp * model

        # Convert matrices to bytes
        mvp_bytes = np.array([x for col in final_mvp.to_list() for x in col], dtype='f4').tobytes()
        model_bytes = np.array([x for col in model.to_list() for x in col], dtype='f4').tobytes()

        self.program['mvp'].write(mvp_bytes)
        self.program['model'].write(model_bytes)

        # Render body
        self.program['base_color'].value = self.BODY_COLOR
        self.program['emissive_color'].value = (0.0, 0.0, 0.0)
        self.program['emissive_strength'].value = 0.0
        self.vao.render(moderngl.TRIANGLES)

        # Render coordinate axes
        if hasattr(self, 'x_axis_vao') and self.x_axis_vao:
            self.program['base_color'].value = (0.9, 0.2, 0.2)  # Red
            self.x_axis_vao.render(moderngl.TRIANGLES)
        if hasattr(self, 'y_axis_vao') and self.y_axis_vao:
            self.program['base_color'].value = (0.2, 0.4, 0.9)  # Blue
            self.y_axis_vao.render(moderngl.TRIANGLES)
        if hasattr(self, 'z_axis_vao') and self.z_axis_vao:
            self.program['base_color'].value = (0.2, 0.8, 0.2)  # Green
            self.z_axis_vao.render(moderngl.TRIANGLES)

        # Render segments with their colors
        color = self.get_color()
        dimmer = self.get_dimmer()

        # Add white channel contribution
        white = self.dmx_values.get('white', 0) / 255.0
        color = (
            min(1.0, color[0] + white),
            min(1.0, color[1] + white),
            min(1.0, color[2] + white)
        )

        # Apply dimmer
        emissive = (color[0] * dimmer, color[1] * dimmer, color[2] * dimmer)

        self.program['base_color'].value = (0.1, 0.1, 0.1)
        self.program['emissive_color'].value = emissive
        self.program['emissive_strength'].value = 1.0 * self.brightness_scale

        self.segment_vao.render(moderngl.TRIANGLES)

        # Render beams for all segments (single color for LED bar)
        if dimmer > 0.01:
            self._render_segment_beams(mvp, model, color, dimmer)

    def _render_segment_beams(self, mvp: glm.mat4, model: glm.mat4,
                               color: Tuple[float, float, float], dimmer: float):
        """Render beams for all segments with the same color/intensity."""
        if not hasattr(self, 'segment_beam_vao') or not self.segment_beam_vao:
            return

        # Enable additive blending
        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE)
        self.ctx.depth_mask = False

        final_mvp = mvp * model
        mvp_bytes = np.array([x for col in final_mvp.to_list() for x in col], dtype='f4').tobytes()

        self.beam_program['mvp'].write(mvp_bytes)
        self.beam_program['beam_color'].value = color
        self.beam_program['beam_intensity'].value = dimmer * self.brightness_scale

        # Render all segment beams at once (same color for all)
        self.segment_beam_vao.render(moderngl.TRIANGLES)

        # Restore state
        self.ctx.depth_mask = True
        self.ctx.disable(moderngl.BLEND)

    def release(self):
        """Release GPU resources."""
        super().release()
        if hasattr(self, 'segment_vao') and self.segment_vao:
            self.segment_vao.release()
        if hasattr(self, 'segment_vbo') and self.segment_vbo:
            self.segment_vbo.release()
        if hasattr(self, 'segment_nbo') and self.segment_nbo:
            self.segment_nbo.release()
        # Segment beam resources
        if hasattr(self, 'segment_beam_vao') and self.segment_beam_vao:
            self.segment_beam_vao.release()
        if hasattr(self, 'segment_beam_vbo') and self.segment_beam_vbo:
            self.segment_beam_vbo.release()
        if hasattr(self, 'segment_beam_abo') and self.segment_beam_abo:
            self.segment_beam_abo.release()
        # Coordinate axes resources
        for attr in ['x_axis_vao', 'x_axis_vbo', 'x_axis_nbo',
                     'y_axis_vao', 'y_axis_vbo', 'y_axis_nbo',
                     'z_axis_vao', 'z_axis_vbo', 'z_axis_nbo']:
            obj = getattr(self, attr, None)
            if obj:
                obj.release()


class PixelBarRenderer(FixtureRenderer):
    """
    Renderer for pixel-controlled LED bar fixtures with per-segment RGBW control.

    Unlike LEDBarRenderer which uses single RGBW values for all segments,
    PixelBarRenderer reads individual RGBW channels for each segment from DMX,
    allowing full per-pixel control like the Varytec Giga Bar 5.
    """

    BODY_COLOR = (0.15, 0.15, 0.18)

    def __init__(self, ctx: moderngl.Context, fixture_data: Dict[str, Any]):
        super().__init__(ctx, fixture_data)

        # Parse pixel segment channel mappings from fixture data
        # Format: [{'red': ch_num, 'green': ch_num, 'blue': ch_num, 'white': ch_num}, ...]
        self.pixel_segments = fixture_data.get('pixel_segments', [])

        # If no pixel_segments provided, fall back to layout-based sequential channels
        if not self.pixel_segments and self.segment_cols > 1:
            # Assume RGBW sequential for each segment
            self._generate_sequential_pixel_segments()

        # Store per-segment colors (RGBW tuples normalized 0-1)
        self.segment_colors = [(0.0, 0.0, 0.0, 0.0)] * self.segment_cols

        self._create_geometry()
        self._create_segment_beams()

    def _generate_sequential_pixel_segments(self):
        """Generate sequential RGBW channel mappings for segments."""
        self.pixel_segments = []
        # Assume layout: Segment1(R,G,B,W), Segment2(R,G,B,W), ...
        for i in range(self.segment_cols):
            base_ch = i * 4  # 4 channels per segment (RGBW)
            self.pixel_segments.append({
                'red': base_ch,
                'green': base_ch + 1,
                'blue': base_ch + 2,
                'white': base_ch + 3
            })

    def _create_geometry(self):
        """Create bar body and segment geometry."""
        # Create shader program
        self.program = self.ctx.program(
            vertex_shader=FIXTURE_VERTEX_SHADER,
            fragment_shader=FIXTURE_FRAGMENT_SHADER
        )

        # Create bar body (housing)
        body_verts, body_norms = GeometryBuilder.create_box(
            self.width, self.height, self.depth
        )

        self.vbo = self.ctx.buffer(body_verts.tobytes())
        self.nbo = self.ctx.buffer(body_norms.tobytes())

        self.vao = self.ctx.vertex_array(
            self.program,
            [
                (self.vbo, '3f', 'in_position'),
                (self.nbo, '3f', 'in_normal'),
            ]
        )
        self.body_vertex_count = len(body_verts) // 3

        # Create individual segment geometry (each segment rendered separately for per-pixel color)
        segment_width = (self.width * 0.9) / self.segment_cols
        segment_height = self.height * 0.6
        segment_depth = 0.01  # Thin emitter surface

        self.segment_vaos = []
        self.segment_vbos = []
        self.segment_nbos = []

        start_x = -self.width * 0.45 + segment_width / 2

        for i in range(self.segment_cols):
            x_offset = start_x + i * segment_width
            verts, norms = GeometryBuilder.create_box(
                segment_width * 0.85,
                segment_height,
                segment_depth,
                center=(x_offset, 0, self.depth / 2 + segment_depth / 2)
            )

            vbo = self.ctx.buffer(np.array(verts, dtype='f4').tobytes())
            nbo = self.ctx.buffer(np.array(norms, dtype='f4').tobytes())

            vao = self.ctx.vertex_array(
                self.program,
                [
                    (vbo, '3f', 'in_position'),
                    (nbo, '3f', 'in_normal'),
                ]
            )

            self.segment_vbos.append(vbo)
            self.segment_nbos.append(nbo)
            self.segment_vaos.append(vao)

        # Store segment dimensions for beam creation
        self.segment_width = segment_width
        self.segment_height = segment_height
        self.segment_start_x = start_x

        # Create coordinate axes for debugging orientation
        self._create_coordinate_axes(axis_origin_z=self.depth / 2 + 0.01)

    def _create_coordinate_axes(self, axis_origin_z: float):
        """Create coordinate axes for debugging fixture orientation.

        Args:
            axis_origin_z: Z position for axis origin (top of fixture)
        """
        # Axis length should exceed bar width for visibility
        axis_length = max(self.width, self.height) + 0.1  # Exceed bar dimensions
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

        self.x_axis_vbo = self.ctx.buffer(x_axis_verts.tobytes())
        self.x_axis_nbo = self.ctx.buffer(x_axis_norms.tobytes())
        self.x_axis_vao = self.ctx.vertex_array(
            self.program,
            [(self.x_axis_vbo, '3f', 'in_position'), (self.x_axis_nbo, '3f', 'in_normal')]
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

        self.y_axis_vbo = self.ctx.buffer(y_axis_verts.tobytes())
        self.y_axis_nbo = self.ctx.buffer(y_axis_norms.tobytes())
        self.y_axis_vao = self.ctx.vertex_array(
            self.program,
            [(self.y_axis_vbo, '3f', 'in_position'), (self.y_axis_nbo, '3f', 'in_normal')]
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

        self.z_axis_vbo = self.ctx.buffer(z_axis_verts.tobytes())
        self.z_axis_nbo = self.ctx.buffer(z_axis_norms.tobytes())
        self.z_axis_vao = self.ctx.vertex_array(
            self.program,
            [(self.z_axis_vbo, '3f', 'in_position'), (self.z_axis_nbo, '3f', 'in_normal')]
        )

    def _create_segment_beams(self):
        """Create per-segment rectangular beams (one VAO per segment for individual colors)."""
        self.beam_program = self.ctx.program(
            vertex_shader=BEAM_VERTEX_SHADER,
            fragment_shader=BEAM_FRAGMENT_SHADER
        )

        beam_length = 0.3  # Short glow near fixture face
        beam_width = self.segment_width * 0.7
        beam_height = self.segment_height * 0.7

        self.segment_beam_vaos = []
        self.segment_beam_vbos = []
        self.segment_beam_abos = []

        for i in range(self.segment_cols):
            x_offset = self.segment_start_x + i * self.segment_width
            base_verts, base_alphas = GeometryBuilder.create_beam_box(
                beam_width, beam_height, beam_length
            )

            # Translate beam to segment position
            beam_verts = []
            for j in range(0, len(base_verts), 3):
                x, y, z = base_verts[j], base_verts[j+1], base_verts[j+2]
                new_x = x + x_offset
                new_y = y
                new_z = z + self.depth / 2 + 0.02
                beam_verts.extend([new_x, new_y, new_z])

            vbo = self.ctx.buffer(np.array(beam_verts, dtype='f4').tobytes())
            abo = self.ctx.buffer(np.array(base_alphas, dtype='f4').tobytes())

            vao = self.ctx.vertex_array(
                self.beam_program,
                [
                    (vbo, '3f', 'in_position'),
                    (abo, '1f', 'in_alpha'),
                ]
            )

            self.segment_beam_vbos.append(vbo)
            self.segment_beam_abos.append(abo)
            self.segment_beam_vaos.append(vao)

    def update_dmx(self, dmx_data: bytes):
        """Update DMX values and calculate per-segment colors."""
        super().update_dmx(dmx_data)

        # Get master dimmer (if any)
        master_dimmer = self.dmx_values.get('dimmer', 255) / 255.0

        # Update per-segment colors from pixel_segments channel mapping
        base_address = self.address - 1  # Convert to 0-indexed

        new_colors = []
        for i, segment in enumerate(self.pixel_segments):
            if i >= self.segment_cols:
                break

            # Get RGBW channel indices relative to fixture address
            r_ch = segment.get('red')
            g_ch = segment.get('green')
            b_ch = segment.get('blue')
            w_ch = segment.get('white')

            # Read DMX values for this segment
            r = dmx_data[base_address + r_ch] / 255.0 if r_ch is not None and base_address + r_ch < 512 else 0.0
            g = dmx_data[base_address + g_ch] / 255.0 if g_ch is not None and base_address + g_ch < 512 else 0.0
            b = dmx_data[base_address + b_ch] / 255.0 if b_ch is not None and base_address + b_ch < 512 else 0.0
            w = dmx_data[base_address + w_ch] / 255.0 if w_ch is not None and base_address + w_ch < 512 else 0.0

            # Apply master dimmer
            r *= master_dimmer
            g *= master_dimmer
            b *= master_dimmer
            w *= master_dimmer

            new_colors.append((r, g, b, w))

        # Pad with zeros if fewer segments parsed than layout width
        while len(new_colors) < self.segment_cols:
            new_colors.append((0.0, 0.0, 0.0, 0.0))

        self.segment_colors = new_colors

    def render(self, mvp: glm.mat4):
        """Render the pixel bar with per-segment colors."""
        # Reset OpenGL state
        self.ctx.disable(moderngl.BLEND)
        self.ctx.depth_mask = True

        model = self.get_model_matrix()
        final_mvp = mvp * model

        # Convert matrices to bytes
        mvp_bytes = np.array([x for col in final_mvp.to_list() for x in col], dtype='f4').tobytes()
        model_bytes = np.array([x for col in model.to_list() for x in col], dtype='f4').tobytes()

        self.program['mvp'].write(mvp_bytes)
        self.program['model'].write(model_bytes)

        # Render body
        self.program['base_color'].value = self.BODY_COLOR
        self.program['emissive_color'].value = (0.0, 0.0, 0.0)
        self.program['emissive_strength'].value = 0.0
        self.vao.render(moderngl.TRIANGLES)

        # Render coordinate axes
        if hasattr(self, 'x_axis_vao') and self.x_axis_vao:
            self.program['base_color'].value = (0.9, 0.2, 0.2)  # Red
            self.x_axis_vao.render(moderngl.TRIANGLES)
        if hasattr(self, 'y_axis_vao') and self.y_axis_vao:
            self.program['base_color'].value = (0.2, 0.4, 0.9)  # Blue
            self.y_axis_vao.render(moderngl.TRIANGLES)
        if hasattr(self, 'z_axis_vao') and self.z_axis_vao:
            self.program['base_color'].value = (0.2, 0.8, 0.2)  # Green
            self.z_axis_vao.render(moderngl.TRIANGLES)

        # Render each segment with its own color
        for i, vao in enumerate(self.segment_vaos):
            if i < len(self.segment_colors):
                r, g, b, w = self.segment_colors[i]
                # Add white channel contribution to RGB
                color = (
                    min(1.0, r + w),
                    min(1.0, g + w),
                    min(1.0, b + w)
                )
                intensity = max(r, g, b, w)  # Use brightest channel as intensity
            else:
                color = (0.0, 0.0, 0.0)
                intensity = 0.0

            self.program['base_color'].value = (0.1, 0.1, 0.1)
            self.program['emissive_color'].value = color
            self.program['emissive_strength'].value = intensity * self.brightness_scale
            vao.render(moderngl.TRIANGLES)

        # Render beams for segments that are lit
        self._render_segment_beams(mvp, model)

    def _render_segment_beams(self, mvp: glm.mat4, model: glm.mat4):
        """Render beams for each segment with its individual color."""
        if not self.segment_beam_vaos:
            return

        # Enable additive blending
        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE)
        self.ctx.depth_mask = False

        final_mvp = mvp * model
        mvp_bytes = np.array([x for col in final_mvp.to_list() for x in col], dtype='f4').tobytes()

        self.beam_program['mvp'].write(mvp_bytes)

        for i, vao in enumerate(self.segment_beam_vaos):
            if i < len(self.segment_colors):
                r, g, b, w = self.segment_colors[i]
                color = (
                    min(1.0, r + w),
                    min(1.0, g + w),
                    min(1.0, b + w)
                )
                intensity = max(r, g, b, w)
            else:
                continue

            if intensity < 0.01:
                continue  # Skip dark segments

            self.beam_program['beam_color'].value = color
            self.beam_program['beam_intensity'].value = intensity * self.brightness_scale
            vao.render(moderngl.TRIANGLES)

        # Restore state
        self.ctx.depth_mask = True
        self.ctx.disable(moderngl.BLEND)

    def release(self):
        """Release GPU resources."""
        super().release()
        # Release segment VAOs
        for vao in getattr(self, 'segment_vaos', []):
            if vao:
                vao.release()
        for vbo in getattr(self, 'segment_vbos', []):
            if vbo:
                vbo.release()
        for nbo in getattr(self, 'segment_nbos', []):
            if nbo:
                nbo.release()
        # Release beam VAOs
        for vao in getattr(self, 'segment_beam_vaos', []):
            if vao:
                vao.release()
        for vbo in getattr(self, 'segment_beam_vbos', []):
            if vbo:
                vbo.release()
        for abo in getattr(self, 'segment_beam_abos', []):
            if abo:
                abo.release()
        # Coordinate axes resources
        for attr in ['x_axis_vao', 'x_axis_vbo', 'x_axis_nbo',
                     'y_axis_vao', 'y_axis_vbo', 'y_axis_nbo',
                     'z_axis_vao', 'z_axis_vbo', 'z_axis_nbo']:
            obj = getattr(self, attr, None)
            if obj:
                obj.release()


class SunstripRenderer(FixtureRenderer):
    """Renderer for sunstrip fixtures with warm white segments."""

    BODY_COLOR = (0.12, 0.12, 0.15)

    def __init__(self, ctx: moderngl.Context, fixture_data: Dict[str, Any]):
        super().__init__(ctx, fixture_data)
        self._create_geometry()
        self._create_segment_beams()

    def _create_geometry(self):
        """Create sunstrip body and lamp geometry."""
        self.program = self.ctx.program(
            vertex_shader=FIXTURE_VERTEX_SHADER,
            fragment_shader=FIXTURE_FRAGMENT_SHADER
        )

        # Create bar body
        body_verts, body_norms = GeometryBuilder.create_box(
            self.width, self.height, self.depth
        )

        self.vbo = self.ctx.buffer(body_verts.tobytes())
        self.nbo = self.ctx.buffer(body_norms.tobytes())

        self.vao = self.ctx.vertex_array(
            self.program,
            [
                (self.vbo, '3f', 'in_position'),
                (self.nbo, '3f', 'in_normal'),
            ]
        )

        # Create individual lamp bulbs (cylinders) - lamps face +Z (up)
        lamp_radius = min(self.width / self.segment_cols * 0.35, 0.03)
        lamp_height = 0.02

        lamp_verts = []
        lamp_norms = []

        spacing = self.width * 0.9 / self.segment_cols
        start_x = -self.width * 0.45 + spacing / 2

        for i in range(self.segment_cols):
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
                new_z = y + self.depth / 2 + lamp_height / 2
                lamp_verts.extend([new_x, new_y, new_z])
            for j in range(0, len(norms_raw), 3):
                nx, ny, nz = norms_raw[j], norms_raw[j+1], norms_raw[j+2]
                lamp_norms.extend([nx, -nz, ny])

        self.lamp_vbo = self.ctx.buffer(np.array(lamp_verts, dtype='f4').tobytes())
        self.lamp_nbo = self.ctx.buffer(np.array(lamp_norms, dtype='f4').tobytes())

        self.lamp_vao = self.ctx.vertex_array(
            self.program,
            [
                (self.lamp_vbo, '3f', 'in_position'),
                (self.lamp_nbo, '3f', 'in_normal'),
            ]
        )
        self.lamp_vertex_count = len(lamp_verts) // 3
        self.vertices_per_lamp = self.lamp_vertex_count // self.segment_cols

        # Store lamp positions and radius for beam rendering
        self.lamp_radius = lamp_radius
        self.lamp_spacing = spacing
        self.lamp_start_x = start_x

        # Create coordinate axes for debugging orientation
        # For bar fixtures, make axes longer than bar width for visibility
        self._create_coordinate_axes(axis_origin_z=self.depth / 2 + 0.01)

    def _create_coordinate_axes(self, axis_origin_z: float):
        """Create coordinate axes for debugging fixture orientation.

        Args:
            axis_origin_z: Z position for axis origin (top of fixture)
        """
        # Axis length should exceed bar width for visibility
        axis_length = max(self.width, self.height) + 0.1  # Exceed bar dimensions
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

        self.x_axis_vbo = self.ctx.buffer(x_axis_verts.tobytes())
        self.x_axis_nbo = self.ctx.buffer(x_axis_norms.tobytes())
        self.x_axis_vao = self.ctx.vertex_array(
            self.program,
            [(self.x_axis_vbo, '3f', 'in_position'), (self.x_axis_nbo, '3f', 'in_normal')]
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

        self.y_axis_vbo = self.ctx.buffer(y_axis_verts.tobytes())
        self.y_axis_nbo = self.ctx.buffer(y_axis_norms.tobytes())
        self.y_axis_vao = self.ctx.vertex_array(
            self.program,
            [(self.y_axis_vbo, '3f', 'in_position'), (self.y_axis_nbo, '3f', 'in_normal')]
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

        self.z_axis_vbo = self.ctx.buffer(z_axis_verts.tobytes())
        self.z_axis_nbo = self.ctx.buffer(z_axis_norms.tobytes())
        self.z_axis_vao = self.ctx.vertex_array(
            self.program,
            [(self.z_axis_vbo, '3f', 'in_position'), (self.z_axis_nbo, '3f', 'in_normal')]
        )

    def _create_segment_beams(self):
        """Create per-segment cylindrical beams for each lamp."""
        self.beam_program = self.ctx.program(
            vertex_shader=BEAM_VERTEX_SHADER,
            fragment_shader=BEAM_FRAGMENT_SHADER
        )

        beam_length = 0.3  # Short glow near fixture face
        beam_radius = self.lamp_radius * 0.8  # Slightly smaller than lamp

        # Create beam geometry for all segments
        all_beam_verts = []
        all_beam_alphas = []

        for i in range(self.segment_cols):
            x_offset = self.lamp_start_x + i * self.lamp_spacing
            # Beam starts at top of lamp, extends upward along +Z
            base_verts, base_alphas = GeometryBuilder.create_beam_cylinder(
                beam_radius, beam_length, segments=8
            )

            # Transform beam vertices to lamp position
            # Beam already extends along +Z, just translate to position
            for j in range(0, len(base_verts), 3):
                x, y, z = base_verts[j], base_verts[j+1], base_verts[j+2]
                new_x = x + x_offset
                new_y = y
                new_z = z + self.depth / 2 + 0.02  # Start above lamp face (+Z)
                all_beam_verts.extend([new_x, new_y, new_z])

            all_beam_alphas.extend(base_alphas)

        self.segment_beam_vbo = self.ctx.buffer(np.array(all_beam_verts, dtype='f4').tobytes())
        self.segment_beam_abo = self.ctx.buffer(np.array(all_beam_alphas, dtype='f4').tobytes())

        self.segment_beam_vao = self.ctx.vertex_array(
            self.beam_program,
            [
                (self.segment_beam_vbo, '3f', 'in_position'),
                (self.segment_beam_abo, '1f', 'in_alpha'),
            ]
        )

        # Calculate vertices per beam for individual rendering
        single_beam_verts, _ = GeometryBuilder.create_beam_cylinder(beam_radius, beam_length, segments=8)
        self.vertices_per_beam = len(single_beam_verts) // 3

    def render(self, mvp: glm.mat4):
        """Render the sunstrip with per-segment dimming."""
        # Reset OpenGL state to prevent transparency issues from previous beam rendering
        self.ctx.disable(moderngl.BLEND)
        self.ctx.depth_mask = True

        model = self.get_model_matrix()
        final_mvp = mvp * model

        mvp_bytes = np.array([x for col in final_mvp.to_list() for x in col], dtype='f4').tobytes()
        model_bytes = np.array([x for col in model.to_list() for x in col], dtype='f4').tobytes()

        self.program['mvp'].write(mvp_bytes)
        self.program['model'].write(model_bytes)

        # Render body
        self.program['base_color'].value = self.BODY_COLOR
        self.program['emissive_color'].value = (0.0, 0.0, 0.0)
        self.program['emissive_strength'].value = 0.0
        self.vao.render(moderngl.TRIANGLES)

        # Render coordinate axes
        if hasattr(self, 'x_axis_vao') and self.x_axis_vao:
            self.program['base_color'].value = (0.9, 0.2, 0.2)  # Red
            self.x_axis_vao.render(moderngl.TRIANGLES)
        if hasattr(self, 'y_axis_vao') and self.y_axis_vao:
            self.program['base_color'].value = (0.2, 0.4, 0.9)  # Blue
            self.y_axis_vao.render(moderngl.TRIANGLES)
        if hasattr(self, 'z_axis_vao') and self.z_axis_vao:
            self.program['base_color'].value = (0.2, 0.8, 0.2)  # Green
            self.z_axis_vao.render(moderngl.TRIANGLES)

        # Render each lamp segment with its own dimmer value
        self.program['base_color'].value = (0.9, 0.85, 0.7)  # Bulb glass color

        # Get per-segment DMX values (or fall back to single dimmer)
        segment_values = getattr(self, 'segment_values', [])

        for i in range(self.segment_cols):
            # Get dimmer for this segment
            if i < len(segment_values):
                dimmer = segment_values[i] / 255.0
            else:
                dimmer = self.get_dimmer()

            emissive = (
                WARM_WHITE_COLOR[0] * dimmer,
                WARM_WHITE_COLOR[1] * dimmer,
                WARM_WHITE_COLOR[2] * dimmer
            )

            self.program['emissive_color'].value = emissive
            self.program['emissive_strength'].value = (1.5 if dimmer > 0.1 else 0.0) * self.brightness_scale

            # Render just this lamp's vertices
            first_vertex = i * self.vertices_per_lamp
            self.lamp_vao.render(
                moderngl.TRIANGLES,
                vertices=self.vertices_per_lamp,
                first=first_vertex
            )

        # Render per-segment beams
        self._render_segment_beams(mvp, model, segment_values)

    def _render_segment_beams(self, mvp: glm.mat4, model: glm.mat4, segment_values: List[int]):
        """Render individual beams for each segment."""
        if not hasattr(self, 'segment_beam_vao') or not self.segment_beam_vao:
            return

        # Enable additive blending for beams
        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE)
        self.ctx.depth_mask = False

        final_mvp = mvp * model
        mvp_bytes = np.array([x for col in final_mvp.to_list() for x in col], dtype='f4').tobytes()
        self.beam_program['mvp'].write(mvp_bytes)

        # Render each segment's beam with its own intensity
        for i in range(self.segment_cols):
            if i < len(segment_values):
                dimmer = segment_values[i] / 255.0
            else:
                dimmer = self.get_dimmer()

            if dimmer > 0.01:
                self.beam_program['beam_color'].value = WARM_WHITE_COLOR
                self.beam_program['beam_intensity'].value = dimmer * self.brightness_scale

                first_vertex = i * self.vertices_per_beam
                self.segment_beam_vao.render(
                    moderngl.TRIANGLES,
                    vertices=self.vertices_per_beam,
                    first=first_vertex
                )

        # Restore state
        self.ctx.depth_mask = True
        self.ctx.disable(moderngl.BLEND)

    def release(self):
        """Release GPU resources."""
        super().release()
        if hasattr(self, 'lamp_vao') and self.lamp_vao:
            self.lamp_vao.release()
        if hasattr(self, 'lamp_vbo') and self.lamp_vbo:
            self.lamp_vbo.release()
        if hasattr(self, 'lamp_nbo') and self.lamp_nbo:
            self.lamp_nbo.release()
        # Segment beam resources
        if hasattr(self, 'segment_beam_vao') and self.segment_beam_vao:
            self.segment_beam_vao.release()
        if hasattr(self, 'segment_beam_vbo') and self.segment_beam_vbo:
            self.segment_beam_vbo.release()
        if hasattr(self, 'segment_beam_abo') and self.segment_beam_abo:
            self.segment_beam_abo.release()
        # Coordinate axes resources
        for attr in ['x_axis_vao', 'x_axis_vbo', 'x_axis_nbo',
                     'y_axis_vao', 'y_axis_vbo', 'y_axis_nbo',
                     'z_axis_vao', 'z_axis_vbo', 'z_axis_nbo']:
            obj = getattr(self, attr, None)
            if obj:
                obj.release()


class MovingHeadRenderer(FixtureRenderer):
    """Renderer for moving head fixtures with base, yoke, and head."""

    BODY_COLOR = (0.1, 0.1, 0.12)
    YOKE_COLOR = (0.15, 0.15, 0.18)

    def __init__(self, ctx: moderngl.Context, fixture_data: Dict[str, Any]):
        super().__init__(ctx, fixture_data)

        # Movement range
        self.pan_max = fixture_data.get('pan_max', 540.0)
        self.tilt_max = fixture_data.get('tilt_max', 270.0)

        # Color wheel data - list of {min, max, color} dicts
        self.color_wheel = fixture_data.get('color_wheel', [])

        # Gobo wheel data - list of {min, max, name, pattern} dicts
        self.gobo_wheel = fixture_data.get('gobo_wheel', [])

        # Current pan/tilt angles (degrees)
        self.current_pan = 0.0
        self.current_tilt = 0.0

        # Gobo rotation state
        self.gobo_rotation_angle = 0.0  # Current rotation angle in radians
        self.last_update_time = 0.0  # For tracking time between updates

        self._create_geometry()

    def get_color_from_wheel(self, dmx_value: int) -> Tuple[float, float, float]:
        """
        Get RGB color from color wheel based on DMX value.

        Args:
            dmx_value: DMX value (0-255)

        Returns:
            RGB tuple (0.0-1.0)
        """
        if not self.color_wheel:
            return (1.0, 1.0, 1.0)  # Default white

        for entry in self.color_wheel:
            if entry['min'] <= dmx_value <= entry['max']:
                color_hex = entry['color']
                # Parse hex color
                if color_hex.startswith('#'):
                    color_hex = color_hex[1:]
                try:
                    r = int(color_hex[0:2], 16) / 255.0
                    g = int(color_hex[2:4], 16) / 255.0
                    b = int(color_hex[4:6], 16) / 255.0
                    return (r, g, b)
                except (ValueError, IndexError):
                    pass

        return (1.0, 1.0, 1.0)  # Default white if no match

    def get_color(self) -> Tuple[float, float, float]:
        """Get current color, using color wheel if available."""
        # First check if we have RGB channels
        color = super().get_color()

        # If no RGB color and we have a color wheel, use it
        if color == (0.0, 0.0, 0.0) and self.color_wheel:
            color_wheel_value = self.dmx_values.get('color_wheel', 0)
            wheel_color = self.get_color_from_wheel(color_wheel_value)
            # Debug: log color wheel usage occasionally
            if not hasattr(self, '_color_log_count'):
                self._color_log_count = 0
            if self._color_log_count < 3 and color_wheel_value > 0:
                self._color_log_count += 1
                print(f"MH {self.name}: color_wheel DMX={color_wheel_value} -> RGB={wheel_color}")
            return wheel_color

        # If still no color from wheel (no wheel data), use white as fallback
        if color == (0.0, 0.0, 0.0):
            return (1.0, 1.0, 1.0)

        return color

    def get_gobo_pattern(self) -> int:
        """
        Get the procedural gobo pattern ID from DMX value.

        Returns:
            Pattern ID (0=open, 1=dots, 2=star, 3=lines, 4=triangle, 5=cross, 6=breakup)
        """
        gobo_dmx = self.dmx_values.get('gobo', 0)

        if not self.gobo_wheel or gobo_dmx == 0:
            return 0  # Open (no gobo)

        # Find matching gobo entry
        for entry in self.gobo_wheel:
            if entry['min'] <= gobo_dmx <= entry['max']:
                return entry.get('pattern', 6)  # Default to breakup if no pattern

        return 0  # Default to open

    def update_gobo_rotation(self, delta_time: float):
        """
        Update gobo rotation based on DMX rotation speed.

        Args:
            delta_time: Time since last update in seconds
        """
        # gobo rotation DMX channel controls speed
        # 0 = no rotation, 1-127 = CW slow to fast, 128-255 = CCW slow to fast
        rotation_dmx = self.dmx_values.get('gobo_rotation', 0)

        if rotation_dmx == 0:
            return  # No rotation

        # Calculate rotation speed (radians per second)
        if rotation_dmx < 128:
            # Clockwise: 1-127 maps to slow-fast
            speed = (rotation_dmx / 127.0) * math.pi * 2  # Up to 1 revolution/sec
        else:
            # Counter-clockwise: 128-255 maps to slow-fast
            speed = -((rotation_dmx - 128) / 127.0) * math.pi * 2

        self.gobo_rotation_angle += speed * delta_time

        # Keep angle in reasonable range
        self.gobo_rotation_angle = self.gobo_rotation_angle % (2 * math.pi)

    def get_focus_sharpness(self, projection_distance: Optional[float] = None) -> float:
        """
        Calculate focus sharpness based on distance to projection.

        Real focus works like a lens: it's sharp at the focused distance,
        and blurs the further you are from that distance.

        Args:
            projection_distance: Distance from lens to floor (if known).
                                If None, uses a default based on fixture height.

        Returns:
            Sharpness value from 0.0 (fully blurred) to 1.0 (perfectly sharp)
        """
        # Get focus DMX value (0-255)
        focus_dmx = self.dmx_values.get('focus', 127)

        # Map focus DMX to a "focused distance" in meters
        # DMX 0 = 1m (near focus), DMX 255 = 10m (far focus)
        # Linear mapping: focus_distance = 1 + (focus_dmx / 255) * 9
        min_focus_distance = 1.0  # meters
        max_focus_distance = 10.0  # meters
        focus_distance = min_focus_distance + (focus_dmx / 255.0) * (max_focus_distance - min_focus_distance)

        # If projection distance not provided, estimate from fixture position
        if projection_distance is None:
            # Use fixture height as rough estimate
            projection_distance = self.position.get('z', 3.0)

        # Calculate sharpness based on how close projection is to focus distance
        # At focus distance: sharpness = 1.0
        # Further away: sharpness decreases
        distance_error = abs(projection_distance - focus_distance)

        # Use a gaussian-like falloff for sharpness
        # blur_rate controls how fast sharpness falls off with distance error
        # 0.3 means ~50% sharpness at 1.2m from focused distance
        blur_rate = 0.3
        sharpness = math.exp(-distance_error * distance_error * blur_rate)

        # Clamp to valid range
        return max(0.0, min(1.0, sharpness))

    def get_floor_projection_distance(self) -> Optional[float]:
        """
        Calculate the distance from lens to floor intersection.

        Returns:
            Distance in meters, or None if beam doesn't hit the floor.
        """
        beam_dir = self.get_beam_direction()

        # Check if beam points downward
        if beam_dir.y >= 0:
            return None

        # Get lens world position
        lens_height = self.position.get('z', 3.0)  # Use Z (height in Y-up coordinate system)

        # Calculate distance along beam to floor (Y=0)
        # Ray: P = lens + t * dir, at floor: P.y = 0
        # Note: In visualizer Y-up system, lens_height represents Y coordinate
        # But we store position as x, y (floor), z (height)
        # So lens_height is the actual height above floor

        # Distance = height / |beam_dir.y|
        distance = lens_height / abs(beam_dir.y)

        # Clamp to reasonable beam length
        if distance > 10.0:
            return 10.0

        return distance

    def _create_geometry(self):
        """Create base, yoke, and head geometry.

        Coordinate system (Z-up, matching global stage coordinates):
        - X-Y plane: horizontal (base plate)
        - Z: vertical (up)
        - At Pan=0, Tilt=0: beam points +X
        - Pan: rotation around Z-axis (vertical)
        - Tilt: rotation around yoke's local Y-axis

        See reference.md for full coordinate system documentation.
        """
        self.program = self.ctx.program(
            vertex_shader=FIXTURE_VERTEX_SHADER,
            fragment_shader=FIXTURE_FRAGMENT_SHADER
        )

        # Proportions based on physical dimensions
        base_size = min(self.width, self.depth)
        base_thickness = self.height * 0.15  # Thickness in Z direction (up)

        yoke_thickness = base_size * 0.15  # Thickness of yoke arms
        yoke_height = self.height * 0.5  # Height in Z direction (up)
        yoke_depth = base_size * 0.8  # Depth along X (forward direction at Pan=0)

        # Head dimensions in local space (before pan/tilt):
        # X = forward/back (toward lens), Y = left/right (tilt axis), Z = up/down
        head_size_x = base_size * 0.5  # Forward/back dimension
        head_size_y = base_size * 0.7  # Left/right dimension (tilt axis)
        head_size_z = self.height * 0.45  # Up/down dimension

        # Create base (rectangular box in X-Y plane, Z is thickness/up)
        base_verts, base_norms = GeometryBuilder.create_box(
            base_size, base_size, base_thickness,
            center=(0, 0, base_thickness / 2)
        )
        self.base_vbo = self.ctx.buffer(base_verts.tobytes())
        self.base_nbo = self.ctx.buffer(base_norms.tobytes())
        self.base_vao = self.ctx.vertex_array(
            self.program,
            [(self.base_vbo, '3f', 'in_position'), (self.base_nbo, '3f', 'in_normal')]
        )
        self.base_vertex_count = len(base_verts) // 3

        # Create coordinate axes on base for debugging orientation
        # Origin at center of base top surface
        axis_origin_z = base_thickness + 0.01
        axis_length = 0.4  # 40cm axes for visibility
        axis_thickness = 0.008  # Thin lines
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

        self.x_axis_vbo = self.ctx.buffer(x_axis_verts.tobytes())
        self.x_axis_nbo = self.ctx.buffer(x_axis_norms.tobytes())
        self.x_axis_vao = self.ctx.vertex_array(
            self.program,
            [(self.x_axis_vbo, '3f', 'in_position'), (self.x_axis_nbo, '3f', 'in_normal')]
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

        self.y_axis_vbo = self.ctx.buffer(y_axis_verts.tobytes())
        self.y_axis_nbo = self.ctx.buffer(y_axis_norms.tobytes())
        self.y_axis_vao = self.ctx.vertex_array(
            self.program,
            [(self.y_axis_vbo, '3f', 'in_position'), (self.y_axis_nbo, '3f', 'in_normal')]
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

        self.z_axis_vbo = self.ctx.buffer(z_axis_verts.tobytes())
        self.z_axis_nbo = self.ctx.buffer(z_axis_norms.tobytes())
        self.z_axis_vao = self.ctx.vertex_array(
            self.program,
            [(self.z_axis_vbo, '3f', 'in_position'), (self.z_axis_nbo, '3f', 'in_normal')]
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

        self.yoke_vbo = self.ctx.buffer(yoke_verts.tobytes())
        self.yoke_nbo = self.ctx.buffer(yoke_norms.tobytes())
        self.yoke_vao = self.ctx.vertex_array(
            self.program,
            [(self.yoke_vbo, '3f', 'in_position'), (self.yoke_nbo, '3f', 'in_normal')]
        )
        self.yoke_vertex_count = len(yoke_verts) // 3

        # Create head (box, will be rotated for tilt around Y-axis)
        # Head created at origin, transformed during render
        # Lens faces +X direction at default position
        head_verts, head_norms = GeometryBuilder.create_box(
            head_size_x, head_size_y, head_size_z
        )
        self.head_vbo = self.ctx.buffer(head_verts.tobytes())
        self.head_nbo = self.ctx.buffer(head_norms.tobytes())
        self.head_vao = self.ctx.vertex_array(
            self.program,
            [(self.head_vbo, '3f', 'in_position'), (self.head_nbo, '3f', 'in_normal')]
        )
        self.head_vertex_count = len(head_verts) // 3

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

        self.lens_vbo = self.ctx.buffer(lens_verts.tobytes())
        self.lens_nbo = self.ctx.buffer(lens_norms.tobytes())
        self.lens_vao = self.ctx.vertex_array(
            self.program,
            [(self.lens_vbo, '3f', 'in_position'), (self.lens_nbo, '3f', 'in_normal')]
        )
        self.lens_vertex_count = len(lens_verts) // 3

        # Store dimensions for head positioning (Z-up coordinate system)
        self.base_thickness = base_thickness  # Height of base in Z
        self.base_size = base_size
        self.yoke_height = yoke_height  # Height of yoke in Z direction
        self.head_size_x = head_size_x  # Head size along X (beam direction at Pan=0)
        self.head_size_y = head_size_y  # Head size along Y (tilt axis)
        self.head_size_z = head_size_z  # Head size along Z (up/down)
        self.lens_radius = lens_radius
        self.lens_depth = lens_depth

        # Create beam cone for light visualization
        self._create_beam_geometry()

    def _create_beam_geometry(self):
        """Create beam cone geometry for light visualization with gobo support."""
        # Beam program with gobo pattern support
        self.beam_program = self.ctx.program(
            vertex_shader=GOBO_BEAM_VERTEX_SHADER,
            fragment_shader=GOBO_BEAM_FRAGMENT_SHADER
        )

        # Calculate beam radius at 5m distance based on beam angle
        beam_length = 5.0  # 5 meters
        beam_radius = beam_length * math.tan(math.radians(self.beam_angle / 2))

        beam_verts, beam_alphas = GeometryBuilder.create_beam_cone(
            beam_radius, beam_length, segments=24
        )

        self.beam_vbo = self.ctx.buffer(beam_verts.tobytes())
        self.beam_abo = self.ctx.buffer(beam_alphas.tobytes())

        self.beam_vao = self.ctx.vertex_array(
            self.beam_program,
            [
                (self.beam_vbo, '3f', 'in_position'),
                (self.beam_abo, '1f', 'in_alpha'),
            ]
        )
        self.beam_vertex_count = len(beam_verts) // 3

        # Create floor projection geometry
        self._create_floor_projection_geometry()

    def _create_floor_projection_geometry(self):
        """Create floor projection disk geometry with gobo support."""
        # Use gobo-enabled floor projection shader
        self.floor_proj_program = self.ctx.program(
            vertex_shader=FLOOR_PROJECTION_VERTEX_SHADER,
            fragment_shader=GOBO_FLOOR_PROJECTION_FRAGMENT_SHADER
        )

        # Create unit disk (will be scaled/positioned via model matrix)
        proj_verts, proj_uvs = GeometryBuilder.create_floor_projection_disk(segments=32)

        self.floor_proj_vbo = self.ctx.buffer(proj_verts.tobytes())
        self.floor_proj_ubo = self.ctx.buffer(proj_uvs.tobytes())

        self.floor_proj_vao = self.ctx.vertex_array(
            self.floor_proj_program,
            [
                (self.floor_proj_vbo, '3f', 'in_position'),
                (self.floor_proj_ubo, '2f', 'in_uv'),
            ]
        )
        self.floor_proj_vertex_count = len(proj_verts) // 3

    def _calculate_floor_intersection(self) -> Optional[Tuple[glm.vec3, float, float, float]]:
        """
        Calculate where the beam intersects the floor (Y=0 plane).

        Returns:
            Tuple of (hit_position, major_radius, minor_radius, rotation_angle) or None if no intersection
            - hit_position: World position where beam hits floor
            - major_radius: Major axis of the ellipse (stretched along beam direction)
            - minor_radius: Minor axis of the ellipse (perpendicular to beam)
            - rotation_angle: Rotation around Y axis to orient ellipse
        """
        # Get head position (lens is on the head, which moves with pan/tilt)
        head_z_offset = self.base_thickness + self.yoke_height / 2

        # Build the same transformation chain as render()
        base_model = self.get_model_matrix()

        # Pan rotation
        pan_rotation = glm.rotate(glm.mat4(1.0), glm.radians(self.current_pan), glm.vec3(0, 0, 1))

        # Head position and tilt
        head_translate = glm.translate(glm.mat4(1.0), glm.vec3(0, 0, head_z_offset))
        tilt_rotation = glm.rotate(glm.mat4(1.0), glm.radians(-self.current_tilt), glm.vec3(0, 1, 0))

        # Full head transform
        head_model = base_model * pan_rotation * head_translate * tilt_rotation

        # Lens is offset along +X from head center (at tilt=0)
        lens_local_pos = glm.vec3(self.head_size_x / 2 + self.lens_depth, 0, 0)
        lens_world_pos = glm.vec3(head_model * glm.vec4(lens_local_pos, 1.0))

        # Get beam direction in world space
        beam_dir = self.get_beam_direction()

        # Check if beam is pointing downward (toward floor)
        if beam_dir.y >= 0:
            return None

        # Calculate intersection with Y=0 plane
        # Ray: P = lens_pos + t * beam_dir
        # At floor: P.y = 0
        # t = -lens_pos.y / beam_dir.y
        t = -lens_world_pos.y / beam_dir.y

        # Check if intersection is within beam length (5m)
        beam_length = 5.0
        if t <= 0 or t > beam_length:
            return None

        # Calculate hit position
        hit_pos = lens_world_pos + beam_dir * t

        # Calculate beam radius at this distance
        beam_radius = t * math.tan(math.radians(self.beam_angle / 2))

        # Calculate ellipse shape based on angle of incidence
        # When beam hits floor at angle, circle becomes ellipse
        cos_angle = abs(beam_dir.y)  # cos of angle from vertical

        # Minor radius is the beam radius (perpendicular to beam's XZ projection)
        minor_radius = beam_radius

        # Major radius is stretched by 1/cos(angle) along the beam's XZ direction
        # Clamp to prevent extreme stretching at shallow angles
        major_radius = beam_radius / max(cos_angle, 0.1)

        # Cap the major radius to prevent extremely elongated ellipses
        major_radius = min(major_radius, beam_radius * 5.0)

        # Calculate rotation angle for ellipse orientation
        # The major axis should align with the XZ projection of the beam direction
        beam_xz = glm.vec2(beam_dir.x, beam_dir.z)
        if glm.length(beam_xz) > 0.01:
            beam_xz = glm.normalize(beam_xz)
            rotation_angle = math.degrees(math.atan2(beam_xz.x, beam_xz.y))
        else:
            rotation_angle = 0.0

        return (hit_pos, major_radius, minor_radius, rotation_angle)

    def update_dmx(self, dmx_data: bytes):
        """Update DMX values and calculate pan/tilt angles."""
        super().update_dmx(dmx_data)

        # Calculate pan angle from DMX
        pan_coarse = self.dmx_values.get('pan', 127)
        pan_fine = self.dmx_values.get('pan_fine', 0)
        pan_combined = (pan_coarse * 256 + pan_fine) / 65535.0

        # Calculate tilt angle from DMX
        tilt_coarse = self.dmx_values.get('tilt', 127)
        tilt_fine = self.dmx_values.get('tilt_fine', 0)
        tilt_combined = (tilt_coarse * 256 + tilt_fine) / 65535.0

        # Map to rotation angles using fixture's pan_max and tilt_max
        # Center-based mapping: DMX 127 = center (0°)
        # DMX 0 = -pan_max/2, DMX 255 = +pan_max/2
        self.current_pan = (pan_combined - 0.5) * self.pan_max

        # Same for tilt: DMX 127 = center (0°)
        # DMX 0 = -tilt_max/2, DMX 255 = +tilt_max/2
        self.current_tilt = (tilt_combined - 0.5) * self.tilt_max

    def get_beam_direction(self) -> glm.vec3:
        """Get the beam direction vector based on current pan/tilt and fixture orientation.

        Y-up coordinate system (matches visualizer):
        - At Pan=0, Tilt=0: beam points along local +X
        - Pan rotates around local Z axis
        - Tilt rotates around local Y axis
        """
        # Start with forward direction (+X at Pan=0, Tilt=0)
        direction = glm.vec3(1, 0, 0)

        # Apply tilt (rotation around Y axis, negated to go +X toward -Y at max tilt)
        # Tilt=0: forward (+X), increasing tilt -> down toward floor
        tilt_rad = glm.radians(-self.current_tilt)
        tilt_mat = glm.rotate(glm.mat4(1.0), tilt_rad, glm.vec3(0, 1, 0))

        # Apply pan (rotation around Z axis in head-local space)
        pan_rad = glm.radians(self.current_pan)
        pan_mat = glm.rotate(glm.mat4(1.0), pan_rad, glm.vec3(0, 0, 1))

        # Build fixture orientation matrix using ABSOLUTE values (same as get_model_matrix)
        # The orientation dialog sends complete orientation values that already
        # include the mounting preset rotation (e.g., hanging = pitch 90°)
        fixture_mat = glm.mat4(1.0)
        fixture_mat = glm.rotate(fixture_mat, glm.radians(self.yaw), glm.vec3(0, 1, 0))
        fixture_mat = glm.rotate(fixture_mat, glm.radians(self.pitch), glm.vec3(1, 0, 0))
        fixture_mat = glm.rotate(fixture_mat, glm.radians(self.roll), glm.vec3(0, 0, 1))

        # Combine rotations: fixture orientation * pan * tilt
        final_mat = fixture_mat * pan_mat * tilt_mat
        direction = glm.vec3(final_mat * glm.vec4(direction, 0.0))

        return glm.normalize(direction)

    def render(self, mvp: glm.mat4):
        """Render the moving head with pan/tilt."""
        import time

        # Update gobo rotation animation
        current_time = time.time()
        if self.last_update_time > 0:
            delta_time = current_time - self.last_update_time
            self.update_gobo_rotation(delta_time)
        self.last_update_time = current_time

        # Ensure clean OpenGL state at start of render
        # This prevents blend state from leaking from previous fixture's beam rendering
        self.ctx.disable(moderngl.BLEND)
        self.ctx.depth_mask = True

        base_model = self.get_model_matrix()

        # Render base (doesn't rotate with pan)
        base_mvp = mvp * base_model
        mvp_bytes = np.array([x for col in base_mvp.to_list() for x in col], dtype='f4').tobytes()
        model_bytes = np.array([x for col in base_model.to_list() for x in col], dtype='f4').tobytes()

        self.program['mvp'].write(mvp_bytes)
        self.program['model'].write(model_bytes)
        self.program['base_color'].value = self.BODY_COLOR
        self.program['emissive_color'].value = (0.0, 0.0, 0.0)
        self.program['emissive_strength'].value = 0.0

        self.base_vao.render(moderngl.TRIANGLES)

        # Render coordinate axes on base (don't rotate with pan)
        # X-axis (Red)
        if hasattr(self, 'x_axis_vao') and self.x_axis_vao:
            self.program['base_color'].value = (0.9, 0.2, 0.2)  # Red
            self.x_axis_vao.render(moderngl.TRIANGLES)

        # Y-axis (Blue)
        if hasattr(self, 'y_axis_vao') and self.y_axis_vao:
            self.program['base_color'].value = (0.2, 0.4, 0.9)  # Blue
            self.y_axis_vao.render(moderngl.TRIANGLES)

        # Z-axis (Green)
        if hasattr(self, 'z_axis_vao') and self.z_axis_vao:
            self.program['base_color'].value = (0.2, 0.8, 0.2)  # Green
            self.z_axis_vao.render(moderngl.TRIANGLES)

        # Reset color for next parts
        self.program['base_color'].value = self.BODY_COLOR

        # Yoke rotates with pan (around Z-axis in Z-up coordinate system)
        pan_rotation = glm.rotate(glm.mat4(1.0), glm.radians(self.current_pan), glm.vec3(0, 0, 1))
        yoke_model = base_model * pan_rotation

        yoke_mvp = mvp * yoke_model
        mvp_bytes = np.array([x for col in yoke_mvp.to_list() for x in col], dtype='f4').tobytes()
        model_bytes = np.array([x for col in yoke_model.to_list() for x in col], dtype='f4').tobytes()

        self.program['mvp'].write(mvp_bytes)
        self.program['model'].write(model_bytes)
        self.program['base_color'].value = self.YOKE_COLOR

        self.yoke_vao.render(moderngl.TRIANGLES)

        # Head rotates with pan and tilt
        # Position head in yoke (Z direction), then apply tilt (around Y-axis)
        head_z = self.base_thickness + self.yoke_height / 2
        head_translate = glm.translate(glm.mat4(1.0), glm.vec3(0, 0, head_z))

        # Tilt rotates around Y-axis (in yoke's local space after pan)
        # Tilt=0: beam forward (+X in yoke space), increasing tilt -> beam up (+Z)
        # Negative rotation around Y to go from +X toward +Z
        tilt_rotation = glm.rotate(glm.mat4(1.0), glm.radians(-self.current_tilt), glm.vec3(0, 1, 0))

        head_model = base_model * pan_rotation * head_translate * tilt_rotation

        head_mvp = mvp * head_model
        mvp_bytes = np.array([x for col in head_mvp.to_list() for x in col], dtype='f4').tobytes()
        model_bytes = np.array([x for col in head_model.to_list() for x in col], dtype='f4').tobytes()

        self.program['mvp'].write(mvp_bytes)
        self.program['model'].write(model_bytes)
        self.program['base_color'].value = self.BODY_COLOR

        self.head_vao.render(moderngl.TRIANGLES)

        # Render lens with emissive color
        color = self.get_color()  # Handles color wheel and white fallback
        dimmer = self.get_dimmer()

        emissive = (color[0] * dimmer, color[1] * dimmer, color[2] * dimmer)

        self.program['base_color'].value = (0.2, 0.2, 0.2)
        self.program['emissive_color'].value = emissive
        self.program['emissive_strength'].value = 1.0 * self.brightness_scale

        self.lens_vao.render(moderngl.TRIANGLES)

        # Render beam and floor projection if dimmer is on
        if dimmer > 0.01:
            self._render_beam(mvp, head_model, color, dimmer)
            self._render_floor_projection(mvp, color, dimmer)

    def _render_single_beam(self, mvp: glm.mat4, head_model: glm.mat4,
                            color: Tuple[float, float, float], intensity: float,
                            prism_offset_angle: float = 0.0, prism_tilt: float = 0.0):
        """
        Render a single light beam cone.

        Args:
            mvp: View-projection matrix
            head_model: Head transformation matrix
            color: RGB color tuple
            intensity: Beam intensity (0-1)
            prism_offset_angle: Rotation around beam axis for prism effect (degrees)
            prism_tilt: Outward tilt for prism effect (degrees)
        """
        # Beam starts at lens front face and extends outward
        # In Z-up system: lens is on +X face of head
        # Beam cone geometry extends along +Z by default, so rotate +90° around Y to point along +X
        beam_rotation = glm.rotate(glm.mat4(1.0), glm.radians(90), glm.vec3(0, 1, 0))
        beam_offset = glm.translate(glm.mat4(1.0), glm.vec3(self.head_size_x / 2 + self.lens_depth, 0, 0))

        # For prism effect: apply rotation and tilt in the beam's native coordinate space
        # The beam cone extends along +Z, so:
        # - Rotation around beam axis = rotation around Z
        # - Tilt outward = rotation around Y (perpendicular to beam)
        # These are applied BEFORE beam_rotation so they transform correctly
        if prism_offset_angle != 0.0 or prism_tilt != 0.0:
            # First tilt outward (around Y in cone's native space)
            prism_tilt_mat = glm.rotate(glm.mat4(1.0), glm.radians(prism_tilt), glm.vec3(0, 1, 0))
            # Then rotate around beam axis (Z in cone's native space)
            prism_rotation = glm.rotate(glm.mat4(1.0), glm.radians(prism_offset_angle), glm.vec3(0, 0, 1))
            # Apply prism effects before beam orientation: tilt first, then rotate around axis
            beam_rotation = beam_rotation * prism_rotation * prism_tilt_mat

        # Apply: head transform -> move to lens position -> orient beam
        beam_model = head_model * beam_offset * beam_rotation

        beam_mvp = mvp * beam_model
        mvp_bytes = np.array([x for col in beam_mvp.to_list() for x in col], dtype='f4').tobytes()

        self.beam_program['mvp'].write(mvp_bytes)
        self.beam_program['beam_color'].value = color
        self.beam_program['beam_intensity'].value = intensity * self.brightness_scale

        # Pass gobo pattern and rotation
        gobo_pattern = self.get_gobo_pattern()
        self.beam_program['gobo_pattern'].value = gobo_pattern
        self.beam_program['gobo_rotation'].value = self.gobo_rotation_angle

        # Pass focus sharpness (distance-based)
        projection_distance = self.get_floor_projection_distance()
        focus_sharpness = self.get_focus_sharpness(projection_distance)
        self.beam_program['focus_sharpness'].value = focus_sharpness

        self.beam_vao.render(moderngl.TRIANGLES)

    def _render_beam(self, mvp: glm.mat4, head_model: glm.mat4,
                     color: Tuple[float, float, float], dimmer: float):
        """Render the light beam cone(s). Supports prism effect (3-facet split)."""
        try:
            # Check if beam resources exist
            if not hasattr(self, 'beam_vao') or self.beam_vao is None:
                return

            # Enable blending for transparency (additive blending)
            self.ctx.enable(moderngl.BLEND)
            # Default blend equation is ADD, just set the blend function
            self.ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE)

            # Disable depth write so beams don't occlude each other
            self.ctx.depth_mask = False

            # Check for prism effect
            prism_value = self.dmx_values.get('prism', 0)
            prism_active = prism_value > 20  # Threshold for "on"

            if prism_active:
                # Render 3 beams for 3-facet prism
                # Each beam rotated 120° around beam axis, tilted outward ~10°
                prism_intensity = dimmer * 0.4 * self.brightness_scale  # 40% each, combined ~120%
                prism_tilt = 10.0  # Degrees outward tilt

                for i, offset_angle in enumerate([0.0, 120.0, 240.0]):
                    self._render_single_beam(mvp, head_model, color, prism_intensity,
                                             prism_offset_angle=offset_angle,
                                             prism_tilt=prism_tilt)
            else:
                # Render single beam
                self._render_single_beam(mvp, head_model, color, dimmer)

            # Restore state
            self.ctx.depth_mask = True
            self.ctx.disable(moderngl.BLEND)

        except Exception as e:
            print(f"Error rendering beam: {e}")
            import traceback
            traceback.print_exc()
            # Try to restore state on error
            try:
                self.ctx.depth_mask = True
                self.ctx.disable(moderngl.BLEND)
            except:
                pass

    def _calculate_prism_floor_intersection(self, prism_offset_angle: float, prism_tilt: float
                                            ) -> Optional[Tuple[glm.vec3, float, float, float]]:
        """
        Calculate floor intersection for a prism-split beam.

        Args:
            prism_offset_angle: Rotation around beam axis (degrees)
            prism_tilt: Outward tilt angle (degrees)

        Returns:
            Same as _calculate_floor_intersection: (hit_pos, major_radius, minor_radius, rotation_angle)
        """
        # Get head position
        head_z_offset = self.base_thickness + self.yoke_height / 2
        base_model = self.get_model_matrix()

        # Pan rotation
        pan_rotation = glm.rotate(glm.mat4(1.0), glm.radians(self.current_pan), glm.vec3(0, 0, 1))

        # Head position and tilt
        head_translate = glm.translate(glm.mat4(1.0), glm.vec3(0, 0, head_z_offset))
        tilt_rotation = glm.rotate(glm.mat4(1.0), glm.radians(-self.current_tilt), glm.vec3(0, 1, 0))

        # Full head transform
        head_model = base_model * pan_rotation * head_translate * tilt_rotation

        # Lens position
        lens_local_pos = glm.vec3(self.head_size_x / 2 + self.lens_depth, 0, 0)
        lens_world_pos = glm.vec3(head_model * glm.vec4(lens_local_pos, 1.0))

        # Get modified beam direction for this prism facet
        direction = glm.vec3(1, 0, 0)

        # Apply tilt and pan (same as get_beam_direction)
        tilt_rad = glm.radians(-self.current_tilt)
        tilt_mat = glm.rotate(glm.mat4(1.0), tilt_rad, glm.vec3(0, 1, 0))

        pan_rad = glm.radians(self.current_pan)
        pan_mat = glm.rotate(glm.mat4(1.0), pan_rad, glm.vec3(0, 0, 1))

        # Prism rotation (around beam axis) and tilt (outward)
        prism_rotation_mat = glm.rotate(glm.mat4(1.0), glm.radians(prism_offset_angle), glm.vec3(1, 0, 0))
        prism_tilt_mat = glm.rotate(glm.mat4(1.0), glm.radians(prism_tilt), glm.vec3(0, 1, 0))

        # Fixture orientation
        fixture_mat = glm.mat4(1.0)
        fixture_mat = glm.rotate(fixture_mat, glm.radians(self.yaw), glm.vec3(0, 1, 0))
        fixture_mat = glm.rotate(fixture_mat, glm.radians(self.pitch), glm.vec3(1, 0, 0))
        fixture_mat = glm.rotate(fixture_mat, glm.radians(self.roll), glm.vec3(0, 0, 1))

        # Combine: fixture * pan * tilt * prism_rotation * prism_tilt
        final_mat = fixture_mat * pan_mat * tilt_mat * prism_rotation_mat * prism_tilt_mat
        beam_dir = glm.normalize(glm.vec3(final_mat * glm.vec4(direction, 0.0)))

        # Check if beam is pointing downward
        if beam_dir.y >= 0:
            return None

        # Calculate intersection with Y=0 plane
        t = -lens_world_pos.y / beam_dir.y
        beam_length = 5.0
        if t <= 0 or t > beam_length:
            return None

        # Calculate hit position
        hit_pos = lens_world_pos + beam_dir * t

        # Calculate beam radius at this distance
        beam_radius = t * math.tan(math.radians(self.beam_angle / 2))

        # Calculate ellipse shape
        cos_angle = abs(beam_dir.y)
        minor_radius = beam_radius
        major_radius = min(beam_radius / max(cos_angle, 0.1), beam_radius * 5.0)

        # Calculate rotation angle
        beam_xz = glm.vec2(beam_dir.x, beam_dir.z)
        if glm.length(beam_xz) > 0.01:
            beam_xz = glm.normalize(beam_xz)
            rotation_angle = math.degrees(math.atan2(beam_xz.x, beam_xz.y))
        else:
            rotation_angle = 0.0

        return (hit_pos, major_radius, minor_radius, rotation_angle)

    def _render_single_floor_projection(self, mvp: glm.mat4,
                                        color: Tuple[float, float, float], intensity: float,
                                        hit_pos: glm.vec3, major_radius: float,
                                        minor_radius: float, rotation_angle: float,
                                        distance_falloff: float):
        """Render a single floor projection ellipse."""
        # Build model matrix for the projection ellipse
        proj_model = glm.mat4(1.0)

        # Translate to hit position (above floor to avoid z-fighting)
        proj_model = glm.translate(proj_model, glm.vec3(hit_pos.x, 0.03, hit_pos.z))

        # Rotate to align major axis with beam direction
        proj_model = glm.rotate(proj_model, glm.radians(rotation_angle), glm.vec3(0, 1, 0))

        # Scale to create ellipse
        proj_model = glm.scale(proj_model, glm.vec3(major_radius, 1.0, minor_radius))

        proj_mvp = mvp * proj_model
        mvp_bytes = np.array([x for col in proj_mvp.to_list() for x in col], dtype='f4').tobytes()

        self.floor_proj_program['mvp'].write(mvp_bytes)
        self.floor_proj_program['projection_color'].value = color
        self.floor_proj_program['projection_intensity'].value = intensity * self.brightness_scale
        self.floor_proj_program['distance_falloff'].value = distance_falloff

        # Pass gobo pattern and rotation
        gobo_pattern = self.get_gobo_pattern()
        self.floor_proj_program['gobo_pattern'].value = gobo_pattern
        self.floor_proj_program['gobo_rotation'].value = self.gobo_rotation_angle

        # Pass focus sharpness (distance-based)
        projection_distance = self.get_floor_projection_distance()
        focus_sharpness = self.get_focus_sharpness(projection_distance)
        self.floor_proj_program['focus_sharpness'].value = focus_sharpness

        self.floor_proj_vao.render(moderngl.TRIANGLES)

    def _render_floor_projection(self, mvp: glm.mat4,
                                  color: Tuple[float, float, float], dimmer: float):
        """Render the floor projection(s). Supports prism effect (3-facet split)."""
        try:
            # Check if floor projection resources exist
            if not hasattr(self, 'floor_proj_vao') or self.floor_proj_vao is None:
                return

            # Enable blending for transparency (additive blending like beams)
            self.ctx.enable(moderngl.BLEND)
            self.ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE)

            # Keep depth-test on (with depth WRITE off) so closer chassis
            # geometry (e.g. a floor PAR sitting under this MH's spot)
            # correctly occludes the projection ellipse. The projection
            # plane at y=0.03 still draws over the stage floor because
            # it sits above the floor's depth.
            self.ctx.depth_mask = False

            # Calculate distance falloff
            beam_length = 5.0
            pos = self.position
            lens_height = pos['z']
            beam_dir = self.get_beam_direction()
            if beam_dir.y < 0:
                distance = abs(lens_height / beam_dir.y)
            else:
                distance = beam_length
            distance_falloff = max(1.0 - (distance / beam_length) * 0.3, 0.5)

            # Check for prism effect
            prism_value = self.dmx_values.get('prism', 0)
            prism_active = prism_value > 20

            if prism_active:
                # Render 3 floor projections for 3-facet prism
                prism_intensity = dimmer * 0.4 * self.brightness_scale  # 40% each
                prism_tilt = 10.0

                for offset_angle in [0.0, 120.0, 240.0]:
                    intersection = self._calculate_prism_floor_intersection(offset_angle, prism_tilt)
                    if intersection:
                        hit_pos, major_radius, minor_radius, rotation_angle = intersection
                        self._render_single_floor_projection(
                            mvp, color, prism_intensity,
                            hit_pos, major_radius, minor_radius, rotation_angle,
                            distance_falloff
                        )
            else:
                # Render single floor projection
                intersection = self._calculate_floor_intersection()
                if intersection:
                    hit_pos, major_radius, minor_radius, rotation_angle = intersection
                    self._render_single_floor_projection(
                        mvp, color, dimmer,
                        hit_pos, major_radius, minor_radius, rotation_angle,
                        distance_falloff
                    )

            # Restore state
            self.ctx.enable(moderngl.DEPTH_TEST)
            self.ctx.depth_mask = True
            self.ctx.disable(moderngl.BLEND)

        except Exception as e:
            print(f"Error rendering floor projection: {e}")
            import traceback
            traceback.print_exc()
            # Try to restore state on error
            try:
                self.ctx.enable(moderngl.DEPTH_TEST)
                self.ctx.depth_mask = True
                self.ctx.disable(moderngl.BLEND)
            except:
                pass

    def release(self):
        """Release GPU resources."""
        super().release()
        for attr in ['base_vao', 'base_vbo', 'base_nbo',
                     'x_axis_vao', 'x_axis_vbo', 'x_axis_nbo',
                     'y_axis_vao', 'y_axis_vbo', 'y_axis_nbo',
                     'z_axis_vao', 'z_axis_vbo', 'z_axis_nbo',
                     'yoke_vao', 'yoke_vbo', 'yoke_nbo',
                     'head_vao', 'head_vbo', 'head_nbo',
                     'lens_vao', 'lens_vbo', 'lens_nbo',
                     'beam_vao', 'beam_vbo', 'beam_abo', 'beam_program',
                     'floor_proj_vao', 'floor_proj_vbo', 'floor_proj_ubo', 'floor_proj_program']:
            obj = getattr(self, attr, None)
            if obj:
                obj.release()


class WashRenderer(FixtureRenderer):
    """Renderer for wash/flood fixtures."""

    BODY_COLOR = (0.12, 0.12, 0.15)

    def __init__(self, ctx: moderngl.Context, fixture_data: Dict[str, Any]):
        super().__init__(ctx, fixture_data)
        self._create_geometry()
        self._create_rectangular_beam()

    def _create_geometry(self):
        """Create wash fixture body and lens."""
        self.program = self.ctx.program(
            vertex_shader=FIXTURE_VERTEX_SHADER,
            fragment_shader=FIXTURE_FRAGMENT_SHADER
        )

        # Create main body
        body_verts, body_norms = GeometryBuilder.create_box(
            self.width, self.height, self.depth
        )

        self.vbo = self.ctx.buffer(body_verts.tobytes())
        self.nbo = self.ctx.buffer(body_norms.tobytes())
        self.vao = self.ctx.vertex_array(
            self.program,
            [(self.vbo, '3f', 'in_position'), (self.nbo, '3f', 'in_normal')]
        )

        # Create lens/front emitter
        lens_width = self.width * 0.85
        lens_height = self.height * 0.85
        lens_depth = 0.02

        lens_verts, lens_norms = GeometryBuilder.create_box(
            lens_width, lens_height, lens_depth,
            center=(0, 0, self.depth / 2 + lens_depth / 2)
        )

        self.lens_vbo = self.ctx.buffer(lens_verts.tobytes())
        self.lens_nbo = self.ctx.buffer(lens_norms.tobytes())
        self.lens_vao = self.ctx.vertex_array(
            self.program,
            [(self.lens_vbo, '3f', 'in_position'), (self.lens_nbo, '3f', 'in_normal')]
        )

        # Store lens dimensions for beam
        self.lens_width = lens_width
        self.lens_height = lens_height

        # Create coordinate axes for debugging orientation
        self._create_coordinate_axes(axis_origin_z=self.depth / 2 + 0.01)

    def _create_coordinate_axes(self, axis_origin_z: float):
        """Create coordinate axes for debugging fixture orientation.

        Args:
            axis_origin_z: Z position for axis origin (top of fixture)
        """
        axis_length = 0.4  # 40cm axes for visibility
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

        self.x_axis_vbo = self.ctx.buffer(x_axis_verts.tobytes())
        self.x_axis_nbo = self.ctx.buffer(x_axis_norms.tobytes())
        self.x_axis_vao = self.ctx.vertex_array(
            self.program,
            [(self.x_axis_vbo, '3f', 'in_position'), (self.x_axis_nbo, '3f', 'in_normal')]
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

        self.y_axis_vbo = self.ctx.buffer(y_axis_verts.tobytes())
        self.y_axis_nbo = self.ctx.buffer(y_axis_norms.tobytes())
        self.y_axis_vao = self.ctx.vertex_array(
            self.program,
            [(self.y_axis_vbo, '3f', 'in_position'), (self.y_axis_nbo, '3f', 'in_normal')]
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

        self.z_axis_vbo = self.ctx.buffer(z_axis_verts.tobytes())
        self.z_axis_nbo = self.ctx.buffer(z_axis_norms.tobytes())
        self.z_axis_vao = self.ctx.vertex_array(
            self.program,
            [(self.z_axis_vbo, '3f', 'in_position'), (self.z_axis_nbo, '3f', 'in_normal')]
        )

    def _create_rectangular_beam(self):
        """Create rectangular beam for wash fixture."""
        self.beam_program = self.ctx.program(
            vertex_shader=BEAM_VERTEX_SHADER,
            fragment_shader=BEAM_FRAGMENT_SHADER
        )

        beam_length = 0.3  # Short glow near fixture face
        beam_width = self.lens_width * 0.8
        beam_height = self.lens_height * 0.8

        # Beam extends from front of lens along +Z
        beam_verts, beam_alphas = GeometryBuilder.create_beam_box(
            beam_width, beam_height, beam_length
        )

        # Offset beam to start just in front of lens
        offset_verts = []
        for i in range(0, len(beam_verts), 3):
            x, y, z = beam_verts[i], beam_verts[i+1], beam_verts[i+2]
            offset_verts.extend([x, y, z + self.depth / 2 + 0.03])

        self.wash_beam_vbo = self.ctx.buffer(np.array(offset_verts, dtype='f4').tobytes())
        self.wash_beam_abo = self.ctx.buffer(beam_alphas.tobytes())

        self.wash_beam_vao = self.ctx.vertex_array(
            self.beam_program,
            [
                (self.wash_beam_vbo, '3f', 'in_position'),
                (self.wash_beam_abo, '1f', 'in_alpha'),
            ]
        )

    def render(self, mvp: glm.mat4):
        """Render the wash fixture."""
        # Reset OpenGL state to prevent transparency issues from previous beam rendering
        self.ctx.disable(moderngl.BLEND)
        self.ctx.depth_mask = True

        model = self.get_model_matrix()
        final_mvp = mvp * model

        mvp_bytes = np.array([x for col in final_mvp.to_list() for x in col], dtype='f4').tobytes()
        model_bytes = np.array([x for col in model.to_list() for x in col], dtype='f4').tobytes()

        self.program['mvp'].write(mvp_bytes)
        self.program['model'].write(model_bytes)

        # Render body
        self.program['base_color'].value = self.BODY_COLOR
        self.program['emissive_color'].value = (0.0, 0.0, 0.0)
        self.program['emissive_strength'].value = 0.0
        self.vao.render(moderngl.TRIANGLES)

        # Render coordinate axes
        if hasattr(self, 'x_axis_vao') and self.x_axis_vao:
            self.program['base_color'].value = (0.9, 0.2, 0.2)  # Red
            self.x_axis_vao.render(moderngl.TRIANGLES)
        if hasattr(self, 'y_axis_vao') and self.y_axis_vao:
            self.program['base_color'].value = (0.2, 0.4, 0.9)  # Blue
            self.y_axis_vao.render(moderngl.TRIANGLES)
        if hasattr(self, 'z_axis_vao') and self.z_axis_vao:
            self.program['base_color'].value = (0.2, 0.8, 0.2)  # Green
            self.z_axis_vao.render(moderngl.TRIANGLES)

        # Render lens with color
        color = self.get_color()
        dimmer = self.get_dimmer()

        # Add white channel
        white = self.dmx_values.get('white', 0) / 255.0
        color = (
            min(1.0, color[0] + white),
            min(1.0, color[1] + white),
            min(1.0, color[2] + white)
        )

        emissive = (color[0] * dimmer, color[1] * dimmer, color[2] * dimmer)

        self.program['base_color'].value = (0.15, 0.15, 0.15)
        self.program['emissive_color'].value = emissive
        self.program['emissive_strength'].value = 1.0 * self.brightness_scale

        self.lens_vao.render(moderngl.TRIANGLES)

        # Render beam when lit
        if dimmer > 0.01:
            self._render_rectangular_beam(mvp, model, color, dimmer)

    def _render_rectangular_beam(self, mvp: glm.mat4, model: glm.mat4,
                                  color: Tuple[float, float, float], dimmer: float):
        """Render the rectangular beam."""
        if not hasattr(self, 'wash_beam_vao') or not self.wash_beam_vao:
            return

        # Enable additive blending
        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE)
        self.ctx.depth_mask = False

        final_mvp = mvp * model
        mvp_bytes = np.array([x for col in final_mvp.to_list() for x in col], dtype='f4').tobytes()

        self.beam_program['mvp'].write(mvp_bytes)
        self.beam_program['beam_color'].value = color
        self.beam_program['beam_intensity'].value = dimmer * self.brightness_scale

        self.wash_beam_vao.render(moderngl.TRIANGLES)

        # Restore state
        self.ctx.depth_mask = True
        self.ctx.disable(moderngl.BLEND)

    def release(self):
        """Release GPU resources."""
        super().release()
        if hasattr(self, 'lens_vao') and self.lens_vao:
            self.lens_vao.release()
        if hasattr(self, 'lens_vbo') and self.lens_vbo:
            self.lens_vbo.release()
        if hasattr(self, 'lens_nbo') and self.lens_nbo:
            self.lens_nbo.release()
        # Beam resources
        if hasattr(self, 'wash_beam_vao') and self.wash_beam_vao:
            self.wash_beam_vao.release()
        if hasattr(self, 'wash_beam_vbo') and self.wash_beam_vbo:
            self.wash_beam_vbo.release()
        if hasattr(self, 'wash_beam_abo') and self.wash_beam_abo:
            self.wash_beam_abo.release()
        # Coordinate axes resources
        for attr in ['x_axis_vao', 'x_axis_vbo', 'x_axis_nbo',
                     'y_axis_vao', 'y_axis_vbo', 'y_axis_nbo',
                     'z_axis_vao', 'z_axis_vbo', 'z_axis_nbo']:
            obj = getattr(self, attr, None)
            if obj:
                obj.release()


class PARRenderer(FixtureRenderer):
    """Renderer for PAR can fixtures (default type)."""

    BODY_COLOR = (0.1, 0.1, 0.12)

    def __init__(self, ctx: moderngl.Context, fixture_data: Dict[str, Any]):
        super().__init__(ctx, fixture_data)
        self._create_geometry()
        self._create_cylindrical_beam()

    def _create_geometry(self):
        """Create PAR can body and lens.

        According to reference.md:
        - Cylindrical body extends along Z axis
        - Lens/beam faces +Z direction
        """
        self.program = self.ctx.program(
            vertex_shader=FIXTURE_VERTEX_SHADER,
            fragment_shader=FIXTURE_FRAGMENT_SHADER
        )

        # PAR can is a cylinder extending along Z axis (per reference.md)
        radius = min(self.width, self.height) / 2

        # Create Y-oriented cylinder, then rotate to Z-oriented
        body_verts_raw, body_norms_raw = GeometryBuilder.create_cylinder(
            radius, self.depth, segments=24
        )

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

        self.vbo = self.ctx.buffer(body_verts.tobytes())
        self.nbo = self.ctx.buffer(body_norms.tobytes())
        self.vao = self.ctx.vertex_array(
            self.program,
            [(self.vbo, '3f', 'in_position'), (self.nbo, '3f', 'in_normal')]
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
            # Rotate and translate to top (+Z)
            lens_verts.extend([x, -z, y + self.depth / 2 + 0.01])
        for i in range(0, len(lens_norms_raw), 3):
            nx, ny, nz = lens_norms_raw[i], lens_norms_raw[i+1], lens_norms_raw[i+2]
            lens_norms.extend([nx, -nz, ny])

        lens_verts = np.array(lens_verts, dtype='f4')
        lens_norms = np.array(lens_norms, dtype='f4')

        self.lens_vbo = self.ctx.buffer(lens_verts.tobytes())
        self.lens_nbo = self.ctx.buffer(lens_norms.tobytes())
        self.lens_vao = self.ctx.vertex_array(
            self.program,
            [(self.lens_vbo, '3f', 'in_position'), (self.lens_nbo, '3f', 'in_normal')]
        )

        # Store lens radius for beam
        self.lens_radius = radius * 0.85
        self.par_radius = radius

        # Create coordinate axes for debugging orientation (Z-up space)
        self._create_coordinate_axes(axis_origin_z=self.depth / 2 + 0.01)

    def _create_coordinate_axes(self, axis_origin_z: float):
        """Create coordinate axes for debugging fixture orientation.

        PAR uses Z-up coordinate system per reference.md:
        - Body extends along Z axis
        - Lens/beam faces +Z direction

        Args:
            axis_origin_z: Z position for axis origin (top of fixture)
        """
        axis_length = 0.4  # 40cm axes for visibility
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

        self.x_axis_vbo = self.ctx.buffer(x_axis_verts.tobytes())
        self.x_axis_nbo = self.ctx.buffer(x_axis_norms.tobytes())
        self.x_axis_vao = self.ctx.vertex_array(
            self.program,
            [(self.x_axis_vbo, '3f', 'in_position'), (self.x_axis_nbo, '3f', 'in_normal')]
        )

        # Y-AXIS (Blue) - pointing along +Y (toward audience)
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

        self.y_axis_vbo = self.ctx.buffer(y_axis_verts.tobytes())
        self.y_axis_nbo = self.ctx.buffer(y_axis_norms.tobytes())
        self.y_axis_vao = self.ctx.vertex_array(
            self.program,
            [(self.y_axis_vbo, '3f', 'in_position'), (self.y_axis_nbo, '3f', 'in_normal')]
        )

        # Z-AXIS (Green) - pointing along +Z (up, same as beam direction)
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

        self.z_axis_vbo = self.ctx.buffer(z_axis_verts.tobytes())
        self.z_axis_nbo = self.ctx.buffer(z_axis_norms.tobytes())
        self.z_axis_vao = self.ctx.vertex_array(
            self.program,
            [(self.z_axis_vbo, '3f', 'in_position'), (self.z_axis_nbo, '3f', 'in_normal')]
        )

    def _create_cylindrical_beam(self):
        """Create cylindrical beam for PAR fixture.

        Beam extends along +Z (up) per reference.md.
        """
        self.beam_program = self.ctx.program(
            vertex_shader=BEAM_VERTEX_SHADER,
            fragment_shader=BEAM_FRAGMENT_SHADER
        )

        beam_length = 0.3  # Short glow near fixture face
        beam_radius = self.lens_radius * 0.8

        # Beam already extends along +Z, just translate to lens position
        beam_verts, beam_alphas = GeometryBuilder.create_beam_cylinder(
            beam_radius, beam_length, segments=12
        )

        # Offset beam to start at lens position (lens is at z = depth/2 + 0.01)
        offset_verts = []
        for i in range(0, len(beam_verts), 3):
            x, y, z = beam_verts[i], beam_verts[i+1], beam_verts[i+2]
            # Beam starts at lens, extends along +Z
            offset_verts.extend([x, y, z + self.depth / 2 + 0.02])

        self.par_beam_vbo = self.ctx.buffer(np.array(offset_verts, dtype='f4').tobytes())
        self.par_beam_abo = self.ctx.buffer(beam_alphas.tobytes())

        self.par_beam_vao = self.ctx.vertex_array(
            self.beam_program,
            [
                (self.par_beam_vbo, '3f', 'in_position'),
                (self.par_beam_abo, '1f', 'in_alpha'),
            ]
        )

    def render(self, mvp: glm.mat4):
        """Render the PAR can.

        Geometry already has lens facing +Z per reference.md.
        No additional rotation needed.
        """
        # Reset OpenGL state to prevent transparency issues from previous beam rendering
        self.ctx.disable(moderngl.BLEND)
        self.ctx.depth_mask = True

        model = self.get_model_matrix()
        final_mvp = mvp * model

        mvp_bytes = np.array([x for col in final_mvp.to_list() for x in col], dtype='f4').tobytes()
        model_bytes = np.array([x for col in model.to_list() for x in col], dtype='f4').tobytes()

        self.program['mvp'].write(mvp_bytes)
        self.program['model'].write(model_bytes)

        # Render body
        self.program['base_color'].value = self.BODY_COLOR
        self.program['emissive_color'].value = (0.0, 0.0, 0.0)
        self.program['emissive_strength'].value = 0.0
        self.vao.render(moderngl.TRIANGLES)

        # Render coordinate axes (rendered with same rotation as body)
        if hasattr(self, 'x_axis_vao') and self.x_axis_vao:
            self.program['base_color'].value = (0.9, 0.2, 0.2)  # Red
            self.x_axis_vao.render(moderngl.TRIANGLES)
        if hasattr(self, 'y_axis_vao') and self.y_axis_vao:
            self.program['base_color'].value = (0.2, 0.4, 0.9)  # Blue
            self.y_axis_vao.render(moderngl.TRIANGLES)
        if hasattr(self, 'z_axis_vao') and self.z_axis_vao:
            self.program['base_color'].value = (0.2, 0.8, 0.2)  # Green
            self.z_axis_vao.render(moderngl.TRIANGLES)

        # Render lens with color
        color = self.get_color()
        dimmer = self.get_dimmer()

        white = self.dmx_values.get('white', 0) / 255.0
        color = (
            min(1.0, color[0] + white),
            min(1.0, color[1] + white),
            min(1.0, color[2] + white)
        )

        emissive = (color[0] * dimmer, color[1] * dimmer, color[2] * dimmer)

        self.program['base_color'].value = (0.15, 0.15, 0.15)
        self.program['emissive_color'].value = emissive
        self.program['emissive_strength'].value = 1.0 * self.brightness_scale

        self.lens_vao.render(moderngl.TRIANGLES)

        # Render beam when lit
        if dimmer > 0.01:
            self._render_cylindrical_beam(mvp, model, color, dimmer)

    def _render_cylindrical_beam(self, mvp: glm.mat4, model: glm.mat4,
                                  color: Tuple[float, float, float], dimmer: float):
        """Render the cylindrical beam."""
        if not hasattr(self, 'par_beam_vao') or not self.par_beam_vao:
            return

        # Enable additive blending
        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE)
        self.ctx.depth_mask = False

        final_mvp = mvp * model
        mvp_bytes = np.array([x for col in final_mvp.to_list() for x in col], dtype='f4').tobytes()

        self.beam_program['mvp'].write(mvp_bytes)
        self.beam_program['beam_color'].value = color
        self.beam_program['beam_intensity'].value = dimmer * self.brightness_scale

        self.par_beam_vao.render(moderngl.TRIANGLES)

        # Restore state
        self.ctx.depth_mask = True
        self.ctx.disable(moderngl.BLEND)

    def release(self):
        """Release GPU resources."""
        super().release()
        if hasattr(self, 'lens_vao') and self.lens_vao:
            self.lens_vao.release()
        if hasattr(self, 'lens_vbo') and self.lens_vbo:
            self.lens_vbo.release()
        if hasattr(self, 'lens_nbo') and self.lens_nbo:
            self.lens_nbo.release()
        # Beam resources
        if hasattr(self, 'par_beam_vao') and self.par_beam_vao:
            self.par_beam_vao.release()
        if hasattr(self, 'par_beam_vbo') and self.par_beam_vbo:
            self.par_beam_vbo.release()
        if hasattr(self, 'par_beam_abo') and self.par_beam_abo:
            self.par_beam_abo.release()
        # Coordinate axes resources
        for attr in ['x_axis_vao', 'x_axis_vbo', 'x_axis_nbo',
                     'y_axis_vao', 'y_axis_vbo', 'y_axis_nbo',
                     'z_axis_vao', 'z_axis_vbo', 'z_axis_nbo']:
            obj = getattr(self, attr, None)
            if obj:
                obj.release()


def _detect_capabilities_from_payload(fixture_data: Dict[str, Any]):
    """Re-detect :class:`FixtureCapabilities` from the TCP payload's keys.

    The show-creator side computes capabilities via the same QXF
    detection pass; the standalone TCP visualizer strips the live
    dataclass during JSON serialization (capabilities are full of
    nested dataclasses + enums + a sealed-union emitter). Rather than
    teach the serializer about each subtype, we just re-run detection
    locally — it's deterministic from the ``(manufacturer, model, mode)``
    triple, all three of which travel in the JSON payload, and the
    standalone has access to the same ``custom_fixtures/`` QXF library.
    """
    try:
        from utils.fixture_capabilities import get_capabilities_for_fixture
    except ImportError:
        return None

    mfr = fixture_data.get('manufacturer')
    model = fixture_data.get('model')
    mode = fixture_data.get('mode') or fixture_data.get('current_mode')
    if not (mfr and model and mode):
        return None

    class _CapsLookupProxy:
        __slots__ = ('manufacturer', 'model', 'current_mode')

        def __init__(self, mfr_, model_, mode_):
            self.manufacturer = mfr_
            self.model = model_
            self.current_mode = mode_

    try:
        return get_capabilities_for_fixture(_CapsLookupProxy(mfr, model, mode))
    except Exception as e:  # pragma: no cover — environment / QXF issue
        print(f"Capability re-detection failed for {mfr}/{model}: {e}")
        return None


class FixtureManager:
    """Manages all fixture renderers and coordinates updates."""

    def __init__(self, ctx: moderngl.Context):
        """
        Initialize fixture manager.

        Args:
            ctx: ModernGL context
        """
        self.ctx = ctx
        self.fixtures: Dict[str, FixtureRenderer] = {}

    def update_fixtures(self, fixtures_data: List[Dict[str, Any]]):
        """
        Update fixtures from TCP message.

        Args:
            fixtures_data: List of fixture dictionaries from TCP
        """
        # Track which fixtures we've seen
        seen_fixtures = set()

        for fixture_data in fixtures_data:
            name = fixture_data.get('name', '')
            if not name:
                continue

            seen_fixtures.add(name)

            # Check if fixture already exists
            if name in self.fixtures:
                existing = self.fixtures[name]
                # Check if fixture has changed significantly
                new_orientation = fixture_data.get('orientation', {})
                orientation_changed = (
                    existing.mounting != new_orientation.get('mounting', 'hanging') or
                    existing.yaw != new_orientation.get('yaw', 0.0) or
                    existing.pitch != new_orientation.get('pitch', 0.0) or
                    existing.roll != new_orientation.get('roll', 0.0)
                )
                if existing.position != fixture_data.get('position') or orientation_changed:
                    # Recreate fixture
                    existing.release()
                    self.fixtures[name] = self._create_fixture(fixture_data)
            else:
                # Create new fixture
                self.fixtures[name] = self._create_fixture(fixture_data)

        # Remove fixtures that no longer exist
        for name in list(self.fixtures.keys()):
            if name not in seen_fixtures:
                self.fixtures[name].release()
                del self.fixtures[name]

        # Normalize brightness based on estimated lumens
        max_lumens = 0.0
        for fixture_data in fixtures_data:
            lumens = fixture_data.get('lumens', 10000.0)
            if lumens > max_lumens:
                max_lumens = lumens

        if max_lumens > 0:
            for fixture_data in fixtures_data:
                name = fixture_data.get('name', '')
                if name in self.fixtures:
                    lumens = fixture_data.get('lumens', 10000.0)
                    # Use sqrt compression to prevent extreme dimming of low-wattage fixtures
                    self.fixtures[name].brightness_scale = math.sqrt(lumens / max_lumens)
                    print(f"  Brightness: {name} = {lumens:.0f} lm -> scale {self.fixtures[name].brightness_scale:.2f}")

        print(f"FixtureManager: {len(self.fixtures)} fixtures loaded")
        for name, fix in self.fixtures.items():
            extra_info = ""
            if isinstance(fix, MovingHeadRenderer):
                # Show pan/tilt channel mapping for moving heads
                ch_map = fix.channel_mapping
                pan_ch = [k for k, v in ch_map.items() if v == 'pan']
                tilt_ch = [k for k, v in ch_map.items() if v == 'tilt']
                dimmer_ch = [k for k, v in ch_map.items() if v == 'dimmer']
                color_ch = [k for k, v in ch_map.items() if v == 'color_wheel']
                cw_count = len(fix.color_wheel) if hasattr(fix, 'color_wheel') else 0
                extra_info = f", pan={pan_ch}, tilt={tilt_ch}, dim={dimmer_ch}, color={color_ch}, wheel_colors={cw_count}"
            print(f"  - {name}: type={fix.__class__.__name__}, U{fix.universe}@{fix.address}{extra_info}")

    def _create_fixture(self, fixture_data: Dict[str, Any]):
        """
        Create appropriate renderer for fixture type.

        With ``FIXTURE_RENDERER=composable``, constructs the new composable
        :class:`visualizer.renderer.composable_fixtures.FixtureRenderer`
        from the ``capabilities`` payload key. The standalone TCP path
        strips that key during JSON serialization (the dataclass tree
        isn't JSON-friendly), so when it's absent we re-detect the
        capabilities locally from ``(manufacturer, model, mode)`` — same
        deterministic lookup the show-creator side runs.

        Args:
            fixture_data: Fixture data dictionary

        Returns:
            FixtureRenderer instance (either composable or legacy)
        """
        if USE_COMPOSABLE_RENDERER:
            capabilities = fixture_data.get('capabilities')
            if capabilities is None:
                capabilities = _detect_capabilities_from_payload(fixture_data)
            if capabilities is not None:
                # Lazy import — avoids a circular dependency with composable_fixtures
                # (which would otherwise have to know about the legacy renderer).
                from visualizer.renderer.composable_fixtures import (
                    FixtureRenderer as ComposableFixtureRenderer,
                )
                return ComposableFixtureRenderer(self.ctx, fixture_data, capabilities)
            # Detection failed (QXF not findable) — fall through to legacy.

        fixture_type = fixture_data.get('fixture_type', 'PAR')

        if fixture_type == 'MH':
            return MovingHeadRenderer(self.ctx, fixture_data)
        elif fixture_type == 'PIXELBAR':
            return PixelBarRenderer(self.ctx, fixture_data)
        elif fixture_type == 'BAR':
            return LEDBarRenderer(self.ctx, fixture_data)
        elif fixture_type == 'SUNSTRIP':
            return SunstripRenderer(self.ctx, fixture_data)
        elif fixture_type == 'WASH':
            return WashRenderer(self.ctx, fixture_data)
        else:  # PAR or unknown
            return PARRenderer(self.ctx, fixture_data)

    def update_dmx(self, universe: int, dmx_data: bytes):
        """
        Update fixtures with new DMX data.

        Args:
            universe: Universe number
            dmx_data: 512 bytes of DMX data
        """
        updated_count = 0
        for fixture in self.fixtures.values():
            if fixture.universe == universe:
                fixture.update_dmx(dmx_data)
                updated_count += 1

        # Debug: log first few DMX updates
        if not hasattr(self, '_dmx_log_count'):
            self._dmx_log_count = 0
        if self._dmx_log_count < 5 and updated_count > 0:
            self._dmx_log_count += 1
            # Show first 20 channels
            ch_preview = [dmx_data[i] for i in range(min(20, len(dmx_data)))]
            print(f"DMX U{universe}: {updated_count} fixtures, ch1-20: {ch_preview}")

    def render(self, mvp: glm.mat4):
        """
        Render all fixtures in two passes (composable only).

        Composable fixtures expose ``render_lighting`` (additive beams +
        floor projections, no depth write) and ``render_chassis`` (opaque
        body, with depth). Drawing all lighting first and then all chassis
        on top guarantees fixture silhouettes stay readable at native
        color regardless of how bright or overlapping the surrounding
        beams are. Legacy fixtures (without the split methods) fall back
        to single-pass.

        Args:
            mvp: View-projection matrix
        """
        two_pass = [
            f for f in self.fixtures.values()
            if hasattr(f, 'render_lighting') and hasattr(f, 'render_chassis')
        ]
        single_pass = [
            f for f in self.fixtures.values()
            if f not in two_pass
        ]

        # Pass 1: additive light volumes for all composable fixtures.
        for fixture in two_pass:
            fixture.render_lighting(mvp)

        # Pass 2: opaque chassis on top.
        for fixture in two_pass:
            fixture.render_chassis(mvp)

        # Legacy fixtures keep their old chassis-then-beam single pass.
        for fixture in single_pass:
            fixture.render(mvp)

    def get_fixture(self, name: str) -> Optional[FixtureRenderer]:
        """Get fixture by name."""
        return self.fixtures.get(name)

    def release(self):
        """Release all GPU resources."""
        for fixture in self.fixtures.values():
            fixture.release()
        self.fixtures.clear()
