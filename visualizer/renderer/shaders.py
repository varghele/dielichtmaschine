"""GLSL shader constants for the composable fixture renderer.

Phase B of the fixture-rewrite. These strings are duplicated from
``visualizer/renderer/fixtures.py`` (left intact until Phase D) — keep
them in sync if either side changes. Phase D will delete the originals
and route all renderers through this module.
"""

from __future__ import annotations


# Warm white color temperature (~2700K) — used by fixtures whose body
# lights a warm-white halo around the lens regardless of beam color.
WARM_WHITE_COLOR = (1.0, 0.85, 0.6)


# ---------------------------------------------------------------------------
# Body shaders — diffuse lighting + emissive on a fixture's chassis mesh
# ---------------------------------------------------------------------------

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
    vec3 light_dir = normalize(vec3(0.5, 1.0, 0.3));
    float diff = max(dot(normalize(v_normal), light_dir), 0.0);

    vec3 ambient = base_color * 0.3;
    vec3 diffuse = base_color * diff * 0.7;
    vec3 emissive = emissive_color * emissive_strength;

    vec3 final_color = ambient + diffuse + emissive;
    fragColor = vec4(final_color, 1.0);
}
"""


GDTF_MESH_VERTEX_SHADER = """
#version 330

in vec3 in_position;
in vec3 in_normal;
in vec2 in_uv;

out vec3 v_normal;
out vec3 v_position;
out vec2 v_uv;

uniform mat4 mvp;
uniform mat4 model;

void main() {
    gl_Position = mvp * vec4(in_position, 1.0);
    v_normal = mat3(model) * in_normal;
    v_position = (model * vec4(in_position, 1.0)).xyz;
    v_uv = in_uv;
}
"""

GDTF_MESH_FRAGMENT_SHADER = """
#version 330

in vec3 v_normal;
in vec3 v_position;
in vec2 v_uv;

out vec4 fragColor;

uniform vec3 base_color;
uniform vec3 emissive_color;
uniform float emissive_strength;
uniform bool use_texture;
uniform sampler2D tex;

void main() {
    // Same two-light model as the procedural fixture shader so mesh and
    // procedural chassis read identically in a mixed rig.
    vec3 light_dir = normalize(vec3(0.5, 1.0, 0.3));
    float diff = max(dot(normalize(v_normal), light_dir), 0.0);

    vec3 albedo = base_color;
    if (use_texture) {
        albedo *= texture(tex, v_uv).rgb;
    }
    vec3 ambient = albedo * 0.3;
    vec3 diffuse = albedo * diff * 0.7;
    vec3 emissive = emissive_color * emissive_strength;

    fragColor = vec4(ambient + diffuse + emissive, 1.0);
}
"""


# ---------------------------------------------------------------------------
# Beam shaders — volumetric light cone / cylinder / box
# ---------------------------------------------------------------------------

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

# Same as BEAM_VERTEX_SHADER but also forwards local position to the
# fragment shader (needed for gobo projection).
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
    v_position = in_position;
}
"""

BEAM_FRAGMENT_SHADER = """
#version 330

in float v_alpha;

out vec4 fragColor;

uniform vec3 beam_color;
uniform float beam_intensity;

void main() {
    float alpha = v_alpha * beam_intensity * 0.8;
    fragColor = vec4(beam_color, alpha);
}
"""

