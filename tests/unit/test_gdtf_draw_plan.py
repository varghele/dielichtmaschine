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
    # Positive PHYSICAL rotation runs opposite to right-handed about
    # the node axes - measured on a real Hero Spot 60, bench protocol
    # 2026-07-13 (see DrawItem.compose). Tilt 90 sends -Z to -Y.
    tilted = beam.compose(0, 90) @ down
    assert tilted == pytest.approx([0, -1, 0, 0], abs=1e-9)
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


def _beam_dir_local(item, pan_g, tilt_g):
    """The emitted beam direction in chassis-local space: the Beam
    node's -Z after composing the chain (the same math the cone uses)."""
    M = item.compose(pan_g, tilt_g)
    return -M[:3, 2]


def _solver_local_dir(pan_deg, tilt_deg):
    """The solver's intended local beam direction for its (pan, tilt):
    Rz(pan) @ Ry(-tilt) applied to +X (calculate_pan_tilt's model)."""
    import math
    p, t = math.radians(pan_deg), math.radians(tilt_deg)
    return np.array([math.cos(t) * math.cos(p),
                     math.cos(t) * math.sin(p),
                     math.sin(t)])


class TestSolverToGdtfAxes:
    """The two yoke models: the solver aims with beam +X / tilt about Y,
    the GDTF chain with beam -Z / tilt about X. The conversion must make
    the chain emit exactly where the solver aimed - this is why aimed
    beams missed their spots (2026-07-13)."""

    def _mover_beam_item(self):
        """A synthetic flipped mover: Pan axis at the base, Tilt at the
        head, beam node below - the Hero Spot 60's shape."""
        from visualizer.renderer.gdtf_draw_plan import (
            ChainStep, DrawItem, _canonicalize_posture,
        )
        beam = DrawItem(
            node_name="Beam", model_name="Beam", is_beam=True,
            chain=[ChainStep(matrix=_translate_z(0.0), axis_attribute="Pan"),
                   ChainStep(matrix=_translate_z(-0.2), axis_attribute="Tilt"),
                   ChainStep(matrix=_translate_z(-0.1), axis_attribute=None)])
        flipped = _canonicalize_posture([beam])
        assert flipped
        return beam

    @pytest.mark.parametrize("pan,tilt", [
        (0.0, 0.0), (30.0, 0.0), (-45.0, 20.0), (90.0, -35.0),
        (170.0, 60.0), (-120.0, -80.0), (21.8, 0.0),
    ])
    def test_chain_emits_where_the_solver_aimed(self, pan, tilt):
        from visualizer.renderer.gdtf_draw_plan import solver_to_gdtf_axes
        beam = self._mover_beam_item()
        pan_g, tilt_g = solver_to_gdtf_axes(pan, tilt, flipped=True)
        np.testing.assert_allclose(
            _beam_dir_local(beam, pan_g, tilt_g),
            _solver_local_dir(pan, tilt), atol=1e-9)

    def test_straight_down_is_the_pan_singularity(self):
        from visualizer.renderer.gdtf_draw_plan import solver_to_gdtf_axes
        # Solver tilt +90 = local +Z; for a flipped chain that is tilt 0
        # (beam along the pan axis), pan undefined -> 0.
        pan_g, tilt_g = solver_to_gdtf_axes(0.0, 90.0, flipped=True)
        assert tilt_g == pytest.approx(0.0, abs=1e-9)
        assert pan_g == 0.0

    def test_unflipped_tree_uses_the_other_signs(self):
        from visualizer.renderer.gdtf_draw_plan import (
            ChainStep, DrawItem, solver_to_gdtf_axes,
        )
        beam = DrawItem(
            node_name="Beam", model_name="Beam", is_beam=True,
            chain=[ChainStep(matrix=_translate_z(0.0), axis_attribute="Pan"),
                   ChainStep(matrix=_translate_z(0.2), axis_attribute="Tilt")])
        for pan, tilt in ((0.0, 0.0), (40.0, 25.0), (-60.0, -10.0)):
            pan_g, tilt_g = solver_to_gdtf_axes(pan, tilt, flipped=False)
            np.testing.assert_allclose(
                _beam_dir_local(beam, pan_g, tilt_g),
                _solver_local_dir(pan, tilt), atol=1e-9)


