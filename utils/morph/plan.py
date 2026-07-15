# utils/morph/plan.py
"""The morph patch plan - the user-authored routing document.

Design authority: docs/design-show-morphing.md sections 3 and 5. A plan
wires (source lane, sublane stream) edges onto target groups, each edge
carrying a mode, transforms, and a fan-in priority. Plans persist as
``*.morphplan.yaml`` - diffable, reviewable, reusable per venue - and
pin the identity of both configs by content hash so a changed rig
invalidates visibly instead of silently.

Edges key their source by ``lane_id`` (stable across lane renames,
phase 0) with the display name carried alongside for diffability. The
unit of protection is the TARGET lane (design doc 5.5): a protected
target group is skipped whole on re-morph. Seeds are plan-global with
per-edge override (design doc 11.6); the 2026-07-16 determinism audit
showed autogen itself is a pure function, so seeds exist for future
stochastic strategies and for the plan format's stability.

Vocabulary note: the UI speaks INTENSITY / COLOUR / POSITION / BEAM;
the data model's sublanes are dimmer / colour / movement / special
(1:1, decided 2026-07-15). This module uses the data-model names.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml

SUBLANES = ("dimmer", "colour", "movement", "special")

MODES = ("copy", "copy_transform", "regenerate")

REGENERATE_STRATEGIES = ("manual", "static_default",
                         "derive_from_intensity", "autogen")

#: transform type -> required parameter names (order = application order
#: within an edge is the LIST order on the edge, not this dict).
TRANSFORM_TYPES = {
    "phase_offset": ("amount",),   # beats or fraction-of-cycle (0..1)
    "mirror": (),
    "invert_direction": (),
    "intensity_scale": ("factor",),
    "spatial_subset": ("selector",),  # e.g. "left-half", "right-half",
                                      # "front-half", "back-half"
}


class PlanError(Exception):
    """A plan that cannot be loaded or fails validation."""


def config_hash(config) -> str:
    """Stable content hash of a Configuration (sha256 of its canonical
    YAML serialization). Used to pin plan <-> config identity."""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    try:
        config.save(path)
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


@dataclass
class MorphEdge:
    """One wire: (source lane, sublane stream) -> target group."""
    source_lane_id: str
    source_lane_name: str          # display/diff only; lane_id is the key
    sublane: str                   # dimmer | colour | movement | special
    target_group: str
    mode: str = "copy"             # copy | copy_transform | regenerate
    transforms: List[Dict] = field(default_factory=list)  # [{type, ...params}]
    priority: int = 0              # fan-in resolution (higher wins)
    regenerate_strategy: str = "manual"
    seed: Optional[int] = None     # per-edge override of the plan seed
    edge_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def validate(self) -> List[str]:
        problems = []
        where = f"edge {self.edge_id} ({self.source_lane_name}/{self.sublane} -> {self.target_group})"
        if self.sublane not in SUBLANES:
            problems.append(f"{where}: unknown sublane '{self.sublane}'")
        if self.mode not in MODES:
            problems.append(f"{where}: unknown mode '{self.mode}'")
        if self.mode == "regenerate" \
                and self.regenerate_strategy not in REGENERATE_STRATEGIES:
            problems.append(f"{where}: unknown regenerate strategy "
                            f"'{self.regenerate_strategy}'")
        if self.mode == "copy" and self.transforms:
            problems.append(f"{where}: transforms require mode "
                            f"copy_transform")
        for transform in self.transforms:
            kind = transform.get("type")
            if kind not in TRANSFORM_TYPES:
                problems.append(f"{where}: unknown transform '{kind}'")
                continue
            for param in TRANSFORM_TYPES[kind]:
                if param not in transform:
                    problems.append(
                        f"{where}: transform '{kind}' missing '{param}'")
        return problems

    def to_dict(self) -> Dict:
        data = {
            "edge_id": self.edge_id,
            "source_lane_id": self.source_lane_id,
            "source_lane_name": self.source_lane_name,
            "sublane": self.sublane,
            "target_group": self.target_group,
            "mode": self.mode,
            "priority": self.priority,
        }
        if self.transforms:
            data["transforms"] = self.transforms
        if self.mode == "regenerate":
            data["regenerate_strategy"] = self.regenerate_strategy
        if self.seed is not None:
            data["seed"] = self.seed
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> "MorphEdge":
        return cls(
            source_lane_id=data.get("source_lane_id", ""),
            source_lane_name=data.get("source_lane_name", ""),
            sublane=data.get("sublane", ""),
            target_group=data.get("target_group", ""),
            mode=data.get("mode", "copy"),
            transforms=list(data.get("transforms") or []),
            priority=int(data.get("priority", 0)),
            regenerate_strategy=data.get("regenerate_strategy", "manual"),
            seed=data.get("seed"),
            edge_id=data.get("edge_id") or uuid.uuid4().hex[:12],
        )


@dataclass
class MorphPlan:
    """The whole routing document, one per (source setlist, target rig)."""
    name: str = ""
    notes: str = ""
    author: str = ""
    created: str = ""              # ISO date string, caller-stamped
    source_hash: str = ""          # config_hash of config A at plan time
    target_hash: str = ""          # config_hash of config B at plan time
    edges: List[MorphEdge] = field(default_factory=list)
    #: target groups whose morphed lanes re-morph must NOT touch
    protected_target_lanes: List[str] = field(default_factory=list)
    seed: int = 0                  # plan-global; per-edge seed overrides
    #: per-song edge overrides: song name -> full edge list replacing
    #: the plan's edges for that song only (design doc 5.2)
    song_overrides: Dict[str, List[MorphEdge]] = field(default_factory=dict)

    # -- queries -----------------------------------------------------------

    def edges_for_song(self, song_name: str) -> List[MorphEdge]:
        return self.song_overrides.get(song_name, self.edges)

    def effective_seed(self, edge: MorphEdge) -> int:
        return edge.seed if edge.seed is not None else self.seed

    def is_protected(self, target_group: str) -> bool:
        return target_group in self.protected_target_lanes

    def validate(self, source_config=None, target_config=None) -> List[str]:
        """Problems as human-readable strings; empty = valid.

        With configs supplied, membership is checked too (unknown
        target groups / source lane ids)."""
        problems = []
        for edge in self.edges:
            problems.extend(edge.validate())
        for song, edges in self.song_overrides.items():
            for edge in edges:
                problems.extend(f"[{song}] {p}" for p in edge.validate())
        if target_config is not None:
            known_groups = set(target_config.groups)
            for edge in self._all_edges():
                if edge.target_group not in known_groups:
                    problems.append(
                        f"edge {edge.edge_id}: target group "
                        f"'{edge.target_group}' not in the target config")
        if source_config is not None:
            known_lanes = {
                lane.lane_id
                for song in source_config.songs.values()
                if song.timeline_data
                for lane in song.timeline_data.lanes
            }
            for edge in self._all_edges():
                if edge.source_lane_id not in known_lanes:
                    problems.append(
                        f"edge {edge.edge_id}: source lane "
                        f"'{edge.source_lane_name}' "
                        f"({edge.source_lane_id}) not in the source config")
        return problems

    def _all_edges(self) -> List[MorphEdge]:
        every = list(self.edges)
        for edges in self.song_overrides.values():
            every.extend(edges)
        return every

    # -- persistence -------------------------------------------------------

    def to_dict(self) -> Dict:
        return {
            "morphplan": 1,        # format version
            "name": self.name,
            "notes": self.notes,
            "author": self.author,
            "created": self.created,
            "source_hash": self.source_hash,
            "target_hash": self.target_hash,
            "seed": self.seed,
            "protected_target_lanes": list(self.protected_target_lanes),
            "edges": [edge.to_dict() for edge in self.edges],
            "song_overrides": {
                song: [edge.to_dict() for edge in edges]
                for song, edges in self.song_overrides.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "MorphPlan":
        if "morphplan" not in data:
            raise PlanError("not a morph plan (missing 'morphplan' key)")
        return cls(
            name=data.get("name", ""),
            notes=data.get("notes", ""),
            author=data.get("author", ""),
            created=data.get("created", ""),
            source_hash=data.get("source_hash", ""),
            target_hash=data.get("target_hash", ""),
            seed=int(data.get("seed", 0)),
            protected_target_lanes=list(
                data.get("protected_target_lanes") or []),
            edges=[MorphEdge.from_dict(e) for e in data.get("edges") or []],
            song_overrides={
                song: [MorphEdge.from_dict(e) for e in edges]
                for song, edges in (data.get("song_overrides") or {}).items()
            },
        )

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.to_dict(), f, sort_keys=False,
                           allow_unicode=True)

    @classmethod
    def load(cls, path: str) -> "MorphPlan":
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except (OSError, yaml.YAMLError) as exc:
            raise PlanError(f"cannot read plan {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise PlanError(f"{path} is not a morph plan")
        return cls.from_dict(data)
