"""Fixture list import/export (utils/fixture_io.py).

Contract under test:
- CSV round-trips patch + position with *effective* z/orientation (group
  defaults resolved), imported back as explicit per-fixture values.
- JSON round-trips everything exactly: modes, override flags, group
  metadata, with fixture definitions deduplicated by (manufacturer, model).
- resolve_modes_from_library swaps the synthesized single mode for the
  real .qxf mode list (custom_fixtures/ ships in-repo, so this runs
  against a real definition).
- apply_fixture_list handles replace vs append, name collisions, and
  group rebuild with property preservation/seeding.
"""

import pytest

from config.models import Configuration, Fixture, FixtureGroup, FixtureMode, Universe
from utils.fixture_io import (
    apply_fixture_list,
    read_fixture_list,
    read_fixture_list_csv,
    read_fixture_list_json,
    resolve_modes_from_library,
    write_fixture_list,
    write_fixture_list_csv,
    write_fixture_list_json,
)


def make_fixture(name, group="Front", universe=1, address=1, **kwargs):
    defaults = dict(
        manufacturer="TestMfr",
        model="TestModel",
        current_mode="Standard",
        available_modes=[
            FixtureMode(name="Standard", channels=10),
            FixtureMode(name="Extended", channels=24),
        ],
        type="MH",
        x=1.5, y=-2.0, z=0.0,
        mounting="hanging", yaw=0.0, pitch=0.0, roll=0.0,
    )
    defaults.update(kwargs)
    return Fixture(universe=universe, address=address, name=name, group=group,
                   **defaults)


@pytest.fixture
def rig_config():
    """Two grouped fixtures (one on group defaults) + one ungrouped."""
    f1 = make_fixture("MH 1", address=1)                    # uses group defaults
    f2 = make_fixture("MH 2", address=11,
                      z=1.2, yaw=45.0, mounting="standing",
                      orientation_uses_group_default=False,
                      z_uses_group_default=False)
    f3 = make_fixture("Solo", group="", address=101)
    group = FixtureGroup(
        "Front", [f1, f2],
        color="#112233",
        default_mounting="hanging",
        default_yaw=10.0, default_pitch=-20.0, default_roll=0.0,
        default_z_height=4.5,
        lighting_role="key",
        export_intensity=200,
    )
    return Configuration(
        fixtures=[f1, f2, f3],
        groups={"Front": group},
        universes={1: Universe(id=1, name="Universe 1", output={})},
    )


class TestCsvRoundTrip:

    def test_effective_values_exported_and_reimported_explicit(self, rig_config, tmp_path):
        path = str(tmp_path / "rig.csv")
        write_fixture_list_csv(path, rig_config)
        fixtures = read_fixture_list_csv(path)

        assert [f.name for f in fixtures] == ["MH 1", "MH 2", "Solo"]

        # MH 1 was on group defaults: the CSV carries the resolved values
        # and the reimported fixture owns them explicitly.
        f1 = fixtures[0]
        assert f1.z == 4.5
        assert (f1.yaw, f1.pitch) == (10.0, -20.0)
        assert f1.orientation_uses_group_default is False
        assert f1.z_uses_group_default is False

        # MH 2 had explicit values: those come through untouched.
        f2 = fixtures[1]
        assert f2.z == 1.2
        assert f2.yaw == 45.0
        assert f2.mounting == "standing"

        # Patch + identity + synthesized mode from the channels column.
        assert (f2.universe, f2.address) == (1, 11)
        assert f2.current_mode == "Standard"
        assert f2.available_modes == [FixtureMode(name="Standard", channels=10)]
        assert f2.type == "MH"

    def test_manufacturer_model_kept_verbatim(self, rig_config, tmp_path):
        # QLC+ model names can carry trailing spaces; lookup matches exactly.
        rig_config.fixtures[0].model = "Retro Flat Par 18x12W RGBW "
        path = str(tmp_path / "rig.csv")
        write_fixture_list_csv(path, rig_config)
        fixtures = read_fixture_list_csv(path)
        assert fixtures[0].model == "Retro Flat Par 18x12W RGBW "

    def test_minimal_hand_written_sheet(self, tmp_path):
        path = tmp_path / "venue.csv"
        path.write_text(
            "manufacturer,model,universe,address\n"
            "Stairville,LED Par 64,1,1\n"
        )
        fixtures = read_fixture_list_csv(str(path))
        f = fixtures[0]
        assert f.name == "LED Par 64"
        assert f.available_modes == [FixtureMode(name="Default", channels=1)]
        assert f.type == "PAR"
        assert f.group == ""

    def test_bad_row_reports_file_and_line(self, tmp_path):
        path = tmp_path / "venue.csv"
        path.write_text(
            "manufacturer,model,universe,address\n"
            "Stairville,LED Par 64,not-a-number,1\n"
        )
        with pytest.raises(ValueError, match="venue.csv, line 2"):
            read_fixture_list_csv(str(path))