class TestAimedBeamHitsTheSpot:
    """THE closed loop the user asked for: aim a hanging GDTF mover at a
    stage-space spot through the real solver, drive the real chain with
    the converted angles, and the emitted beam (in stage coordinates)
    must point exactly at the spot - no eyes needed."""

    FIXTURE = (0.0, 0.0, 5.0)   # hung 5 m above centre stage

    @pytest.mark.parametrize("target", [
        (2.0, 0.0, 0.0),     # floor, stage right
        (-2.0, 0.0, 0.0),    # floor, stage left
        (0.0, -2.0, 0.0),    # floor, toward the audience
        (0.0, 2.0, 0.0),     # floor, upstage
        (1.5, -1.5, 1.0),    # off-axis, raised (a lit spot on a riser)
        (0.0, 0.0, 0.0),     # straight down
    ], ids=lambda t: f"({t[0]},{t[1]},{t[2]})")
    def test_hanging_gdtf_mover_hits_the_spot(self, target):
        from utils.orientation import (
            calculate_pan_tilt, fixture_rotation_matrix, preset_angles,
        )
        from visualizer.renderer.gdtf_draw_plan import solver_to_gdtf_axes

        yaw, pitch, roll = preset_angles('hanging')
        pan, tilt = calculate_pan_tilt(
            *self.FIXTURE, *target, 'hanging', yaw, pitch, roll)

        beam = TestSolverToGdtfAxes()._mover_beam_item()
        pan_g, tilt_g = solver_to_gdtf_axes(pan, tilt, flipped=True)
        local = _beam_dir_local(beam, pan_g, tilt_g)

        # chassis local -> scene (the renderer's model matrix), then
        # scene (x, y_up, z_depth) -> stage (x, depth, height).
        scene = fixture_rotation_matrix(yaw, pitch, roll) @ local
        stage_dir = np.array([scene[0], scene[2], scene[1]])

        want = np.array(target) - np.array(self.FIXTURE)
        want = want / np.linalg.norm(want)
        np.testing.assert_allclose(stage_dir, want, atol=1e-6)


class TestOutputYokeHitsThroughRealChain:
    """The OUTPUT-boundary conversion (utils/yoke.apply_yoke_to_universe)
    must make the EMITTED DMX, read back and fed to the real yoke (the
    GDTF chain), land the beam on the target - the bug the bench found
    2026-07-13 (a straight-down target came out horizontal on the wire).
    Synthetic chain, so it runs in CI without the Share file."""

    class _Map:
        universe = 1
        pan_channels = [0]
        pan_fine_channels = [1]
        tilt_channels = [2]
        tilt_fine_channels = [3]
        pan_range = 540.0
        tilt_range = 220.0

        def get_absolute_address(self, offset):
            return (1, offset)

    def _hanging_mover_beam(self):
        from visualizer.renderer.gdtf_draw_plan import (
            ChainStep, DrawItem, _canonicalize_posture,
        )
        beam = DrawItem(
            node_name="Beam", model_name="Beam", is_beam=True,
            chain=[ChainStep(matrix=_translate_z(0.0), axis_attribute="Pan"),
                   ChainStep(matrix=_translate_z(-0.2), axis_attribute="Tilt"),
                   ChainStep(matrix=_translate_z(-0.1), axis_attribute=None)])
        assert _canonicalize_posture([beam])
        return beam

    @pytest.mark.parametrize("target", [
        (2.0, 0.0, 0.0), (-2.0, 0.0, 0.0), (0.0, -2.0, 0.0),
        (0.0, 2.0, 0.0), (0.0, 0.0, 0.0), (1.5, -1.5, 1.0),
    ], ids=lambda t: f"({t[0]},{t[1]},{t[2]})")
    def test_emitted_dmx_hits_the_spot_on_the_real_yoke(self, target):
        from utils.orientation import (
            calculate_pan_tilt, fixture_rotation_matrix,
            pan_tilt_to_dmx16, preset_angles,
        )
        from utils.yoke import apply_yoke_to_universe

        beam = self._hanging_mover_beam()
        fixture = (0.0, 0.0, 5.0)
        yaw, pitch, roll = preset_angles("hanging")

        # solver aim -> emit solver DMX -> output boundary converts in
        # place -> read back as the real head would -> drive the chain.
        pan_s, tilt_s = calculate_pan_tilt(
            *fixture, *target, "hanging", yaw, pitch, roll, 540.0, 220.0)
        buf = bytearray(512)
        buf[0], buf[1], buf[2], buf[3] = pan_tilt_to_dmx16(
            pan_s, tilt_s, 540.0, 220.0)

        apply_yoke_to_universe(buf, self._Map(), flipped=True)

        pan_phys = ((buf[0] * 256 + buf[1]) / 65535.0 - 0.5) * 540.0
        tilt_phys = ((buf[2] * 256 + buf[3]) / 65535.0 - 0.5) * 220.0
        local = -np.array(beam.compose(pan_phys, tilt_phys))[:3, 2]
        scene = fixture_rotation_matrix(yaw, pitch, roll) @ local
        stage = np.array([scene[0], scene[2], scene[1]])
        want = np.array(target) - np.array(fixture)
        want = want / np.linalg.norm(want)
        np.testing.assert_allclose(stage, want, atol=5e-3)


