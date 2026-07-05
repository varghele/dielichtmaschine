"""Project templates / starter rigs (utils/templates.py).

Contract:
- list_templates discovers the bundled demo rigs, pairs each with its
  demo-show variant, carries display metadata + fixture counts, and is
  sorted smallest-first.
- instantiate_template copies (never opens in place), brings the audio
  bundle along for show variants, refuses destinations inside the
  templates root, and the copy loads as a working Configuration whose
  demo-show audio resolves via the new location's audiofiles/.
"""

from __future__ import annotations

import os

import pytest

from config.models import Configuration
from utils.templates import (
    instantiate_template,
    list_templates,
    templates_root,
)


class TestListTemplates:

    def test_discovers_the_five_demo_rigs(self):
        templates = {t.key for t in list_templates()}
        assert templates == {
            "club_band", "band_midsize", "festival_mainstage",
            "dj_edm", "theatre_static",
        }

    def test_metadata_and_ordering(self):
        templates = list_templates()
        counts = [t.fixture_count for t in templates]
        assert counts == sorted(counts)
        assert counts[0] == 9  # club_band is the smallest starter
        for t in templates:
            assert t.name and t.description
            assert os.path.exists(t.rig_path)
            assert t.show_path is not None and os.path.exists(t.show_path)

    def test_missing_root_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr("utils.templates.templates_root",
                            lambda: str(tmp_path / "nowhere"))
        assert list_templates() == []


class TestInstantiate:

    @pytest.fixture
    def club_band(self):
        return next(t for t in list_templates() if t.key == "club_band")

    def test_rig_only_copy_loads(self, club_band, tmp_path):
        dest = str(tmp_path / "my_project.yaml")
        path = instantiate_template(club_band, dest, include_show=False)
        assert path == os.path.abspath(dest)

        config = Configuration.load(path)
        assert len(config.fixtures) == 9
        assert not config.shows  # rig variant has no demo show
        assert not os.path.isdir(str(tmp_path / "audiofiles"))

    def test_show_variant_brings_audio_bundle(self, club_band, tmp_path):
        dest = str(tmp_path / "my_project.yaml")
        instantiate_template(club_band, dest, include_show=True)

        config = Configuration.load(dest)
        assert "Demo" in config.shows
        audio_name = config.shows["Demo"].timeline_data.audio_file_path
        assert audio_name
        # The audio resolves via the NEW project's bundle dir.
        bundle = config.audio_bundle_dir()
        assert bundle == str(tmp_path / "audiofiles")
        assert os.path.exists(os.path.join(bundle, os.path.basename(audio_name)))

    def test_template_files_untouched(self, club_band, tmp_path):
        before_rig = open(club_band.rig_path, "rb").read()
        instantiate_template(club_band, str(tmp_path / "p.yaml"), include_show=True)
        assert open(club_band.rig_path, "rb").read() == before_rig

    def test_refuses_destination_inside_templates_root(self, club_band):
        inside = os.path.join(templates_root(), "rigs", "oops.yaml")
        with pytest.raises(ValueError, match="outside the bundled templates"):
            instantiate_template(club_band, inside)
        assert not os.path.exists(inside)

    def test_existing_audio_not_overwritten(self, club_band, tmp_path):
        audio_dir = tmp_path / "audiofiles"
        audio_dir.mkdir()
        # Learn the audio basename from the template itself.
        source_config = Configuration.load(club_band.show_path)
        basename = os.path.basename(
            source_config.shows["Demo"].timeline_data.audio_file_path)
        existing = audio_dir / basename
        existing.write_bytes(b"user-version")

        instantiate_template(club_band, str(tmp_path / "p.yaml"), include_show=True)
        assert existing.read_bytes() == b"user-version"
