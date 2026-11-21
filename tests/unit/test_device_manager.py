"""
Tests for :mod:`audio.device_manager` — classification, filtering, and
the Windows ASIO registry probe.

The fixture ``tests/fixtures/audio_devices_win_no_asio.json`` is a
verbatim dump of ``sd.query_devices()`` + ``sd.query_hostapis()`` from
a real Windows machine with no ASIO host API loaded but several ASIO
drivers registered (Focusrite, ASIO4ALL, etc.). It exercises:

- 43 devices across 4 host APIs (MME, DirectSound, WASAPI, WDM-KS)
- Microsoft Sound Mapper + "Primärer Sound*treiber" abstract endpoints
- @System32\\drivers\\bthhfenum.sys Bluetooth Hands-Free entries
- MME 31-char truncations of names whose full forms exist on other APIs
- Multiple Realtek WDM-KS stream splits (Mic Array / Mic / Stereomix)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from audio.device_manager import (
    DeviceCategory,
    DeviceManager,
    _classify,
    _classify_device,
    _clean_display_name,
    _physical_id,
    asio_status,
    get_registered_asio_drivers,
)


FIXTURE_PATH = (Path(__file__).parent.parent
                / "fixtures" / "audio_devices_win_no_asio.json")


@pytest.fixture
def raw_fixture():
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def patched_sounddevice(raw_fixture):
    """Patch ``sounddevice`` so DeviceManager sees the captured fixture
    instead of probing the local system at test time."""
    devices = raw_fixture["devices"]
    host_apis = raw_fixture["host_apis"]

    def query_devices(index=None):
        if index is None:
            return devices
        return devices[index]

    def query_hostapis():
        return host_apis

    with patch("audio.device_manager.sd") as mock_sd:
        mock_sd.query_devices.side_effect = query_devices
        mock_sd.query_hostapis.side_effect = query_hostapis
        mock_sd.default.device = [-1, -1]
        yield mock_sd


# ── Pure classifier helpers ──────────────────────────────────────────


class TestClassifyName:
    """Cover :func:`_classify` against representative samples from the
    fixture without going through enumeration plumbing."""

    def test_mapper_microsoft_sound_mapper(self):
        assert _classify("Microsoft Sound Mapper - Input", 44100, 2, 0) == \
            DeviceCategory.MAPPER

    def test_mapper_german_directsound_primary(self):
        assert _classify("Primärer Soundaufnahmetreiber", 44100, 2, 0) == \
            DeviceCategory.MAPPER
        assert _classify("Primärer Soundtreiber", 44100, 0, 2) == \
            DeviceCategory.MAPPER

    def test_telephony_system32_path(self):
        raw = ("Output (@System32\\drivers\\bthhfenum.sys,#4;%1 "
               "Hands-Free HF Audio%0\n;(Galaxy S22))")
        assert _classify(raw, 8000, 0, 1) == DeviceCategory.TELEPHONY

    def test_telephony_directsound_hands_free_44k(self):
        # DirectSound reports 44.1 kHz for HFP even though hardware is
        # 16 kHz — the name-based marker must catch it.
        raw = "Kopfhörer (IE PRO BT Module Hands-Free AG Audio)"
        assert _classify(raw, 44100, 1, 0) == DeviceCategory.TELEPHONY

    def test_telephony_low_rate_mono_no_name_marker(self):
        # Generic 8 kHz mono with no marker — heuristic fallback.
        assert _classify("Some Bluetooth Voice Thing", 8000, 1, 0) == \
            DeviceCategory.TELEPHONY

    def test_physical_realtek_wasapi(self):
        assert _classify("Mikrofon (Realtek(R) Audio)", 48000, 2, 0) == \
            DeviceCategory.PHYSICAL

    def test_physical_steam_virtual(self):
        # Steam Streaming Microphone is a virtual driver but treated as
        # PHYSICAL for UX since users may want to capture from it.
        assert _classify("Mikrofon (Steam Streaming Microphone)",
                         44100, 1, 0) == DeviceCategory.PHYSICAL

    def test_low_rate_stereo_not_telephony(self):
        # Stereo at low rate is unusual but not HFP — keep it.
        assert _classify("Weird vintage card", 11025, 2, 0) == \
            DeviceCategory.PHYSICAL


class TestCleanDisplayName:
    def test_strips_system32_path_with_trailing_label(self):
        raw = ("Output (@System32\\drivers\\bthhfenum.sys,#4;%1 "
               "Hands-Free HF Audio%0\n;(Galaxy S22))")
        assert _clean_display_name(raw) == "Galaxy S22 (Bluetooth Handsfree)"

    def test_strips_system32_path_generic_fallback(self):
        raw = "Output (@System32\\drivers\\bthhfenum.sys,#1)"
        assert _clean_display_name(raw) == "Bluetooth Handsfree (Output)"

    def test_collapses_whitespace(self):
        assert _clean_display_name("  Foo  \n  bar  ") == "Foo bar"

    def test_passes_through_normal_names(self):
        assert _clean_display_name("Mikrofon (Realtek(R) Audio)") == \
            "Mikrofon (Realtek(R) Audio)"


class TestPhysicalId:
    def test_strips_realtek_trademark(self):
        assert _physical_id("Mikrofon (Realtek(R) Audio)") == \
            "mikrofon (realtek audio)"

    def test_strips_wdm_ks_wave_suffix(self):
        # "Wave)" inside parens (e.g. "Steam Streaming Microphone Wave")
        # is dropped so the WDM-KS variant collapses with the WASAPI one.
        assert _physical_id("Mikrofon (Steam Streaming Microphone Wave)") == \
            "mikrofon (steam streaming microphone)"

    def test_keeps_meaningful_stream_distinctions(self):
        # WDM-KS exposes different signal paths on the same Realtek
        # card; users may pick between them deliberately, so they must
        # NOT collapse.
        mic_array = _physical_id("Mikrofon (Realtek HD Audio Mic Array input)")
        stereomix = _physical_id("Stereomix (Realtek HD Audio Stereo input)")
        assert mic_array != stereomix


# ── ASIO registry probe (mocked winreg) ──────────────────────────────


class TestAsioRegistryProbe:
    @pytest.fixture
    def fake_winreg(self):
        """Stub winreg with a configurable set of ASIO driver entries."""
        import sys

        class _FakeKey:
            def __init__(self, entries):
                self.entries = entries

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        class _FakeWinreg:
            HKEY_LOCAL_MACHINE = "HKLM"

            def __init__(self):
                self.entries_per_path = {}

            def OpenKey(self, hive, path):
                if path not in self.entries_per_path:
                    raise OSError("path not registered")
                return _FakeKey(self.entries_per_path[path])

            @staticmethod
            def EnumKey(key, i):
                if i >= len(key.entries):
                    raise OSError("end of list")
                return key.entries[i]

        fake = _FakeWinreg()
        sys.modules["winreg"] = fake  # type: ignore
        yield fake
        del sys.modules["winreg"]

    def test_returns_empty_on_non_windows(self, monkeypatch):
        monkeypatch.setattr("audio.device_manager.sys.platform", "linux")
        assert get_registered_asio_drivers() == []

    def test_reads_hklm_software_asio(self, fake_winreg, monkeypatch):
        monkeypatch.setattr("audio.device_manager.sys.platform", "win32")
        fake_winreg.entries_per_path[r"SOFTWARE\ASIO"] = [
            "Focusrite USB ASIO",
            "ASIO4ALL v2",
        ]
        assert get_registered_asio_drivers() == [
            "Focusrite USB ASIO",
            "ASIO4ALL v2",
        ]

    def test_dedups_across_wow6432(self, fake_winreg, monkeypatch):
        monkeypatch.setattr("audio.device_manager.sys.platform", "win32")
        fake_winreg.entries_per_path[r"SOFTWARE\ASIO"] = ["A", "B"]
        fake_winreg.entries_per_path[r"SOFTWARE\WOW6432Node\ASIO"] = ["B", "C"]
        assert get_registered_asio_drivers() == ["A", "B", "C"]


class TestAsioStatus:
    def test_ok_when_in_portaudio_and_registered(
            self, patched_sounddevice, monkeypatch):
        patched_sounddevice.query_hostapis.side_effect = lambda: [
            {"name": "ASIO"}, {"name": "Windows WASAPI"}]
        monkeypatch.setattr(
            "audio.device_manager.get_registered_asio_drivers",
            lambda: ["Focusrite USB ASIO"],
        )
        s = asio_status()
        assert s["in_portaudio"] is True
        assert s["level"] == "ok"
        assert "Focusrite USB ASIO" in s["message"]

    def test_warn_when_registered_but_not_loaded(
            self, patched_sounddevice, monkeypatch):
        # patched_sounddevice already returns the fixture's host APIs,
        # which don't include ASIO.
        monkeypatch.setattr(
            "audio.device_manager.get_registered_asio_drivers",
            lambda: ["Focusrite USB ASIO", "ASIO4ALL v2"],
        )
        s = asio_status()
        assert s["in_portaudio"] is False
        assert s["level"] == "warn"
        assert "Plug in" in s["message"]
        assert "Focusrite USB ASIO" in s["message"]
        assert "ASIO4ALL v2" in s["message"]

    def test_info_when_no_asio_at_all_on_windows(
            self, patched_sounddevice, monkeypatch):
        monkeypatch.setattr(
            "audio.device_manager.get_registered_asio_drivers",
            lambda: [],
        )
        monkeypatch.setattr("audio.device_manager.sys.platform", "win32")
        s = asio_status()
        assert s["level"] == "info"
        assert "ASIO4ALL" in s["message"]


# ── DeviceManager — enumeration + filtering ──────────────────────────


class TestEnumerationAgainstRealFixture:
    """End-to-end tests against the captured 43-device fixture."""

    def test_raw_count_matches_fixture(self, patched_sounddevice):
        dm = DeviceManager()
        all_devs = dm._all_devices_classified()
        assert len(all_devs) == 43

    def test_curated_inputs_drops_telephony_and_mappers(self, patched_sounddevice):
        dm = DeviceManager()
        inputs = dm.enumerate_input_devices()
        # Real systems vary; assert the *qualitative* properties.
        assert all(d.category == DeviceCategory.PHYSICAL for d in inputs), \
            f"Curated list leaked non-physical: {[d.display_name for d in inputs]}"
        # No abstract mapper survives.
        names = [d.display_name for d in inputs]
        assert "Microsoft Sound Mapper - Input" not in names
        assert "Primärer Soundaufnahmetreiber" not in names
        # No @System32 path survives.
        assert not any("@System32" in n for n in names)
        # No Hands-Free entry survives (telephony name marker).
        assert not any("Hands-Free" in n for n in names)
        # Curated list is meaningfully smaller than raw.
        assert len(inputs) < 15, f"Curated list still too big: {len(inputs)}"

    def test_curated_drops_mme_truncated_telephony(self, patched_sounddevice):
        dm = DeviceManager()
        names = [d.display_name for d in dm.enumerate_input_devices()]
        # The truncated MME entry "Kopfh�rer (IE PRO BT Module Han" was
        # being misclassified as PHYSICAL before the MME-fixup pass.
        for n in names:
            assert not n.startswith("Kopfh"), \
                f"Truncated MME telephony entry leaked: {n!r}"

    def test_wasapi_filter_returns_only_wasapi(self, patched_sounddevice):
        dm = DeviceManager()
        wasapi = dm.enumerate_input_devices(host_api_filter="Windows WASAPI")
        assert wasapi  # at least one
        assert all(d.host_api == "Windows WASAPI" for d in wasapi)

    def test_quality_ranking_orders_apis(self, patched_sounddevice):
        dm = DeviceManager()
        inputs = dm.enumerate_input_devices()
        # Devices are sorted by (quality_rank, display_name). The first
        # entry's host API should be the best-ranked one available.
        host_apis_in_order = [d.host_api for d in inputs]
        # WASAPI (rank 10) should precede WDM-KS (rank 20) which should
        # precede DirectSound (rank 60) which precedes MME (rank 70).
        expected_priority = ["Windows WASAPI", "Windows WDM-KS",
                             "Windows DirectSound", "MME"]
        seen_indices = [expected_priority.index(api)
                        for api in host_apis_in_order
                        if api in expected_priority]
        assert seen_indices == sorted(seen_indices), \
            f"Out-of-order host APIs in curated list: {host_apis_in_order}"

    def test_include_mappers_resurrects_mappers(self, patched_sounddevice):
        dm = DeviceManager()
        with_mappers = dm.enumerate_input_devices(include_mappers=True)
        names = [d.display_name for d in with_mappers]
        assert "Microsoft Sound Mapper - Input" in names

    def test_include_telephony_resurrects_handsfree(self, patched_sounddevice):
        dm = DeviceManager()
        with_tel = dm.enumerate_input_devices(include_telephony=True)
        assert any(d.category == DeviceCategory.TELEPHONY for d in with_tel)

    def test_dedup_off_keeps_duplicates(self, patched_sounddevice):
        dm = DeviceManager()
        deduped = dm.enumerate_input_devices(dedup_physical=True)
        raw = dm.enumerate_input_devices(dedup_physical=False)
        # Raw should have at least as many entries as deduped (and on
        # the captured fixture, strictly more because of MME truncations).
        assert len(raw) >= len(deduped)

    def test_get_available_host_apis_ordered_by_quality(self, patched_sounddevice):
        dm = DeviceManager()
        apis = dm.get_available_host_apis()
        names_in_order = [name for _, name in apis]
        # The fixture has WASAPI, WDM-KS, DirectSound, MME. Best first.
        assert names_in_order.index("Windows WASAPI") < \
            names_in_order.index("Windows DirectSound")
        assert names_in_order.index("Windows WDM-KS") < \
            names_in_order.index("MME")

    def test_audio_device_str_uses_display_name(self, patched_sounddevice):
        dm = DeviceManager()
        inputs = dm.enumerate_input_devices()
        # __str__ should use display_name, not raw name, when available.
        assert inputs[0].display_name in str(inputs[0])


class TestClassifyDevice:
    """Cover :func:`_classify_device` end-to-end."""

    def test_returns_full_tuple(self):
        info = {
            "name": "Mikrofon (Realtek(R) Audio)",
            "max_input_channels": 2,
            "max_output_channels": 0,
            "default_samplerate": 48000.0,
        }
        category, display, pid, rank = _classify_device(info, "Windows WASAPI")
        assert category == DeviceCategory.PHYSICAL
        assert display == "Mikrofon (Realtek(R) Audio)"
        assert pid == "mikrofon (realtek audio)"
        assert rank == 10  # WASAPI

    def test_unknown_api_gets_high_rank(self):
        info = {
            "name": "X",
            "max_input_channels": 2,
            "max_output_channels": 0,
            "default_samplerate": 48000.0,
        }
        _, _, _, rank = _classify_device(info, "Some Future API")
        assert rank == 99
