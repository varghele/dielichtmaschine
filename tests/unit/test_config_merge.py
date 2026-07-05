"""Cross-config show import (utils/config_merge.py).

Contract:
- merge_shows deep-copies shows (source objects never aliased), resolves
  name conflicts per mode (rename / overwrite / skip), reports groups the
  target config lacks, and copies the audio file from the source bundle
  into the target bundle (path normalized to basename).
- list_import_candidates summarizes the source's shows against the
  target (conflicts, missing groups) for the picker dialog.
"""

from __future__ import annotations

import os

import pytest

from config.models import (
    Configuration, FixtureGroup, LightLane, Show, ShowPart, TimelineData,
)
from utils.config_merge import (
    list_import_candidates,
    merge_shows,
    referenced_groups,
)


def make_show(name, groups=("Front",), audio=None):
    lanes = [LightLane(name=f"Lane {g}", fixture_targets=[g]) for g in groups]
    return Show(
        name=name,
        parts=[ShowPart(name="Intro", color="#fff", signature="4/4",
                        bpm=120.0, num_bars=4, transition="instant")],
        timeline_data=TimelineData(lanes=lanes, audio_file_path=audio),
    )


def make_config(tmp_path, subdir, shows=(), groups=("Front",), audio_files=()):
    """A saved-on-disk config whose audiofiles/ bundle contains audio_files."""
    config_dir = tmp_path / subdir
    config_dir.mkdir()
    (config_dir / "audiofiles").mkdir()
    for filename in audio_files:
        (config_dir / "audiofiles" / filename).write_bytes(b"RIFF-fake-audio")
    config = Configuration(
        shows={s.name: s for s in shows},
        groups={g: FixtureGroup(g, []) for g in groups},
    )
    config._loaded_from = str(config_dir / "config.yaml")
    return config


class TestReferencedGroups:

    def test_collects_lane_targets_sorted_unique(self):
        show = make_show("A", groups=("Wash", "Front", "Wash"))
        assert referenced_groups(show) == ["Front", "Wash"]

    def test_show_without_timeline(self):
        show = Show(name="Bare")
        assert referenced_groups(show) == []


class TestListImportCandidates:

    def test_summary_flags_conflicts_and_missing_groups(self, tmp_path):
        source = make_config(
            tmp_path, "src",
            shows=[make_show("Opener", groups=("Front", "Lasers"), audio="opener.ogg")],
            groups=("Front", "Lasers"),
        )
        target = make_config(tmp_path, "dst", shows=[make_show("Opener")])

        (candidate,) = list_import_candidates(source, target)
        assert candidate.name == "Opener"
        assert candidate.num_parts == 1
        assert candidate.missing_groups == ["Lasers"]
        assert candidate.audio_file == "opener.ogg"
        assert candidate.name_conflict is True


