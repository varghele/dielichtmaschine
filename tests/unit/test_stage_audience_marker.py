# tests/unit/test_stage_audience_marker.py
"""The AUDIENCE floor marker (visualizer/renderer/stage.py): pure
stroke geometry on the downstage apron - world -Z is the audience side
(stage front, negative stage-Y). GL-free."""

from visualizer.renderer.stage import (
    _MARKER_GLYPHS, _MARKER_TEXT, audience_marker_segments,
)


class TestAudienceMarkerSegments:
    def test_every_glyph_of_the_text_exists(self):
        for ch in _MARKER_TEXT.replace(" ", ""):
            assert ch in _MARKER_GLYPHS

    def test_all_segments_beyond_the_downstage_edge(self):
        segments = audience_marker_segments(10.0, 6.0)
        assert len(segments) > 30   # 8 letters + 2 chevrons of strokes
        for x1, z1, x2, z2 in segments:
            assert z1 < -3.0 and z2 < -3.0   # past the stage edge
            assert z1 > -5.0 and z2 > -5.0   # on the apron, not in orbit

    def test_marker_fits_the_stage_width(self):
        for width in (3.0, 10.0, 24.0):
            xs = [v for x1, _z1, x2, _z2 in
                  audience_marker_segments(width, 6.0) for v in (x1, x2)]
            assert max(xs) <= 0.5 * width * 0.8 + 1e-6
            assert min(xs) >= -0.5 * width * 0.8 - 1e-6
            # Centered.
            assert abs((max(xs) + min(xs)) / 2.0) < 1e-6

    def test_letter_height_caps_at_one_meter(self):
        zs = [v for _x1, z1, _x2, z2 in
              audience_marker_segments(60.0, 6.0) for v in (z1, z2)]
        assert max(zs) - min(zs) <= 1.0 + 1e-6

    def test_scales_with_stage_depth(self):
        shallow = audience_marker_segments(10.0, 4.0)
        deep = audience_marker_segments(10.0, 12.0)
        # Same lettering, translated to each stage's downstage edge.
        assert max(z for _x1, z1, _x2, z2 in shallow
                   for z in (z1, z2)) > \
            max(z for _x1, z1, _x2, z2 in deep for z in (z1, z2))
