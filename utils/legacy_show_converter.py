"""Best-effort converter: legacy ``ShowEffect`` shows -> modern timeline blocks.

Early shows stored lighting as a flat list of :class:`ShowEffect` entries
(``fixture_group`` + ``effect`` string ``"module.function"`` + ``intensity`` +
``color`` + ``speed`` + ``spot``, tied to a named ``show_part``). The current
engine renders *sublane* blocks (:class:`DimmerBlock` / :class:`ColourBlock` /
:class:`MovementBlock`) whose effect names come from ``DIMMER_REGISTRY`` /
``MOVEMENT_REGISTRY``. The two vocabularies have diverged, so this conversion is
**best-effort and lossy**:

* legacy effect names are mapped to their closest modern ``effect_type`` via
  :data:`LEGACY_EFFECT_MAP` (renames + nearest-equivalents);
* colour-texture effects with no modern intensity equivalent (``plasma``,
  ``rainbow_rgbw``) are approximated by a lit dimmer pattern while the legacy
  ``color`` is preserved as a :class:`ColourBlock`;
* per ``(group, part)`` all legacy effects are merged into a single
  :class:`LightBlock` envelope (one dimmer + optional colour + optional
  movement), rather than stacking overlapping blocks.

Anything unmapped falls back to a lit ``static`` dimmer so fixtures are at least
visible. :data:`LEGACY_EFFECT_MAP` is the one place to refine fidelity.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from config.models import (
    Song, TimelineData, LightLane, LightBlock,
    DimmerBlock, ColourBlock, MovementBlock,
)
from timeline.song_structure import SongStructure

# legacy "module.function" -> (sublane, modern effect_type, dimmer_direction)
# sublane is "dimmer" or "movement"; direction only matters for dimmer "fade".
_D = "dimmer"
_M = "movement"
LEGACY_EFFECT_MAP: Dict[str, Tuple[str, str, str]] = {
    # --- dimmer / intensity effects ---------------------------------------
    "dimmers.static": (_D, "static", "down"),
    "bars.static": (_D, "static", "down"),
    "dimmers.strobe": (_D, "strobe", "down"),
    "bars.strobe": (_D, "strobe", "down"),
    "bars.random_strobe": (_D, "strobe", "down"),      # randomized strobe -> strobe
    "dimmers.ping_pong_smooth": (_D, "ping_pong", "down"),
    "bars.ping_pong_smooth": (_D, "ping_pong", "down"),
    "bars.ping_pong": (_D, "ping_pong", "down"),
    "bars.heartbeat": (_D, "heartbeat", "down"),
    "bars.pulse": (_D, "pulse", "down"),
    "bars.breathing": (_D, "throb", "down"),           # breathing ~= throb
    "bars.wave": (_D, "wave", "down"),
    "dimmers.waterfall": (_D, "waterfall", "down"),
    "bars.flicker": (_D, "sparkle", "down"),           # random flicker ~= sparkle
    "bars.noise": (_D, "sparkle", "down"),
    "bars.starfall": (_D, "sparkle", "down"),
    "dimmers.twinkle": (_D, "sparkle", "down"),
    "moving_heads.twinkle": (_D, "sparkle", "down"),
    "bars.fade_in": (_D, "fade", "up"),
    "bars.fade_out": (_D, "fade", "down"),
    # colour-texture effects: no modern intensity twin -> keep fixtures lit and
    # let the ColourBlock carry the hue. plasma animates, rainbow stays lit.
    "bars.plasma": (_D, "wave", "down"),
    "multicolor.plasma": (_D, "wave", "down"),
    "bars.rainbow_rgbw": (_D, "static", "down"),
    # --- movement effects (also get a lit static dimmer) ------------------
    "moving_heads.whirl": (_M, "circle", "down"),
    "moving_heads.wave_sweep": (_M, "linear_sweep", "down"),
    "moving_heads.focus_on_spot": (_M, "static", "down"),
}

# Effects with no entry fall back to this (fixtures lit, no motion).
_FALLBACK = (_D, "static", "down")


def _colour_from_hex(hex_str: str, start: float, end: float) -> Optional[ColourBlock]:
    """Parse ``#RRGGBB`` into an RGB ColourBlock; None if empty/invalid."""
    if not hex_str:
        return None
    s = hex_str.lstrip("#").strip()
    if len(s) != 6:
        return None
    try:
        r, g, b = (int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None
    return ColourBlock(start_time=start, end_time=end, color_mode="RGB",
                       red=float(r), green=float(g), blue=float(b))


def convert_legacy_show(show: Song) -> TimelineData:
    """Convert a legacy effects-based :class:`Show` to modern ``TimelineData``.

    Returns fresh ``TimelineData`` (one lane per fixture group). The input
    show's ``parts`` supply block timing; its ``effects`` supply the content.
    """
    structure = SongStructure()
    structure.load_from_show_parts(show.parts)
    part_times = {p.name: (p.start_time, p.start_time + p.duration) for p in structure.parts}

    # Merge all legacy effects for a given (group, part) into one envelope.
    buckets: Dict[Tuple[str, str], List] = defaultdict(list)
    for e in show.effects:
        buckets[(e.fixture_group, e.show_part)].append(e)

    lanes: Dict[str, LightLane] = {}
    for (group, part_name), effs in buckets.items():
        if part_name not in part_times:
            continue
        start, end = part_times[part_name]

        # Colour: first effect that carries one.
        colour = next((_colour_from_hex(e.color, start, end) for e in effs
                       if _colour_from_hex(e.color, start, end)), None)

        # Dimmer: prefer a mapped *non-static* dimmer effect; brightness = the
        # brightest intensity requested for this group in this part.
        intensity = max((float(e.intensity) for e in effs), default=255.0)
        dim_choice = _FALLBACK
        speed = "1"
        for e in effs:
            sublane, etype, direction = LEGACY_EFFECT_MAP.get(e.effect, _FALLBACK)
            if sublane == _D and etype != "static":
                dim_choice = (sublane, etype, direction)
                speed = str(e.speed or "1")
                break
        dimmer = DimmerBlock(
            start_time=start, end_time=end, intensity=intensity,
            effect_type=dim_choice[1], effect_speed=speed, direction=dim_choice[2],
        )

        # Movement: first mapped movement effect (points at its spot if named).
        movement = None
        for e in effs:
            sublane, etype, _dir = LEGACY_EFFECT_MAP.get(e.effect, _FALLBACK)
            if sublane == _M:
                movement = MovementBlock(
                    start_time=start, end_time=end, effect_type=etype,
                    effect_speed=str(e.speed or "1"),
                    target_spot_name=(e.spot or None),
                )
                break

        block = LightBlock(start_time=start, end_time=end,
                           effect_name=f"legacy:{part_name}", name=part_name)
        block.dimmer_blocks = [dimmer]
        if colour:
            block.colour_blocks = [colour]
        if movement:
            block.movement_blocks = [movement]

        lane = lanes.get(group)
        if lane is None:
            lane = LightLane(name=group, fixture_targets=[group], light_blocks=[])
            lanes[group] = lane
        lane.light_blocks.append(block)

    return TimelineData(lanes=list(lanes.values()))


def convert_show_in_place(show: Song, audio_file_path: Optional[str] = None) -> Song:
    """Populate ``show.timeline_data`` from its legacy effects (kept intact)."""
    td = convert_legacy_show(show)
    td.audio_file_path = audio_file_path
    show.timeline_data = td
    return show
