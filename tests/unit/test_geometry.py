"""Smoke tests for the procedural mesh builder (v1.5.5 hardening, G10).

``utils/geometry.py`` feeds every chassis, beam and floor-projection
mesh in the visualizer and the orientation preview, but had no direct
test. These pin array shapes, bounds, normals and winding, so a change
that breaks a mesh fails here instead of as a subtly wrong picture.

Winding note: the box and the cylinder are both wound counter-clockwise
seen from outside (the cylinder was clockwise until 2026-10-13). The
renderer never enables face culling (visualizer/renderer/camera.py), so
the flip changes no pixel; it makes both meshes ready for culling.
"""

from __future__ import annotations

import numpy as np
import pytest

from utils.geometry import GeometryBuilder as G


def _tris(vertices):
    return vertices.reshape(-1, 3, 3)


def _face_normals(vertices):
    t = _tris(vertices)
    return np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])


class TestBox:
    def test_shape_bounds_and_normals(self):
        v, n = G.create_box(2.0, 4.0, 6.0, center=(1.0, 2.0, 3.0))
        assert v.dtype == np.float32 and n.dtype == np.float32
        assert v.shape == n.shape == (36 * 3,)
        pts = v.reshape(-1, 3)
        assert pts.min(axis=0) == pytest.approx([0.0, 0.0, 0.0])
        assert pts.max(axis=0) == pytest.approx([2.0, 4.0, 6.0])
        norms = n.reshape(-1, 3)
        assert np.linalg.norm(norms, axis=1) == pytest.approx(np.ones(36))

    def test_normals_point_outward_and_winding_is_ccw(self):
        v, n = G.create_box(1.0, 1.0, 1.0, center=(5.0, -2.0, 0.5))
        centre = np.array([5.0, -2.0, 0.5])
        tri = _tris(v)
        vertex_normals = n.reshape(-1, 3, 3)[:, 0]
        outward = tri.mean(axis=1) - centre
        assert np.all(np.einsum("ij,ij->i", outward, vertex_normals) > 0)
        assert np.all(np.einsum("ij,ij->i", _face_normals(v), vertex_normals) > 0)


class TestCylinder:
    @pytest.mark.parametrize("segments", [3, 8, 16, 33])
    def test_shape_and_bounds(self, segments):
        v, n = G.create_cylinder(0.5, 2.0, segments=segments, center=(0, 1, 0))
        # sides: 2 tris per segment, caps: 1 tri per segment each
        assert v.shape == n.shape == (segments * 4 * 3 * 3,)
        pts = v.reshape(-1, 3)
        assert pts[:, 1].min() == pytest.approx(0.0)
        assert pts[:, 1].max() == pytest.approx(2.0)
        radial = np.hypot(pts[:, 0], pts[:, 2])
        assert radial.max() == pytest.approx(0.5, abs=1e-6)
        assert np.linalg.norm(n.reshape(-1, 3), axis=1) == \
            pytest.approx(np.ones(len(pts)), abs=1e-6)

    def test_normals_point_outward_and_winding_is_ccw(self):
        v, n = G.create_cylinder(1.0, 1.0, segments=12, center=(2.0, 3.0, -1.0))
        vertex_normals = n.reshape(-1, 3, 3).mean(axis=1)
        outward = _tris(v).mean(axis=1) - np.array([2.0, 3.0, -1.0])
        assert np.all(np.einsum("ij,ij->i", outward, vertex_normals) > 0)
        assert np.all(np.einsum("ij,ij->i", _face_normals(v),
                                vertex_normals) > 0)


class TestBeams:
    @pytest.mark.parametrize("segments", [4, 16])
    def test_cone_runs_tip_to_base_along_z(self, segments):
        v, a = G.create_beam_cone(0.3, 5.0, segments=segments)
        pts = v.reshape(-1, 3)
        assert len(pts) == len(a) == segments * 3
        assert np.all(pts[0::3] == 0.0)
        assert np.all(a[0::3] == 1.0) and np.all(a[1::3] == 0.0)
        assert pts[:, 2].max() == pytest.approx(5.0)
        base = pts[1::3]
        assert np.hypot(base[:, 0], base[:, 1]) == \
            pytest.approx(np.full(segments, 0.3), abs=1e-6)

    def test_cylinder_beam_fades_with_distance(self):
        v, a = G.create_beam_cylinder(0.2, 4.0, segments=6)
        pts = v.reshape(-1, 3)
        assert len(pts) == len(a) == 6 * 9
        assert np.all(a[pts[:, 2] == 0.0] == 1.0)
        assert np.all(a[pts[:, 2] == 4.0] == 0.0)

    def test_box_beam_bounds(self):
        v, a = G.create_beam_box(1.0, 0.5, 3.0)
        pts = v.reshape(-1, 3)
        assert len(pts) == len(a) == 30
        assert pts.min(axis=0) == pytest.approx([-0.5, -0.25, 0.0])
        assert pts.max(axis=0) == pytest.approx([0.5, 0.25, 3.0])
        assert set(np.unique(a)) <= {0.0, 1.0}


class TestFloorDisk:
    def test_unit_disk_in_xz_with_uvs_in_range(self):
        v, uv = G.create_floor_projection_disk(segments=24)
        pts = v.reshape(-1, 3)
        uvs = uv.reshape(-1, 2)
        assert len(pts) == len(uvs) == 24 * 3
        assert np.all(pts[:, 1] == 0.0)
        assert np.hypot(pts[:, 0], pts[:, 2]).max() == pytest.approx(1.0, abs=1e-6)
        assert uvs.min() >= 0.0 and uvs.max() <= 1.0
        assert np.all(uvs[0::3] == 0.5)
