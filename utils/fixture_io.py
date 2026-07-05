"""Fixture list (rig) import/export, surfaced via File menu actions.

Round-trips the rig — patch, grouping, position, orientation — without the
rest of the project, so a rig can be sent to another QLC+ user, pre-filled
from a venue's spec sheet, or version-controlled on its own.

Two formats, mirroring utils/show_io.py's CSV/YAML split:

- **CSV** (.csv): one row per fixture, spec-sheet friendly. Columns:
  ``name, manufacturer, model, type, mode, channels, universe, address,
  group, x, y, z, mounting, yaw, pitch, roll``. Z and orientation are the
  *effective* values (group defaults resolved), so the sheet reads as the
  physical truth; on import they become explicit per-fixture values.
  Only ``manufacturer, model, universe, address`` are required — a
  hand-written venue sheet with just those columns imports fine.
- **JSON** (.json): full fidelity. Fixture definitions (manufacturer,
  model, type, modes) are deduplicated into a ``definitions`` list that
  fixtures reference by index, group metadata (color, defaults, lighting
  role) is preserved, and the group-default override flags survive the
  round-trip exactly.

Neither read function touches the QLC+ fixture library; CSV rows fall back
to a single synthesized mode. Call ``resolve_modes_from_library`` afterwards
to swap those for the real mode lists where a .qxf can be found.
"""
from __future__ import annotations
import csv
import json
import os
from typing import Dict, List, Optional, Tuple

from config.models import Fixture, FixtureGroup, FixtureMode, StageLayer
from utils.dmx_conflicts import fixture_channel_count

CSV_FIELDNAMES = [
    'name', 'manufacturer', 'model', 'type', 'mode', 'channels',
    'universe', 'address', 'group', 'layer', 'x', 'y', 'z',
    'mounting', 'yaw', 'pitch', 'roll',
]

JSON_FORMAT_NAME = 'qlcshowcreator-fixture-list'
JSON_FORMAT_VERSION = 1

GROUP_PROP_KEYS = [
    'color', 'default_mounting', 'default_yaw', 'default_pitch',
    'default_roll', 'default_z_height', 'lighting_role', 'export_intensity',
]


def detect_format(path: str) -> str:
    """Return 'csv' or 'json' based on the file extension. Raises ValueError
    for anything else."""
    ext = os.path.splitext(path)[1].lower()
    if ext == '.csv':
        return 'csv'
    if ext == '.json':
        return 'json'
    raise ValueError(f"Unsupported extension: {ext!r}. Use .csv or .json.")


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def write_fixture_list_csv(path: str, config) -> None:
    """Write config.fixtures as a flat CSV rig sheet.

    Z and orientation columns carry the effective values (group defaults
    resolved) — the sheet describes where fixtures physically are, not the
    internal override bookkeeping.
    """
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for fixture in config.fixtures:
            group = config.groups.get(fixture.group) if fixture.group else None
            mounting, yaw, pitch, roll = fixture.get_effective_orientation(group)
            writer.writerow({
                'name': fixture.name,
                'manufacturer': fixture.manufacturer,
                'model': fixture.model,
                'type': fixture.type,
                'mode': fixture.current_mode,
                'channels': fixture_channel_count(fixture),
                'universe': fixture.universe,
                'address': fixture.address,
                'group': fixture.group,
                'layer': fixture.layer,
                'x': fixture.x,
                'y': fixture.y,
                'z': fixture.get_effective_z(group),
                'mounting': mounting,
                'yaw': yaw,
                'pitch': pitch,
                'roll': roll,
            })


