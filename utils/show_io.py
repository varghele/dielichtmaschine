"""Explicit show structure import/export, surfaced via File menu actions.

In v1.0 the show data model has a single source of truth: ``config.yaml``.
CSV files on disk are an interchange format, not a backing store. This
module is the file-format layer behind the explicit
``File -> Import / Export Show Structure`` actions.

Two formats are supported:

- **CSV** (.csv): the song-structure metadata only, the same 6-column
  layout the old auto-CSV-save used. Compatible with existing show CSVs.
  Columns: ``showpart, signature, bpm, num_bars, transition, color``.
- **YAML** (.yaml): the full show including parts, effects, timeline data
  (lanes, blocks, audio_file_path), and trigger metadata. Round-trips a
  show completely independently of the parent config.

CSV detection is by file extension. YAML import uses ``Song.from_dict`` so
new fields flow through automatically as the data model grows.
"""
from __future__ import annotations
import csv
import os
from typing import List, Tuple

import yaml

from config.models import Song, ShowPart


CSV_FIELDNAMES = ['showpart', 'signature', 'bpm', 'num_bars', 'transition', 'color']


def detect_format(path: str) -> str:
    """Return 'csv' or 'yaml' based on the file extension. Raises ValueError
    for anything else."""
    ext = os.path.splitext(path)[1].lower()
    if ext == '.csv':
        return 'csv'
    if ext in ('.yaml', '.yml'):
        return 'yaml'
    raise ValueError(f"Unsupported extension: {ext!r}. Use .csv or .yaml.")


def read_show_structure_csv(path: str) -> List[ShowPart]:
    """Read a 6-column structure CSV into a list of ShowPart objects."""
    parts: List[ShowPart] = []
    with open(path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            parts.append(ShowPart(
                name=row['showpart'],
                color=row['color'],
                signature=row['signature'],
                bpm=float(row['bpm']),
                num_bars=int(row['num_bars']),
                transition=row['transition'],
            ))
    return parts


def write_show_structure_csv(path: str, show: Song) -> None:
    """Write the parts of ``show`` to a 6-column structure CSV."""
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for part in show.parts:
            writer.writerow({
                'showpart': part.name,
                'signature': part.signature,
                'bpm': part.bpm,
                'num_bars': part.num_bars,
                'transition': part.transition,
                'color': part.color,
            })


def read_show_yaml(path: str) -> Song:
    """Read a standalone show YAML and reconstruct a Show.

    The file's top-level ``name:`` field is required; it becomes the show
    name. Raises ValueError if missing.
    """
    with open(path, 'r') as f:
        data = yaml.safe_load(f) or {}
    name = data.get('name')
    if not name:
        raise ValueError(
            f"YAML show file is missing a 'name:' field at the top level: {path}"
        )
    return Song.from_dict(name, data)


def write_show_yaml(path: str, show: Song) -> None:
    """Write a Show as a standalone YAML file. Includes the name field so
    the file can be read back without external context."""
    data = {'name': show.name, **show.to_dict()}
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False)


def read_show(path: str) -> Tuple[Song, str]:
    """Format-agnostic entry point.

    Returns ``(show, format)`` where ``format`` is ``'csv'`` or ``'yaml'``.
    For CSV input, the show's name is derived from the file basename and
    only ``parts`` are populated. For YAML input, the full Show is read.
    """
    fmt = detect_format(path)
    if fmt == 'csv':
        parts = read_show_structure_csv(path)
        name = os.path.splitext(os.path.basename(path))[0]
        return Song(name=name, parts=parts), 'csv'
    return read_show_yaml(path), 'yaml'


def write_show(path: str, show: Song) -> str:
    """Format-agnostic entry point. Returns the chosen format string."""
    fmt = detect_format(path)
    if fmt == 'csv':
        write_show_structure_csv(path, show)
    else:
        write_show_yaml(path, show)
    return fmt
