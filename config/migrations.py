"""Ordered schema migrations for project files (YAML and .lms).

Every project save stamps ``schema_version: CURRENT_SCHEMA_VERSION`` at
the top level. A file without the key is version 0 (everything written
before the stamp existed). ``Configuration.load`` calls
:func:`migrate` on the RAW loaded dict, before ``expand_compact``, and
runs every step from the file's version up to CURRENT, in order.

Rule for adding a step (keep it boring):

1. Append ONE ``MigrationStep(from_version=N, name=..., apply=...)``
   to ``STEPS`` where N is ``CURRENT_SCHEMA_VERSION``, then bump
   ``CURRENT_SCHEMA_VERSION`` to N + 1 (one step per version). Never
   reorder, renumber or delete a released step: files in the wild are
   stamped with it.
2. A step takes the raw file dict (compact format: ``block_defs`` /
   ``light_block_defs`` tables, ``light_blocks`` as refs) and mutates it
   in place. It must be idempotent and must not touch Qt or the
   fixture library.
3. Ship a test in ``tests/unit/test_config_migrations.py`` that feeds
   a dict at version N through the step.

Repairs that must run on EVERY load regardless of the stamp stay at
the object level, not here: the orientation correction
(``utils/orientation.migrate_orientation_angles`` in
``Configuration.load``) also repairs hand-edited values, the legacy
``Fixture(group=...)`` constructor keyword is used by the CSV/JSON
fixture import (``utils/fixture_io.py``), and ``LightBlock.from_dict``'s
legacy ``duration`` is shared with the effect clipboard and the
standalone song YAML import (``utils/show_io.py``). Morph plans and riff/scene
library files carry their own format/version fields and are out of
scope.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

SCHEMA_VERSION_KEY = "schema_version"


@dataclass(frozen=True)
class MigrationStep:
    from_version: int          # migrates from_version -> from_version + 1
    name: str
    apply: Callable[[Dict], None]


def _songs_key(data: Dict) -> None:
    """Configs written before the setlist rework store the songs under a
    top-level ``shows:`` key. The per-file block tables are untouched by
    the rename, so ``expand_compact`` works on the migrated key."""
    if 'songs' not in data and 'shows' in data:
        data['songs'] = data.pop('shows')


def _fixture_group_list(data: Dict) -> None:
    """Pre-multi-group fixtures carry one ``group:`` string. Same rule as
    ``Fixture.__post_init__``: a null ``groups`` is empty, a non-empty
    ``groups`` wins, ``""`` stays ungrouped."""
    for f_data in data.get('fixtures') or []:
        if not isinstance(f_data, dict) or 'group' not in f_data:
            continue
        group = f_data.pop('group')
        groups = f_data.get('groups')
        if groups is None:
            groups = []
        if not groups and group:
            groups = [group]
        f_data['groups'] = groups


def _drop_fixture_direction_rotation(data: Dict) -> None:
    """``direction`` and ``rotation`` predate yaw/pitch/roll and carry
    nothing the model reads any more."""
    for f_data in data.get('fixtures') or []:
        if isinstance(f_data, dict):
            f_data.pop('direction', None)
            f_data.pop('rotation', None)


def _v0_legacy_keys(data: Dict) -> None:
    """Version 0 -> 1: the raw-key renames every pre-versioning load
    already applied (``shows`` -> ``songs``, fixture ``group`` ->
    ``groups``, deprecated ``direction`` / ``rotation`` dropped)."""
    _songs_key(data)
    _fixture_group_list(data)
    _drop_fixture_direction_rotation(data)


STEPS: List[MigrationStep] = [
    MigrationStep(0, "v0_legacy_keys", _v0_legacy_keys),
]

CURRENT_SCHEMA_VERSION = 1


def read_version(data: Dict) -> Tuple[int, Optional[str]]:
    """The file's schema version and a warning for a bad stamp.

    Missing -> 0. A non-integer (or negative, or bool) value -> 0 with a
    warning, so a garbage stamp still gets every migration."""
    if SCHEMA_VERSION_KEY not in data:
        return 0, None
    raw = data[SCHEMA_VERSION_KEY]
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return 0, (f"Project file has an unreadable schema_version "
                   f"({raw!r}); loaded it as a pre-versioning file.")
    return raw, None


def steps_between(start: int, end: int) -> List[MigrationStep]:
    """The steps that bring a version ``start`` file to ``end``, in order."""
    return [step for step in STEPS if start <= step.from_version < end]


def migrate(data: Dict) -> Tuple[int, List[str]]:
    """Run the pending steps on ``data`` in place and drop the stamp.

    Returns ``(file_version, warnings)``. A file newer than this build
    runs no steps and loads best effort; it gets a warning."""
    version, problem = read_version(data)
    data.pop(SCHEMA_VERSION_KEY, None)
    warnings = [problem] if problem else []
    if version > CURRENT_SCHEMA_VERSION:
        warnings.append(
            f"Project file was written by a newer version of Lichtmaschine "
            f"(schema {version}, this build knows {CURRENT_SCHEMA_VERSION}); "
            f"loaded best effort, newer settings may be missing.")
        return version, warnings
    for step in steps_between(version, CURRENT_SCHEMA_VERSION):
        step.apply(data)
    return version, warnings
