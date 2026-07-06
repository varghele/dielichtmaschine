# tests/unit/test_gdtf_persistence.py
"""Phase 2 of docs/gdtf-integration-plan.md: persistence and QLC+ interop.

- Fixture provenance fields round-trip through config YAML; pre-GDTF
  configs (no such fields) load unchanged with the qxf default.
- The .qxw exporter writes a companion .qxf next to the workspace for
  GDTF fixtures QLC+ doesn't know, and skips fixtures that have a real
  same-identity .qxf in the library.
- Fixture-list import resolution stamps provenance from the library.

Reuses the synthetic GDTF fixtures from test_gdtf_loader (self-authored;
GDTF Share files cannot be committed).
"""
import os

import pytest
import yaml

from config.models import Configuration, Fixture, FixtureGroup, FixtureMode
from utils import fixture_library as fl
from utils.fixture_library import clear_library_cache, get_definition, parse_fixture_file

from tests.unit.test_gdtf_loader import (
    MATCHING_QXF,
    SPOT_DESCRIPTION,
    _write_gdtf,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture(autouse=True)
def _fresh_caches():
    clear_library_cache()
    yield
    clear_library_cache()
    from utils import fixture_utils
    fixture_utils.clear_fixture_definitions_cache()


@pytest.fixture()
def gdtf_dir(tmp_path, monkeypatch):
    d = tmp_path / "gdtf"
    d.mkdir()
    _write_gdtf(d, "Testlight@Test_Spot_60.gdtf", SPOT_DESCRIPTION)
    monkeypatch.setattr(fl, "fixture_search_dirs", lambda: [(str(d), "gdtf")])
    return d


def _spot_fixture():
    return Fixture(
        universe=1, address=1,
        manufacturer="Testlight", model="Test Spot 60",
        name="Spot 1", group="Movers",
        current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=13)],
        type="MH",
        definition_source="gdtf",
        gdtf_fixture_type_id="11111111-2222-3333-4444-555555555555",
    )


def _config_with(fixture):
    config = Configuration()
    config.fixtures.append(fixture)
    config.groups["Movers"] = FixtureGroup("Movers", [fixture])
    config.ensure_universes_for_fixtures()
    return config


# ---------------------------------------------------------------------------
# YAML persistence
# ---------------------------------------------------------------------------

def test_provenance_round_trips_through_yaml(tmp_path):
    config = _config_with(_spot_fixture())
    path = tmp_path / "config.yaml"
    config.save(str(path))

    loaded = Configuration.load(str(path))
    fixture = loaded.fixtures[0]
    assert fixture.definition_source == "gdtf"
    assert fixture.gdtf_fixture_type_id == "11111111-2222-3333-4444-555555555555"


def test_pre_gdtf_config_defaults_to_qxf(tmp_path):
    """A config saved before the schema bump has no provenance fields."""
    config = _config_with(_spot_fixture())
    path = tmp_path / "config.yaml"
    config.save(str(path))

    # Strip the new fields from the YAML, as an old config would look.
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    def _strip(node):
        if isinstance(node, dict):
            node.pop("definition_source", None)
            node.pop("gdtf_fixture_type_id", None)
            for value in node.values():
                _strip(value)
        elif isinstance(node, list):
            for item in node:
                _strip(item)

    _strip(data)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f)

    loaded = Configuration.load(str(path))
    fixture = loaded.fixtures[0]
    assert fixture.definition_source == "qxf"
    assert fixture.gdtf_fixture_type_id is None


# ---------------------------------------------------------------------------
# Companion .qxf generation on .qxw export
# ---------------------------------------------------------------------------

def _export(config):
    from utils.create_workspace import create_qlc_workspace
    workspace_out = os.path.join(REPO_ROOT, "workspace.qxw")
    companion_dir = os.path.join(REPO_ROOT, "gdtf_companion_fixtures")
    try:
        create_qlc_workspace(config, None)
        companions = sorted(os.listdir(companion_dir)) \
            if os.path.isdir(companion_dir) else []
        contents = {}
        for fname in companions:
            with open(os.path.join(companion_dir, fname), encoding="utf-8") as f:
                contents[fname] = f.read()
    finally:
        if os.path.exists(workspace_out):
            os.remove(workspace_out)
        if os.path.isdir(companion_dir):
            for fname in os.listdir(companion_dir):
                os.remove(os.path.join(companion_dir, fname))
            os.rmdir(companion_dir)
    return companions, contents


