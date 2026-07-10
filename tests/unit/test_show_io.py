"""Tests for utils.show_io (File -> Import/Export Show Structure)."""
import os
from pathlib import Path

import pytest

from config.models import Song, ShowPart, ShowEffect, TimelineData
from utils.show_io import (
    CSV_FIELDNAMES,
    detect_format,
    read_show,
    read_show_structure_csv,
    read_show_yaml,
    write_show,
    write_show_structure_csv,
    write_show_yaml,
)


def _make_show(name="TestShow"):
    return Song(
        name=name,
        parts=[
            ShowPart(name="intro", color="#00ff00", signature="4/4",
                     bpm=120, num_bars=8, transition="instant"),
            ShowPart(name="verse", color="#ff0000", signature="4/4",
                     bpm=120, num_bars=16, transition="gradual"),
        ],
        effects=[
            ShowEffect(show_part="intro", fixture_group="PARS",
                       effect="static", speed="1", color="red",
                       intensity=200, spot=""),
        ],
        timeline_data=None,
        trigger_device="",
        trigger_channel=-1,
    )


def test_detect_format():
    assert detect_format("foo.csv") == "csv"
    assert detect_format("foo.CSV") == "csv"
    assert detect_format("foo.yaml") == "yaml"
    assert detect_format("foo.yml") == "yaml"
    with pytest.raises(ValueError):
        detect_format("foo.txt")


def test_csv_round_trip(tmp_path: Path):
    show = _make_show()
    path = tmp_path / "demo.csv"
    write_show_structure_csv(str(path), show)

    parts = read_show_structure_csv(str(path))
    assert len(parts) == 2
    assert [p.name for p in parts] == ["intro", "verse"]
    assert parts[0].bpm == 120
    assert parts[1].transition == "gradual"


def test_csv_uses_six_column_layout(tmp_path: Path):
    path = tmp_path / "demo.csv"
    write_show_structure_csv(str(path), _make_show())
    header = path.read_text().splitlines()[0].split(",")
    assert header == CSV_FIELDNAMES


def test_yaml_round_trip(tmp_path: Path):
    show = _make_show("YamlShow")
    path = tmp_path / "demo.yaml"
    write_show_yaml(str(path), show)

    loaded = read_show_yaml(str(path))
    assert loaded.name == "YamlShow"
    assert len(loaded.parts) == 2
    assert loaded.parts[0].color == "#00ff00"
    assert len(loaded.effects) == 1
    assert loaded.effects[0].fixture_group == "PARS"


def test_yaml_round_trip_with_timeline_data(tmp_path: Path):
    show = _make_show("WithTimeline")
    show.timeline_data = TimelineData(audio_file_path="song.mp3")
    path = tmp_path / "demo.yaml"
    write_show_yaml(str(path), show)

    loaded = read_show_yaml(str(path))
    assert loaded.timeline_data is not None
    assert loaded.timeline_data.audio_file_path == "song.mp3"


def test_yaml_missing_name_raises(tmp_path: Path):
    path = tmp_path / "broken.yaml"
    path.write_text("parts: []\n")  # no name field
    with pytest.raises(ValueError, match="name"):
        read_show_yaml(str(path))


def test_format_agnostic_csv(tmp_path: Path):
    show = _make_show()
    path = tmp_path / "song_name.csv"
    fmt = write_show(str(path), show)
    assert fmt == "csv"
    loaded, fmt = read_show(str(path))
    assert fmt == "csv"
    assert loaded.name == "song_name"  # derived from basename
    assert len(loaded.parts) == 2


def test_format_agnostic_yaml(tmp_path: Path):
    show = _make_show("InYaml")
    path = tmp_path / "anything.yaml"
    write_show(str(path), show)
    loaded, fmt = read_show(str(path))
    assert fmt == "yaml"
    assert loaded.name == "InYaml"
    assert len(loaded.parts) == 2


def test_csv_export_drops_effects_and_timeline(tmp_path: Path):
    """CSV is structure-only by design. Effects + timeline_data don't round-trip
    through CSV. Round-tripping via CSV gives only parts back."""
    show = _make_show()
    show.timeline_data = TimelineData(audio_file_path="audio.wav")
    path = tmp_path / "structureonly.csv"
    write_show(str(path), show)
    loaded, _ = read_show(str(path))
    assert loaded.parts  # parts survive
    assert loaded.effects == []  # effects do not
    assert loaded.timeline_data is None  # timeline does not
