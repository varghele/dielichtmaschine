"""Computed position presets for the Live tab's POSITION pool.

The pool's PRESETS subsection is not a list of canned looks: every
preset is computed from the stage setup the config already carries
(stage dimensions, mover positions, stage layers, placed stage
elements). A preset is either a POINT (all beams converge on one
derived point - CENTRE, AUDIENCE, and one preset per placed element
the catalog knows a focus for) or a PATTERN (each mover derives its
own target from its own position - CROSS, FAN OUT, FLOOR, CEILING).

Presets carry real target data from day one (``target_for``), but no
pan/tilt math: converting a target into per-fixture pan/tilt is the
v1.5a focus-geometry milestone, and making a light move is the output
arbiter (todo.md). Same in-memory honesty as the whole Live surface.

COORDINATE FRAME: config/stage space - X centered left-right, Y depth
centered with NEGATIVE = front/audience, Z height, meters. Do NOT mix
in autogen/spatial.py's 0..D depth convention (CLAUDE.md gotcha).

Position ids are namespaced so LiveState can prune by origin:

- ``preset:<name>``           geometry preset, never pruned
- ``preset:element:<id>``     element preset, pruned with its element
- ``mark:<spot name>``        spike mark, pruned with its spot
"""

from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

# -- id namespaces ----------------------------------------------------------

PRESET_PREFIX = "preset:"
ELEMENT_PRESET_PREFIX = "preset:element:"
MARK_PREFIX = "mark:"


def mark_id(spot_name: str) -> str:
    """The position id for a spike mark (``config.spots`` key)."""
    return MARK_PREFIX + spot_name


def mark_name(position_id: str) -> str:
    """The spot name back out of a ``mark:`` position id."""
    return position_id[len(MARK_PREFIX):]


# -- geometry constants (meters) --------------------------------------------

# CENTRE: centre stage at a body-high focus point.
CENTRE_FOCUS_HEIGHT = 1.5
# AUDIENCE: this far past the downstage edge, at head height.
AUDIENCE_THROW = 3.0
AUDIENCE_HEAD_HEIGHT = 2.0
# CROSS: beams scissor across the centreline onto the floor zone.
CROSS_FLOOR_HEIGHT = 0.5
# ...fixtures closer to the centreline than this band mirror to a fixed
# throw instead of -x (mirroring 0.1 m to -0.1 m would not read as a
# cross at all).
CROSS_CENTRE_BAND = 0.3
CROSS_CENTRE_THROW = 1.5
# FAN OUT: outward past the stage edges, raised.
FAN_THROW = 2.0
FAN_HEIGHT = 4.0
# CEILING: straight up from wherever the fixture hangs.
CEILING_RAISE = 10.0
# FLOOR: straight down to the deck directly beneath the fixture - the
# natural rest for a hanging mover (CEILING is its standing counterpart).
FLOOR_Z = 0.0
# Element presets focus this far above the element's plane (its stage
# layer's z_height, or the deck at 0).
ELEMENT_FOCUS_RAISE = 1.2

# Placed stage elements that earn a preset (StageElement.kind from
# utils/stage_element_catalog.py -> preset label). Duplicate kinds get
# a numeric suffix ("Drums 2").
ELEMENT_PRESET_KINDS = {
    "drum-riser": "Drums",
    "keys": "Keys",
    "foh": "FOH",
    "mic-stand": "Mic",
}

KIND_POINT = "point"
KIND_PATTERN = "pattern"


def group_has_movers(group) -> bool:
    """Whether a fixture group can take a position palette (pan/tilt).

    Keys on the group's auto-detected sublane capabilities
    (``FixtureGroupCapabilities.has_movement`` - set when the fixture
    definitions carry Pan/Tilt channels, the same flag the timeline's
    movement sublane keys on). Falls back to the fixture-type test used
    by autogen/spatial.py (type ``MH`` / ``WASH``) for configs whose
    capabilities were never scanned. Shared by the Live tab's pool
    gating and the busk output layer's position pass.
    """
    caps = getattr(group, "capabilities", None)
    if caps is not None and getattr(caps, "has_movement", False):
        return True
    return any(getattr(f, "type", "") in ("MH", "WASH")
               for f in (getattr(group, "fixtures", None) or []))

# The tag shown under pattern presets (point presets show their target
# coordinates, mono, like the spike-mark cells).
PATTERN_TAG = "Per fixture"


@dataclass(frozen=True)
class PositionPreset:
    """One computed preset: identity + label + a target resolver.

    ``point`` presets ignore the fixture and return the shared target;
    ``pattern`` presets derive the target from the fixture's own
    position via the ``pattern`` callable.
    """

    preset_id: str
    label: str
    kind: str                # KIND_POINT | KIND_PATTERN
    tag: str
    point: Optional[Tuple[float, float, float]] = None
    pattern: Optional[Callable] = None   # fixture -> (x, y, z)

    def target_for(self, fixture) -> Tuple[float, float, float]:
        """The stage-space target (x, y, z) for this fixture."""
        if self.kind == KIND_POINT:
            return self.point
        return self.pattern(fixture)


