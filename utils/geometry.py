# utils/geometry.py
# Shared procedural geometry builder used by orientation dialog and visualizer

import math
from typing import Tuple

import numpy as np


class GeometryBuilder:
    """Utility class for building procedural geometry."""

    @staticmethod
    def create_box(width: float, height: float, depth: float,
                   center: Tuple[float, float, float] = (0, 0, 0)) -> Tuple[np.ndarray, np.ndarray]:
        """
        Create a box mesh.

        Args:
            width: Box width (X axis)
            height: Box height (Y axis)
            depth: Box depth (Z axis)
            center: Center position

        Returns:
            Tuple of (vertices, normals) as numpy arrays
        """
        hw, hh, hd = width / 2, height / 2, depth / 2
        cx, cy, cz = center

        # 6 faces, 2 triangles each, 3 vertices per triangle = 36 vertices
        vertices = []
        normals = []

        # Front face (+Z)
        vertices.extend([
            cx - hw, cy - hh, cz + hd,
            cx + hw, cy - hh, cz + hd,
            cx + hw, cy + hh, cz + hd,
            cx - hw, cy - hh, cz + hd,
            cx + hw, cy + hh, cz + hd,
            cx - hw, cy + hh, cz + hd,
        ])
        normals.extend([0, 0, 1] * 6)

        # Back face (-Z)
        vertices.extend([
            cx + hw, cy - hh, cz - hd,
            cx - hw, cy - hh, cz - hd,
            cx - hw, cy + hh, cz - hd,
            cx + hw, cy - hh, cz - hd,
            cx - hw, cy + hh, cz - hd,
            cx + hw, cy + hh, cz - hd,
        ])
        normals.extend([0, 0, -1] * 6)

        # Right face (+X)
        vertices.extend([
            cx + hw, cy - hh, cz + hd,
            cx + hw, cy - hh, cz - hd,
            cx + hw, cy + hh, cz - hd,
            cx + hw, cy - hh, cz + hd,
            cx + hw, cy + hh, cz - hd,
            cx + hw, cy + hh, cz + hd,
        ])
        normals.extend([1, 0, 0] * 6)

        # Left face (-X)
        vertices.extend([
            cx - hw, cy - hh, cz - hd,
            cx - hw, cy - hh, cz + hd,
            cx - hw, cy + hh, cz + hd,
            cx - hw, cy - hh, cz - hd,
            cx - hw, cy + hh, cz + hd,
            cx - hw, cy + hh, cz - hd,
        ])
        normals.extend([-1, 0, 0] * 6)

        # Top face (+Y)
        vertices.extend([
            cx - hw, cy + hh, cz + hd,
            cx + hw, cy + hh, cz + hd,
            cx + hw, cy + hh, cz - hd,
            cx - hw, cy + hh, cz + hd,
            cx + hw, cy + hh, cz - hd,
            cx - hw, cy + hh, cz - hd,
        ])
        normals.extend([0, 1, 0] * 6)

        # Bottom face (-Y)
        vertices.extend([
            cx - hw, cy - hh, cz - hd,
            cx + hw, cy - hh, cz - hd,
            cx + hw, cy - hh, cz + hd,
            cx - hw, cy - hh, cz - hd,
            cx + hw, cy - hh, cz + hd,
            cx - hw, cy - hh, cz + hd,
        ])
        normals.extend([0, -1, 0] * 6)

        return np.array(vertices, dtype='f4'), np.array(normals, dtype='f4')

    @staticmethod
    def create_cylinder(radius: float, height: float, segments: int = 16,
                        center: Tuple[float, float, float] = (0, 0, 0)) -> Tuple[np.ndarray, np.ndarray]:
        """
        Create a cylinder mesh oriented along Y axis.

        Triangles are wound counter-clockwise seen from outside, like
        the box, so the mesh is ready for back-face culling.

        Args:
            radius: Cylinder radius
            height: Cylinder height
            segments: Number of segments around circumference
            center: Center position

        Returns:
            Tuple of (vertices, normals) as numpy arrays
        """
        cx, cy, cz = center
        hh = height / 2

        vertices = []
        normals = []

        # Side faces
        for i in range(segments):
            angle1 = 2 * math.pi * i / segments
            angle2 = 2 * math.pi * (i + 1) / segments

            x1, z1 = math.cos(angle1) * radius, math.sin(angle1) * radius
            x2, z2 = math.cos(angle2) * radius, math.sin(angle2) * radius

            # Two triangles for this segment
            # Triangle 1
            vertices.extend([
                cx + x1, cy - hh, cz + z1,
                cx + x2, cy + hh, cz + z2,
                cx + x2, cy - hh, cz + z2,
            ])
            normals.extend([
                math.cos(angle1), 0, math.sin(angle1),
                math.cos(angle2), 0, math.sin(angle2),
                math.cos(angle2), 0, math.sin(angle2),
            ])

            # Triangle 2
            vertices.extend([
                cx + x1, cy - hh, cz + z1,
                cx + x1, cy + hh, cz + z1,
                cx + x2, cy + hh, cz + z2,
            ])
            normals.extend([
                math.cos(angle1), 0, math.sin(angle1),
                math.cos(angle1), 0, math.sin(angle1),
                math.cos(angle2), 0, math.sin(angle2),
            ])

        # Top cap
        for i in range(segments):
            angle1 = 2 * math.pi * i / segments
            angle2 = 2 * math.pi * (i + 1) / segments

            x1, z1 = math.cos(angle1) * radius, math.sin(angle1) * radius
            x2, z2 = math.cos(angle2) * radius, math.sin(angle2) * radius

            vertices.extend([
                cx, cy + hh, cz,
                cx + x2, cy + hh, cz + z2,
                cx + x1, cy + hh, cz + z1,
            ])
            normals.extend([0, 1, 0] * 3)

        # Bottom cap
        for i in range(segments):
            angle1 = 2 * math.pi * i / segments
            angle2 = 2 * math.pi * (i + 1) / segments

            x1, z1 = math.cos(angle1) * radius, math.sin(angle1) * radius
            x2, z2 = math.cos(angle2) * radius, math.sin(angle2) * radius

            vertices.extend([
                cx, cy - hh, cz,
                cx + x1, cy - hh, cz + z1,
                cx + x2, cy - hh, cz + z2,
            ])
            normals.extend([0, -1, 0] * 3)

        return np.array(vertices, dtype='f4'), np.array(normals, dtype='f4')

    @staticmethod
    def create_beam_cone(base_radius: float, length: float, segments: int = 16) -> Tuple[np.ndarray, np.ndarray]:
        """
        Create a beam cone mesh for volumetric lighting.

        The cone starts at origin and extends along +Z axis.
        Alpha values are 1.0 at tip, fading to 0.0 at base edges.

        Args:
            base_radius: Radius at the base of the cone
            length: Length of the cone
            segments: Number of segments around circumference

        Returns:
            Tuple of (vertices, alphas) as numpy arrays
        """
        vertices = []
        alphas = []

        # Cone from tip (0,0,0) to base at z=length
        for i in range(segments):
            angle1 = 2 * math.pi * i / segments
            angle2 = 2 * math.pi * (i + 1) / segments

            x1, y1 = math.cos(angle1) * base_radius, math.sin(angle1) * base_radius
            x2, y2 = math.cos(angle2) * base_radius, math.sin(angle2) * base_radius

            # Triangle from tip to two base vertices
            # Tip vertex (bright)
            vertices.extend([0, 0, 0])
            alphas.append(1.0)

            # Base vertex 1 (dim)
            vertices.extend([x1, y1, length])
            alphas.append(0.0)

            # Base vertex 2 (dim)
            vertices.extend([x2, y2, length])
            alphas.append(0.0)

        return np.array(vertices, dtype='f4'), np.array(alphas, dtype='f4')

    @staticmethod
    def create_beam_cylinder(radius: float, length: float, segments: int = 12) -> Tuple[np.ndarray, np.ndarray]:
        """
        Create a cylindrical beam mesh for volumetric lighting.

        The cylinder starts at origin and extends along +Z axis.
        Alpha fades from 1.0 at origin to 0.0 at the end.

        Args:
            radius: Radius of the cylinder
            length: Length of the cylinder
            segments: Number of segments around circumference

        Returns:
            Tuple of (vertices, alphas) as numpy arrays
        """
        vertices = []
        alphas = []

        # Create cylinder sides with fading alpha
        for i in range(segments):
            angle1 = 2 * math.pi * i / segments
            angle2 = 2 * math.pi * (i + 1) / segments

            x1, y1 = math.cos(angle1) * radius, math.sin(angle1) * radius
            x2, y2 = math.cos(angle2) * radius, math.sin(angle2) * radius

            # Two triangles per segment (quad)
            # Triangle 1: near edge to far edge
            vertices.extend([x1, y1, 0])  # Near 1
            alphas.append(1.0)
            vertices.extend([x2, y2, 0])  # Near 2
            alphas.append(1.0)
            vertices.extend([x2, y2, length])  # Far 2
            alphas.append(0.0)

            # Triangle 2
            vertices.extend([x1, y1, 0])  # Near 1
            alphas.append(1.0)
            vertices.extend([x2, y2, length])  # Far 2
            alphas.append(0.0)
            vertices.extend([x1, y1, length])  # Far 1
            alphas.append(0.0)

        # End cap (bright)
        for i in range(segments):
            angle1 = 2 * math.pi * i / segments
            angle2 = 2 * math.pi * (i + 1) / segments

            x1, y1 = math.cos(angle1) * radius, math.sin(angle1) * radius
            x2, y2 = math.cos(angle2) * radius, math.sin(angle2) * radius

            vertices.extend([0, 0, 0])  # Center
            alphas.append(1.0)
            vertices.extend([x1, y1, 0])
            alphas.append(1.0)
            vertices.extend([x2, y2, 0])
            alphas.append(1.0)

        return np.array(vertices, dtype='f4'), np.array(alphas, dtype='f4')

    @staticmethod
    def create_beam_box(width: float, height: float, length: float) -> Tuple[np.ndarray, np.ndarray]:
        """
        Create a rectangular beam mesh for volumetric lighting.

        The box starts at origin and extends along +Z axis.
        Alpha fades from 1.0 at origin to 0.0 at the end.

        Args:
            width: Width of the beam (X axis)
            height: Height of the beam (Y axis)
            length: Length of the beam (Z axis)

        Returns:
            Tuple of (vertices, alphas) as numpy arrays
        """
        hw, hh = width / 2, height / 2
        vertices = []
        alphas = []

        # Four sides of the box with fading alpha

        # Top face (+Y)
        vertices.extend([-hw, hh, 0, hw, hh, 0, hw, hh, length])  # Tri 1
        alphas.extend([1.0, 1.0, 0.0])
        vertices.extend([-hw, hh, 0, hw, hh, length, -hw, hh, length])  # Tri 2
        alphas.extend([1.0, 0.0, 0.0])

        # Bottom face (-Y)
        vertices.extend([hw, -hh, 0, -hw, -hh, 0, -hw, -hh, length])  # Tri 1
        alphas.extend([1.0, 1.0, 0.0])
        vertices.extend([hw, -hh, 0, -hw, -hh, length, hw, -hh, length])  # Tri 2
        alphas.extend([1.0, 0.0, 0.0])

        # Right face (+X)
        vertices.extend([hw, -hh, 0, hw, hh, 0, hw, hh, length])  # Tri 1
        alphas.extend([1.0, 1.0, 0.0])
        vertices.extend([hw, -hh, 0, hw, hh, length, hw, -hh, length])  # Tri 2
        alphas.extend([1.0, 0.0, 0.0])

        # Left face (-X)
        vertices.extend([-hw, hh, 0, -hw, -hh, 0, -hw, -hh, length])  # Tri 1
        alphas.extend([1.0, 1.0, 0.0])
        vertices.extend([-hw, hh, 0, -hw, -hh, length, -hw, hh, length])  # Tri 2
        alphas.extend([1.0, 0.0, 0.0])

        # Front face (near end, z=0) - bright
        vertices.extend([-hw, -hh, 0, hw, -hh, 0, hw, hh, 0])  # Tri 1
        alphas.extend([1.0, 1.0, 1.0])
        vertices.extend([-hw, -hh, 0, hw, hh, 0, -hw, hh, 0])  # Tri 2
        alphas.extend([1.0, 1.0, 1.0])

        return np.array(vertices, dtype='f4'), np.array(alphas, dtype='f4')

    @staticmethod
    def create_floor_projection_disk(segments: int = 32) -> Tuple[np.ndarray, np.ndarray]:
        """
        Create a unit disk for floor projection.

        The disk is centered at origin in the XZ plane (Y=0) with radius 1.
        It will be scaled and positioned via model matrix during rendering.

        Args:
            segments: Number of segments around circumference

        Returns:
            Tuple of (vertices, uvs) as numpy arrays
            - vertices: XYZ positions (Y=0 for all)
            - uvs: UV coordinates for gradient calculation
        """
        vertices = []
        uvs = []

        # Create triangular fan from center
        for i in range(segments):
            angle1 = 2 * math.pi * i / segments
            angle2 = 2 * math.pi * (i + 1) / segments

            x1, z1 = math.cos(angle1), math.sin(angle1)
            x2, z2 = math.cos(angle2), math.sin(angle2)

            # Center vertex
            vertices.extend([0, 0, 0])
            uvs.extend([0.5, 0.5])

            # Edge vertex 1
            vertices.extend([x1, 0, z1])
            uvs.extend([(x1 + 1) / 2, (z1 + 1) / 2])

            # Edge vertex 2
            vertices.extend([x2, 0, z2])
            uvs.extend([(x2 + 1) / 2, (z2 + 1) / 2])

        return np.array(vertices, dtype='f4'), np.array(uvs, dtype='f4')
