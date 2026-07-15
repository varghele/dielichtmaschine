"""Cross-config show import: pull selected shows from another config.

The "get last year's set into this venue's config" feature. Works on the
object model (Configuration.load / Song.to_dict round-trip), never on raw
YAML — v1.0's compact serializer keeps block templates in per-file
top-level tables (block_defs / light_block_defs), so copying raw show
dicts between files would re-point template refs into the wrong table.
That is why the old root-level merge_configs.py script was retired in
favor of this module.

Semantics:
- Shows are deep-copied via their dict round-trip, so the source config
  stays untouched.
- Name conflicts resolve per the caller's choice: rename ("Name (2)"),
  overwrite, or skip.
- Referenced fixture groups that don't exist in the target config are
  reported, not fixed — group retargeting is the v1.5b morphing work.
  The show still imports; lanes targeting missing groups stay dormant
  until the user re-points them.
- Audio: the show's audio file (basename, resolved against the source
  config's audiofiles/ bundle, or a legacy absolute path) is copied into
  the target's bundle and the show keeps referencing the basename.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from typing import List, Optional

from config.models import Configuration, Song


def referenced_groups(show: Song) -> List[str]:
    """Every fixture-group name the show targets (timeline lanes plus the
    legacy effects table), sorted, without duplicates."""
    names = set()
    if show.timeline_data:
        for lane in show.timeline_data.lanes:
            names.update(t for t in lane.fixture_targets if t)
    for effect in show.effects:
        if effect.fixture_group:
            names.add(effect.fixture_group)
    return sorted(names)


@dataclass
class ShowImportCandidate:
    """One show of the source config, summarized for the picker dialog."""
    name: str
    num_parts: int
    groups: List[str]
    missing_groups: List[str]      # groups the target config doesn't have
    audio_file: Optional[str]      # basename, or None
    name_conflict: bool            # a show of this name exists in the target


def list_import_candidates(source: Configuration,
                           target: Configuration) -> List[ShowImportCandidate]:
    candidates = []
    for name, show in source.songs.items():
        groups = referenced_groups(show)
        audio = None
        if show.timeline_data and show.timeline_data.audio_file_path:
            audio = os.path.basename(show.timeline_data.audio_file_path)
        candidates.append(ShowImportCandidate(
            name=name,
            num_parts=len(show.parts),
            groups=groups,
            missing_groups=[g for g in groups if g not in target.groups],
            audio_file=audio,
            name_conflict=name in target.songs,
        ))
    return candidates


@dataclass
class ShowMergeResult:
    source_name: str
    final_name: Optional[str]      # None when skipped
    action: str                    # 'added' | 'renamed' | 'overwritten' | 'skipped'
    missing_groups: List[str] = field(default_factory=list)
    audio_action: str = 'none'     # 'copied' | 'already-present' | 'not-found' | 'none'


def _unique_show_name(name: str, existing) -> str:
    n = 2
    while f"{name} ({n})" in existing:
        n += 1
    return f"{name} ({n})"


def _locate_source_audio(source: Configuration, audio_path: str) -> Optional[str]:
    basename = os.path.basename(audio_path)
    bundle = source.audio_bundle_dir()
    if bundle:
        candidate = os.path.join(bundle, basename)
        if os.path.exists(candidate):
            return candidate
    if os.path.isabs(audio_path) and os.path.exists(audio_path):
        return audio_path
    return None


def _copy_show_audio(source: Configuration, target: Configuration,
                     show: Song) -> str:
    """Copy the show's audio into the target bundle; returns the action.
    Always normalizes the show's stored path to the basename so it
    resolves via the target's bundle dir from now on."""
    if not (show.timeline_data and show.timeline_data.audio_file_path):
        return 'none'
    audio_path = show.timeline_data.audio_file_path
    basename = os.path.basename(audio_path)
    show.timeline_data.audio_file_path = basename

    src = _locate_source_audio(source, audio_path)
    if src is None:
        return 'not-found'
    target_dir = target.audio_bundle_dir(create=True)
    if target_dir is None:
        # Target config has never been saved — nowhere to bundle to.
        return 'not-found'
    dst = os.path.join(target_dir, basename)
    if os.path.exists(dst):
        return 'already-present'
    shutil.copy2(src, dst)
    return 'copied'


def merge_shows(target: Configuration, source: Configuration,
                show_names: List[str], on_conflict: str = 'rename',
                copy_audio: bool = True) -> List[ShowMergeResult]:
    """Pull the named shows from ``source`` into ``target``.

    on_conflict: 'rename' (default), 'overwrite', or 'skip'.
    """
    if on_conflict not in ('rename', 'overwrite', 'skip'):
        raise ValueError(f"Unknown conflict mode: {on_conflict!r}")

    results = []
    for name in show_names:
        if name not in source.songs:
            raise KeyError(f"Source config has no show named {name!r}")

        action = 'added'
        final_name = name
        if name in target.songs:
            if on_conflict == 'skip':
                results.append(ShowMergeResult(
                    source_name=name, final_name=None, action='skipped'))
                continue
            if on_conflict == 'overwrite':
                action = 'overwritten'
            else:
                final_name = _unique_show_name(name, target.songs)
                action = 'renamed'

        # Deep copy through the dict round-trip so target edits never
        # write back into the source config's objects.
        show = Song.from_dict(final_name, source.songs[name].to_dict())

        audio_action = _copy_show_audio(source, target, show) if copy_audio else 'none'

        results.append(ShowMergeResult(
            source_name=name,
            final_name=final_name,
            action=action,
            missing_groups=[g for g in referenced_groups(show)
                            if g not in target.groups],
            audio_action=audio_action,
        ))
        target.songs[final_name] = show

    return results
