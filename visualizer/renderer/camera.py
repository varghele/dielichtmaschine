# visualizer/renderer/camera.py
# Orbit camera for 3D stage visualization

import math
import glm


# ---------------------------------------------------------------------------
# Stage-to-display correction (the "mirrored stage" fix, 2026-07-12)
#
# Every renderer builds its geometry in the historical scene frame
#   stage (x, y, z_height) -> scene (x, z_height, y)
# which SWAPS two axes. A two-axis swap has determinant -1: it is a
# REFLECTION, so the whole scene was a mirror image of the real stage
# (floor text came out as mirror writing, and a beam aimed at a spot
# appeared to hit its mirror image). Everything inside the scene was
# self-consistent, which is why beams still landed on their targets -
# the mirror only showed up against reality.
#
# The correction is one change of basis applied at the VIEW matrix, so
# no renderer, no model matrix, and above all NO PAN/TILT MATH changes:
#   display = DISPLAY_FLIP * scene,   DISPLAY_FLIP = diag(1, 1, -1)
# Composed with the scene mapping this gives stage (x, y, z) ->
# display (x, z, -y): determinant +1, a proper rotation, so the picture
# is finally a faithful copy of the stage rather than its mirror.
#
# Consequences, all desirable:
# - Stage depth +Y (upstage) maps to display -Z, so the AUDIENCE side
#   (-Y) lands at display +Z, which is where the default camera already
#   sits (azimuth 45) - the view now looks at the stage FROM the
#   audience instead of from behind the band.
# - The coordinate gizmo consumes the view matrix too, so it flips with
#   the scene and keeps agreeing with what is drawn.
# - Face culling is never enabled in this renderer, so the reflected
#   winding is harmless; blending and depth are unaffected.
#
# DMX is untouched by design: utils/orientation.py keeps solving pan and
# tilt in the scene frame, and both the target and the beam it produces
# get the same correction, so what the arbiter sends the rig is exactly
# what it sent before this fix.
# ---------------------------------------------------------------------------
DISPLAY_FLIP = glm.mat4(
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, -1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


class OrbitCamera:
    """
    Orbiting camera that rotates around a target point.

    Controls:
    - Left mouse drag: Orbit (rotate around target)
    - Right mouse drag: Pan (move target point)
    - Scroll wheel: Zoom (change distance to target)
    - Home key: Reset to default view
    """

    def __init__(self):
        # Target point (center of stage)
        self.target = glm.vec3(0.0, 0.0, 0.0)

        # Spherical coordinates relative to target
        self.distance = 15.0  # Distance from target
        self.azimuth = 45.0   # Horizontal angle (degrees)
        self.elevation = 30.0  # Vertical angle (degrees)

        # Limits
        self.min_distance = 2.0
        self.max_distance = 100.0
        self.min_elevation = 5.0
        self.max_elevation = 89.0

        # Sensitivity
        self.orbit_sensitivity = 0.3
        self.pan_sensitivity = 0.01
        self.zoom_sensitivity = 0.1

        # Projection parameters
        self.fov = 45.0  # Field of view (degrees)
        self.aspect = 16.0 / 9.0
        self.near = 0.1
        self.far = 500.0

        # Default values for reset
        self._default_target = glm.vec3(0.0, 0.0, 0.0)
        self._default_distance = 15.0
        self._default_azimuth = 45.0
        self._default_elevation = 30.0

    def reset(self):
        """Reset camera to default position."""
        self.target = glm.vec3(self._default_target)
        self.distance = self._default_distance
        self.azimuth = self._default_azimuth
        self.elevation = self._default_elevation

    def set_stage_size(self, width: float, depth: float):
        """
        Adjust camera to fit stage.

        Args:
            width: Stage width in meters
            depth: Stage depth in meters
        """
        # Center target on stage
        self.target = glm.vec3(0.0, 0.0, 0.0)
        self._default_target = glm.vec3(0.0, 0.0, 0.0)

        # Adjust distance to see entire stage
        max_dim = max(width, depth)
        self.distance = max_dim * 1.5
        self._default_distance = self.distance

    def orbit(self, delta_x: float, delta_y: float):
        """
        Rotate camera around target.

        Args:
            delta_x: Horizontal mouse movement
            delta_y: Vertical mouse movement
        """
        self.azimuth -= delta_x * self.orbit_sensitivity
        self.elevation += delta_y * self.orbit_sensitivity

        # Wrap azimuth
        self.azimuth = self.azimuth % 360.0

        # Clamp elevation
        self.elevation = max(self.min_elevation, min(self.max_elevation, self.elevation))

    def pan(self, delta_x: float, delta_y: float):
        """
        Move target point (pan camera).

        Args:
            delta_x: Horizontal mouse movement
            delta_y: Vertical mouse movement
        """
        # Get camera right and up vectors
        right = self._get_right_vector()
        up = glm.vec3(0.0, 1.0, 0.0)  # World up for horizontal panning

        # Calculate pan amount based on distance
        pan_scale = self.distance * self.pan_sensitivity

        # Apply pan
        self.target += right * (-delta_x * pan_scale)
        self.target += up * (delta_y * pan_scale)

    def zoom(self, delta: float):
        """
        Zoom camera (change distance to target).

        Args:
            delta: Scroll wheel delta (positive = zoom in)
        """
        zoom_factor = 1.0 - delta * self.zoom_sensitivity
        self.distance *= zoom_factor
        self.distance = max(self.min_distance, min(self.max_distance, self.distance))

    def set_aspect(self, aspect: float):
        """Set aspect ratio for projection matrix."""
        self.aspect = aspect

    def get_position(self) -> glm.vec3:
        """Get camera position in world space."""
        # Convert spherical to Cartesian
        azimuth_rad = math.radians(self.azimuth)
        elevation_rad = math.radians(self.elevation)

        x = self.distance * math.cos(elevation_rad) * math.sin(azimuth_rad)
        y = self.distance * math.sin(elevation_rad)
        z = self.distance * math.cos(elevation_rad) * math.cos(azimuth_rad)

        return self.target + glm.vec3(x, y, z)

    def get_view_matrix(self) -> glm.mat4:
        """Get view matrix for rendering.

        Carries the stage-to-display correction (:data:`DISPLAY_FLIP`):
        renderers hand in geometry in the historical mirrored scene
        frame, and this matrix turns it into a faithful, non-reflected
        view of the stage. The camera itself therefore lives in display
        space - azimuth 45 looks at the stage from the AUDIENCE side.
        """
        position = self.get_position()
        view = glm.lookAt(position, self.target, glm.vec3(0.0, 1.0, 0.0))
        return view * DISPLAY_FLIP

    def get_projection_matrix(self) -> glm.mat4:
        """Get projection matrix for rendering."""
        return glm.perspective(
            glm.radians(self.fov),
            self.aspect,
            self.near,
            self.far
        )

    def get_view_projection_matrix(self) -> glm.mat4:
        """Get combined view-projection matrix (display-corrected)."""
        return self.get_projection_matrix() * self.get_view_matrix()

    def _get_right_vector(self) -> glm.vec3:
        """Get camera right vector for panning."""
        azimuth_rad = math.radians(self.azimuth)
        return glm.vec3(
            math.cos(azimuth_rad),
            0.0,
            -math.sin(azimuth_rad)
        )

    def _get_forward_vector(self) -> glm.vec3:
        """Get camera forward vector."""
        azimuth_rad = math.radians(self.azimuth)
        elevation_rad = math.radians(self.elevation)

        return glm.vec3(
            -math.cos(elevation_rad) * math.sin(azimuth_rad),
            -math.sin(elevation_rad),
            -math.cos(elevation_rad) * math.cos(azimuth_rad)
        )
