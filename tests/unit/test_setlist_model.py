# tests/unit/test_setlist_model.py
"""Unit tests for the setlist model (docs/setlist-plan.md S1).

Covers the new dataclasses (SongTrigger, PauseLook, SetlistEntry,
Setlist), the Configuration songs+setlist YAML round-trip, and the
legacy `shows:` load path that synthesizes a setlist.
"""

import os

import yaml

from config.models import (
    Configuration, Song, ShowPart, Setlist, SetlistEntry, SongTrigger,
    PauseLook, TimelineData, LightLane, LightBlock, DimmerBlock,
)


def _part(name="Intro", color="#ff0000"):
    return ShowPart(name=name, color=color, signature="4/4",
                    bpm=120.0, num_bars=4, transition="instant")


class TestSongTrigger:

    def test_defaults(self):
        t = SongTrigger()
        assert t.mode == "manual"
        assert t.value == 0
        assert t.channel == 1
        assert t.timecode == ""

    def test_roundtrip(self):
        t = SongTrigger(mode="midi_pc", value=5, channel=3, timecode="")
        assert SongTrigger.from_dict(t.to_dict()) == t

    def test_roundtrip_timecode(self):
        t = SongTrigger(mode="mtc", timecode="00:14:32:00")
        loaded = SongTrigger.from_dict(t.to_dict())
        assert loaded == t
        assert loaded.timecode == "00:14:32:00"

    def test_from_empty_dict_uses_defaults(self):
        assert SongTrigger.from_dict({}) == SongTrigger()


class TestPauseLook:

    def test_defaults(self):
        p = PauseLook()
        assert p.mode == "hold_last"
        assert p.level == 20
        assert p.until == "trigger"
        assert p.duration_s == 0.0

    def test_roundtrip(self):
        p = PauseLook(mode="warm_white", level=35, until="duration",
                      duration_s=90.0)
        assert PauseLook.from_dict(p.to_dict()) == p

    def test_from_empty_dict_uses_defaults(self):
        assert PauseLook.from_dict({}) == PauseLook()

    def test_scene_mode_round_trips_and_stays_off_old_looks(self):
        """Mode "scene" (2026-07-17 minimal pause engine): the scene
        key round-trips, and looks without one write no key so
        pre-scene files stay byte-identical."""
        p = PauseLook(mode="scene", level=100, until="trigger",
                      scene="stellwerk/Red Room")
        back = PauseLook.from_dict(p.to_dict())
        assert back == p and back.scene == "stellwerk/Red Room"
        assert "scene" not in PauseLook().to_dict()
        assert PauseLook.from_dict({"mode": "blackout"}).scene == ""


class TestSetlistEntry:

    def test_roundtrip(self):
        e = SetlistEntry(
            song="Monsters",
            trigger=SongTrigger(mode="midi_note", value=36, channel=10),
            pause_after=PauseLook(mode="blackout", until="duration",
                                  duration_s=15.0),
        )
        assert SetlistEntry.from_dict(e.to_dict()) == e

    def test_defaults(self):
        e = SetlistEntry(song="Opener")
        assert e.trigger == SongTrigger()
        assert e.pause_after == PauseLook()

    def test_from_dict_missing_subobjects(self):
        e = SetlistEntry.from_dict({"song": "Opener"})
        assert e.song == "Opener"
        assert e.trigger == SongTrigger()
        assert e.pause_after == PauseLook()


class TestSetlist:

    def test_defaults(self):
        s = Setlist()
        assert s.name == ""
        assert s.entries == []
        assert s.sync_mode == "manual"
        assert s.sync_device == ""

    def test_roundtrip(self):
        s = Setlist(
            name="Herbsttour 2026",
            entries=[
                SetlistEntry(song="Opener",
                             trigger=SongTrigger(mode="midi_pc", value=1)),
                SetlistEntry(song="Monsters",
                             trigger=SongTrigger(mode="follow"),
                             pause_after=PauseLook(mode="ambient_loop")),
            ],
            sync_mode="midi",
            sync_device="Akai APC Mini mk2",
        )
        assert Setlist.from_dict(s.to_dict()) == s

    def test_from_song_names_sorted_manual_hold_last(self):
        s = Setlist.from_song_names(["Zebra", "Alpha", "Monsters"])
        assert [e.song for e in s.entries] == ["Alpha", "Monsters", "Zebra"]
        for entry in s.entries:
            assert entry.trigger.mode == "manual"
            assert entry.pause_after.mode == "hold_last"
            assert entry.pause_after.until == "trigger"
        assert s.sync_mode == "manual"