def read_fixture_list_csv(path: str) -> List[Fixture]:
    """Read a rig CSV into Fixture objects.

    Tolerates hand-written sheets: only manufacturer, model, universe and
    address are required per row. Each fixture gets a single synthesized
    mode from the ``mode``/``channels`` columns (defaults: 'Default', 1
    channel); resolve_modes_from_library upgrades that when possible.
    """
    fixtures: List[Fixture] = []
    with open(path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        for line, row in enumerate(reader, start=2):
            try:
                # Keep manufacturer/model verbatim — QLC+ model names can
                # carry trailing spaces and library lookup matches exactly.
                manufacturer = row.get('manufacturer') or ''
                model = row.get('model') or ''
                if not manufacturer.strip() or not model.strip():
                    raise ValueError("manufacturer and model are required")
                mode = (row.get('mode') or '').strip() or 'Default'
                channels = int(row.get('channels') or 1)
                fixtures.append(Fixture(
                    universe=int(row['universe']),
                    address=int(row['address']),
                    manufacturer=manufacturer,
                    model=model,
                    name=(row.get('name') or '').strip() or model,
                    group=(row.get('group') or '').strip(),
                    layer=(row.get('layer') or '').strip(),
                    current_mode=mode,
                    available_modes=[FixtureMode(name=mode, channels=channels)],
                    type=(row.get('type') or '').strip() or 'PAR',
                    x=float(row.get('x') or 0.0),
                    y=float(row.get('y') or 0.0),
                    z=float(row.get('z') or 0.0),
                    mounting=(row.get('mounting') or '').strip() or 'hanging',
                    yaw=float(row.get('yaw') or 0.0),
                    pitch=float(row.get('pitch') or 0.0),
                    roll=float(row.get('roll') or 0.0),
                    # CSV carries resolved values, so they are this
                    # fixture's own from here on.
                    orientation_uses_group_default=False,
                    z_uses_group_default=False,
                ))
            except (KeyError, ValueError) as e:
                raise ValueError(f"{os.path.basename(path)}, line {line}: {e}") from e
    return fixtures


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

def write_fixture_list_json(path: str, config) -> None:
    """Write config.fixtures + group metadata as a self-contained JSON rig."""
    definitions: List[dict] = []
    def_index: Dict[Tuple[str, str], int] = {}

    fixture_dicts = []
    for fixture in config.fixtures:
        key = (fixture.manufacturer, fixture.model)
        if key not in def_index:
            def_index[key] = len(definitions)
            definitions.append({
                'manufacturer': fixture.manufacturer,
                'model': fixture.model,
                'type': fixture.type,
                'modes': [
                    {'name': m.name, 'channels': m.channels}
                    for m in fixture.available_modes
                ],
            })
        fixture_dicts.append({
            'name': fixture.name,
            'definition': def_index[key],
            'mode': fixture.current_mode,
            'universe': fixture.universe,
            'address': fixture.address,
            'group': fixture.group,
            'layer': fixture.layer,
            'x': fixture.x,
            'y': fixture.y,
            'z': fixture.z,
            'mounting': fixture.mounting,
            'yaw': fixture.yaw,
            'pitch': fixture.pitch,
            'roll': fixture.roll,
            'orientation_uses_group_default': fixture.orientation_uses_group_default,
            'z_uses_group_default': fixture.z_uses_group_default,
        })

    groups = {
        name: {key: getattr(group, key) for key in GROUP_PROP_KEYS}
        for name, group in config.groups.items()
    }

    data = {
        'format': JSON_FORMAT_NAME,
        'version': JSON_FORMAT_VERSION,
        'definitions': definitions,
        'groups': groups,
        'layers': [
            {'name': l.name, 'z_height': l.z_height, 'visible': l.visible}
            for l in getattr(config, 'stage_layers', [])
        ],
        'fixtures': fixture_dicts,
    }
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def read_fixture_list_json(path: str) -> Tuple[List[Fixture], Dict[str, dict], List[StageLayer]]:
    """Read a JSON rig back into (fixtures, group_props, layers).

    group_props maps group name -> the GROUP_PROP_KEYS subset that was
    exported; apply_fixture_list uses it to seed groups that don't exist
    in the target config yet. layers are the exported StageLayer planes.
    """
    with open(path, 'r') as f:
        data = json.load(f)
    if data.get('format') != JSON_FORMAT_NAME:
        raise ValueError(
            f"Not a fixture list file (format field is {data.get('format')!r})"
        )

    definitions = data.get('definitions', [])
    fixtures: List[Fixture] = []
    for i, fd in enumerate(data.get('fixtures', [])):
        try:
            definition = definitions[fd['definition']]
            fixtures.append(Fixture(
                universe=int(fd['universe']),
                address=int(fd['address']),
                manufacturer=definition['manufacturer'],
                model=definition['model'],
                name=fd['name'],
                group=fd.get('group', ''),
                layer=fd.get('layer', ''),
                current_mode=fd['mode'],
                available_modes=[
                    FixtureMode(name=m['name'], channels=int(m['channels']))
                    for m in definition['modes']
                ],
                type=definition.get('type', 'PAR'),
                x=float(fd.get('x', 0.0)),
                y=float(fd.get('y', 0.0)),
                z=float(fd.get('z', 0.0)),
                mounting=fd.get('mounting', 'hanging'),
                yaw=float(fd.get('yaw', 0.0)),
                pitch=float(fd.get('pitch', 0.0)),
                roll=float(fd.get('roll', 0.0)),
                orientation_uses_group_default=bool(
                    fd.get('orientation_uses_group_default', True)),
                z_uses_group_default=bool(fd.get('z_uses_group_default', True)),
            ))
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise ValueError(
                f"{os.path.basename(path)}, fixture #{i}: {e}"
            ) from e

    group_props = {
        name: {key: props[key] for key in GROUP_PROP_KEYS if key in props}
        for name, props in (data.get('groups') or {}).items()
    }
    layers = [
        StageLayer(
            name=ld['name'],
            z_height=float(ld.get('z_height', 3.0)),
            visible=bool(ld.get('visible', True)),
        )
        for ld in (data.get('layers') or [])
    ]
    return fixtures, group_props, layers


# ---------------------------------------------------------------------------
# Format-agnostic entry points
# ---------------------------------------------------------------------------

def read_fixture_list(path: str) -> Tuple[List[Fixture], Dict[str, dict], List[StageLayer], str]:
    """Returns (fixtures, group_props, layers, format). CSV has no group or
    layer metadata sections, so those are empty for it (fixtures still carry
    layer names; apply_fixture_list synthesizes missing layers)."""
    fmt = detect_format(path)
    if fmt == 'csv':
        return read_fixture_list_csv(path), {}, [], 'csv'
    fixtures, group_props, layers = read_fixture_list_json(path)
    return fixtures, group_props, layers, 'json'


def write_fixture_list(path: str, config) -> str:
    """Format-agnostic entry point. Returns the chosen format string."""
    fmt = detect_format(path)
    if fmt == 'csv':
        write_fixture_list_csv(path, config)
    else:
        write_fixture_list_json(path, config)
    return fmt


# ---------------------------------------------------------------------------
# Library resolution + applying to a config
# ---------------------------------------------------------------------------

def resolve_modes_from_library(fixtures: List[Fixture]) -> List[str]:
    """Replace synthesized single-mode lists with the real .qxf mode lists.

    Scans the QLC+ fixture library (and custom_fixtures/) for each distinct
    (manufacturer, model) via the shared definitions cache. Fixtures whose
    definition can't be found keep their synthesized mode. Returns a list of
    human-readable warnings for the unresolved models.
    """
    from utils.fixture_utils import get_cached_fixture_definitions

    needed = {(f.manufacturer, f.model) for f in fixtures}
    definitions = get_cached_fixture_definitions(needed)

    warnings = []
    for manufacturer, model in sorted(needed):
        key = f"{manufacturer}_{model}"
        alt_key = f"{manufacturer}_{model.replace(' ', '_')}"
        definition = definitions.get(key) or definitions.get(alt_key)
        if not definition or not definition.get('modes'):
            warnings.append(
                f"{manufacturer} {model}: no .qxf found in the fixture "
                f"library; keeping the mode from the imported file"
            )
            continue
        modes = [
            FixtureMode(name=m['name'], channels=len(m['channels']))
            for m in definition['modes']
        ]
        for fixture in fixtures:
            if (fixture.manufacturer, fixture.model) != (manufacturer, model):
                continue
            fixture.available_modes = [
                FixtureMode(name=m.name, channels=m.channels) for m in modes
            ]
            if not any(m.name == fixture.current_mode for m in modes):
                warnings.append(
                    f"{fixture.name}: mode {fixture.current_mode!r} not in "
                    f"the .qxf; falling back to {modes[0].name!r}"
                )
                fixture.current_mode = modes[0].name
    return warnings


def _unique_name(name: str, existing: set) -> str:
    if name not in existing:
        return name
    n = 2
    while f"{name} ({n})" in existing:
        n += 1
    return f"{name} ({n})"


def apply_fixture_list(config, fixtures: List[Fixture],
                       group_props: Optional[Dict[str, dict]] = None,
                       layers: Optional[List[StageLayer]] = None,
                       replace: bool = False) -> None:
    """Apply an imported fixture list to a Configuration.

    replace=True swaps the whole rig; replace=False appends, renaming
    imported fixtures whose names collide ("Name (2)"). Groups are rebuilt
    from fixture membership; existing groups keep their properties, groups
    new to the config are seeded from group_props (JSON) or defaults (CSV).
    Stage layers merge by name (existing layers win); a fixture referencing
    a layer nobody defines gets one synthesized at its own height.
    """
    if replace:
        config.fixtures = []
        config.groups = {}
        config.stage_layers = []

    existing_names = {f.name for f in config.fixtures}
    for fixture in fixtures:
        fixture.name = _unique_name(fixture.name, existing_names)
        existing_names.add(fixture.name)
        config.fixtures.append(fixture)

    existing_layers = {l.name for l in config.stage_layers}
    for layer in (layers or []):
        if layer.name not in existing_layers:
            config.stage_layers.append(layer)
            existing_layers.add(layer.name)
    for fixture in fixtures:
        if fixture.layer and fixture.layer not in existing_layers:
            config.stage_layers.append(
                StageLayer(name=fixture.layer, z_height=fixture.z)
            )
            existing_layers.add(fixture.layer)

    # Rebuild group membership, preserving props of groups already present.
    old_groups = config.groups
    config.groups = {}
    for fixture in config.fixtures:
        if not fixture.group:
            continue
        if fixture.group not in config.groups:
            if fixture.group in old_groups:
                group = old_groups[fixture.group]
                group.fixtures = []
            else:
                group = FixtureGroup(fixture.group, [])
                for key, value in (group_props or {}).get(fixture.group, {}).items():
                    setattr(group, key, value)
            config.groups[fixture.group] = group
        config.groups[fixture.group].fixtures.append(fixture)

    config.ensure_universes_for_fixtures()
