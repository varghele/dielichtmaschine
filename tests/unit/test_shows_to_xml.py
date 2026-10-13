"""Smoke tests for the song -> QLC+ Show export (v1.5.5 hardening, G10).

``utils/to_xml/shows_to_xml.py`` was only reached through the demo hash
check and two narrow tests. These run ``create_shows`` on the demo
shows and pin the structural contract QLC+ relies on: function IDs are
unique and dense, every Track points at a hidden Scene, every
ShowFunction at a Sequence bound to that Scene and placed at its
block's start time. Edge cases cover lanes the export must leave out.

Bug pinned here: a song without timeline lanes was reported in
Help > Warnings as "left out of the workspace" while its (empty) Show
function was in fact exported, and the VC show buttons point at it.
The warning now says what happens.
"""

from __future__ import annotations

import contextlib
import io
import os
import xml.etree.ElementTree as ET

import pytest

from config.models import (
    Configuration,
    DimmerBlock,
    LightBlock,
    LightLane,
    Song,
    TimelineData,
)
from utils import user_warnings
from utils.create_workspace import create_fixture_elements
from utils.fixture_utils import load_fixture_definitions_from_qlc
from utils.to_xml.shows_to_xml import create_shows

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _load(rig: str) -> Configuration:
    return Configuration.load(
        os.path.join(REPO_ROOT, "demos", "shows", f"{rig}.lms"))


def _export(config: Configuration):
    """Run create_shows into a bare Engine element (stdout muted)."""
    models = {(f.manufacturer, f.model)
              for g in config.groups.values() for f in g.fixtures}
    definitions = load_fixture_definitions_from_qlc(models)
    engine = ET.Element("Engine")
    with contextlib.redirect_stdout(io.StringIO()):
        fixture_ids = create_fixture_elements(engine, config)
        next_id = create_shows(engine, config, fixture_ids, definitions)
    return engine, next_id


@pytest.fixture
def warnings_log(monkeypatch):
    log = user_warnings.UserWarningsLog()
    monkeypatch.setattr(user_warnings, "_log", log)
    return log


def _functions(engine):
    return {f.get("ID"): f for f in engine.findall("Function")}


@pytest.mark.parametrize("rig", ["club_band", "theatre_static", "dj_edm"])
class TestDemoShowStructure:
    def test_function_ids_are_unique_and_dense(self, rig):
        engine, next_id = _export(_load(rig))
        ids = sorted(int(f.get("ID")) for f in engine.findall("Function"))
        assert ids == list(range(next_id))

    def test_one_show_per_song_with_first_part_bpm(self, rig):
        config = _load(rig)
        engine, _ = _export(config)
        shows = {f.get("Name"): f for f in engine.findall("Function")
                 if f.get("Type") == "Show"}
        assert set(shows) == set(config.songs)
        for name, song in config.songs.items():
            division = shows[name].find("TimeDivision")
            assert division.get("Type") == "Time"
            assert float(division.get("BPM")) == float(song.parts[0].bpm)

    def test_tracks_scenes_and_sequences_link_up(self, rig):
        config = _load(rig)
        engine, _ = _export(config)
        by_id = _functions(engine)
        show_funcs = 0
        for show in (f for f in engine.findall("Function")
                     if f.get("Type") == "Show"):
            tracks = show.findall("Track")
            assert tracks, f"{show.get('Name')} exported no tracks"
            assert [t.get("ID") for t in tracks] == \
                [str(i) for i in range(len(tracks))]
            for track in tracks:
                scene = by_id[track.get("SceneID")]
                assert scene.get("Type") == "Scene"
                assert scene.get("Hidden") == "True"
                assert scene.findall("FixtureVal")
                starts = []
                for sf in track.findall("ShowFunction"):
                    seq = by_id[sf.get("ID")]
                    assert seq.get("Type") == "Sequence"
                    assert seq.get("BoundScene") == track.get("SceneID")
                    steps = seq.findall("Step")
                    assert steps
                    assert [s.get("Number") for s in steps] == \
                        [str(i) for i in range(len(steps))]
                    starts.append(int(sf.get("StartTime")))
                    show_funcs += 1
                assert all(s >= 0 for s in starts)
        assert show_funcs > 0

    def test_show_function_starts_match_block_starts(self, rig):
        config = _load(rig)
        engine, _ = _export(config)
        expected = set()
        for song in config.songs.values():
            for lane in song.timeline_data.lanes:
                for block in lane.light_blocks:
                    subs = (list(block.dimmer_blocks) + list(block.colour_blocks)
                            + list(block.movement_blocks)
                            + list(block.special_blocks))
                    if subs:
                        expected.add(int(min(b.start_time for b in subs) * 1000))
        exported = {int(sf.get("StartTime"))
                    for sf in engine.iter("ShowFunction")}
        assert exported and exported <= expected