class TestConfigurationRoundtrip:

    def _make_config(self):
        songs = {
            "Opener": Song(name="Opener", parts=[_part()]),
            "Monsters": Song(
                name="Monsters",
                parts=[_part("Verse", "#00ff00")],
                timeline_data=TimelineData(lanes=[
                    LightLane(name="Front", fixture_targets=["Front"],
                              light_blocks=[LightBlock(
                                  start_time=0.0, end_time=4.0,
                                  effect_name="bars.static",
                                  dimmer_blocks=[DimmerBlock(
                                      start_time=0.0, end_time=4.0)])])
                ]),
            ),
        }
        setlist = Setlist(
            name="Evening",
            entries=[
                SetlistEntry(song="Monsters",
                             trigger=SongTrigger(mode="midi_pc", value=5,
                                                 channel=2)),
                SetlistEntry(song="Opener",
                             trigger=SongTrigger(mode="follow"),
                             pause_after=PauseLook(mode="warm_white",
                                                   level=30,
                                                   until="duration",
                                                   duration_s=60.0)),
            ],
            sync_mode="mtc",
            sync_device="LTC Reader",
        )
        return Configuration(songs=songs, setlist=setlist)

    def test_save_writes_songs_and_setlist_keys(self, tmp_path):
        config = self._make_config()
        path = str(tmp_path / "config.yaml")
        config.save(path)
        with open(path) as f:
            raw = yaml.safe_load(f)
        assert "songs" in raw
        assert "shows" not in raw
        assert "setlist" in raw
        assert set(raw["songs"]) == {"Opener", "Monsters"}
        # Compact serializer block tables keep their per-file layout.
        assert "block_defs" in raw
        assert "light_block_defs" in raw

    def test_roundtrip_songs_and_setlist_equal(self, tmp_path):
        config = self._make_config()
        path = str(tmp_path / "config.yaml")
        config.save(path)
        loaded = Configuration.load(path)

        assert set(loaded.songs) == set(config.songs)
        for name, song in config.songs.items():
            assert loaded.songs[name].to_dict() == song.to_dict()
        assert loaded.setlist == config.setlist

    def test_setlist_order_preserved_not_sorted(self, tmp_path):
        """The setlist keeps the authored entry order (Monsters before
        Opener), it is never re-sorted on load."""
        config = self._make_config()
        path = str(tmp_path / "config.yaml")
        config.save(path)
        loaded = Configuration.load(path)
        assert [e.song for e in loaded.setlist.entries] == ["Monsters",
                                                            "Opener"]


class TestLegacyShowsLoad:

    LEGACY_YAML = """\
fixtures: []
groups: {}
universes: {}
spots: {}
workspace_path: null
shows_directory: null
shows:
  Zebra:
    parts:
    - name: Intro
      color: '#ff0000'
      signature: 4/4
      bpm: 120.0
      num_bars: 4
      transition: instant
    effects: []
    timeline_data: null
    trigger_device: null
    trigger_channel: null
  Alpha:
    parts:
    - name: Drop
      color: '#00ff00'
      signature: 4/4
      bpm: 174.0
      num_bars: 8
      transition: instant
    effects: []
    timeline_data: null
    trigger_device: null
    trigger_channel: null
"""

    def test_legacy_shows_key_loads_as_songs(self, tmp_path):
        path = tmp_path / "legacy.yaml"
        path.write_text(self.LEGACY_YAML)
        config = Configuration.load(str(path))
        assert set(config.songs) == {"Alpha", "Zebra"}
        assert config.songs["Zebra"].parts[0].name == "Intro"
        assert config.songs["Alpha"].parts[0].bpm == 174.0

    def test_legacy_load_synthesizes_setlist(self, tmp_path):
        path = tmp_path / "legacy.yaml"
        path.write_text(self.LEGACY_YAML)
        config = Configuration.load(str(path))
        # Sorted song-name order, manual triggers, hold-last pauses.
        assert [e.song for e in config.setlist.entries] == ["Alpha", "Zebra"]
        for entry in config.setlist.entries:
            assert entry.trigger == SongTrigger(mode="manual")
            assert entry.pause_after == PauseLook(mode="hold_last",
                                                  until="trigger")
        assert config.setlist.sync_mode == "manual"

    def test_legacy_resaves_as_songs(self, tmp_path):
        """Loading a legacy config and saving writes the new key layout."""
        path = tmp_path / "legacy.yaml"
        path.write_text(self.LEGACY_YAML)
        config = Configuration.load(str(path))
        out = str(tmp_path / "resaved.yaml")
        config.save(out)
        with open(out) as f:
            raw = yaml.safe_load(f)
        assert "songs" in raw and "shows" not in raw
        assert "setlist" in raw
        reloaded = Configuration.load(out)
        assert set(reloaded.songs) == {"Alpha", "Zebra"}
        assert reloaded.setlist == config.setlist


class TestDemoLegacyLoad:
    """Legacy `shows:` configs must load through the legacy path
    forever. The bundled demos converted to the current .lms format
    2026-07-16, so the legacy fixture is a preserved copy of the old
    band_midsize demo under tests/fixtures/."""

    DEMO = os.path.join(os.path.dirname(__file__), "..",
                        "fixtures", "legacy_band_midsize.yaml")

    def test_band_midsize_loads_songs_and_setlist(self):
        config = Configuration.load(os.path.abspath(self.DEMO))
        assert config.songs, "demo config must expose its shows as songs"
        for name, song in config.songs.items():
            assert song.name == name
            assert song.parts, f"song {name!r} lost its parts"
        # Synthesized setlist: every song, sorted by name, manual/hold-last.
        assert [e.song for e in config.setlist.entries] == \
            sorted(config.songs)
        for entry in config.setlist.entries:
            assert entry.trigger.mode == "manual"
            assert entry.pause_after.mode == "hold_last"
            assert entry.pause_after.until == "trigger"
