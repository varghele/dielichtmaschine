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


def _translate_z(z):
    m = np.eye(4)
    m[2, 3] = z
    return m


def _item(name, z, is_beam=False):
    from visualizer.renderer.gdtf_draw_plan import ChainStep, DrawItem
    return DrawItem(node_name=name, model_name=name,
                    chain=[ChainStep(matrix=_translate_z(z),
                                     axis_attribute=None)],
                    is_beam=is_beam)


class TestPostureCanonicalization:
    """GDTF suspends fixtures below their attachment origin (tree at
    negative Z); the chassis frame is standing-authored (+Z up), and the
    mounting presets flip a STANDING body. A hanging-authored plan must
    be rotated upright or hung rigs render standing with beams at the
    ceiling (the tester.lms Hero Spot 60 bug, 2026-07-13)."""

    def test_hanging_authored_tree_is_rotated_upright(self):
        from visualizer.renderer.gdtf_draw_plan import _canonicalize_posture
        items = [_item("Base", 0.0), _item("Head", -0.24),
                 _item("Beam", -0.33, is_beam=True)]
        _canonicalize_posture(items)
        zs = {i.node_name: i.compose(0, 0)[2, 3] for i in items}
        assert zs["Base"] == pytest.approx(0.0)
        assert zs["Head"] == pytest.approx(0.24), "head above the base"
        assert zs["Beam"] == pytest.approx(0.33), "beam above the head"

    def test_standing_authored_tree_is_untouched(self):
        from visualizer.renderer.gdtf_draw_plan import _canonicalize_posture
        items = [_item("Base", 0.0), _item("Cell", 0.04)]
        _canonicalize_posture(items)
        assert items[0].compose(0, 0)[2, 3] == pytest.approx(0.0)
        assert items[1].compose(0, 0)[2, 3] == pytest.approx(0.04)
        assert len(items[0].chain) == 1, "no flip step prepended"

    def test_flat_tree_is_untouched(self):
        from visualizer.renderer.gdtf_draw_plan import _canonicalize_posture
        items = [_item("Body", 0.0)]
        _canonicalize_posture(items)
        assert len(items[0].chain) == 1

    def test_axis_rotations_survive_the_flip(self):
        # Pan/tilt still articulate the flipped subtree about the GDTF
        # axis nodes; the flip is a rigid root rotation, not a re-rig.
        from visualizer.renderer.gdtf_draw_plan import (
            ChainStep, DrawItem, _canonicalize_posture,
        )
        beam = DrawItem(
            node_name="Beam", model_name="Beam",
            chain=[ChainStep(matrix=_translate_z(-0.2),
                             axis_attribute="Pan")],
            is_beam=True)
        _canonicalize_posture([beam])
        no_pan = beam.compose(0, 0)
        panned = beam.compose(90, 0)
        # Position is on the pan axis, so it must not move under pan...
        assert panned[:3, 3] == pytest.approx(no_pan[:3, 3], abs=1e-9)
        # ...but the frame must have rotated.
        assert not np.allclose(panned[:3, :3], no_pan[:3, :3])


_HERO_SPOT = glob.glob(os.path.join(REPO_ROOT, "gdtf_fixtures",
                                    "Varytec@Hero Spot 60@*.gdtf"))


@pytest.mark.skipif(not _HERO_SPOT,
                    reason="local Share download not present (not committed)")
def test_real_hero_spot_is_canonicalized_upright():
    defn = parse_gdtf_file(_HERO_SPOT[0])
    plan = build_draw_plan(defn.gdtf, "14-channel DMX mode")
    beam = next(i for i in plan if i.is_beam)
    # Authored hanging (beam at z=-0.325); canonicalized it sits above
    # the attachment origin so the hanging preset flips it back down.
    assert beam.compose(0, 0)[2, 3] > 0.3


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