class TestJsonRoundTrip:

    def test_full_fidelity(self, rig_config, tmp_path):
        path = str(tmp_path / "rig.json")
        write_fixture_list_json(path, rig_config)
        fixtures, group_props = read_fixture_list_json(path)

        for original, restored in zip(rig_config.fixtures, fixtures):
            assert restored == original

        assert group_props["Front"] == {
            'color': "#112233",
            'default_mounting': "hanging",
            'default_yaw': 10.0,
            'default_pitch': -20.0,
            'default_roll': 0.0,
            'default_z_height': 4.5,
            'lighting_role': "key",
            'export_intensity': 200,
        }

    def test_definitions_deduplicated(self, rig_config, tmp_path):
        import json
        path = str(tmp_path / "rig.json")
        write_fixture_list_json(path, rig_config)
        with open(path) as f:
            data = json.load(f)
        # Three fixtures, one (manufacturer, model): one definition.
        assert len(data['definitions']) == 1
        assert len(data['fixtures']) == 3
        assert data['definitions'][0]['modes'] == [
            {'name': 'Standard', 'channels': 10},
            {'name': 'Extended', 'channels': 24},
        ]

    def test_rejects_foreign_json(self, tmp_path):
        path = tmp_path / "other.json"
        path.write_text('{"something": "else"}')
        with pytest.raises(ValueError, match="Not a fixture list"):
            read_fixture_list_json(str(path))


class TestFormatDispatch:

    def test_round_trip_via_entry_points(self, rig_config, tmp_path):
        for ext in ("csv", "json"):
            path = str(tmp_path / f"rig.{ext}")
            assert write_fixture_list(path, rig_config) == ext
            fixtures, group_props, fmt = read_fixture_list(path)
            assert fmt == ext
            assert len(fixtures) == 3
            assert bool(group_props) == (ext == "json")

    def test_unsupported_extension(self, rig_config, tmp_path):
        with pytest.raises(ValueError, match="Unsupported extension"):
            write_fixture_list(str(tmp_path / "rig.xlsx"), rig_config)


class TestResolveModes:

    def test_resolves_from_custom_fixtures(self):
        # Ships in-repo: custom_fixtures/Stairville-Retro-Flat-Par-....qxf
        f = make_fixture(
            "Par 1",
            manufacturer="Stairville",
            model="Retro Flat Par 18x12W RGBW ",
            current_mode="8 Channel",
            available_modes=[FixtureMode(name="8 Channel", channels=8)],
        )
        warnings = resolve_modes_from_library([f])
        assert warnings == []
        assert [(m.name, m.channels) for m in f.available_modes] == [
            ("4 Channel", 4), ("6 Channel", 6), ("8 Channel", 8),
        ]
        assert f.current_mode == "8 Channel"

    def test_unknown_model_keeps_synthesized_mode_and_warns(self):
        f = make_fixture(
            "Mystery",
            manufacturer="NoSuchMfr",
            model="NoSuchModel",
            current_mode="Default",
            available_modes=[FixtureMode(name="Default", channels=7)],
        )
        warnings = resolve_modes_from_library([f])
        assert len(warnings) == 1
        assert "NoSuchMfr NoSuchModel" in warnings[0]
        assert f.available_modes == [FixtureMode(name="Default", channels=7)]

    def test_unknown_mode_falls_back_to_first_real_mode(self):
        f = make_fixture(
            "Par 1",
            manufacturer="Stairville",
            model="Retro Flat Par 18x12W RGBW ",
            current_mode="99 Channel",
            available_modes=[FixtureMode(name="99 Channel", channels=99)],
        )
        warnings = resolve_modes_from_library([f])
        assert f.current_mode == "4 Channel"
        assert any("99 Channel" in w for w in warnings)


class TestApplyFixtureList:

    def test_replace_swaps_rig_and_seeds_groups(self, rig_config):
        imported = [make_fixture("New 1", group="Rear", universe=2)]
        apply_fixture_list(
            rig_config, imported,
            group_props={"Rear": {'color': '#aabbcc', 'lighting_role': 'wash'}},
            replace=True,
        )
        assert [f.name for f in rig_config.fixtures] == ["New 1"]
        assert set(rig_config.groups) == {"Rear"}
        rear = rig_config.groups["Rear"]
        assert rear.color == '#aabbcc'
        assert rear.lighting_role == 'wash'
        assert rear.fixtures == imported
        assert 2 in rig_config.universes  # auto-created

    def test_append_renames_collisions_and_keeps_existing_group_props(self, rig_config):
        imported = [
            make_fixture("MH 1", group="Front", address=101),   # name clash
            make_fixture("MH 1", group="Front", address=111),   # clashes twice
        ]
        apply_fixture_list(rig_config, imported,
                           group_props={"Front": {'color': '#ff0000'}},
                           replace=False)
        names = [f.name for f in rig_config.fixtures]
        assert names == ["MH 1", "MH 2", "Solo", "MH 1 (2)", "MH 1 (3)"]
        # Existing group keeps its own properties; imported props only seed
        # groups that are new to the config.
        front = rig_config.groups["Front"]
        assert front.color == "#112233"
        assert front.lighting_role == "key"
        assert len(front.fixtures) == 4

    def test_append_to_empty_config(self):
        config = Configuration()
        apply_fixture_list(config, [make_fixture("A", group="G")], replace=False)
        assert len(config.fixtures) == 1
        assert set(config.groups) == {"G"}
