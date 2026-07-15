# tests/unit/test_morph_analysis_cache.py
"""The morph analysis cache (design doc 5.7) and the autogen
regeneration strategy riding it: cache round-trip incl. the 32-float
flux envelope the matcher needs, resolution precedence (fresh cache
without audio is trusted; stale cache with audio recomputes; nothing ->
unavailable), Song.analysis_cache persistence, and the deterministic
per-section movement synthesis."""

import pytest

from audio.spectral_analysis import SectionAnalysis, SongAnalysis
from config.models import (Configuration, DimmerBlock, Fixture,
                           FixtureGroup, FixtureMode, LightBlock, LightLane,
                           ShowPart, Song, TimelineData, Universe)
from utils.morph import analysis_cache as ac
from utils.morph.compile import compile_setlist
from utils.morph.plan import MorphEdge, MorphPlan


def _analysis():
    return SongAnalysis(
        sections=[
            SectionAnalysis(name="Intro", start_time=0.0, end_time=8.0,
                            spectral_flux_avg=0.2,
                            spectral_flux_envelope=[0.1] * 32,
                            rms_energy=0.2, spectral_contrast_avg=0.3,
                            vocal_presence=0.1, spectral_richness=0.4),
            SectionAnalysis(name="Drop", start_time=8.0, end_time=16.0,
                            spectral_flux_avg=0.9,
                            spectral_flux_envelope=[0.8] * 32,
                            rms_energy=0.9, spectral_contrast_avg=0.8,
                            vocal_presence=0.2, spectral_richness=0.9),
        ],
        global_flux_range=(0.05, 0.95), duration=16.0)


def _fixture(name, group="G"):
    return Fixture(universe=1, address=1, manufacturer="M", model="X",
                   current_mode="Std",
                   available_modes=[FixtureMode(name="Std", channels=1)],
                   name=name, group=group)


def _song(lanes=None):
    return Song(name="S",
                parts=[ShowPart(name="Intro", color="#fff", signature="4/4",
                                bpm=120.0, num_bars=4,
                                transition="instant"),
                       ShowPart(name="Drop", color="#f00", signature="4/4",
                                bpm=120.0, num_bars=4,
                                transition="instant")],
                timeline_data=TimelineData(lanes=lanes or []))


class TestCacheRoundTrip:
    def test_cache_carries_the_flux_envelope(self):
        cache = ac.analysis_to_cache(_analysis(), "hash123")
        restored = ac.cache_to_analysis(cache)
        assert restored.sections[0].spectral_flux_envelope == [0.1] * 32
        assert restored.duration == 16.0
        assert cache["audio_hash"] == "hash123"

    def test_song_persists_the_cache(self):
        song = _song()
        song.analysis_cache = ac.analysis_to_cache(_analysis(), "h")
        loaded = Song.from_dict("S", song.to_dict())
        assert loaded.analysis_cache["sections"][1]["rms_energy"] == 0.9

    def test_clean_song_serializes_without_the_key(self):
        assert "analysis_cache" not in _song().to_dict()


class TestResolve:
    def _config(self, song):
        cfg = Configuration(fixtures=[], groups={},
                            universes={1: Universe(id=1, name="U",
                                                   output={})})
        cfg.songs = {"S": song}
        return cfg

    def test_cache_without_audio_is_trusted(self):
        song = _song()
        song.analysis_cache = ac.analysis_to_cache(_analysis(), "h")
        analysis, source = ac.resolve(song, self._config(song))
        assert source == "cache"
        assert len(analysis.sections) == 2

    def test_nothing_available_is_honest(self):
        song = _song()
        analysis, source = ac.resolve(song, self._config(song))
        assert analysis is None and source == ""

    def test_stale_cache_recomputes_from_audio(self, tmp_path,
                                               monkeypatch):
        song = _song()
        song.analysis_cache = ac.analysis_to_cache(_analysis(), "stale")
        wav = tmp_path / "song.wav"
        wav.write_bytes(b"RIFFfakewav")
        song.timeline_data.audio_file_path = str(wav)

        recomputed = _analysis()
        calls = {}

        def fake_analyze(path, structure):
            calls["path"] = path
            return recomputed
        import utils.morph.analysis_cache as mod
        monkeypatch.setattr("audio.spectral_analysis.analyze_song",
                            fake_analyze)
        analysis, source = mod.resolve(song, self._config(song))
        assert source == "recomputed"
        assert calls["path"] == str(wav)
        # the refreshed cache now carries the real hash
        assert song.analysis_cache["audio_hash"] == \
            ac.audio_content_hash(str(wav))


class TestRelativeEnergies:
    def test_formula_matches_the_generator(self):
        energies = ac.relative_energies(_analysis())
        # Intro: rank 0 -> 0.6*0 + 0.4*0.3 = 0.12; Drop: 0.6*1 + 0.4*0.8
        assert energies[0] == pytest.approx(0.12)
        assert energies[1] == pytest.approx(0.92)


class TestAutogenRegeneration:
    def test_sections_become_movement_blocks(self):
        lane = LightLane(name="Pars", fixture_targets=["G"], light_blocks=[
            LightBlock(0.0, 16.0, "x",
                       dimmer_blocks=[DimmerBlock(0.0, 16.0)])])
        song = _song(lanes=[lane])
        song.analysis_cache = ac.analysis_to_cache(_analysis(), "h")
        a = Configuration(fixtures=[_fixture("p")],
                          groups={"G": FixtureGroup("G",
                                                    [_fixture("p")])},
                          universes={1: Universe(id=1, name="U",
                                                 output={})})
        a.songs = {"S": song}
        b = Configuration(fixtures=[_fixture("w", "WASH")],
                          groups={"WASH": FixtureGroup(
                              "WASH", [_fixture("w", "WASH")])},
                          universes={1: Universe(id=1, name="U",
                                                 output={})})
        b.songs = {}
        plan = MorphPlan(edges=[MorphEdge(
            source_lane_id=lane.lane_id, source_lane_name="Pars",
            sublane="movement", target_group="WASH", mode="regenerate",
            regenerate_strategy="autogen")])
        import copy
        one = compile_setlist(a, plan, copy.deepcopy(b))
        assert not one.report.has_errors
        blocks = [m for lb in
                  one.songs["S"].timeline_data.lanes[0].light_blocks
                  for m in lb.movement_blocks]
        assert [(m.start_time, m.end_time) for m in blocks] == \
            [(0.0, 8.0), (8.0, 16.0)]
        # deterministic across compiles (fresh B each time - the compile
        # mutates B by design when it creates default spots, reported)
        two = compile_setlist(a, plan, copy.deepcopy(b))
        assert one.songs["S"].to_dict() == two.songs["S"].to_dict()
        # the quiet intro moves gently, the drop moves wide
        assert blocks[0].pan_amplitude < blocks[1].pan_amplitude
