"""SceneLibrary + Scene model tests.

A Scene is a whole-rig look spanning multiple fixture groups (parallel to
a Riff, but selection-agnostic). These pin the library's public shape
(mirroring RiffLibrary) and the Scene JSON round-trip. No engine resolve
is exercised - the model is a data shell for now.
"""

from __future__ import annotations

import os

from config.models import Scene
from scenes.scene_library import SceneLibrary


def _scene(name, category="general", color="", groups=None):
    return Scene(name=name, category=category, color=color,
                 groups=groups or [])


class TestSceneModel:
    def test_defaults(self):
        s = Scene(name="Blackout")
        assert s.category == "general"
        assert s.description == ""
        assert s.color == ""
        assert s.groups == []
        assert s.tags == []
        assert s.author == ""
        assert s.version == "1.0"

    def test_to_from_dict_round_trip(self):
        s = Scene(name="Warm Wash", category="looks",
                  description="A warm full-rig wash",
                  color="#F0562E", groups=["Front Pars", "Rear Wash"],
                  tags=["warm", "wash"], author="varghele", version="1.2")
        data = s.to_dict()
        back = Scene.from_dict(data)
        assert back == s

    def test_from_dict_tolerates_missing_keys(self):
        s = Scene.from_dict({"name": "Bare"})
        assert s.name == "Bare"
        assert s.groups == []
        assert s.color == ""


class TestSceneLibrary:
    def test_missing_directory_is_empty_no_crash(self, tmp_path):
        missing = os.path.join(str(tmp_path), "does_not_exist")
        lib = SceneLibrary(scenes_directory=missing)
        assert lib.scene_count() == 0
        assert lib.get_all_scenes() == []
        assert len(lib) == 0

    def test_add_get_and_has(self, tmp_path):
        lib = SceneLibrary(scenes_directory=str(tmp_path))
        s = _scene("Warm Wash", category="looks", color="#F0562E")
        lib.add_scene(s, category="looks")
        assert lib.has_scene("looks/Warm Wash")
        assert "looks/Warm Wash" in lib
        got = lib.get_scene("looks/Warm Wash")
        assert got is s
        assert got.category == "looks"
        assert lib.get_scene("looks/Nope") is None

    def test_scene_count(self, tmp_path):
        lib = SceneLibrary(scenes_directory=str(tmp_path))
        assert lib.scene_count() == 0
        lib.add_scene(_scene("A"))
        lib.add_scene(_scene("B"))
        assert lib.scene_count() == 2

    def test_get_all_scenes_sorted_by_category_then_name(self, tmp_path):
        lib = SceneLibrary(scenes_directory=str(tmp_path))
        lib.add_scene(_scene("Zebra", category="looks"), category="looks")
        lib.add_scene(_scene("Alpha", category="looks"), category="looks")
        lib.add_scene(_scene("Gamma", category="ballads"),
                      category="ballads")
        names = [(s.category, s.name) for s in lib.get_all_scenes()]
        assert names == [
            ("ballads", "Gamma"),
            ("looks", "Alpha"),
            ("looks", "Zebra"),
        ]

    def test_loads_scenes_from_disk(self, tmp_path):
        import json
        category_dir = tmp_path / "looks"
        category_dir.mkdir()
        scene = _scene("Warm Wash", category="looks", color="#F0562E",
                       groups=["Front Pars"])
        (category_dir / "warm.json").write_text(
            json.dumps(scene.to_dict()), encoding="utf-8")
        lib = SceneLibrary(scenes_directory=str(tmp_path))
        assert lib.scene_count() == 1
        got = lib.get_scene("looks/Warm Wash")
        assert got is not None
        assert got.color == "#F0562E"
        assert got.groups == ["Front Pars"]