class TestPhysicalClamp:
    """The rendered head must stop where the real head stops: converted
    angles clamp to the mode's physical Pan/Tilt travel, mirroring the
    DMX encode - a hanging mover aimed at the ceiling pins at its tilt
    limit in BOTH the visualizer and on the wire (user observation
    2026-07-13: 'ceiling is not possible with hanging moving heads, the
    visualizer however allows it')."""

    def test_clamp_pins_out_of_travel_angles(self):
        from visualizer.renderer.gdtf_draw_plan import clamp_to_physical
        assert clamp_to_physical(0.0, 180.0, 270.0, 110.0) == (0.0, 110.0)
        assert clamp_to_physical(-300.0, 45.0, 270.0, 110.0) == \
            (-270.0, 45.0)
        assert clamp_to_physical(30.0, 90.0, 270.0, 110.0) == (30.0, 90.0)

    def test_half_ranges_default_when_absent(self):
        from visualizer.renderer.gdtf_draw_plan import physical_half_ranges

        class _NoPhysical:
            channel_physical = []
        assert physical_half_ranges(_NoPhysical(), "Any") == (270.0, 135.0)

    def test_half_ranges_read_the_mode(self):
        from utils.gdtf_data import GdtfChannelPhysical
        from visualizer.renderer.gdtf_draw_plan import physical_half_ranges

        class _G:
            channel_physical = [
                GdtfChannelPhysical("M", "Pan", "Yoke", 0, -270.0, 270.0),
                GdtfChannelPhysical("M", "Tilt", "Head", 2, -110.0, 110.0),
                GdtfChannelPhysical("Other", "Tilt", "Head", 2, -90.0, 90.0),
            ]
        assert physical_half_ranges(_G(), "M") == (270.0, 110.0)


_HERO_SPOT = glob.glob(os.path.join(REPO_ROOT, "gdtf_fixtures",
                                    "Varytec@Hero Spot 60@*.gdtf"))


@pytest.mark.skipif(not _HERO_SPOT,
                    reason="local Share download not present (not committed)")
def test_real_hero_spot_hits_the_spot():
    """The same closed loop through the REAL Hero Spot 60 chain."""
    from utils.orientation import (
        calculate_pan_tilt, fixture_rotation_matrix, preset_angles,
    )
    from visualizer.renderer.gdtf_draw_plan import solver_to_gdtf_axes

    defn = parse_gdtf_file(_HERO_SPOT[0])
    plan = build_draw_plan(defn.gdtf, "14-channel DMX mode")
    assert plan.flipped
    beam = next(i for i in plan if i.is_beam)

    fixture = (0.0, 0.0, 5.0)
    yaw, pitch, roll = preset_angles('hanging')
    for target in ((2.0, 0.0, 0.0), (0.0, -2.0, 0.0), (-1.0, 1.0, 0.0)):
        pan, tilt = calculate_pan_tilt(
            *fixture, *target, 'hanging', yaw, pitch, roll)
        pan_g, tilt_g = solver_to_gdtf_axes(pan, tilt, flipped=True)
        local = _beam_dir_local(beam, pan_g, tilt_g)
        scene = fixture_rotation_matrix(yaw, pitch, roll) @ local
        stage_dir = np.array([scene[0], scene[2], scene[1]])
        want = np.array(target) - np.array(fixture)
        want = want / np.linalg.norm(want)
        np.testing.assert_allclose(stage_dir, want, atol=1e-6,
                                   err_msg=f"missed the spot at {target}")


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
