# tests/unit/test_morph_preview.py
"""Side-by-side morph preview: the two renders run sequentially (the
two-config audit's GL constraint) and failures degrade to None instead
of raising. The real-GL render itself is exercised once, skipped where
no context exists."""

import os

import pytest

from config.models import (Configuration, DimmerBlock, Fixture,
                           FixtureGroup, FixtureMode, LightBlock,
                           LightLane, ShowPart, Song, TimelineData,
                           Universe)
from utils.morph import preview


def _config_song(group="G"):
    fixture = Fixture(universe=1, address=1, manufacturer="M", model="X",
                      current_mode="Std",
                      available_modes=[FixtureMode(name="Std", channels=1)],
                      name=f"f-{group}", group=group)
    cfg = Configuration(
        fixtures=[fixture],
        groups={group: FixtureGroup(group, [fixture])},
        universes={1: Universe(id=1, name="U", output={})})
    lane = LightLane(name=group, fixture_targets=[group], light_blocks=[
        LightBlock(0.0, 8.0, "x",
                   dimmer_blocks=[DimmerBlock(0.0, 8.0)])])
    song = Song(name="S",
                parts=[ShowPart(name="All", color="#fff", signature="4/4",
                                bpm=120.0, num_bars=4,
                                transition="instant")],
                timeline_data=TimelineData(lanes=[lane]))
    return cfg, song


class TestRenderPair:
    def test_sequential_order_and_paths(self, tmp_path, monkeypatch):
        calls = []

        def fake_render(config, song, time_s, output_dir, prefix,
                        camera, width, height):
            calls.append(prefix)
            path = os.path.join(output_dir, f"{prefix}.png")
            open(path, "wb").close()
            return path
        monkeypatch.setattr(preview, "_render_still", fake_render)
        a_cfg, a_song = _config_song("A")
        b_cfg, b_song = _config_song("B")
        a, b = preview.render_pair(a_cfg, a_song, b_cfg, b_song, 2.0,
                                   str(tmp_path))
        assert calls == ["src", "dst"]  # strictly sequential
        assert a.endswith("src.png") and b.endswith("dst.png")

    def test_one_side_failing_degrades_to_none(self, tmp_path,
                                               monkeypatch):
        def fake_render(config, song, time_s, output_dir, prefix,
                        camera, width, height):
            if prefix == "src":
                raise RuntimeError("no GL")
            path = os.path.join(output_dir, f"{prefix}.png")
            open(path, "wb").close()
            return path
        monkeypatch.setattr(preview, "_render_still", fake_render)
        a_cfg, a_song = _config_song("A")
        b_cfg, b_song = _config_song("B")
        a, b = preview.render_pair(a_cfg, a_song, b_cfg, b_song, 2.0,
                                   str(tmp_path))
        assert a is None and b is not None


@pytest.mark.gl
class TestRealRender:
    def test_real_pair_renders_two_pngs(self, tmp_path):
        try:
            import moderngl
            ctx = moderngl.create_standalone_context()
            ctx.release()
        except Exception:
            pytest.skip("no standalone GL context on this machine")
        a_cfg, a_song = _config_song("A")
        b_cfg, b_song = _config_song("B")
        a, b = preview.render_pair(a_cfg, a_song, b_cfg, b_song, 1.0,
                                   str(tmp_path), width=320, height=180)
        assert a and os.path.getsize(a) > 0
        assert b and os.path.getsize(b) > 0