def test_companion_qxf_written_for_unknown_gdtf_fixture(gdtf_dir, tmp_path):
    from utils import fixture_utils
    fixture_utils.clear_fixture_definitions_cache()

    config = _config_with(_spot_fixture())
    companions, contents = _export(config)

    assert companions == ["Testlight-Test-Spot-60.qxf"]
    text = contents[companions[0]]
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>\n'
                           '<!DOCTYPE FixtureDefinition>')

    # The companion parses as a normal .qxf and is semantically identical
    # to the GDTF definition it was generated from.
    companion_path = tmp_path / "Testlight-Test-Spot-60.qxf"
    companion_path.write_text(text, encoding="utf-8")
    reparsed = parse_fixture_file(str(companion_path))
    original = get_definition("Testlight", "Test Spot 60")
    assert reparsed.source == "qxf"
    assert reparsed.to_legacy_dict() == original.to_legacy_dict()
    assert reparsed.legacy_type == original.legacy_type
    assert reparsed.layout == original.layout


def test_no_companion_when_qxf_twin_exists(tmp_path, monkeypatch, capsys):
    gdtf_d = tmp_path / "gdtf"
    qxf_d = tmp_path / "qxf"
    gdtf_d.mkdir()
    qxf_d.mkdir()
    _write_gdtf(gdtf_d, "spot.gdtf", SPOT_DESCRIPTION)
    (qxf_d / "Testlight-Test-Spot-60.qxf").write_text(MATCHING_QXF, encoding="utf-8")
    monkeypatch.setattr(fl, "fixture_search_dirs",
                        lambda: [(str(gdtf_d), "gdtf"), (str(qxf_d), "bundled")])
    from utils import fixture_utils
    fixture_utils.clear_fixture_definitions_cache()

    config = _config_with(_spot_fixture())
    companions, _contents = _export(config)
    assert companions == []
    assert "no companion needed" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Fixture-list import resolution stamps provenance
# ---------------------------------------------------------------------------

def test_config_load_reconciles_shadowed_mode_names(gdtf_dir, tmp_path, capsys):
    """A config authored against .qxf mode names keeps working when a
    GDTF shadows the identity: the closest-footprint mode is adopted."""
    fixture = _spot_fixture()
    fixture.current_mode = "14 Channel"  # qxf-style name, 13ch footprint
    fixture.available_modes = [FixtureMode(name="14 Channel", channels=13)]
    config = _config_with(fixture)
    path = tmp_path / "config.yaml"
    config.save(str(path))

    loaded = Configuration.load(str(path))
    f = loaded.fixtures[0]
    assert f.current_mode == "Standard"          # the GDTF mode, 13 ch
    assert f.available_modes[0].channels == 13
    assert f.definition_source == "gdtf"
    assert "not in the resolved gdtf definition" in capsys.readouterr().out


def test_config_load_leaves_matching_modes_alone(gdtf_dir, tmp_path):
    config = _config_with(_spot_fixture())  # current_mode already "Standard"
    path = tmp_path / "config.yaml"
    config.save(str(path))
    loaded = Configuration.load(str(path))
    assert loaded.fixtures[0].current_mode == "Standard"


def test_json_rig_round_trips_provenance(tmp_path):
    from utils.fixture_io import read_fixture_list_json, write_fixture_list_json

    config = _config_with(_spot_fixture())
    path = tmp_path / "rig.json"
    write_fixture_list_json(str(path), config)
    fixtures, _groups, _layers = read_fixture_list_json(str(path))
    assert fixtures[0].definition_source == "gdtf"
    assert fixtures[0].gdtf_fixture_type_id == "11111111-2222-3333-4444-555555555555"


def test_resolve_modes_stamps_gdtf_provenance(gdtf_dir):
    from utils import fixture_utils
    fixture_utils.clear_fixture_definitions_cache()
    from utils.fixture_io import resolve_modes_from_library

    fixture = _spot_fixture()
    # Simulate a CSV import: synthesized single mode, unknown provenance.
    fixture.available_modes = [FixtureMode(name="Standard", channels=1)]
    fixture.definition_source = "qxf"
    fixture.gdtf_fixture_type_id = None

    warnings = resolve_modes_from_library([fixture])
    assert warnings == []
    assert fixture.available_modes[0].channels == 13
    assert fixture.definition_source == "gdtf"
    assert fixture.gdtf_fixture_type_id == "11111111-2222-3333-4444-555555555555"