def _coord_tag(x: float, y: float) -> str:
    """The small mono coordinate tag, same format as the mark cells."""
    return f"{x:.1f} · {y:.1f}"


def _cross_target(fixture) -> Tuple[float, float, float]:
    x = float(getattr(fixture, "x", 0.0))
    y = float(getattr(fixture, "y", 0.0))
    if abs(x) < CROSS_CENTRE_BAND:
        # Near-centre: a fixed throw to the OTHER side so the beam still
        # crosses the centreline; sign(0) = +1 counts as stage right.
        target_x = -CROSS_CENTRE_THROW if x >= 0 else CROSS_CENTRE_THROW
    else:
        target_x = -x
    return (target_x, min(y, 0.0), CROSS_FLOOR_HEIGHT)


def _make_fan_target(stage_width: float) -> Callable:
    def _fan_target(fixture) -> Tuple[float, float, float]:
        x = float(getattr(fixture, "x", 0.0))
        y = float(getattr(fixture, "y", 0.0))
        throw = stage_width / 2.0 + FAN_THROW
        # sign(0) = +1: a dead-centre fixture fans stage right.
        return (throw if x >= 0 else -throw, y, FAN_HEIGHT)
    return _fan_target


def _ceiling_target(fixture) -> Tuple[float, float, float]:
    return (float(getattr(fixture, "x", 0.0)),
            float(getattr(fixture, "y", 0.0)),
            float(getattr(fixture, "z", 0.0)) + CEILING_RAISE)


def _floor_target(fixture) -> Tuple[float, float, float]:
    """Straight down: the deck point directly beneath the fixture."""
    return (float(getattr(fixture, "x", 0.0)),
            float(getattr(fixture, "y", 0.0)),
            FLOOR_Z)


def _element_identity(element, index: int) -> str:
    """A stable identity for the element preset id. Falls back to the
    config position for legacy elements without an element_id (the
    fallback is deterministic per rebuild; compute_presets and
    element_preset_ids derive it identically, so pruning stays exact)."""
    return element.element_id or f"idx{index}"


def _element_focus_z(config, element) -> float:
    layer = config.get_stage_layer(element.layer) if element.layer else None
    base = layer.z_height if layer is not None else 0.0
    return base + ELEMENT_FOCUS_RAISE


def compute_presets(config) -> List[PositionPreset]:
    """All computable presets for this config, in deterministic order:
    the five geometry presets, then one preset per placed stage element
    whose kind is in ELEMENT_PRESET_KINDS (config.stage_elements
    order), duplicate kinds suffixed ("Drums 2")."""
    stage_width = float(getattr(config, "stage_width", 10.0))
    # Stage depth (the model calls it stage_height for compatibility).
    stage_depth = float(getattr(config, "stage_height", 6.0))

    centre = (0.0, 0.0, CENTRE_FOCUS_HEIGHT)
    audience = (0.0, -(stage_depth / 2.0 + AUDIENCE_THROW),
                AUDIENCE_HEAD_HEIGHT)
    presets = [
        PositionPreset("preset:centre", "Centre", KIND_POINT,
                       _coord_tag(centre[0], centre[1]), point=centre),
        PositionPreset("preset:audience", "Audience", KIND_POINT,
                       _coord_tag(audience[0], audience[1]),
                       point=audience),
        PositionPreset("preset:cross", "Cross", KIND_PATTERN,
                       PATTERN_TAG, pattern=_cross_target),
        PositionPreset("preset:fanout", "Fan Out", KIND_PATTERN,
                       PATTERN_TAG, pattern=_make_fan_target(stage_width)),
        PositionPreset("preset:floor", "Floor", KIND_PATTERN,
                       PATTERN_TAG, pattern=_floor_target),
        PositionPreset("preset:ceiling", "Ceiling", KIND_PATTERN,
                       PATTERN_TAG, pattern=_ceiling_target),
    ]

    label_counts: dict = {}
    for index, element in enumerate(getattr(config, "stage_elements", [])
                                    or []):
        base_label = ELEMENT_PRESET_KINDS.get(element.kind)
        if base_label is None:
            continue
        label_counts[base_label] = label_counts.get(base_label, 0) + 1
        count = label_counts[base_label]
        label = base_label if count == 1 else f"{base_label} {count}"
        point = (float(element.x), float(element.y),
                 _element_focus_z(config, element))
        presets.append(PositionPreset(
            ELEMENT_PRESET_PREFIX + _element_identity(element, index),
            label, KIND_POINT, _coord_tag(point[0], point[1]),
            point=point))
    return presets


def element_preset_ids(config) -> List[str]:
    """The currently valid ``preset:element:`` ids, for LiveState's
    pruning (an element preset whose element left the config is
    stale)."""
    ids = []
    for index, element in enumerate(getattr(config, "stage_elements", [])
                                    or []):
        if element.kind in ELEMENT_PRESET_KINDS:
            ids.append(ELEMENT_PRESET_PREFIX
                       + _element_identity(element, index))
    return ids
