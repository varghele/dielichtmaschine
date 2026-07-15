# utils/morph/preflight.py
"""Phase 2 of venue adaptation: the on-site pre-flight checklist
(design doc 7). The morph reconciled the show with config B; this
reconciles config B with physical reality - a GENERATED, operator-
driven checklist. The capture rule (7.1) is load-bearing: captured
values land in the CONFIG (calibration, geometry), never in show
blocks.

This module is the checklist MODEL: generation from plan + setlist
(7.3), persistence with per-item completion state (7.4), and the
export-guard predicate (7.5). Driving the rig into testable states and
the capture UI ride the Live surface and land with the pre-flight
screen; every item is operator-confirmed - the automation is in
generating items, never in judging correctness (7.2).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml

from utils.morph.compile import SUBLANE_ATTRS
from utils.morph.plan import MorphPlan

#: generated order (design doc 7.3): cheapest and grossest-error first
ITEM_ORDER = ("flash", "spot_verify", "focus_capture", "colour_sanity",
              "special_verify", "scrub")


@dataclass
class PreflightItem:
    item_id: str
    kind: str                 # one of ITEM_ORDER
    group: str                # target group under test ("" for scrub)
    title: str
    instruction: str
    #: what the app should drive when the item runs (interpreted by the
    #: pre-flight screen; the model just records it)
    drive_state: Dict = field(default_factory=dict)
    done: bool = False
    result: str = ""          # "ok" | "fixed" | "" (pending)
    completed_at: str = ""    # ISO timestamp, caller-stamped

    def to_dict(self) -> Dict:
        return {
            "item_id": self.item_id, "kind": self.kind,
            "group": self.group, "title": self.title,
            "instruction": self.instruction,
            "drive_state": self.drive_state, "done": self.done,
            "result": self.result, "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "PreflightItem":
        return cls(**{k: data.get(k, v) for k, v in {
            "item_id": "", "kind": "", "group": "", "title": "",
            "instruction": "", "drive_state": {}, "done": False,
            "result": "", "completed_at": ""}.items()})


@dataclass
class PreflightChecklist:
    """The persisted checklist for one (plan, target config) pairing."""
    plan_hash: str = ""
    target_hash: str = ""
    items: List[PreflightItem] = field(default_factory=list)
    completed_at: str = ""    # stamped when the LAST item completes
    #: target-config content hash at completion time; a later
    #: calibration edit makes the completion stale (design doc 7.5)
    completed_target_hash: str = ""

    @property
    def complete(self) -> bool:
        return bool(self.items) and all(item.done for item in self.items)

    def pending(self) -> List[PreflightItem]:
        return [item for item in self.items if not item.done]

    def mark_done(self, item_id: str, result: str = "ok",
                  stamp: str = "") -> None:
        for item in self.items:
            if item.item_id == item_id:
                item.done = True
                item.result = result
                item.completed_at = stamp
                break

    def reopen(self, item_id: str) -> None:
        """The fix-and-re-test loop (design doc 7.2): remediation
        reopens the SAME item, never skips it."""
        for item in self.items:
            if item.item_id == item_id:
                item.done = False
                item.result = ""
                item.completed_at = ""
                break

    # -- persistence -------------------------------------------------------

    def to_dict(self) -> Dict:
        return {
            "preflight": 1,
            "plan_hash": self.plan_hash,
            "target_hash": self.target_hash,
            "completed_at": self.completed_at,
            "completed_target_hash": self.completed_target_hash,
            "items": [item.to_dict() for item in self.items],
        }

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.to_dict(), f, sort_keys=False,
                           allow_unicode=True)

    @classmethod
    def load(cls, path: str) -> "PreflightChecklist":
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        checklist = cls(
            plan_hash=data.get("plan_hash", ""),
            target_hash=data.get("target_hash", ""),
            completed_at=data.get("completed_at", ""),
            completed_target_hash=data.get("completed_target_hash", ""))
        checklist.items = [PreflightItem.from_dict(i)
                           for i in data.get("items", [])]
        return checklist

    @staticmethod
    def default_path(config_path: str) -> str:
        base, _ext = os.path.splitext(config_path)
        return base + ".preflight.yaml"


# ---------------------------------------------------------------------------
# generation (design doc 7.3)
# ---------------------------------------------------------------------------

def _routed_sublanes(source_config, plan: MorphPlan) -> Dict[str, set]:
    """target group -> sublanes any edge feeds (regenerate included)."""
    routed: Dict[str, set] = {}
    for song_name in source_config.songs:
        for edge in plan.edges_for_song(song_name):
            if edge.mode == "regenerate" \
                    and edge.regenerate_strategy == "manual":
                continue
            routed.setdefault(edge.target_group, set()).add(edge.sublane)
    return routed


def _spots_used(source_config, target_config) -> List[str]:
    """Spot names the morphed shows will aim at: every spot the target
    config defines that any movement block references, plus the target
    config's own spots as fallback references."""
    used = set()
    for song in source_config.songs.values():
        if not song.timeline_data:
            continue
        for lane in song.timeline_data.lanes:
            for lb in lane.light_blocks:
                for m in lb.movement_blocks:
                    if m.target_spot_name:
                        used.add(m.target_spot_name)
    known = set(getattr(target_config, "spots", {}) or {})
    return sorted(used & known) or sorted(known)


