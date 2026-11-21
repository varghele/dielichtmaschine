"""Song playback: the one pygame player (v1.5.6, roadmap "Two audio
playback paths", decision 2026-11-21: keep pygame, fix its gaps).

Covers:
- the Audio Settings output device, sample rate and buffer reach
  pygame.mixer.init (they were ignored while pygame played), an
  unopenable device falls back to the system default with a Help >
  Warnings entry, and a live reconfigure keeps file, position and play
  state;
- the audio lane's M button mutes the pygame player (it was wired only
  to the removed sounddevice engine) and unmute restores the volume;
- one shared player with an owner: a tab drives it only while it holds
  it, so the Shows and Structure tabs never pause, seek or re-volume
  each other's song;
- the persisted settings helpers and the rewritten dialog.

pygame is replaced by a recording fake: no audio device is opened.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from audio import simple_audio_player as sap  # noqa: E402


class _FakeMusic:
    def __init__(self, log):
        self.log = log
        self.volume = None

    def load(self, path):
        self.log.append(("load", path))

    def play(self, start=0.0):
        self.log.append(("play", start))

    def pause(self):
        self.log.append(("pause",))

    def unpause(self):
        self.log.append(("unpause",))

    def stop(self):
        self.log.append(("stop",))

    def set_volume(self, v):
        self.volume = v


class _FakeSound:
    def __init__(self, path):
        pass

    def get_length(self):
        return 120.0


class _FakeMixer:
    def __init__(self, log, bad_devices=()):
        self.log = log
        self.bad_devices = set(bad_devices)
        self.inited = None
        self.music = _FakeMusic(log)
        self.Sound = _FakeSound

    def get_init(self):
        return self.inited

    def init(self, frequency=44100, size=-16, channels=2, buffer=2048,
             devicename=None):
        if devicename in self.bad_devices:
            raise RuntimeError("No such device.")
        self.inited = (frequency, buffer, devicename)
        self.log.append(("init", frequency, buffer, devicename))

    def quit(self):
        self.inited = None
        self.log.append(("quit",))


class _FakePygame:
    def __init__(self, bad_devices=()):
        self.log = []
        self.mixer = _FakeMixer(self.log, bad_devices)


@pytest.fixture
def fake_pygame(monkeypatch):
    fake = _FakePygame(bad_devices={"Unplugged Interface"})
    monkeypatch.setattr(sap, "pygame", fake)
    monkeypatch.setattr(sap, "PYGAME_AVAILABLE", True)
    sap._shared_player = None
    yield fake
    sap._shared_player = None


@pytest.fixture
def song(tmp_path):
    path = tmp_path / "song.ogg"
    path.write_bytes(b"\0")
    return str(path)


class TestOutputSettingsReachPygame:
    def test_device_rate_and_buffer_open_the_mixer(self, fake_pygame):
        player = sap.SimpleAudioPlayer()
        assert player.initialize(48000, 1024, "Scarlett 6i6")
        assert fake_pygame.mixer.inited == (48000, 1024, "Scarlett 6i6")
        assert player.active_device == "Scarlett 6i6"

    def test_empty_device_is_the_system_default(self, fake_pygame):
        player = sap.SimpleAudioPlayer()
        assert player.initialize(44100, 2048, "")
        assert fake_pygame.mixer.inited == (44100, 2048, None)
        assert player.active_device == ""

    def test_unopenable_device_falls_back_to_default_and_warns(
            self, fake_pygame, monkeypatch):
        from utils import user_warnings
        warned = []
        monkeypatch.setattr(user_warnings, "warn",
                            lambda msg, **kw: warned.append((msg, kw)))
        player = sap.SimpleAudioPlayer()
        assert player.initialize(44100, 2048, "Unplugged Interface")
        assert fake_pygame.mixer.inited == (44100, 2048, None)
        assert player.active_device == ""
        assert len(warned) == 1
        assert "Unplugged Interface" in warned[0][0]
        assert warned[0][1]["category"] == "audio"

    def test_reconfigure_keeps_file_position_and_play_state(
            self, fake_pygame, song, monkeypatch):
        player = sap.SimpleAudioPlayer()
        player.initialize(44100, 2048, "")
        player.load(song)
        player.play(30.0)
        monkeypatch.setattr(player, "get_current_position", lambda: 42.0)
        fake_pygame.log.clear()

        assert player.reconfigure(48000, 512, "Scarlett 6i6")

        assert fake_pygame.mixer.inited == (48000, 512, "Scarlett 6i6")
        assert ("load", song) in fake_pygame.log
        assert fake_pygame.log[-1] == ("play", 42.0)
        assert player.is_playing()

    def test_reconfigure_with_unchanged_settings_is_a_no_op(
            self, fake_pygame):
        player = sap.SimpleAudioPlayer()
        player.initialize(44100, 2048, "")
        fake_pygame.log.clear()
        assert player.reconfigure(44100, 2048, "")
        assert fake_pygame.log == []

    def test_apply_output_settings_leaves_an_unopened_player_alone(
            self, fake_pygame):
        sap.shared_player()  # created, never initialized
        assert sap.apply_output_settings(48000, 512, "X")
        assert fake_pygame.mixer.inited is None

    def test_ensure_shared_player_opens_with_stored_settings(
            self, fake_pygame):
        from utils.app_settings import set_audio_output_settings
        set_audio_output_settings("Scarlett 6i6", 48000, 1024)
        try:
            player = sap.ensure_shared_player()
            assert player is sap.shared_player()
            assert fake_pygame.mixer.inited == (48000, 1024, "Scarlett 6i6")
        finally:
            set_audio_output_settings("", 44100, 2048)


class TestMute:
    def test_mute_silences_and_unmute_restores_the_volume(
            self, fake_pygame, song):
        player = sap.SimpleAudioPlayer()
        player.initialize()
        player.load(song)
        player.set_volume(0.6)
        assert fake_pygame.mixer.music.volume == pytest.approx(0.6)

        player.set_muted(True)
        assert fake_pygame.mixer.music.volume == 0.0
        assert player.get_volume() == pytest.approx(0.6)
        assert player.is_muted()

        player.set_volume(0.3)  # moving the slider while muted stays silent
        assert fake_pygame.mixer.music.volume == 0.0

        player.set_muted(False)
        assert fake_pygame.mixer.music.volume == pytest.approx(0.3)

    def test_mute_survives_loading_the_next_song(self, fake_pygame, song):
        player = sap.SimpleAudioPlayer()
        player.initialize()
        player.set_muted(True)
        player.load(song)
        assert fake_pygame.mixer.music.volume == 0.0


class TestSharedOwnership:
    def test_claim_loads_once_and_switching_owner_stops_the_old_song(
            self, fake_pygame, song, tmp_path):
        other = tmp_path / "other.ogg"
        other.write_bytes(b"\0")
        player = sap.SimpleAudioPlayer()
        player.initialize()
        shows, structure = object(), object()

        assert player.claim(shows, song)
        player.play(0.0)
        fake_pygame.log.clear()
        assert player.claim(shows, song)          # same owner, same file
        assert ("load", song) not in fake_pygame.log
        assert player.is_playing()

        assert player.claim(structure, str(other))
        assert player.is_owned_by(structure)
        assert not player.is_owned_by(shows)
        assert not player.is_playing()
        assert ("load", str(other)) in fake_pygame.log

    def test_release_only_drops_the_holder(self, fake_pygame, song):
        player = sap.SimpleAudioPlayer()
        player.initialize()
        a, b = object(), object()
        player.claim(a, song)
        player.release(b)
        assert player.is_owned_by(a)
        player.release(a)
        assert player.owner is None


class _Slider:
    def __init__(self, value):
        self._v = value

    def value(self):
        return self._v


class _Button:
    def __init__(self, checked):
        self._c = checked

    def isChecked(self):
        return self._c


class _Lane:
    def __init__(self, path, volume=80, muted=False):
        self._path = path
        self.volume_slider = _Slider(volume)
        self.mute_button = _Button(muted)

    def get_audio_file_path(self):
        return self._path


def _tab_stub(cls, player, lane):
    """Duck-typed tab: just the attributes the audio methods read."""
    stub = type("Stub", (), {})()
    stub.simple_audio_player = player
    stub.audio_lane = lane
    stub._owns_audio = lambda: cls._owns_audio(stub)
    return stub


@pytest.mark.parametrize("tab_path", ["gui.tabs.shows_tab.ShowsTab",
                                      "gui.tabs.structure_tab.StructureTab"])
class TestTabsDriveOnlyWhileOwning:
    def _cls(self, tab_path):
        import importlib
        mod, name = tab_path.rsplit(".", 1)
        return getattr(importlib.import_module(mod), name)

    def test_lane_mute_and_volume_reach_the_player_while_owned(
            self, tab_path, fake_pygame, song):
        cls = self._cls(tab_path)
        player = sap.SimpleAudioPlayer()
        player.initialize()
        tab = _tab_stub(cls, player, _Lane(song))
        player.claim(tab, song)

        cls._on_lane_mute_toggled(tab, True)
        assert player.is_muted()
        cls._on_lane_volume_changed(tab, 25)
        assert player.get_volume() == pytest.approx(0.25)

    def test_a_tab_that_does_not_own_the_player_leaves_it_alone(
            self, tab_path, fake_pygame, song):
        cls = self._cls(tab_path)
        player = sap.SimpleAudioPlayer()
        player.initialize()
        tab = _tab_stub(cls, player, _Lane(song))
        player.claim(object(), song)   # the OTHER tab holds it
        player.set_volume(0.9)

        cls._on_lane_mute_toggled(tab, True)
        cls._on_lane_volume_changed(tab, 10)
        assert not player.is_muted()
        assert player.get_volume() == pytest.approx(0.9)


def test_structure_tab_play_claims_with_its_lane_volume_and_mute(
        fake_pygame, song):
    """The Structure tab plays through the shared player too, carrying its
    own lane's volume and mute (it used the removed sounddevice engine,
    whose settings lookup never reached the main window)."""
    from gui.tabs.structure_tab import StructureTab

    class _Timer:
        def start(self):
            self.started = True

    class _Btn:
        def setText(self, text):
            self.text = text

    tab = _tab_stub(StructureTab, None, _Lane(song, volume=40, muted=True))
    tab.song_structure = object()
    tab.playhead_position = 12.0
    tab.play_btn = _Btn()
    tab.playback_timer = _Timer()
    tab._audio_controls_wired = True   # skip the real signal wiring
    tab._init_audio_engine = lambda: setattr(
        tab, "simple_audio_player", sap.ensure_shared_player())

    StructureTab._start_playback(tab)

    player = sap.shared_player()
    assert player.is_owned_by(tab)
    assert player.get_volume() == pytest.approx(0.4)
    assert player.is_muted()
    assert ("play", 12.0) in fake_pygame.log


class TestStoredSettings:
    def test_defaults(self):
        from utils.app_settings import (audio_output_settings,
                                        set_audio_output_settings)
        set_audio_output_settings("", 44100, 2048)
        assert audio_output_settings() == {
            "output_device": "", "sample_rate": 44100, "buffer_size": 2048}

    def test_round_trip_and_unknown_rate_falls_back(self):
        from utils.app_settings import (app_settings, audio_output_settings,
                                        set_audio_output_settings)
        try:
            set_audio_output_settings("Scarlett 6i6", 96000, 512)
            assert audio_output_settings() == {
                "output_device": "Scarlett 6i6", "sample_rate": 96000,
                "buffer_size": 512}
            app_settings().setValue("audio/sample_rate", 22050)
            assert audio_output_settings()["sample_rate"] == 44100
        finally:
            set_audio_output_settings("", 44100, 2048)


class TestAudioSettingsDialog:
    @pytest.fixture
    def dialog_factory(self, qapp, fake_pygame):
        from gui.audio_settings_dialog import AudioSettingsDialog
        made = []

        def make(devices=("Scarlett 6i6", "HDMI")):
            d = AudioSettingsDialog(device_lister=lambda: list(devices))
            made.append(d)
            return d
        yield make
        for d in made:
            d.deleteLater()
        from utils.app_settings import set_audio_output_settings
        set_audio_output_settings("", 44100, 2048)

    def test_lists_system_default_first_then_sdl_devices(
            self, dialog_factory):
        d = dialog_factory()
        items = [d.device_combo.itemText(i)
                 for i in range(d.device_combo.count())]
        assert items == ["System default", "Scarlett 6i6", "HDMI"]
        assert d.device_combo.currentData() == ""

    def test_stored_device_that_is_unplugged_stays_selected(
            self, dialog_factory):
        from utils.app_settings import set_audio_output_settings
        set_audio_output_settings("Old Interface", 48000, 1024)
        d = dialog_factory()
        assert d.device_combo.currentText() == "Old Interface (not connected)"
        assert d.selected_settings() == {
            "output_device": "Old Interface", "sample_rate": 48000,
            "buffer_size": 1024}

    def test_latency_readout_follows_rate_and_buffer(self, dialog_factory):
        d = dialog_factory()
        d.sample_rate_combo.setCurrentIndex(d.sample_rate_combo.findData(48000))
        d.buffer_combo.setCurrentIndex(d.buffer_combo.findData(4096))
        assert d.latency_label.text() == "about 85 ms"   # 4096 / 48000 s

    def test_ok_persists_and_reopens_a_running_player(
            self, dialog_factory, fake_pygame):
        from utils.app_settings import audio_output_settings
        player = sap.shared_player()
        player.initialize(44100, 2048, "")
        d = dialog_factory()
        d.device_combo.setCurrentIndex(d.device_combo.findData("HDMI"))
        d.sample_rate_combo.setCurrentIndex(d.sample_rate_combo.findData(48000))
        d.accept()
        assert audio_output_settings() == {
            "output_device": "HDMI", "sample_rate": 48000,
            "buffer_size": 2048}
        assert fake_pygame.mixer.inited == (48000, 2048, "HDMI")

    def test_no_live_input_controls_any_more(self, dialog_factory):
        """The old Audio Input group's values were never read by anything;
        live input is chosen on the Auto tab."""
        from PyQt6.QtWidgets import QCheckBox
        d = dialog_factory()
        assert d.findChildren(QCheckBox) == []