# Beam fragment with gobo pattern modulation and focus-based blur.
GOBO_BEAM_FRAGMENT_SHADER = """
#version 330

in float v_alpha;
in vec3 v_position;

out vec4 fragColor;

uniform vec3 beam_color;
uniform float beam_intensity;
uniform int gobo_pattern;
uniform float gobo_rotation;
uniform float focus_sharpness;

const float PI = 3.14159265359;

vec2 rotate_2d(vec2 p, float angle) {
    float c = cos(angle);
    float s = sin(angle);
    return vec2(p.x * c - p.y * s, p.x * s + p.y * c);
}

float beam_gobo_pattern(vec2 uv, int pattern, float blur) {
    if (pattern == 0) return 1.0;

    vec2 centered = uv;
    float dist = length(centered);
    float angle = atan(centered.y, centered.x);

    float edge_blur = mix(0.02, 0.25, blur);

    if (pattern == 1) {
        float dot_angle = mod(angle + PI, PI / 3.0) - PI / 6.0;
        float dots = smoothstep(0.25 + edge_blur, 0.15 - edge_blur, abs(dot_angle)) *
                     smoothstep(0.2 + edge_blur, 0.08 - edge_blur, abs(dist - 0.5));
        return dots;
    }
    if (pattern == 2) {
        float star_radius = 0.35 + 0.2 * cos(angle * 6.0);
        float star = smoothstep(star_radius + 0.08 + edge_blur, star_radius - 0.08 - edge_blur, dist);
        return star;
    }
    if (pattern == 3) {
        float line_pattern = abs(sin(angle * 3.0));
        return smoothstep(0.3 - edge_blur, 0.5 + edge_blur, line_pattern);
    }
    if (pattern == 4) {
        float d1 = centered.y + 0.35;
        float d2 = -0.866 * centered.x - 0.5 * centered.y + 0.35;
        float d3 = 0.866 * centered.x - 0.5 * centered.y + 0.35;
        float tri = smoothstep(-edge_blur, 0.06 + edge_blur, min(min(d1, d2), d3));
        return tri;
    }
    if (pattern == 5) {
        float cross_angle = mod(abs(angle), PI / 2.0);
        float cross = smoothstep(0.18 + edge_blur, 0.12 - edge_blur, min(cross_angle, PI / 2.0 - cross_angle));
        return cross;
    }
    float breakup = 0.5 + 0.5 * sin(angle * 7.0 + dist * 10.0);
    breakup *= 0.5 + 0.5 * sin(angle * 5.0 - dist * 8.0);
    float blur_smooth = mix(0.25, 0.45, blur);
    return smoothstep(blur_smooth, 1.0 - blur_smooth, breakup);
}

void main() {
    float z_pos = max(0.1, v_position.z);
    vec2 beam_uv = v_position.xy / z_pos * 2.0;
    beam_uv = rotate_2d(beam_uv, gobo_rotation);

    float blur = 1.0 - focus_sharpness;
    float pattern_value = beam_gobo_pattern(beam_uv, gobo_pattern, blur);

    float gobo_brightness = mix(0.5, 1.0, pattern_value);

    float edge_softness = mix(0.15, 0.0, focus_sharpness);
    float edge_alpha = smoothstep(edge_softness, 1.0, v_alpha);
    float adjusted_alpha = mix(v_alpha, edge_alpha, 0.5);

    float base_alpha = adjusted_alpha * beam_intensity * 0.3;
    float alpha = base_alpha * gobo_brightness;

    fragColor = vec4(beam_color, alpha);
}
"""


# ---------------------------------------------------------------------------
# Floor projection shaders — soft spotlight footprint on the floor plane
# ---------------------------------------------------------------------------

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
    vec2 centered = v_uv - vec2(0.5);
    float dist = length(centered) * 2.0;

    float soft_edge = 1.0 - smoothstep(0.0, 1.0, dist);
    float gaussian = exp(-dist * dist * 1.5);

    float alpha = soft_edge * gaussian * projection_intensity * distance_falloff;
    alpha = clamp(alpha, 0.0, 0.9);
    fragColor = vec4(projection_color, alpha);
}
"""

# Floor projection with gobo pattern + focus-based blur.
GOBO_FLOOR_PROJECTION_FRAGMENT_SHADER = """
#version 330

in vec2 v_uv;

out vec4 fragColor;

uniform vec3 projection_color;
uniform float projection_intensity;
uniform float distance_falloff;
uniform int gobo_pattern;
uniform float gobo_rotation;
uniform float focus_sharpness;

const float PI = 3.14159265359;

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

float gobo_dots(vec2 uv, float blur) {
    vec2 centered = uv - vec2(0.5);
    float angle = atan(centered.y, centered.x);
    float dist = length(centered) * 2.0;

    float dot_angle = mod(angle + PI, PI / 3.0) - PI / 6.0;
    float dot_dist = abs(dist - 0.5);
    float angular_dist = abs(dot_angle) * dist;

    float edge = mix(0.05, 0.2, blur);
    float dot = smoothstep(0.15 + edge, 0.1 - edge, length(vec2(dot_dist, angular_dist)));
    return dot;
}

