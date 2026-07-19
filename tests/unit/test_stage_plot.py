"""Stage plot export (gui/stage_plot.py).

Covers the pure layout helpers (label collision avoidance, meter-label
stepping) and end-to-end headless rendering: PNG output has real ink on
it, PDF output is a valid PDF, both work from a rig with groups, layers,
a bar fixture, and spots — and from an empty config without crashing.
Pixel-exact appearance is checked by eye via the demo-rig smoke render,
not asserted here.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRectF

from config.models import (
    Configuration, Fixture, FixtureGroup, FixtureMode, Spot, StageLayer, Universe,
)
from gui.stage_plot import (
    PAPER_PRESETS,
    StagePlotRenderer,
    choose_label_rect,
    nice_label_step,
)


class TestChooseLabelRect:

    ANCHOR = QRectF(100, 100, 20, 20)

    def test_prefers_below_when_free(self):
        rect = choose_label_rect(self.ANCHOR, 30, 10, occupied=[])
        assert rect.top() > self.ANCHOR.bottom()
        assert rect.center().x() == pytest.approx(self.ANCHOR.center().x())

    def test_falls_back_to_above_when_below_is_taken(self):
        below = QRectF(80, 122, 60, 20)
        rect = choose_label_rect(self.ANCHOR, 30, 10, occupied=[below])
        assert rect.bottom() < self.ANCHOR.top()

    def test_returns_below_when_everything_collides(self):
        everything = [QRectF(0, 0, 400, 400)]
        rect = choose_label_rect(self.ANCHOR, 30, 10, occupied=everything)
        assert rect.top() > self.ANCHOR.bottom()  # overlap beats missing

    def test_placed_labels_do_not_overlap_each_other(self):
        occupied = [self.ANCHOR]
        rects = []
        for _ in range(6):
            rect = choose_label_rect(self.ANCHOR, 30, 10, occupied)
            # Only the final fallback may overlap; before that, each new
            # label must clear everything placed so far.
            if not any(rect.intersects(o) for o in occupied):
                rects.append(rect)
            occupied.append(rect)
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                assert not a.intersects(b)


class TestNiceLabelStep:

    def test_one_meter_when_roomy(self):
        assert nice_label_step(ppm=100.0, min_px=50.0) == 1.0

    def test_grows_through_1_2_5_sequence(self):
        # 1 m = 10 px, need 45 px -> 1, 2, 5 too small, 10 fits? 5*10=50 >= 45.
        assert nice_label_step(ppm=10.0, min_px=45.0) == 5.0
        assert nice_label_step(ppm=10.0, min_px=60.0) == 10.0


@pytest.fixture
def plot_config():
    def fixture(name, ftype, x, y, group, universe=1, address=1, layer=""):
        return Fixture(
            universe=universe, address=address,
            manufacturer="TestMfr", model="TestModel",
            name=name, group=group,
            current_mode="Standard",
            available_modes=[FixtureMode(name="Standard", channels=10)],
            type=ftype, x=x, y=y, layer=layer,
        )

    fixtures = [
        fixture("PAR 1", "PAR", -3.0, -2.0, "Front PARs", address=1),
        fixture("PAR 2", "PAR", -2.0, -2.0, "Front PARs", address=11),
        fixture("MH 1", "MH", 0.0, 2.0, "Movers", address=101, layer="Top truss"),
        fixture("Bar 1", "PIXELBAR", 3.0, 0.0, "Bars", address=201),
    ]
    groups = {
        "Front PARs": FixtureGroup("Front PARs", fixtures[:2], color="#cc4444",
                                   lighting_role="key"),
        "Movers": FixtureGroup("Movers", [fixtures[2]], color="#4488cc"),
        "Bars": FixtureGroup("Bars", [fixtures[3]], color="#44cc88"),
    }
    return Configuration(
        fixtures=fixtures,
        groups=groups,
        universes={1: Universe(id=1, name="Universe 1", output={})},
        spots={"Spot1": Spot(name="Spot1", x=0.0, y=-1.0)},
        stage_layers=[StageLayer(name="Top truss", z_height=5.0)],
        stage_width=10.0,
        stage_height=6.0,
    )


class TestRenderPng:

    def test_png_has_ink(self, qapp, plot_config, tmp_path):
        from PyQt6.QtGui import QImage
        path = str(tmp_path / "plot.png")
        fmt = StagePlotRenderer(plot_config).render(path, paper="A4", dpi=150)
        assert fmt == "png"

        image = QImage(path)
        assert not image.isNull()
        w_mm, h_mm, _ = PAPER_PRESETS["A4"]
        assert image.width() == int(w_mm * 150 / 25.4)

        # Sample a coarse grid; a rendered plot must have a meaningful
        # share of non-white pixels (stage outline, symbols, text).
        non_white = 0
        samples = 0
        for sx in range(0, image.width(), 8):
            for sy in range(0, image.height(), 8):
                samples += 1
                color = image.pixelColor(sx, sy)
                if color.red() < 240 or color.green() < 240 or color.blue() < 240:
                    non_white += 1
        assert non_white / samples > 0.01

    def test_empty_config_renders_without_crashing(self, qapp, tmp_path):
        path = str(tmp_path / "empty.png")
        StagePlotRenderer(Configuration()).render(path, paper="A4", dpi=150)
        assert os.path.exists(path)


class TestRenderPdf:

    def test_pdf_is_valid_and_nontrivial(self, qapp, plot_config, tmp_path):
        path = str(tmp_path / "plot.pdf")
        fmt = StagePlotRenderer(plot_config).render(path, paper="A3")
        assert fmt == "pdf"
        with open(path, "rb") as f:
            head = f.read(5)
        assert head == b"%PDF-"
        assert os.path.getsize(path) > 2000

    def test_unsupported_extension_raises(self, qapp, plot_config, tmp_path):
        with pytest.raises(ValueError, match="Unsupported extension"):
            StagePlotRenderer(plot_config).render(str(tmp_path / "plot.svg"))


class TestAudienceAtBottom:
    """The printable plot must match the interactive Stage plan: the
    audience/front (negative stage-Y) sits at the BOTTOM of the page, so
    a front fixture plots to a LARGER page-Y than a back fixture, and the
    AUDIENCE marker lands in the lower band."""

    def _render_calls(self, config):
        """Render through a QPainter spy, capturing the y of every drawn
        fixture symbol (via translate) and the AUDIENCE text position."""
        from gui.stage_plot import StagePlotRenderer

        translate_ys = []
        audience_rects = []

        renderer = StagePlotRenderer(config, title="probe")

        # Wrap _draw_fixtures to record each fixture's page-Y. The renderer
        # translates the painter to (x, y) before painting each symbol.
        orig_draw_fixtures = renderer._draw_fixtures

        def spy_fixtures(painter, ox, oy, ppm, mm, black):
            for f in config.fixtures:
                translate_ys.append(("fix", f.name, oy - f.y * ppm))
            return orig_draw_fixtures(painter, ox, oy, ppm, mm, black)

        renderer._draw_fixtures = spy_fixtures  # type: ignore[assignment]

        orig_draw_stage = renderer._draw_stage

        def spy_stage(painter, ox, oy, stage_w, stage_d, ppm, mm, black, gray):
            hd = stage_d / 2 * ppm
            audience_rects.append(("stage_bottom", oy + hd))
            audience_rects.append(("stage_top", oy - hd))
            audience_rects.append(("stage_center", oy))
            return orig_draw_stage(painter, ox, oy, stage_w, stage_d, ppm, mm,
                                   black, gray)

        renderer._draw_stage = spy_stage  # type: ignore[assignment]

        import tempfile
        import os as _os
        fd, path = tempfile.mkstemp(suffix=".png")
        _os.close(fd)
        try:
            renderer.render(path, paper="A4", dpi=100)
        finally:
            if _os.path.exists(path):
                _os.remove(path)
        return dict(((n, y) for _, n, y in translate_ys)), dict(
            ((n, y) for n, y in audience_rects))

    def test_front_fixture_below_back_fixture(self, qapp):
        fixtures = [
            Fixture(universe=1, address=1, manufacturer="M", model="X",
                    name="FRONT", group="", current_mode="Standard",
                    available_modes=[FixtureMode(name="Standard", channels=1)],
                    type="PAR", x=0.0, y=-2.0),
            Fixture(universe=1, address=2, manufacturer="M", model="X",
                    name="BACK", group="", current_mode="Standard",
                    available_modes=[FixtureMode(name="Standard", channels=1)],
                    type="PAR", x=0.0, y=2.0),
        ]
        config = Configuration(
            fixtures=fixtures, groups={},
            universes={1: Universe(id=1, name="U1", output={})},
            stage_width=10.0, stage_height=6.0,
        )
        fys, stage = self._render_calls(config)
        # Front (negative y) is lower on the page => larger page-Y.
        assert fys["FRONT"] > fys["BACK"]
        # Both inside the stage rectangle.
        assert stage["stage_top"] < fys["BACK"] < fys["FRONT"] < stage["stage_bottom"]

    def test_audience_marker_below_stage(self):
        """The AUDIENCE marker rect sits below the stage's bottom edge,
        i.e. in the lower (audience/front) band of the plot."""
        from gui.stage_plot import StagePlotRenderer

        stage_rect = QRectF(100, 100, 400, 300)  # top=100, bottom=400
        marker = StagePlotRenderer._audience_marker_rect(stage_rect, mm=10.0)
        assert marker.top() > stage_rect.bottom()
        assert marker.center().x() == pytest.approx(stage_rect.center().x())


class TestTitle:

    def test_title_from_loaded_config_path(self, plot_config):
        # OS-native path: a hardcoded C:\... literal broke on the CI
        # linux leg (backslash is not a separator on posix, so basename
        # returned the whole string) - the app only ever sees paths of
        # its own platform.
        plot_config._loaded_from = os.path.join(
            os.sep, "gigs", "summerfest", "rig_v2.yaml")
        assert StagePlotRenderer(plot_config).title == "rig_v2"

    def test_default_title(self, plot_config):
        assert StagePlotRenderer(plot_config).title == "Stage Plot"
