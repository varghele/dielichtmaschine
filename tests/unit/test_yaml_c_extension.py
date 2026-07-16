# tests/unit/test_yaml_c_extension.py
"""The libyaml fast path (2026-07-16 performance pass): when PyYAML
carries the C extension, Configuration.save/load use CDumper /
CSafeLoader - the pure-python path made autosave a near-second UI
freeze on real projects. The C emitter's output must stay
TEXT-IDENTICAL to the pure-python Dumper's, so saved files never
change shape with the environment."""

import yaml

import pytest

from config.models import (_YAML_DUMPER, _YAML_SAFE_LOADER,
                           Configuration, Fixture, FixtureMode,
                           FixtureGroup, Universe)


def _sample_config():
    fixtures = [Fixture(universe=1, address=1 + i, manufacturer="M",
                        model="X", current_mode="Std",
                        available_modes=[FixtureMode(name="Std",
                                                     channels=3)],
                        name=f"f{i}", group="G", x=i * 0.5, y=-1.25)
                for i in range(4)]
    cfg = Configuration(
        fixtures=fixtures,
        groups={"G": FixtureGroup("G", fixtures)},
        universes={1: Universe(id=1, name="U1", output={})})
    cfg.songs = {}
    return cfg


class TestFastYaml:

    def test_c_classes_selected_when_libyaml_present(self):
        if not yaml.__with_libyaml__:
            pytest.skip("PyYAML built without libyaml")
        assert _YAML_DUMPER is yaml.CDumper
        assert _YAML_SAFE_LOADER is yaml.CSafeLoader

    def test_fallback_classes_are_valid_either_way(self):
        assert _YAML_DUMPER in (getattr(yaml, "CDumper", None),
                                yaml.Dumper)
        assert _YAML_SAFE_LOADER in (getattr(yaml, "CSafeLoader", None),
                                     yaml.SafeLoader)

    def test_c_dump_text_identical_to_python_dump(self, tmp_path):
        if not yaml.__with_libyaml__:
            pytest.skip("PyYAML built without libyaml")
        cfg = _sample_config()
        path = tmp_path / "c.yaml"
        cfg.save(str(path))
        c_text = path.read_text()

        # The same save through the pure-python Dumper.
        import config.models as models
        original = models._YAML_DUMPER
        models._YAML_DUMPER = yaml.Dumper
        try:
            path_py = tmp_path / "py.yaml"
            cfg.save(str(path_py))
        finally:
            models._YAML_DUMPER = original
        assert c_text == path_py.read_text()

    def test_save_load_round_trip(self, tmp_path):
        cfg = _sample_config()
        path = str(tmp_path / "roundtrip.lms")
        cfg.save(path)
        back = Configuration.load(path)
        assert len(back.fixtures) == 4
        assert back.fixtures[1].x == 0.5
        assert back.fixtures[0].y == -1.25
        assert "G" in back.groups
