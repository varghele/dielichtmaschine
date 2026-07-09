"""Fixture beam/direction follows the stage-Y flip (display-only).

The 2D plan and printable plot render the audience/front (negative
stage-Y) at the BOTTOM. The flip mirrored fixture POSITION only, so the
drawn beam/orientation must be mirrored too, or a front-aimed moving
head still points upstage. The mirror is a negation of the rotation the
symbol is drawn with (a vertical reflection composed with rotate(a)
equals rotate(-a) for a facing along the horizontal local +X axis).

These tests pin that:
  1. a front-aimed fixture's 2D beam points to the LOWER half and a
     back-aimed one to the UPPER half,
  2. the printable plot's orientation angle matches the Stage tab's,
  3. stored orientation values are untouched by a placement round trip.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QTransform

from config.models import Configuration, Fixture, FixtureMode


def _fixture(name, ftype="MH", x=0.0, y=0.0, yaw=0.0, pitch=0.0, roll=0.0):
    return Fixture(universe=1, address=1, manufacturer="M", model="X",
                   name=name, group="G", current_mode="Std",
                   available_modes=[FixtureMode(name="Std", channels=8)],
                   type=ftype, x=x, y=y, yaw=yaw, pitch=pitch, roll=roll,
                   orientation_uses_group_default=False)


def _beam_screen_dir(item):
    """Screen-space unit vector the fixture's beam (local +X) points in,
    after the rotation the item paints with."""
    t = QTransform()
    t.rotate(item._paint_rotation())
    return t.map(QPointF(1.0, 0.0))


class TestBeamFollowsFlip:
    def test_front_aimed_points_to_lower_half(self, qapp):
        """A moving head aimed at the audience (yaw 180) draws its beam
        toward the BOTTOM of the plan (positive screen-Y)."""
        from gui.stage_items import FixtureItem
        item = FixtureItem("MH 1", "MH", "#ffffff")
        item.rotation_angle = 180.0
        assert _beam_screen_dir(item).y() > 0.0

    def test_back_aimed_points_to_upper_half(self, qapp):
        """A moving head aimed upstage (yaw 0) draws its beam toward the
        TOP of the plan (negative screen-Y)."""
        from gui.stage_items import FixtureItem
        item = FixtureItem("MH 1", "MH", "#ffffff")
        item.rotation_angle = 0.0
        assert _beam_screen_dir(item).y() < 0.0

    def test_flip_is_pure_negation(self, qapp):
        """The drawn rotation is exactly the negation of the un-mirrored
        facing (yaw + 90 for a non-bar) - no residual offset."""
        from gui.stage_items import FixtureItem
        item = FixtureItem("MH 1", "MH", "#ffffff")
        for yaw in (0.0, 45.0, 90.0, 137.0, 180.0, 270.0):
            item.rotation_angle = yaw
            assert item._paint_rotation() == pytest.approx(-(yaw + 90.0))


class TestPlotMatchesPlan:
    @pytest.mark.parametrize("ftype,yaw,pitch,roll", [
        ("MH", 0.0, 0.0, 0.0),
        ("MH", 180.0, 0.0, 0.0),
        ("PAR", 42.0, 0.0, 0.0),
        ("BAR", 30.0, 10.0, 5.0),
        ("PIXELBAR", 200.0, 0.0, 0.0),
    ])
    def test_plot_angle_equals_item_rotation(self, qapp, ftype, yaw, pitch, roll):
        """The printable plot draws each fixture at the same screen angle
        the Stage tab's FixtureItem uses, so the two views agree."""
        from gui.stage_items import FixtureItem
        from gui.stage_plot import plot_fixture_angle

        item = FixtureItem("F", ftype, "#ffffff")
        item.rotation_angle = yaw
        item.pitch = pitch
        item.roll = roll
        assert (plot_fixture_angle(ftype, yaw, pitch, roll)
                == pytest.approx(item._paint_rotation()))

    def test_plot_front_aimed_points_down(self, qapp):
        """The plot's front-aimed beam (yaw 180) also faces the bottom."""
        from gui.stage_plot import plot_fixture_angle
        t = QTransform()
        t.rotate(plot_fixture_angle("MH", 180.0, 0.0, 0.0))
        assert t.map(QPointF(1.0, 0.0)).y() > 0.0


class TestOrientationValuesUnchanged:
    def test_placement_round_trip_preserves_orientation(self, qapp, tmp_path):
        """Placing/saving a fixture through the flipped StageView leaves
        its stored orientation (yaw/pitch/roll) byte-identical: the
        beam-direction fix is display-only, like the position flip."""
        from gui.StageView import StageView

        config = Configuration()
        config.fixtures = [_fixture("MH 1", x=2.0, y=-3.0,
                                    yaw=137.0, pitch=12.0, roll=-8.0)]
        view = StageView()
        try:
            view.set_config(config)
            view.update_from_config()
            view.save_positions_to_config()

            f = config.fixtures[0]
            assert f.yaw == pytest.approx(137.0)
            assert f.pitch == pytest.approx(12.0)
            assert f.roll == pytest.approx(-8.0)

            path = str(tmp_path / "rig.yaml")
            config.save(path)
            loaded = Configuration.load(path)
            lf = loaded.fixtures[0]
            assert lf.yaw == f.yaw
            assert lf.pitch == f.pitch
            assert lf.roll == f.roll
        finally:
            view.deleteLater()
