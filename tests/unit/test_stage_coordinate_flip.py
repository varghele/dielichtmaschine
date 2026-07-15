"""Stage plan Y-axis orientation: the audience/front sits at the BOTTOM.

The 2D plan renders negative stage-Y (front / audience) at the bottom
of the view and positive stage-Y (back) at the top. This is a
display-only flip in ``StageView.meters_to_pixels`` /
``pixels_to_meters``; stored config coordinates are untouched.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import Configuration, Fixture, FixtureMode


def _fixture(name, x=0.0, y=0.0):
    return Fixture(universe=1, address=1, manufacturer="M", model="X",
                   name=name, group="G", current_mode="Std",
                   available_modes=[FixtureMode(name="Std", channels=8)],
                   type="MH", x=x, y=y)


@pytest.fixture
def view(qapp):
    from gui.StageView import StageView
    stage_view = StageView()
    stage_view.set_config(Configuration())
    yield stage_view
    stage_view.deleteLater()


class TestCoordinateFlip:
    @pytest.mark.parametrize("x_m,y_m", [
        (0.0, 0.0),
        (2.0, -3.0),   # front / audience
        (-1.5, 3.0),   # back
        (4.0, 0.5),
        (-2.25, -1.75),
    ])
    def test_round_trip_identity(self, view, x_m, y_m):
        """pixels_to_meters(meters_to_pixels(x, y)) == (x, y) exactly,
        with the flipped Y still inverting cleanly."""
        x_px, y_px = view.meters_to_pixels(x_m, y_m)
        rx, ry = view.pixels_to_meters(x_px, y_px)
        assert rx == pytest.approx(x_m, abs=1e-9)
        assert ry == pytest.approx(y_m, abs=1e-9)

    def test_front_renders_below_back(self, view):
        """A front fixture (negative Y) maps to a LARGER y_px (lower on
        screen) than a back fixture (positive Y)."""
        _, front_y_px = view.meters_to_pixels(0.0, -3.0)
        _, back_y_px = view.meters_to_pixels(0.0, 3.0)
        assert front_y_px > back_y_px

    def test_bottom_of_screen_is_front(self, view):
        """A drop near the bottom edge of the plan yields a NEGATIVE
        y_m (front / audience side)."""
        center_y_px = view.padding + (view.stage_depth_m / 2) * view.pixels_per_meter
        low_screen_y = center_y_px + 2.0 * view.pixels_per_meter  # below center
        _, y_m = view.pixels_to_meters(0.0, low_screen_y)
        assert y_m < 0

    def test_config_coordinates_unchanged_by_placement(self, view, tmp_path):
        """Placing a fixture at (x, -3) and saving/loading preserves the
        stored Y byte-identically: the flip is display-only."""
        config = view.config
        config.fixtures = [_fixture("MH 1", x=2.0, y=-3.0)]
        view.update_from_config()

        # The item lands below stage center (front = bottom)...
        item = view.fixtures["MH 1"]
        center_y_px = view.padding + (view.stage_depth_m / 2) * view.pixels_per_meter
        assert item.pos().y() > center_y_px

        # ...and saving back recovers the exact stored Y, unchanged.
        view.save_positions_to_config()
        assert config.fixtures[0].y == pytest.approx(-3.0, abs=1e-9)

        path = str(tmp_path / "rig.yaml")
        config.save(path)
        loaded = Configuration.load(path)
        assert loaded.fixtures[0].y == config.fixtures[0].y
        assert loaded.fixtures[0].x == config.fixtures[0].x
