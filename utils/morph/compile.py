# utils/morph/compile.py
"""The morph compile: (config A, songs, plan, config B) -> new songs.

Design authority: docs/design-show-morphing.md section 3 (routing,
transforms, fan-in, re-enveloping, shared channels, specials) and 5
(lineage, re-morph, determinism). Pure and deterministic: no RNG, no
clocks (timestamps come in via ``stamp``), no Qt. The output is
ordinary ``Song`` objects - playback, export, and the editor never
learn that morphing exists.

v1 policies where the design left room (recorded in
docs/focus-morphing-plan.md):

- **Envelopes**: morphed ``LightBlock`` envelopes are the connected
  components of the routed sublane blocks (interval union). Blocks are
  NEVER split: the block model cannot express a phase-shifted rudiment
  continuation, so splitting would violate the design's own
  phase-preservation demand. (Design doc 11.3 leaves the cut policy
  open; this is the conservative answer.)
- **Fan-in**: colour blocks (pure value spans) are CLIPPED to the
  non-overlapping remainder when they lose; rudiment-cycled blocks
  (dimmer with an effect, movement, special) are dropped WHOLE when
  they overlap a winner, phase-safe and reported. Dimmer winners are
  chosen HTP-style by block intensity, everything else by edge
  priority.
- **Shared channels** (design doc 3.4): playback already renders
  dimmer blocks on colour-only groups; the compile flags the gap cases
  (colour with no dimmer coverage) in the report instead of
  synthesizing blocks.
- **Regeneration**: manual / static_default / derive_from_intensity are
  implemented; ``autogen`` edges fail validation with the design's
  prescribed downgrade message until the analysis cache lands.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from config.models import (LightBlock, LightLane, MovementBlock, Song)
from utils.morph.plan import MorphEdge, MorphPlan, config_hash

SUBLANE_ATTRS = {
    "dimmer": "dimmer_blocks",
    "colour": "colour_blocks",
    "movement": "movement_blocks",
    "special": "special_blocks",
}

#: derive_from_intensity complement map: dimmer effect_type ->
#: (movement effect_type, speed multiplier override or None)
DERIVE_MOVEMENT = {
    "pulse": ("circle", None),
    "throb": ("circle", None),
    "fade": ("circle", "1/2"),
    "wave": ("figure_8", None),
    "chase": ("bounce", None),
    "ping_pong": ("bounce", None),
    "waterfall": ("bounce", None),
    "sparkle": ("random", None),
    "random_stroke": ("random", None),
    "strobe": ("bounce", "2"),
    "static": ("circle", "1/4"),
}
DERIVE_DEFAULT = ("circle", "1/2")


@dataclass
class ReportEntry:
    kind: str        # routed | transform | fanin_loss | dropped_special |
                     # regenerated | gap | destroyed | note | error
    song: str
    message: str
    edge_id: str = ""

    def format(self) -> str:
        tag = f" [{self.edge_id}]" if self.edge_id else ""
        return f"[{self.kind}]{tag} {self.song}: {self.message}"


@dataclass
class MorphReport:
    """The plan's execution trace (design doc 6): because the plan is
    user-authored, this reads as confirmation, not surprise."""
    entries: List[ReportEntry] = field(default_factory=list)

    def add(self, kind: str, song: str, message: str, edge_id: str = ""):
        self.entries.append(ReportEntry(kind, song, message, edge_id))

    def of_kind(self, kind: str) -> List[ReportEntry]:
        return [e for e in self.entries if e.kind == kind]

    @property
    def has_errors(self) -> bool:
        return bool(self.of_kind("error"))

    def to_markdown(self, title: str = "Morph report") -> str:
        lines = [f"# {title}", ""]
        for entry in self.entries:
            lines.append(f"- {entry.format()}")
        if not self.entries:
            lines.append("- (clean: every edge applied without loss)")
        return "\n".join(lines) + "\n"


@dataclass
class MorphResult:
    songs: Dict[str, Song]
    report: MorphReport
    lineage: Dict[str, str]


# ---------------------------------------------------------------------------
# transforms
# ---------------------------------------------------------------------------

def _apply_transforms(blocks: list, sublane: str, edge: MorphEdge,
                      report: MorphReport, song: str) -> list:
    for transform in edge.transforms:
        kind = transform.get("type")
        if kind == "intensity_scale":
            if sublane != "dimmer":
                report.add("note", song,
                           f"intensity_scale ignored on {sublane} stream",
                           edge.edge_id)
                continue
            factor = float(transform.get("factor", 1.0))
            for b in blocks:
                b.intensity = max(0.0, min(255.0, b.intensity * factor))
        elif kind == "phase_offset":
            amount = float(transform.get("amount", 0.0))  # fraction of cycle
            if sublane == "movement":
                for b in blocks:
                    b.phase_offset_enabled = True
                    b.phase_offset_degrees = (
                        b.phase_offset_degrees + amount * 360.0) % 360.0
            else:
                report.add("note", song,
                           f"phase_offset has no per-block phase on "
                           f"{sublane} streams in v1; ignored",
                           edge.edge_id)
        elif kind in ("mirror", "invert_direction"):
            if sublane == "dimmer":
                flip = {"down": "up", "up": "down",
                        "in": "out", "out": "in"}
                for b in blocks:
                    b.direction = flip.get(b.direction, b.direction)
            elif sublane == "movement":
                for b in blocks:
                    b.phase_offset_enabled = True
                    b.phase_offset_degrees = (
                        b.phase_offset_degrees + 180.0) % 360.0
            else:
                report.add("note", song,
                           f"{kind} has no meaning on {sublane}; ignored",
                           edge.edge_id)
        elif kind == "spatial_subset":
            # Resolved at routing time (needs the target group); the
            # transform is recorded here so the loop stays exhaustive.
            pass
        if kind and kind != "spatial_subset":
            report.add("transform", song,
                       f"{kind} applied to {sublane} -> "
                       f"{edge.target_group}", edge.edge_id)
    return blocks


def _subset_selector(edge: MorphEdge) -> Optional[str]:
    for transform in edge.transforms:
        if transform.get("type") == "spatial_subset":
            return transform.get("selector", "")
    return None


def resolve_spatial_subset(target_config, group_name: str,
                           selector: str) -> str:
    """Materialize a spatial-subset group in config B and return its
    name. Uses the canonical group order's geometry; idempotent."""
    from config.models import FixtureGroup
    group = target_config.groups[group_name]
    label = {"left-half": "left half", "right-half": "right half",
             "front-half": "front half", "back-half": "back half"}.get(
        selector, selector)
    subset_name = f"{group_name} ({label})"
    if subset_name in target_config.groups:
        return subset_name
    fixtures = list(group.fixtures)
    axis = 0 if selector in ("left-half", "right-half") else 1
    values = sorted((f.x if axis == 0 else f.y) for f in fixtures)
    median = values[len(values) // 2] if values else 0.0
    if selector in ("left-half", "front-half"):
        chosen = [f for f in fixtures
                  if (f.x if axis == 0 else f.y) < median] or fixtures[:1]
    else:
        chosen = [f for f in fixtures
                  if (f.x if axis == 0 else f.y) >= median] or fixtures[-1:]
    subset = FixtureGroup(subset_name, list(chosen), color=group.color,
                          default_mounting=group.default_mounting,
                          default_yaw=group.default_yaw,
                          default_pitch=group.default_pitch,
                          default_roll=group.default_roll,
                          default_z_height=group.default_z_height,
                          lighting_role=group.lighting_role,
                          export_intensity=group.export_intensity)
    subset.apply_fixture_order()
    target_config.groups[subset_name] = subset
    return subset_name


# ---------------------------------------------------------------------------
# fan-in
# ---------------------------------------------------------------------------

def _overlaps(a, b) -> bool:
    return a.start_time < b.end_time and b.start_time < a.end_time


def _is_clip_safe(sublane: str, block) -> bool:
    """Clipping is phase-safe only for value spans without a cycle."""
    if sublane == "colour":
        return True
    if sublane == "dimmer":
        return getattr(block, "effect_type", "static") == "static"
    return False


def _clip_block(block, winners) -> list:
    """The non-overlapping remainder of ``block`` against winner spans;
    may come back as 0, 1 or 2 pieces."""
    spans = [(block.start_time, block.end_time)]
    for w in winners:
        next_spans = []
        for s, e in spans:
            if w.end_time <= s or w.start_time >= e:
                next_spans.append((s, e))
                continue
            if s < w.start_time:
                next_spans.append((s, w.start_time))
            if w.end_time < e:
                next_spans.append((w.end_time, e))
        spans = next_spans
    pieces = []
    for s, e in spans:
        if e - s <= 1e-6:
            continue
        piece = copy.deepcopy(block)
        piece.start_time, piece.end_time = s, e
        pieces.append(piece)
    return pieces


def _bake_dangling_spots(blocks: list, source_config, target_config,
                         edge, song_name: str, report) -> None:
    """Movement blocks aiming at a NAMED spot keep the name only when
    the target rig has that spot; otherwise the source spot's position
    bakes into ``target_point`` (2026-07-16 fix - a dangling spot name
    used to fall back to the raw pan/tilt authored for rig A's movers,
    which on rig B pointed anywhere but the stage). The look stays
    anchored to the same point in space; a same-named spot in the
    target rig wins so venue-local re-aiming keeps working."""
    target_spots = getattr(target_config, "spots", None) or {}
    source_spots = getattr(source_config, "spots", None) or {}
    baked = 0
    dropped = set()
    for block in blocks:
        name = getattr(block, "target_spot_name", None)
        if not name or name in target_spots:
            continue
        spot = source_spots.get(name)
        if spot is None:
            dropped.add(name)
            continue
        block.target_point = [float(spot.x), float(spot.y),
                              float(spot.z)]
        block.target_spot_name = None
        baked += 1
    if baked:
        report.add("transform", song_name,
                   f"{baked} movement block(s) re-anchored from source "
                   f"spots to world points ('{edge.target_group}' has "
                   f"no spot of that name)", edge.edge_id)
    for name in sorted(dropped):
        report.add("note", song_name,
                   f"movement spot '{name}' exists in neither config; "
                   f"blocks keep their authored pan/tilt", edge.edge_id)


def _resolve_fan_in(contributions: List[Tuple[MorphEdge, list]],
                    sublane: str, song: str,
                    report: MorphReport) -> list:
    """One target group's stream for one sublane type; overlaps resolve
    dimmer-HTP / priority-LTP statically (design doc 3.3)."""
    if not contributions:
        return []
    if len(contributions) == 1:
        return contributions[0][1]

    tagged = []
    for edge, blocks in contributions:
        for block in blocks:
            if sublane == "dimmer":
                rank = (float(getattr(block, "intensity", 0.0)),
                        edge.priority)
            else:
                rank = (float(edge.priority),)
            tagged.append((rank, edge, block))
    # Highest rank first; stable for equal ranks (plan edge order).
    tagged.sort(key=lambda item: item[0], reverse=True)

    kept: list = []
    for rank, edge, block in tagged:
        overlapping = [k for k in kept if _overlaps(k, block)]
        if not overlapping:
            kept.append(block)
            continue
        if _is_clip_safe(sublane, block):
            pieces = _clip_block(block, overlapping)
            kept.extend(pieces)
            report.add("fanin_loss", song,
                       f"{sublane} block {block.start_time:.2f}-"
                       f"{block.end_time:.2f}s clipped to "
                       f"{len(pieces)} piece(s) under a higher-priority "
                       f"stream", edge.edge_id)
        else:
            report.add("fanin_loss", song,
                       f"{sublane} block {block.start_time:.2f}-"
                       f"{block.end_time:.2f}s dropped (overlaps a "
                       f"higher-priority stream; cycled blocks are "
                       f"never clipped)", edge.edge_id)
    kept.sort(key=lambda b: b.start_time)
    return kept


# ---------------------------------------------------------------------------
# regeneration (design doc 3.2)
# ---------------------------------------------------------------------------

def _song_duration(song: Song) -> float:
    from timeline.song_structure import SongStructure
    structure = SongStructure()
    structure.load_from_show_parts(song.parts)
    return structure.get_total_duration()


def _default_target(target_config) -> dict:
    """Ambient default: the Floor plane when the rig defines one, else
    centre stage."""
    try:
        from autogen.spatial import compute_stage_planes
        planes = {p.name for p in compute_stage_planes(target_config)}
        if "Floor" in planes:
            return {"target_plane_name": "Floor"}
    except Exception:
        pass
    return {"target_point": [0.0, 0.0, 0.0]}


def _regenerate_movement(edge: MorphEdge, source_dimmer: list,
                         song: Song, target_config,
                         report: MorphReport) -> list:
    strategy = edge.regenerate_strategy
    if strategy == "manual":
        report.add("regenerated", song.name,
                   f"movement -> {edge.target_group}: intentionally "
                   f"empty - author by hand", edge.edge_id)
        return []
    if strategy == "static_default":
        duration = _song_duration(song)
        block = MovementBlock(start_time=0.0, end_time=duration,
                              effect_type="circle", effect_speed="1/4",
                              pan_amplitude=10.0, tilt_amplitude=8.0,
                              **_default_target(target_config))
        report.add("regenerated", song.name,
                   f"movement -> {edge.target_group}: static_default "
                   f"ambient circle over {duration:.1f}s", edge.edge_id)
        return [block]
    if strategy == "derive_from_intensity":
        blocks = []
        for d in source_dimmer:
            effect, speed = DERIVE_MOVEMENT.get(
                getattr(d, "effect_type", "static"), DERIVE_DEFAULT)
            blocks.append(MovementBlock(
                start_time=d.start_time, end_time=d.end_time,
                effect_type=effect,
                effect_speed=speed or d.effect_speed,
                pan_amplitude=30.0, tilt_amplitude=20.0,
                **_default_target(target_config)))
        report.add("regenerated", song.name,
                   f"movement -> {edge.target_group}: "
                   f"derive_from_intensity emitted {len(blocks)} "
                   f"block(s) (seed {edge.seed if edge.seed is not None else 'plan'})",
                   edge.edge_id)
        return blocks
    if strategy == "autogen":
        return _regenerate_autogen(edge, song, target_config, report)
    report.add("error", song.name,
               f"unknown regenerate strategy '{strategy}'", edge.edge_id)
    return []


def _regenerate_autogen(edge: MorphEdge, song: Song, target_config,
                        report: MorphReport) -> list:
    """The autogen movement-strategy pass over cached (or recomputed)
    per-section metrics (design doc 3.2 strategy 4 + 5.7). Deterministic:
    the selector rotates shapes by section index and thresholds on the
    cached scalars - no RNG (2026-07-16 audit)."""
    from utils.morph.analysis_cache import relative_energies, resolve
    analysis, source = resolve(song, target_config)
    if analysis is None:
        report.add("error", song.name,
                   f"autogen regeneration needs the song's analysis "
                   f"cache or its bundled audio; neither is available - "
                   f"downgrade this edge to derive_from_intensity or "
                   f"static_default", edge.edge_id)
        return []

    from autogen.generator import _select_movement_strategy
    from autogen.spatial import ensure_default_spots
    had_spots = bool(getattr(target_config, "spots", None))
    spot_names = ensure_default_spots(target_config)
    if not had_spots and spot_names:
        report.add("note", song.name,
                   f"default spots {spot_names} created in the target "
                   f"config for autogen movement targets", edge.edge_id)

    energies = relative_energies(analysis)
    blocks = []
    for index, section in enumerate(analysis.sections):
        bpm = song.parts[index].bpm if index < len(song.parts) else 120.0
        strategy = _select_movement_strategy(
            section, bpm, spot_names, section_index=index,
            relative_energy=energies[index])
        blocks.append(MovementBlock(
            start_time=section.start_time, end_time=section.end_time,
            effect_type=strategy.shape,
            pan_amplitude=strategy.amplitude,
            tilt_amplitude=strategy.amplitude * 0.6,
            target_spot_name=strategy.target_spot))
    report.add("regenerated", song.name,
               f"movement -> {edge.target_group}: autogen emitted "
               f"{len(blocks)} section block(s) from {source} analysis "
               f"(seed {edge.seed if edge.seed is not None else 'plan'})",
               edge.edge_id)
    return blocks


# ---------------------------------------------------------------------------
# envelopes (design doc 3.5, v1 interval-union policy)
# ---------------------------------------------------------------------------

def _build_envelopes(streams: Dict[str, list], source_names: List[str],
                     edge_ids: List[str]) -> List[LightBlock]:
    intervals = []
    for sublane, blocks in streams.items():
        for block in blocks:
            intervals.append((block.start_time, block.end_time))
    if not intervals:
        return []
    intervals.sort()
    components = [list(intervals[0])]
    for s, e in intervals[1:]:
        if s <= components[-1][1] + 1e-6:
            components[-1][1] = max(components[-1][1], e)
        else:
            components.append([s, e])

    provenance = "morphed:" + ",".join(sorted(set(edge_ids)))
    label = "morph:" + "+".join(sorted(set(source_names))) if source_names \
        else "morph:regenerated"
    envelopes = []
    for s, e in components:
        envelope = LightBlock(start_time=s, end_time=e,
                              effect_name="morph.composite",
                              name=label, provenance=provenance)
        for sublane, blocks in streams.items():
            attr = SUBLANE_ATTRS[sublane]
            members = [b for b in blocks
                       if b.start_time >= s - 1e-6 and b.end_time <= e + 1e-6]
            getattr(envelope, attr).extend(
                sorted(members, key=lambda b: b.start_time))
        envelopes.append(envelope)
    return envelopes


# ---------------------------------------------------------------------------
# the compile
# ---------------------------------------------------------------------------

def _same_definition(source_config, lane, target_config,
                     target_group: str) -> bool:
    """Specials rule (design doc 3.6): identical fixture definition
    identity between the lane's first source group and the target."""
    src_groups = [g for g in lane.fixture_targets
                  if g.split(":")[0] in source_config.groups]
    if not src_groups:
        return False
    src = source_config.groups[src_groups[0].split(":")[0]]
    dst = target_config.groups.get(target_group)
    if dst is None or not src.fixtures or not dst.fixtures:
        return False
    src_ident = {(f.manufacturer, f.model) for f in src.fixtures}
    dst_ident = {(f.manufacturer, f.model) for f in dst.fixtures}
    return src_ident == dst_ident


def compile_song(song: Song, plan: MorphPlan, source_config,
                 target_config, report: MorphReport) -> Optional[Song]:
    """Compile one song through the plan. Returns the morphed song, or
    None when the song has no timeline data."""
    if not song.timeline_data:
        report.add("note", song.name, "no timeline data; skipped")
        return None
    lanes_by_id = {lane.lane_id: lane
                   for lane in song.timeline_data.lanes}
    edges = plan.edges_for_song(song.name)
    # Lanes are PER SONG: a plan wired across the whole setlist (the
    # patchbay catalogs every song's lanes) routinely carries edges
    # for other songs' lanes. Those are not this song's business and
    # must skip silently - only a lane id found in NO source song is a
    # broken edge (fixed 2026-07-16: the single-song demo shows never
    # exercised this, and a real 12-song project drowned in errors).
    all_lane_ids = {lane.lane_id
                    for s in source_config.songs.values()
                    if s.timeline_data
                    for lane in s.timeline_data.lanes}

    # target group -> sublane -> [(edge, blocks)]
    buckets: Dict[str, Dict[str, List[Tuple[MorphEdge, list]]]] = {}
    routed_sources = set()

    for edge in edges:
        lane = lanes_by_id.get(edge.source_lane_id)
        if lane is None and edge.source_lane_id in all_lane_ids:
            continue                       # another song's lane
        target_group = edge.target_group
        selector = _subset_selector(edge)
        if selector:
            target_group = resolve_spatial_subset(
                target_config, edge.target_group, selector)
            report.add("transform", song.name,
                       f"spatial_subset({selector}) -> materialized "
                       f"group '{target_group}'", edge.edge_id)
        bucket = buckets.setdefault(target_group, {})

        if edge.mode == "regenerate":
            source_dimmer = []
            if lane is not None:
                for lb in lane.light_blocks:
                    source_dimmer.extend(copy.deepcopy(lb.dimmer_blocks))
            if edge.sublane != "movement":
                report.add("error", song.name,
                           f"regenerate is movement-only in v1 "
                           f"(edge routes {edge.sublane})", edge.edge_id)
                continue
            blocks = _regenerate_movement(edge, source_dimmer, song,
                                          target_config, report)
            bucket.setdefault("movement", []).append((edge, blocks))
            continue

        if lane is None:
            report.add("error", song.name,
                       f"source lane '{edge.source_lane_name}' "
                       f"({edge.source_lane_id}) not in this song",
                       edge.edge_id)
            continue

        if edge.sublane == "special" and not _same_definition(
                source_config, lane, target_config, edge.target_group):
            report.add("dropped_special", song.name,
                       f"special stream from '{lane.name}' dropped: "
                       f"'{edge.target_group}' is not the same fixture "
                       f"definition (design rule 3.6)", edge.edge_id)
            continue

        attr = SUBLANE_ATTRS[edge.sublane]
        blocks = []
        for lb in lane.light_blocks:
            blocks.extend(copy.deepcopy(getattr(lb, attr)))
        blocks.sort(key=lambda b: b.start_time)
        if not blocks:
            report.add("note", song.name,
                       f"'{lane.name}' has no {edge.sublane} blocks; "
                       f"edge produced nothing", edge.edge_id)
            continue
        if edge.sublane == "movement":
            _bake_dangling_spots(blocks, source_config, target_config,
                                 edge, song.name, report)
        blocks = _apply_transforms(blocks, edge.sublane, edge, report,
                                   song.name)
        bucket.setdefault(edge.sublane, []).append((edge, blocks))
        routed_sources.add((edge.source_lane_id, edge.sublane))
        report.add("routed", song.name,
                   f"{len(blocks)} {edge.sublane} block(s) "
                   f"'{lane.name}' -> '{target_group}'", edge.edge_id)

    # Unrouted source streams = deliberate drops, surfaced (doc 3).
    for lane in song.timeline_data.lanes:
        for sublane, attr in SUBLANE_ATTRS.items():
            count = sum(len(getattr(lb, attr)) for lb in lane.light_blocks)
            if count and (lane.lane_id, sublane) not in routed_sources:
                report.add("note", song.name,
                           f"unrouted source stream: '{lane.name}' "
                           f"{sublane} ({count} block(s)) - deliberate "
                           f"drop")

    # Resolve fan-in and build the morphed lanes.
    morphed = Song(
        name=song.name,
        parts=copy.deepcopy(song.parts),
        effects=[],
        # Fresh lanes, SAME music: the morphed song keeps the source
        # song's audio reference (dropped until 2026-07-16 - a morphed
        # show arrived at the venue with silent timelines).
        timeline_data=type(song.timeline_data)(
            audio_file_path=song.timeline_data.audio_file_path),
        palette=dict(song.palette),
        trigger_device=song.trigger_device,
        trigger_channel=song.trigger_channel,
    )
    for target_group in sorted(buckets):
        sublane_streams: Dict[str, list] = {}
        edge_ids: List[str] = []
        source_names: List[str] = []
        for sublane, contributions in buckets[target_group].items():
            resolved = _resolve_fan_in(contributions, sublane,
                                       song.name, report)
            if resolved:
                sublane_streams[sublane] = resolved
            for edge, _blocks in contributions:
                edge_ids.append(edge.edge_id)
                if edge.source_lane_name:
                    source_names.append(edge.source_lane_name)
        # Shared-channel gap flags (design doc 3.4; playback already
        # multiplies dimmer into colour-only groups).
        group = target_config.groups.get(target_group)
        caps = getattr(group, "capabilities", None)
        if caps is not None and not caps.has_dimmer:
            if "colour" in sublane_streams and \
                    "dimmer" not in sublane_streams:
                report.add("gap", song.name,
                           f"'{target_group}': colour routed with no "
                           f"dimmer stream on a colour-only group - "
                           f"likely an unintended always-on")
        envelopes = _build_envelopes(sublane_streams, source_names,
                                     edge_ids)
        if not envelopes:
            continue
        # Deterministic lane identity: (song, target, contributing
        # edges) - a re-morph reproduces the same id, so plans and
        # protection keep meaning across compiles (design doc 5.6).
        import hashlib
        lane_id = hashlib.sha256(
            f"morph:{song.name}:{target_group}:"
            f"{','.join(sorted(set(edge_ids)))}".encode()).hexdigest()[:32]
        morphed.timeline_data.lanes.append(LightLane(
            name=target_group,
            fixture_targets=[target_group],
            light_blocks=envelopes,
            lane_id=lane_id,
        ))
    return morphed


def compile_setlist(source_config, plan: MorphPlan, target_config,
                    stamp: Optional[Dict[str, str]] = None) -> MorphResult:
    """Compile every song in the source config through the plan.

    ``stamp`` carries the caller's timestamp/app-version for the
    lineage record (the compile itself never reads a clock)."""
    import hashlib
    import json

    report = MorphReport()
    problems = plan.validate(source_config=source_config,
                             target_config=target_config)
    for problem in problems:
        report.add("error", "-", problem)
    if report.has_errors:
        return MorphResult(songs={}, report=report, lineage={})

    plan_hash = hashlib.sha256(
        json.dumps(plan.to_dict(), sort_keys=True).encode()).hexdigest()
    lineage = {
        "plan_hash": plan_hash,
        "source_hash": plan.source_hash or config_hash(source_config),
        "target_hash": plan.target_hash or config_hash(target_config),
        **(stamp or {}),
    }

    songs: Dict[str, Song] = {}
    for name, song in source_config.songs.items():
        morphed = compile_song(song, plan, source_config, target_config,
                               report)
        if morphed is not None:
            morphed.lineage = dict(lineage)
            songs[name] = morphed
    return MorphResult(songs=songs, report=report, lineage=lineage)


# ---------------------------------------------------------------------------
# apply / re-morph (design doc 5.4, 5.5)
# ---------------------------------------------------------------------------

def pending_destruction(result: MorphResult, target_config,
                        plan: MorphPlan) -> List[str]:
    """What an apply would destroy: hand-edited blocks in unprotected
    lanes of same-named songs already in config B."""
    destroyed = []
    for name in result.songs:
        existing = target_config.songs.get(name)
        if existing is None or not existing.timeline_data:
            continue
        for lane in existing.timeline_data.lanes:
            if plan.is_protected(lane.name):
                continue
            for block in lane.light_blocks:
                if block.provenance == "hand_edited":
                    destroyed.append(
                        f"{name} / {lane.name}: hand-edited block "
                        f"{block.start_time:.2f}-{block.end_time:.2f}s")
    return destroyed


def apply_morph(result: MorphResult, target_config, plan: MorphPlan,
                force: bool = False) -> List[str]:
    """Write the morphed songs into config B (blunt replace, design doc
    5.4). Protected target lanes survive from the existing songs.

    Returns the destroyed-hand-edits manifest. Raises ``ValueError``
    when hand edits would be destroyed and ``force`` is False - the
    caller confirms with the manifest and retries with force=True."""
    destroyed = pending_destruction(result, target_config, plan)
    if destroyed and not force:
        raise ValueError(
            "re-morph would destroy hand-edited blocks; confirm with "
            "force=True:\n" + "\n".join(destroyed))
    for name, song in result.songs.items():
        existing = target_config.songs.get(name)
        if existing is not None and existing.timeline_data:
            protected = [lane for lane in existing.timeline_data.lanes
                         if plan.is_protected(lane.name)]
            for lane in protected:
                song.timeline_data.lanes = [
                    l for l in song.timeline_data.lanes
                    if l.name != lane.name]
                song.timeline_data.lanes.append(lane)
                result.report.add("note", name,
                                  f"target lane '{lane.name}' is "
                                  f"protected - left untouched")
        target_config.songs[name] = song
    for entry in destroyed:
        result.report.add("destroyed", "-", entry)
    return destroyed