def _group_has_movement(target_config, group: str) -> bool:
    caps = getattr(target_config.groups.get(group), "capabilities", None)
    return caps is None or caps.has_movement


def generate_checklist(source_config, plan: MorphPlan, target_config,
                       busiest_song: Optional[str] = None
                       ) -> PreflightChecklist:
    """The checklist the morph already knows how to write (7.3):
    flash tests first (patch/address), then spot verification
    (orientation), focus capture, colour sanity (channel order / mode),
    specials, and a final scrub-through."""
    routed = _routed_sublanes(source_config, plan)
    spots = _spots_used(source_config, target_config)
    items: List[PreflightItem] = []

    def add(kind, group, title, instruction, drive_state):
        items.append(PreflightItem(
            item_id=f"{kind}:{group or 'show'}:{len(items):03d}",
            kind=kind, group=group, title=title,
            instruction=instruction, drive_state=drive_state))

    for group in sorted(routed):
        if "dimmer" in routed[group] or "colour" in routed[group]:
            add("flash", group, f"Flash test · {group}",
                "The app flashes the whole group at full. Confirm every "
                "fixture in the group lights - a silent fixture is a "
                "patch/address error.",
                {"group": group, "action": "flash_full"})

    for group in sorted(routed):
        if "movement" in routed[group] and \
                _group_has_movement(target_config, group):
            for spot in spots:
                add("spot_verify", group,
                    f"Aim check · {group} -> {spot}",
                    f"All movers of {group} aim at {spot}, full, white. "
                    f"Confirm the beams land there; INCORRECT branches "
                    f"into orientation calibration and re-tests this "
                    f"item.",
                    {"group": group, "action": "aim_spot", "spot": spot})
            add("focus_capture", group, f"Focus capture · {group}",
                "Adjust focus/zoom live until the beam edge is crisp at "
                "the working distance, then CAPTURE - the value lands "
                "in the fixture calibration, never in the show.",
                {"group": group, "action": "hold_aim_for_capture"})

    for group in sorted(routed):
        if "colour" in routed[group]:
            add("colour_sanity", group, f"Colour sanity · {group}",
                "The app steps RED, GREEN, BLUE. Confirm the colours "
                "match the labels - a swap means wrong channel order or "
                "a different fixture mode than the rig list claimed.",
                {"group": group, "action": "rgb_steps"})

    for group in sorted(routed):
        if "special" in routed[group]:
            add("special_verify", group, f"Beam check · {group}",
                "The app steps the routed gobo/prism states. Confirm "
                "they match.",
                {"group": group, "action": "special_steps"})

    scrub_song = busiest_song or (sorted(source_config.songs)[0]
                                  if source_config.songs else "")
    if scrub_song:
        add("scrub", "", f"Scrub-through · {scrub_song}",
            "Scrub the busiest section end to end and eyeball the "
            "whole picture.",
            {"song": scrub_song, "action": "scrub"})

    checklist = PreflightChecklist(items=items)
    return checklist


# ---------------------------------------------------------------------------
# export guard (design doc 7.5)
# ---------------------------------------------------------------------------

def export_guard_message(checklist_path: str,
                         current_target_hash: str) -> Optional[str]:
    """The hard warning the exporter must show, or None when clear.

    A `.qxw` export MATERIALIZES pan/tilt: exporting before pre-flight
    completion bakes uncalibrated geometry into the file. Also stale:
    the checklist completed, but the config changed afterwards."""
    if not os.path.exists(checklist_path):
        return None
    try:
        checklist = PreflightChecklist.load(checklist_path)
    except Exception:
        return None
    if not checklist.complete:
        remaining = len(checklist.pending())
        return (f"The venue pre-flight checklist is INCOMPLETE "
                f"({remaining} item(s) open). A .qxw export bakes the "
                f"current, unverified geometry into the file - native "
                f"playback would keep following calibration fixes, the "
                f"export will not.")
    if checklist.completed_target_hash and \
            current_target_hash != checklist.completed_target_hash:
        return ("The config changed AFTER the pre-flight checklist was "
                "completed - the export would bake geometry the "
                "checklist never verified. Re-run the affected items "
                "or re-complete the checklist.")
    return None
