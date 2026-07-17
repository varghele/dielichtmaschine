"""_on_audio_file_loaded bundles audio next to the CONFIG FILE, never
into shows_directory (gig-day regression, 2026-07-17).

The Stellwerk kit's configs travelled from another machine carrying
that machine's absolute ``shows_directory``
(C:/Users/varghele/...); loading an audio file ran
``os.makedirs(shows_directory + '/audiofiles')``, which walked the
missing parents and died with PermissionError on C:/Users/varghele.
The fix routes the copy through ``Configuration.audio_bundle_dir``
(<config dir>/audiofiles/, the exact place ``_load_show`` resolves
audio from) and downgrades every bundle failure to a user warning.

ShowsTab cannot be constructed headlessly (embedded GL visualizer +
audio engine), so the method is exercised UNBOUND on a duck-typed
stub, the same layer-focused pattern as
test_shows_tab_show_switch.py.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import Configuration, Song, TimelineData
from gui.tabs.shows_tab import ShowsTab
from utils import user_warnings


class _AudioLaneStub:
    def __init__(self):
        self.audio_file_path = None
        self.file_path_edit = _LineEditStub()


class _LineEditStub:
    def __init__(self):
        self.text = ""
        self.tooltip = ""

    def setText(self, value):
        self.text = value

    def setToolTip(self, value):
        self.tooltip = value


class _TabStub:
    """Duck-typed ``self`` for ShowsTab._on_audio_file_loaded."""

    def __init__(self, config, song_name):
        self.config = config
        self.current_song_name = song_name
        self.audio_lane = _AudioLaneStub()
        self.simple_audio_player = None
        self.audio_mixer = None


def _make_config(tmp_path, shows_directory):
    cfg = Configuration(fixtures=[], groups={}, universes={})
    cfg.songs = {"S1": Song(name="S1", timeline_data=TimelineData())}
    cfg.shows_directory = shows_directory
    path = str(tmp_path / "project" / "show.lms")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cfg.save(path)
    return Configuration.load(path), path


def _call(stub, file_path):
    ShowsTab._on_audio_file_loaded(stub, file_path)


def test_bundles_next_to_config_not_into_shows_directory(tmp_path):
    """The copy lands in <config dir>/audiofiles/ and the show stores
    the basename; the foreign shows_directory is never created."""
    foreign = str(tmp_path / "other_machine" / "kit")   # never created
    cfg, cfg_path = _make_config(tmp_path, foreign)
    src = tmp_path / "downloads" / "song.wav"
    src.parent.mkdir()
    src.write_bytes(b"RIFF....WAVE")

    stub = _TabStub(cfg, "S1")
    _call(stub, str(src))

    bundled = os.path.join(os.path.dirname(cfg_path), "audiofiles",
                           "song.wav")
    assert os.path.isfile(bundled), "audio must bundle next to the config"
    assert cfg.songs["S1"].timeline_data.audio_file_path == "song.wav"
    assert stub.audio_lane.audio_file_path == bundled
    assert stub.audio_lane.file_path_edit.text == "song.wav"
    assert not os.path.exists(foreign), \
        "the foreign shows_directory must never be created"


def test_file_already_in_bundle_stores_basename(tmp_path):
    cfg, cfg_path = _make_config(tmp_path, "")
    bundle = tmp_path / "project" / "audiofiles"
    bundle.mkdir()
    src = bundle / "song.wav"
    src.write_bytes(b"RIFF....WAVE")

    stub = _TabStub(cfg, "S1")
    _call(stub, str(src))

    assert cfg.songs["S1"].timeline_data.audio_file_path == "song.wav"


def test_bundle_failure_warns_and_keeps_the_original_path(tmp_path,
                                                          monkeypatch):
    """A PermissionError from the bundle dir must not crash: the show
    keeps the original absolute reference and a warning is recorded."""
    cfg, _ = _make_config(tmp_path, "")
    src = tmp_path / "song.wav"
    src.write_bytes(b"RIFF....WAVE")

    def boom(self, create=False):
        raise PermissionError(5, "Zugriff verweigert", r"C:\Users\other")

    monkeypatch.setattr(Configuration, "audio_bundle_dir", boom)
    log = user_warnings.get_log()
    before = len(log._entries)

    stub = _TabStub(cfg, "S1")
    _call(stub, str(src))   # must not raise

    assert cfg.songs["S1"].timeline_data.audio_file_path == str(src)
    new = [e for e in log._entries[before:] if e.category == "audio"]
    assert new, "the bundle failure must surface as a user warning"


def test_copy_failure_warns_and_keeps_the_original_path(tmp_path,
                                                        monkeypatch):
    cfg, _ = _make_config(tmp_path, "")
    src = tmp_path / "song.wav"
    src.write_bytes(b"RIFF....WAVE")

    import shutil

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copy2", boom)
    log = user_warnings.get_log()
    before = len(log._entries)

    stub = _TabStub(cfg, "S1")
    _call(stub, str(src))   # must not raise

    assert cfg.songs["S1"].timeline_data.audio_file_path == str(src)
    new = [e for e in log._entries[before:] if e.category == "audio"]
    assert new, "the copy failure must surface as a user warning"
