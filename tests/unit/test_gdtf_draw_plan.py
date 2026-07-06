# tests/unit/test_gdtf_draw_plan.py
"""Kinematic draw plan for GDTF mesh rendering (GL-free, plan Phase 3)."""
import glob
import os
import zipfile

import numpy as np
import pytest

from utils.gdtf_loader import parse_gdtf_file
from visualizer.renderer.gdtf_draw_plan import build_draw_plan

from tests.unit.test_gdtf_loader import SPOT_DESCRIPTION

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture()
def spot_defn(tmp_path):
    path = os.path.join(str(tmp_path), "spot.gdtf")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("description.xml", SPOT_DESCRIPTION)
    return parse_gdtf_file(path)


def test_plan_items_and_axis_chain(spot_defn):
    plan = build_draw_plan(spot_defn.gdtf, "Standard")
    by_name = {i.node_name: i for i in plan}
    assert "Base" in by_name and by_name["Base"].model_name == "BaseModel"
    assert "Beam1" in by_name and by_name["Beam1"].is_beam

    beam = by_name["Beam1"]
    axes = [s.axis_attribute for s in beam.chain if s.axis_attribute]
    assert axes == ["Pan", "Tilt"], "beam sits below yoke pan then head tilt"
    base_axes = [s.axis_attribute for s in by_name["Base"].chain if s.axis_attribute]
    assert base_axes == [], "base is static"


def test_compose_applies_live_rotations(spot_defn):
    beam = next(i for i in build_draw_plan(spot_defn.gdtf, "Standard")
                if i.is_beam)
    # All transforms identity in the synthetic file, so composed motion
    # is pure pan/tilt. -Z (beam direction) must stay -Z under pan only.
    down = np.array([0, 0, -1, 0.0])
    assert np.allclose(beam.compose(90, 0) @ down, down, atol=1e-9)
    # Tilt 90 about X sends -Z to -Y... (right-handed X rotation).
    tilted = beam.compose(0, 90) @ down
    assert tilted == pytest.approx([0, 1, 0, 0], abs=1e-9)
    # Pan then rotates that within the horizontal plane.
    pan_tilt = beam.compose(90, 90) @ down
    assert pan_tilt == pytest.approx([-1, 0, 0, 0], abs=1e-9)


def test_unknown_mode_falls_back_to_first_tree(spot_defn):
    plan = build_draw_plan(spot_defn.gdtf, "No Such Mode")
    assert any(i.is_beam for i in plan)


_MAGICBLADE = glob.glob(os.path.join(REPO_ROOT, "gdtf_fixtures",
                                     "Ayrton@MagicBlade R@*.gdtf"))


@pytest.mark.skipif(not _MAGICBLADE,
                    reason="local Share download not present (not committed)")
def test_real_magicblade_plan():
    defn = parse_gdtf_file(_MAGICBLADE[0])
    plan = build_draw_plan(defn.gdtf, "Extended")
    assert plan, "plan must not be empty"
    modeled = [i for i in plan if i.model_name]
    assert modeled, "MagicBlade carries models"
    beams = [i for i in plan if i.is_beam]
    assert beams
    axes = [s.axis_attribute for s in beams[0].chain if s.axis_attribute]
    assert axes == ["Pan", "Tilt"]
