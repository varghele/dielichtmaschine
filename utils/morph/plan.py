# utils/morph/plan.py
"""The morph patch plan - the user-authored routing document.

Design authority: docs/design-show-morphing.md sections 3 and 5. A plan
wires (source lane, sublane stream) edges onto target groups, each edge
carrying a mode, transforms, and a fan-in priority. Plans persist as
``*.morphplan.yaml`` - diffable, reviewable, reusable per venue - and
pin the identity of both configs by content hash so a changed rig
invalidates visibly instead of silently.

Edges key their source by GROUP SELECTOR (``"WASH"``, ``"WASH:0"``) -
the same vocabulary ``LightLane.fixture_targets`` speaks - so ONE plan
covers the whole setlist, per design doc 5.2: "lanes are keyed by group
targets, which are consistent across songs in a config... the single
biggest workflow multiplier in the design".

Format 1 keyed edges by ``lane_id`` instead, a per-lane uuid4. Because
lanes live inside a song, that made every wire per-song: a real 12-song
gig needed 293 edges to express 39 distinct wires, and the patchbay
listed all 58 song-qualified lanes. ``migrate_legacy_edges()`` collapses
format-1 plans on load (2026-08-08). The unit of protection is still the
TARGET lane (design doc 5.5): a protected target group is skipped whole
on re-morph. Seeds are plan-global with
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
    """One wire: (source group selector, sublane stream) -> target group.

    The source key is a GROUP SELECTOR - a group name, optionally with an
    indexed suffix (``"WASH"``, ``"WASH:0"``) - exactly the vocabulary
    ``LightLane.fixture_targets`` speaks. That is what makes one plan
    cover a whole setlist (design doc 5.2: "lanes are keyed by group
    targets, which are consistent across songs in a config").
    """
    source_group: str              # group selector, e.g. "WASH" / "WASH:0"
    sublane: str                   # dimmer | colour | movement | special
    target_group: str
    mode: str = "copy"             # copy | copy_transform | regenerate
    transforms: List[Dict] = field(default_factory=list)  # [{type, ...params}]
    priority: int = 0              # fan-in resolution (higher wins)
    regenerate_strategy: str = "manual"
    seed: Optional[int] = None     # per-edge override of the plan seed
    edge_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    #: format-1 plans keyed the source by a PER-SONG lane uuid. Carried
    #: only until migrate_legacy_edges() resolves it onto source_group;
    #: never written back out.
    legacy_lane_id: str = ""

    @property
    def source_base_group(self) -> str:
        """The selector's group name, without any ``:N`` index suffix."""
        return self.source_group.split(":")[0]

    def validate(self) -> List[str]:
        problems = []
        where = (f"edge {self.edge_id} "
                 f"({self.source_group}/{self.sublane} -> {self.target_group})")
        if not self.source_group:
            problems.append(
                f"{where}: no source group. A format-1 (lane-keyed) plan "
                f"needs migrate_legacy_edges(source_config) first.")
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
            "source_group": self.source_group,
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
            source_group=data.get("source_group", ""),
            # format 1: per-song lane uuid, resolved by migrate_legacy_edges
            legacy_lane_id=data.get("source_lane_id", ""),
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
            known_groups = set(source_config.groups)
            for edge in self._all_edges():
                if edge.source_group and \
                        edge.source_base_group not in known_groups:
                    problems.append(
                        f"edge {edge.edge_id}: source group "
                        f"'{edge.source_group}' not in the source config")
        return problems

    # -- migration ---------------------------------------------------------

    def needs_migration(self) -> bool:
        """True when this plan still carries format-1 lane-keyed edges."""
        return any(not e.source_group and e.legacy_lane_id
                   for e in self._all_edges())

    def migrate_legacy_edges(self, source_config) -> int:
        """Collapse format-1 (lane-keyed) edges onto group selectors.

        Format 1 keyed each edge by ``LightLane.lane_id``, a per-lane
        uuid4 - so a plan had to repeat the same wire once per SONG, and
        the patchbay listed every song's lanes. This resolves each lane
        id to that lane's ``fixture_targets`` selector(s) and dedupes,
        which is what the design specified all along (5.2).

        A lane with several targets yields one edge per target. Returns
        the number of edges dropped as duplicates; unresolvable edges are
        left alone so ``validate()`` reports them rather than silently
        discarding routing the user authored.
        """
        lane_targets = {}
        for song in source_config.songs.values():
            if not song.timeline_data:
                continue
            for lane in song.timeline_data.lanes:
                if lane.fixture_targets:
                    lane_targets[lane.lane_id] = list(lane.fixture_targets)

        dropped = 0
        self.edges, n = self._collapse(self.edges, lane_targets)
        dropped += n
        for song in list(self.song_overrides):
            self.song_overrides[song], n = self._collapse(
                self.song_overrides[song], lane_targets)
            dropped += n
        return dropped

    @staticmethod
    def _collapse(edges: List[MorphEdge], lane_targets: Dict[str, List[str]]):
        """Resolve legacy edges to group selectors and drop duplicates,
        preserving first-seen order (the plan is a reviewable document -
        a stable diff matters)."""
        import copy as _copy
        import json

        out: List[MorphEdge] = []
        seen = set()
        dropped = 0
        for edge in edges:
            if edge.source_group or not edge.legacy_lane_id:
                selectors = [edge.source_group]
            else:
                selectors = lane_targets.get(edge.legacy_lane_id)
                if not selectors:
                    out.append(edge)      # unresolvable; validate() flags it
                    continue
            for index, selector in enumerate(selectors):
                signature = (
                    selector, edge.sublane, edge.target_group, edge.mode,
                    edge.priority, edge.regenerate_strategy, edge.seed,
                    json.dumps(edge.transforms, sort_keys=True),
                )
                if signature in seen:
                    dropped += 1
                    continue
                seen.add(signature)
                resolved = _copy.deepcopy(edge)
                resolved.source_group = selector
                resolved.legacy_lane_id = ""
                # A multi-target lane fans out to one edge per selector;
                # they must not share the original's edge_id.
                if index:
                    resolved.edge_id = uuid.uuid4().hex[:12]
                out.append(resolved)
        return out, dropped

    def _all_edges(self) -> List[MorphEdge]:
        every = list(self.edges)
        for edges in self.song_overrides.values():
            every.extend(edges)
        return every

    # -- persistence -------------------------------------------------------

    def to_dict(self) -> Dict:
        return {
            "morphplan": 2,        # format version (2: group-keyed edges)
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