float gobo_star(vec2 uv, float blur) {
    vec2 centered = uv - vec2(0.5);
    float angle = atan(centered.y, centered.x);
    float dist = length(centered) * 2.0;

    float star_angle = mod(angle + PI, PI / 3.0) - PI / 6.0;
    float star_radius = 0.3 + 0.2 * cos(star_angle * 6.0);

    float edge = mix(0.05, 0.15, blur);
    return smoothstep(star_radius + edge, star_radius - edge, dist);
}

float gobo_lines(vec2 uv, float blur) {
    float line = mod(uv.x * 10.0, 2.0);
    float edge = mix(0.1, 0.4, blur);
    float mask = smoothstep(0.3 - edge, 0.5 + edge, line) * (1.0 - smoothstep(1.5 - edge, 1.7 + edge, line));

    vec2 centered = uv - vec2(0.5);
    float dist = length(centered) * 2.0;
    float circle_edge = mix(0.1, 0.3, blur);
    float circle = 1.0 - smoothstep(0.8 - circle_edge, 1.0 + circle_edge, dist);

    return mask * circle;
}

float gobo_triangle(vec2 uv, float blur) {
    vec2 centered = uv - vec2(0.5);

    float d1 = centered.y + 0.3;
    float d2 = -0.866 * centered.x - 0.5 * centered.y + 0.3;
    float d3 = 0.866 * centered.x - 0.5 * centered.y + 0.3;

    float tri = min(min(d1, d2), d3);
    float edge = mix(0.02, 0.1, blur);
    return smoothstep(-edge, edge, tri);
}

float gobo_cross(vec2 uv, float blur) {
    vec2 centered = abs(uv - vec2(0.5));

    float arm_width = 0.1 + blur * 0.05;
    float arm_length = 0.35;

    float edge = mix(0.01, 0.1, blur);
    float h_arm = smoothstep(arm_width + edge, arm_width - edge, centered.y) *
                  smoothstep(arm_length + edge, arm_length - edge, centered.x);
    float v_arm = smoothstep(arm_width + edge, arm_width - edge, centered.x) *
                  smoothstep(arm_length + edge, arm_length - edge, centered.y);

    return max(h_arm, v_arm);
}

float gobo_breakup(vec2 uv, float blur) {
    vec2 centered = uv - vec2(0.5);
    float dist = length(centered) * 2.0;

    float angle = atan(centered.y, centered.x);
    float pattern = 0.5 + 0.5 * sin(angle * 7.0 + dist * 15.0);
    pattern *= 0.5 + 0.5 * sin(angle * 5.0 - dist * 10.0 + 1.0);
    pattern *= 0.5 + 0.5 * sin(angle * 3.0 + dist * 8.0 + 2.0);

    float low = mix(0.2, 0.35, blur);
    float high = mix(0.3, 0.45, blur);
    float threshold = smoothstep(low, high, pattern);

    float circle_edge = mix(0.1, 0.3, blur);
    float circle = 1.0 - smoothstep(0.7 - circle_edge, 0.9 + circle_edge, dist);

    return threshold * circle;
}

float get_gobo_pattern(vec2 uv, int pattern, float blur) {
    if (pattern == 0) return 1.0;
    if (pattern == 1) return gobo_dots(uv, blur);
    if (pattern == 2) return gobo_star(uv, blur);
    if (pattern == 3) return gobo_lines(uv, blur);
    if (pattern == 4) return gobo_triangle(uv, blur);
    if (pattern == 5) return gobo_cross(uv, blur);
    return gobo_breakup(uv, blur);
}

void main() {
    vec2 rotated_uv = rotate_uv(v_uv, gobo_rotation);

    float blur = 1.0 - focus_sharpness;
    float gobo_mask = get_gobo_pattern(rotated_uv, gobo_pattern, blur);

    vec2 centered = v_uv - vec2(0.5);
    float dist = length(centered) * 2.0;

    float gaussian_width = mix(2.5, 1.0, focus_sharpness);
    float gaussian = exp(-dist * dist * gaussian_width);

    float edge_start = mix(-0.2, 0.0, focus_sharpness);
    float edge_end = mix(1.2, 1.0, focus_sharpness);
    float soft_edge = 1.0 - smoothstep(edge_start, edge_end, dist);

    float alpha = soft_edge * gaussian * gobo_mask * projection_intensity * distance_falloff;
    alpha = clamp(alpha, 0.0, 0.9);
    fragColor = vec4(projection_color, alpha);
}
"""