class TestMergeShows:

    def test_added_show_is_a_deep_copy(self, tmp_path):
        source = make_config(tmp_path, "src", shows=[make_show("Opener")])
        target = make_config(tmp_path, "dst")

        (result,) = merge_shows(target, source, ["Opener"], copy_audio=False)
        assert result.action == "added"
        assert result.final_name == "Opener"

        target.shows["Opener"].parts[0].bpm = 999.0
        assert source.shows["Opener"].parts[0].bpm == 120.0

    def test_rename_on_conflict(self, tmp_path):
        source = make_config(tmp_path, "src", shows=[make_show("Opener")])
        target = make_config(tmp_path, "dst", shows=[make_show("Opener")])

        (result,) = merge_shows(target, source, ["Opener"],
                                on_conflict="rename", copy_audio=False)
        assert result.action == "renamed"
        assert result.final_name == "Opener (2)"
        assert set(target.shows) == {"Opener", "Opener (2)"}
        assert target.shows["Opener (2)"].name == "Opener (2)"

    def test_overwrite_on_conflict(self, tmp_path):
        source = make_config(
            tmp_path, "src",
            shows=[make_show("Opener", groups=("Wash",))], groups=("Wash",))
        target = make_config(tmp_path, "dst", shows=[make_show("Opener")])

        (result,) = merge_shows(target, source, ["Opener"],
                                on_conflict="overwrite", copy_audio=False)
        assert result.action == "overwritten"
        assert referenced_groups(target.shows["Opener"]) == ["Wash"]

    def test_skip_on_conflict(self, tmp_path):
        source = make_config(tmp_path, "src", shows=[make_show("Opener")])
        target = make_config(tmp_path, "dst", shows=[make_show("Opener")])

        (result,) = merge_shows(target, source, ["Opener"],
                                on_conflict="skip", copy_audio=False)
        assert result.action == "skipped"
        assert result.final_name is None
        assert len(target.shows) == 1

    def test_missing_groups_reported_not_fixed(self, tmp_path):
        source = make_config(
            tmp_path, "src",
            shows=[make_show("Opener", groups=("Front", "Lasers"))],
            groups=("Front", "Lasers"),
        )
        target = make_config(tmp_path, "dst")  # only has "Front"

        (result,) = merge_shows(target, source, ["Opener"], copy_audio=False)
        assert result.missing_groups == ["Lasers"]
        # Lane still targets the missing group — retargeting is v1.4b.
        assert "Lasers" in referenced_groups(target.shows["Opener"])

    def test_unknown_show_raises(self, tmp_path):
        source = make_config(tmp_path, "src")
        target = make_config(tmp_path, "dst")
        with pytest.raises(KeyError, match="NoSuchShow"):
            merge_shows(target, source, ["NoSuchShow"])

    def test_invalid_conflict_mode_raises(self, tmp_path):
        source = make_config(tmp_path, "src")
        target = make_config(tmp_path, "dst")
        with pytest.raises(ValueError, match="conflict mode"):
            merge_shows(target, source, [], on_conflict="explode")


class TestAudioCopy:

    def test_audio_copied_into_target_bundle(self, tmp_path):
        source = make_config(tmp_path, "src",
                             shows=[make_show("Opener", audio="opener.ogg")],
                             audio_files=("opener.ogg",))
        target = make_config(tmp_path, "dst")

        (result,) = merge_shows(target, source, ["Opener"])
        assert result.audio_action == "copied"
        assert os.path.exists(str(tmp_path / "dst" / "audiofiles" / "opener.ogg"))
        assert target.shows["Opener"].timeline_data.audio_file_path == "opener.ogg"

    def test_audio_already_present_is_not_overwritten(self, tmp_path):
        source = make_config(tmp_path, "src",
                             shows=[make_show("Opener", audio="opener.ogg")],
                             audio_files=("opener.ogg",))
        target = make_config(tmp_path, "dst", audio_files=("opener.ogg",))
        existing = tmp_path / "dst" / "audiofiles" / "opener.ogg"
        existing.write_bytes(b"target-version")

        (result,) = merge_shows(target, source, ["Opener"])
        assert result.audio_action == "already-present"
        assert existing.read_bytes() == b"target-version"

    def test_missing_audio_reported(self, tmp_path):
        source = make_config(tmp_path, "src",
                             shows=[make_show("Opener", audio="ghost.ogg")])
        target = make_config(tmp_path, "dst")

        (result,) = merge_shows(target, source, ["Opener"])
        assert result.audio_action == "not-found"
        # Path still normalized to basename for the target's bundle dir.
        assert target.shows["Opener"].timeline_data.audio_file_path == "ghost.ogg"

    def test_legacy_absolute_path_resolves_and_copies(self, tmp_path):
        loose = tmp_path / "loose_track.ogg"
        loose.write_bytes(b"loose")
        source = make_config(tmp_path, "src",
                             shows=[make_show("Opener", audio=str(loose))])
        target = make_config(tmp_path, "dst")

        (result,) = merge_shows(target, source, ["Opener"])
        assert result.audio_action == "copied"
        assert target.shows["Opener"].timeline_data.audio_file_path == "loose_track.ogg"

    def test_show_without_audio(self, tmp_path):
        source = make_config(tmp_path, "src", shows=[make_show("Opener")])
        target = make_config(tmp_path, "dst")
        (result,) = merge_shows(target, source, ["Opener"])
        assert result.audio_action == "none"