class TestLanesTheExportLeavesOut:
    def _song_with(self, config, lanes, parts=True):
        base = next(iter(config.songs.values()))
        song = Song(name="Probe", parts=list(base.parts) if parts else [],
                    timeline_data=TimelineData(lanes=lanes))
        config.songs = {"Probe": song}
        return song

    def _group_name(self, config):
        return next(name for name, g in config.groups.items() if g.fixtures)

    def test_song_without_lanes_exports_an_empty_show_and_says_so(self, warnings_log):
        config = _load("club_band")
        self._song_with(config, [], parts=False)
        engine, next_id = _export(config)
        shows = [f for f in engine.findall("Function") if f.get("Type") == "Show"]
        assert [s.get("Name") for s in shows] == ["Probe"]
        assert shows[0].findall("Track") == []
        assert shows[0].find("TimeDivision").get("BPM") == "120"
        assert next_id == 1
        messages = [e.message for e in warnings_log.entries()]
        assert any("Probe" in m and "empty show" in m for m in messages)
        assert not any("left out" in m for m in messages)

    def test_untargeted_and_unknown_lanes_are_skipped_with_warnings(self, warnings_log):
        config = _load("club_band")
        block = LightBlock(
            start_time=0.0, end_time=2.0, effect_name="probe", dimmer_blocks=[
                DimmerBlock(start_time=0.0, end_time=2.0, intensity=255.0)])
        self._song_with(config, [
            LightLane(name="Nobody", fixture_targets=[], light_blocks=[block]),
            LightLane(name="Ghost", fixture_targets=["No Such Group"],
                      light_blocks=[block]),
        ])
        engine, _ = _export(config)
        show = next(f for f in engine.findall("Function") if f.get("Type") == "Show")
        assert show.findall("Track") == []
        messages = " | ".join(e.message for e in warnings_log.entries())
        assert "Nobody" in messages
        assert "Ghost" in messages

    def test_empty_light_block_gets_no_sequence(self):
        config = _load("club_band")
        group = self._group_name(config)
        full = LightBlock(
            start_time=1.0, end_time=3.0, effect_name="probe", dimmer_blocks=[
                DimmerBlock(start_time=1.0, end_time=3.0, intensity=200.0)])
        empty = LightBlock(start_time=4.0, end_time=6.0, effect_name="probe")
        self._song_with(config, [
            LightLane(name="L", fixture_targets=[group], light_blocks=[full, empty]),
        ])
        engine, _ = _export(config)
        starts = [sf.get("StartTime") for sf in engine.iter("ShowFunction")]
        assert starts == ["1000"]

    def test_muted_lane_exports_a_muted_track(self):
        config = _load("club_band")
        group = self._group_name(config)
        block = LightBlock(
            start_time=0.0, end_time=2.0, effect_name="probe", dimmer_blocks=[
                DimmerBlock(start_time=0.0, end_time=2.0, intensity=255.0)])
        self._song_with(config, [
            LightLane(name="L", fixture_targets=[group], muted=True,
                      light_blocks=[block]),
        ])
        engine, _ = _export(config)
        tracks = list(engine.iter("Track"))
        assert tracks and all(t.get("isMute") == "1" for t in tracks)
        assert tracks[0].get("Name") == group.upper()
