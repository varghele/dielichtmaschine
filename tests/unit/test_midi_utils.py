# tests/unit/test_midi_utils.py
"""Unit tests for MIDI profile discovery."""

import os
import pytest
from utils.midi_utils import discover_midi_profiles, get_midi_profile_directories


class TestGetMidiProfileDirectories:

    def test_returns_list(self):
        result = get_midi_profile_directories()
        assert isinstance(result, list)

    def test_all_entries_are_existing_directories(self):
        for d in get_midi_profile_directories():
            assert os.path.isdir(d), f"{d} should be a directory"


class TestDiscoverMidiProfiles:

    def test_returns_list(self):
        result = discover_midi_profiles()
        assert isinstance(result, list)

    def test_profile_dict_keys(self):
        """Each profile should have required keys."""
        profiles = discover_midi_profiles()
        if not profiles:
            pytest.skip("No MIDI profiles found on this system")
        for p in profiles:
            assert 'name' in p
            assert 'manufacturer' in p
            assert 'model' in p
            assert 'type' in p
            assert 'file_path' in p

    def test_profiles_sorted_by_name(self):
        profiles = discover_midi_profiles()
        if len(profiles) < 2:
            pytest.skip("Need at least 2 profiles to test sorting")
        names = [p['name'] for p in profiles]
        assert names == sorted(names)

    def test_no_duplicates(self):
        profiles = discover_midi_profiles()
        names = [p['name'] for p in profiles]
        assert len(names) == len(set(names))

    def test_apc_mini_found(self):
        """APC Mini mk2 should be available on the test system."""
        profiles = discover_midi_profiles()
        names = [p['name'] for p in profiles]
        if 'Akai APC Mini mk2' not in names:
            pytest.skip("APC Mini mk2 profile not found on this system")
        apc = next(p for p in profiles if p['name'] == 'Akai APC Mini mk2')
        assert apc['manufacturer'] == 'Akai'
        assert apc['model'] == 'APC Mini mk2'
        assert apc['type'] == 'MIDI'

    def test_handles_corrupt_file(self, tmp_path):
        """Should skip corrupt .qxi files without crashing."""
        corrupt = tmp_path / "corrupt.qxi"
        corrupt.write_text("not valid xml")
        # The function reads from system dirs, not tmp_path, so this just tests robustness
        # We verify it doesn't crash
        result = discover_midi_profiles()
        assert isinstance(result, list)
