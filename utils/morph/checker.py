# utils/morph/checker.py
"""The completeness checker (design doc 6): per (target group,
capability) time coverage of the routed streams, plus the mirror view
(source streams feeding nothing). Runs live in the patchbay and gates
the commit with a blocking warning; saved expectations double as the
show's minimum-rig manifest - the old roadmap item for free.

Pure plan+config arithmetic: nothing here compiles or mutates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from utils.morph.compile import SUBLANE_ATTRS, _song_duration
from utils.morph.plan import MorphPlan


@dataclass
class Coverage:
    """One (song, target group, sublane) row."""
    song: str
    target_group: str
    sublane: str
    fraction: float                 # 0.0 - 1.0 of the song's duration
    routed_edges: int

    @property
    def percent(self) -> int:
        return int(round(self.fraction * 100))


@dataclass
class CheckResult:
    coverage: List[Coverage] = field(default_factory=list)
    #: (song, lane name, sublane, block count) source streams no edge eats
    unrouted_sources: List[Tuple[str, str, str, int]] = field(
        default_factory=list)

    def gaps(self, capability_map: Dict[str, "set"]) -> List[Coverage]:
        """Rows where a target group HAS a capability but receives
        nothing (fraction 0) - the blocking-warning material.
        ``capability_map``: group -> set of sublanes it can render."""
        rows = []
        for row in self.coverage:
            if row.fraction == 0.0 and \
                    row.sublane in capability_map.get(row.target_group,
                                                      set()):
                rows.append(row)
        return rows


def _union_length(intervals: List[Tuple[float, float]]) -> float:
    if not intervals:
        return 0.0
    intervals = sorted(intervals)
    total, cur_s, cur_e = 0.0, intervals[0][0], intervals[0][1]
    for s, e in intervals[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            total += cur_e - cur_s
            cur_s, cur_e = s, e
    total += cur_e - cur_s
    return total


def group_capabilities(config) -> Dict[str, set]:
    """group -> the sublanes its fixtures can render, from the stored
    FixtureGroupCapabilities (absent = assume everything, so gaps stay
    conservative rather than silent)."""
    result = {}
    for name, group in config.groups.items():
        caps = getattr(group, "capabilities", None)
        if caps is None:
            result[name] = set(SUBLANE_ATTRS)
            continue
        have = set()
        if caps.has_dimmer:
            have.add("dimmer")
        if caps.has_colour:
            have.add("colour")
        if caps.has_movement:
            have.add("movement")
        if caps.has_special:
            have.add("special")
        result[name] = have
    return result


def check(source_config, plan: MorphPlan, target_config) -> CheckResult:
    """Coverage per (song, target group, sublane) + the unrouted mirror."""
    result = CheckResult()
    for song_name, song in source_config.songs.items():
        if not song.timeline_data:
            continue
        duration = _song_duration(song) or 1.0
        lanes_by_id = {lane.lane_id: lane
                       for lane in song.timeline_data.lanes}
        edges = plan.edges_for_song(song_name)

        routed: Dict[Tuple[str, str], List[Tuple[float, float]]] = {}
        edge_counts: Dict[Tuple[str, str], int] = {}
        eaten = set()
        for edge in edges:
            key = (edge.target_group, edge.sublane)
            if edge.mode == "regenerate":
                # Regeneration promises full coverage by construction
                # (manual strategy honestly promises nothing).
                if edge.regenerate_strategy != "manual":
                    routed.setdefault(key, []).append((0.0, duration))
                edge_counts[key] = edge_counts.get(key, 0) + 1
                continue
            lane = lanes_by_id.get(edge.source_lane_id)
            if lane is None:
                continue
            attr = SUBLANE_ATTRS[edge.sublane]
            spans = [(b.start_time, b.end_time)
                     for lb in lane.light_blocks
                     for b in getattr(lb, attr)]
            routed.setdefault(key, []).extend(spans)
            edge_counts[key] = edge_counts.get(key, 0) + 1
            eaten.add((lane.lane_id, edge.sublane))

        # Every target group x sublane the plan touches, plus every
        # capability the target group could render (0% rows included -
        # they ARE the point of the checker).
        capability_map = group_capabilities(target_config)
        touched_groups = {edge.target_group for edge in edges}
        for group in sorted(touched_groups):
            for sublane in SUBLANE_ATTRS:
                if sublane not in capability_map.get(group, set()) and \
                        (group, sublane) not in routed:
                    continue
                spans = routed.get((group, sublane), [])
                fraction = min(1.0, _union_length(spans) / duration)
                result.coverage.append(Coverage(
                    song=song_name, target_group=group, sublane=sublane,
                    fraction=fraction,
                    routed_edges=edge_counts.get((group, sublane), 0)))

        for lane in song.timeline_data.lanes:
            for sublane, attr in SUBLANE_ATTRS.items():
                count = sum(len(getattr(lb, attr))
                            for lb in lane.light_blocks)
                if count and (lane.lane_id, sublane) not in eaten:
                    result.unrouted_sources.append(
                        (song_name, lane.name, sublane, count))
    return result
