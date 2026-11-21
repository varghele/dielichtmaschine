# tests/unit/test_morph_preview.py
"""Side-by-side morph preview strips (utils/morph/preview.render_strip):
one batched capture_stills call per side, the two sides strictly
sequential (the two-config audit's GL constraint), sorted and deduped
times, and a failing side degrading to an empty map instead of raising.
The renderer is faked except in TestRealRender (skipped without a
standalone GL context). The single-still render_pair was removed in
v1.5.6 once the screen moved to strips."""

import os

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


class TestRenderStrip:
    """Batching is the whole point: ONE renderer and ONE capture_stills
    call per rig, carrying every requested time.

    capture_stills walks the song once at render fps updating DMX on
    every frame, and only pays for a GL read on frames it keeps - so the
    cost tracks how far into the song you go, not how many frames you
    want. Measured on a real 4:39 song: one still at 90% costs 7.1 s,
    twenty spread across the song cost 7.3 s. Rendering per slider
    position paid that walk again each time (2026-08-08).
    """

    def _fake_renderer(self, monkeypatch, calls):
        class FakeRenderer:
            def __init__(self, config, song, definitions, **kwargs):
                self.kwargs = kwargs

            def capture_stills(self, times, output_dir, prefix="still"):
                calls.append({"prefix": prefix, "times": list(times)})
                written = []
                for t in sorted(set(times)):
                    path = os.path.join(output_dir, f"{prefix}_{t}.png")
                    open(path, "wb").close()
                    written.append(path)
                return written

        monkeypatch.setattr(
            "utils.render.offline_renderer.OfflineRenderer", FakeRenderer)
        monkeypatch.setattr(
            "utils.fixture_utils.load_fixture_definitions_from_qlc",
            lambda models: {})

    def test_one_batched_call_per_side(self, tmp_path, monkeypatch):
        calls = []
        self._fake_renderer(monkeypatch, calls)
        a_cfg, a_song = _config_song("A")
        b_cfg, b_song = _config_song("B")
        times = [0.0, 2.0, 4.0, 6.0]

        src, dst = preview.render_strip(a_cfg, a_song, b_cfg, b_song,
                                        times, str(tmp_path))

        assert [c["prefix"] for c in calls] == ["src", "dst"], \
            "source first, then morphed - two live GL contexts on one " \
            "thread are unsafe"
        assert all(c["times"] == times for c in calls), \
            "every frame goes in ONE call, not one call per frame"
        assert sorted(src) == times
        assert sorted(dst) == times

    def test_times_are_sorted_and_deduped(self, tmp_path, monkeypatch):
        calls = []
        self._fake_renderer(monkeypatch, calls)
        a_cfg, a_song = _config_song("A")
        b_cfg, b_song = _config_song("B")

        src, _dst = preview.render_strip(a_cfg, a_song, b_cfg, b_song,
                                         [4.0, 0.0, 4.0, 2.0],
                                         str(tmp_path))
        assert sorted(src) == [0.0, 2.0, 4.0]

    def test_a_failing_side_degrades_to_an_empty_map(self, tmp_path,
                                                     monkeypatch):
        """One rig without GL must not take the other down."""
        def boom(config, song, times, output_dir, prefix, camera,
                 width, height):
            if prefix == "dst":
                raise RuntimeError("no GL")
            return [os.path.join(output_dir, "src.png")]

        monkeypatch.setattr(preview, "_render_side", boom)
        a_cfg, a_song = _config_song("A")
        b_cfg, b_song = _config_song("B")
        src, dst = preview.render_strip(a_cfg, a_song, b_cfg, b_song,
                                        [0.0], str(tmp_path))
        assert src and dst == {}

    def test_missing_song_renders_nothing(self, tmp_path, monkeypatch):
        calls = []
        self._fake_renderer(monkeypatch, calls)
        a_cfg, a_song = _config_song("A")
        b_cfg, _b_song = _config_song("B")
        src, dst = preview.render_strip(a_cfg, a_song, b_cfg, None,
                                        [0.0], str(tmp_path))
        assert src and dst == {}
        assert [c["prefix"] for c in calls] == ["src"]


class TestRealRender:
    """The one real-GL pass through the preview pipeline (ported from the
    removed render_pair test): both sides write non-empty PNGs."""

    def test_real_strip_renders_both_sides(self, tmp_path):
        import pytest
        try:
            import moderngl
            ctx = moderngl.create_standalone_context()
            ctx.release()
        except Exception:
            pytest.skip("no standalone GL context on this machine")
        a_cfg, a_song = _config_song("A")
        b_cfg, b_song = _config_song("B")
        src, dst = preview.render_strip(a_cfg, a_song, b_cfg, b_song, [1.0],
                                        str(tmp_path), width=320, height=180)
        assert src and all(os.path.getsize(p) > 0 for p in src.values())
        assert dst and all(os.path.getsize(p) > 0 for p in dst.values())
