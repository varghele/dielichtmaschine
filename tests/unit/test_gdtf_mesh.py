# tests/unit/test_gdtf_mesh.py
"""Unit tests for the GLB mesh bake (GDTF plan Phase 3).

Synthetic GLBs are authored in-test via trimesh; one optional test runs
against a real Share download when gdtf_fixtures/ is populated locally
(never in CI - Share files are not committed).
"""
import glob
import os
import zipfile

import numpy as np
import pytest
import trimesh

from utils.gdtf_mesh import BakedMesh, clear_mesh_cache, load_glb_mesh

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_mesh_cache()
    yield
    clear_mesh_cache()


def _gdtf_with_glb(tmp_path, box_extents=(100.0, 50.0, 25.0)):
    """A minimal .gdtf zip holding one GLB box (mm-scale, like the wild)."""
    mesh = trimesh.creation.box(extents=box_extents)
    glb_bytes = trimesh.Scene(mesh).export(file_type='glb')
    path = os.path.join(str(tmp_path), "mesh_test.gdtf")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("description.xml", "<GDTF/>")
        z.writestr("models/gltf/body.glb", glb_bytes)
    return path


def test_bake_scales_to_model_dims_pivot_preserved(tmp_path):
    path = _gdtf_with_glb(tmp_path)  # 100 x 50 x 25 units, centered
    baked = load_glb_mesh(path, "models/gltf/body.glb",
                          target_dims_m=(1.0, 0.5, 0.25))
    assert isinstance(baked, BakedMesh)
    positions = baked.vertex_data[:, :3]
    extents = positions.max(axis=0) - positions.min(axis=0)
    assert extents == pytest.approx((1.0, 0.5, 0.25), abs=1e-5)
    # Pivot preserved: the box was centered at the origin and must stay so.
    center = (positions.max(axis=0) + positions.min(axis=0)) / 2
    assert center == pytest.approx((0, 0, 0), abs=1e-6)


def test_bake_layout_and_types(tmp_path):
    path = _gdtf_with_glb(tmp_path)
    baked = load_glb_mesh(path, "models/gltf/body.glb")
    assert baked.vertex_data.dtype == np.float32
    assert baked.vertex_data.shape[1] == 8   # pos3 + normal3 + uv2
    assert baked.indices.dtype == np.uint32
    assert len(baked.indices) % 3 == 0
    assert baked.triangle_count == 12        # a box
    # Normals are unit length
    lengths = np.linalg.norm(baked.vertex_data[:, 3:6], axis=1)
    assert lengths == pytest.approx(np.ones_like(lengths), abs=1e-4)
    assert len(baked.base_color) == 4


def test_vertex_cap_rejects(tmp_path, capsys):
    path = _gdtf_with_glb(tmp_path)
    assert load_glb_mesh(path, "models/gltf/body.glb", max_vertices=4) is None
    assert "rejected" in capsys.readouterr().out


def test_broken_glb_returns_none_and_caches(tmp_path):
    path = os.path.join(str(tmp_path), "broken.gdtf")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("models/gltf/bad.glb", b"not a glb")
    assert load_glb_mesh(path, "models/gltf/bad.glb") is None
    assert load_glb_mesh(path, "models/gltf/bad.glb") is None  # cached miss


def test_bake_result_is_cached(tmp_path):
    path = _gdtf_with_glb(tmp_path)
    first = load_glb_mesh(path, "models/gltf/body.glb")
    assert load_glb_mesh(path, "models/gltf/body.glb") is first


_MAGICBLADE = glob.glob(os.path.join(REPO_ROOT, "gdtf_fixtures",
                                     "Ayrton@MagicBlade R@*.gdtf"))


@pytest.mark.skipif(not _MAGICBLADE,
                    reason="local Share download not present (not committed)")
def test_real_magicblade_head_glb_bakes():
    from utils.gdtf_loader import parse_gdtf_file
    defn = parse_gdtf_file(_MAGICBLADE[0])
    model = next(m for m in defn.gdtf.models.values() if m.glb_path())
    baked = load_glb_mesh(defn.path, model.glb_path(),
                          target_dims_m=(model.length_m, model.width_m,
                                         model.height_m))
    assert baked is not None
    assert 0 < baked.vertex_count <= 60000
    extents = (baked.vertex_data[:, :3].max(axis=0)
               - baked.vertex_data[:, :3].min(axis=0))
    assert extents.max() < 2.0, "meters now, not millimeters"
    assert baked.vertex_data[:, 6:8].any(), "real file carries UVs"
