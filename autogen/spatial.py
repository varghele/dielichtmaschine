"""Spatial lighting model for algorithmic show generation.

Implements Section 6 of the theory: fixture group classification by
stage position, vocal focus rules, density scaling, and gobo/prism activation.
"""

from enum import Enum
from typing import Dict, List, Optional
from dataclasses import dataclass

from config.models import (
    Configuration, FixtureGroup, Spot, StagePlane, primary_group,
)


class ActivationRole(Enum):
    """Role a fixture group plays within a section's phrase structure."""
    FULL = "full"            # Plays both groove and fill blocks
    GROOVE_ONLY = "groove"   # Plays only groove blocks
    FILL_ONLY = "fill"       # Plays only fill blocks (punches in for fills)


class LightingRole(Enum):
    """Semantic role a fixture group plays in the show design.

    Assigned by the user in config YAML, used by autogen for
    activation priority and temporal behavior.

    Rhythm and movement are attributes (applied per-section by the
    algorithm), not roles. Any role can have rhythmic or movement
    behavior depending on the section's audio character.
    """
    WASH = "wash"        # Base illumination, broad coverage, always on
    KEY = "key"          # Front-of-stage visibility, vocal-aware, always on
    TEXTURE = "texture"  # Gobos, prism, breakup patterns, medium+ energy
    ACCENT = "accent"    # Sparse, high-impact peaks — strobes, blinders


@dataclass
class GroupActivation:
    """Activation state for a fixture group in a section."""
    weight: float            # 0.0 = inactive, 0.1-1.0 = intensity weight
    role: ActivationRole = ActivationRole.FULL


@dataclass
class GroupClassification:
    """Stage position and role classification for a fixture group."""
    name: str
    zone: str  # "front", "mid", "back", "overhead"
    has_moving_heads: bool = False
    has_gobos: bool = False
    has_prism: bool = False
    lighting_role: str = ""  # User-assigned: backbone, accent, ambient, movement, effect


def classify_fixture_groups(config: Configuration) -> Dict[str, GroupClassification]:
    """Classify each fixture group by stage position.

    Classification based on average Y and Z positions of group's fixtures,
    relative to stage dimensions.

    Coordinate convention (matches ``gui/StageView.py`` and the 3D
    visualiser): X and Y are both **centered** at the origin, with
    ``y < 0`` downstage (closer to audience) and ``y > 0`` upstage.
    Valid Y range is therefore ``[-stage_height/2, +stage_height/2]``.

    Zone thresholds split that range into thirds: a group is "front" if
    its average Y is in the lower third (≤ ``-stage_height/6``), "back"
    if it's in the upper third (≥ ``+stage_height/6``), and "mid"
    otherwise. "overhead" overrides the Y zone when fixtures sit above
    half the assumed ceiling height (4 m default).

    Earlier versions used ``avg_y < D * 0.33`` / ``avg_y > D * 0.66``
    which assumed Y ranged ``[0, D]``. With the real centered-Y data
    almost every fixture got classified "front" because ``avg_y < D*0.33``
    is true for any ``y`` in roughly the lower 0.83 of the stage. That
    broke ``apply_vocal_rule`` (which boosts front fixtures during
    vocals) and ``_group_activation_priority`` (zone-based cascade).

    Returns:
        {group_name: GroupClassification}
    """
    stage_depth = config.stage_height  # Y axis = depth, centered at 0
    stage_z = 4.0  # Default ceiling height estimate (z is bottom-up, not centered)

    # Split the stage into thirds along Y, expressed in centered
    # coordinates. ``front_threshold`` is the upper bound of the
    # downstage third; ``back_threshold`` is the lower bound of the
    # upstage third. The middle third sits between them.
    front_threshold = -stage_depth / 6.0
    back_threshold = stage_depth / 6.0

    classifications = {}
    for group_name, group in config.groups.items():
        if not group.fixtures:
            continue

        # Average position
        avg_y = sum(f.y for f in group.fixtures) / len(group.fixtures)
        avg_z = sum(
            f.get_effective_z(group) if hasattr(f, 'get_effective_z') else getattr(f, 'z', 0.0)
            for f in group.fixtures
        ) / len(group.fixtures)

        # Classify zone
        if avg_z > stage_z * 0.5:
            zone = "overhead"
        elif stage_depth > 0 and avg_y < front_threshold:
            zone = "front"
        elif stage_depth > 0 and avg_y > back_threshold:
            zone = "back"
        else:
            zone = "mid"

        # Detect capabilities
        has_mh = any(
            getattr(f, 'type', '') in ('MH', 'WASH')
            for f in group.fixtures
        )

        capabilities = group.capabilities
        has_special = False
        if capabilities:
            has_special = getattr(capabilities, 'has_special', False)
        # If no capabilities detected, infer from fixture type (MH/WASH often have gobos)
        if not has_special and has_mh:
            has_special = True
        has_gobos = has_special
        has_prism = has_special

        classifications[group_name] = GroupClassification(
            name=group_name,
            zone=zone,
            has_moving_heads=has_mh,
            has_gobos=has_gobos,
            has_prism=has_prism,
            lighting_role=getattr(group, 'lighting_role', ''),
        )

    return classifications


def apply_vocal_rule(
    group_classifications: Dict[str, GroupClassification],
    vocal_presence: float,
) -> Dict[str, float]:
    """Compute intensity weight per group based on vocal presence.

    When vocals are present, front-stage groups get boosted.
    When absent, back/overhead groups get boosted.

    Returns:
        {group_name: weight} where weight is 0.0-1.0 multiplier
    """
    weights = {}
    for name, gc in group_classifications.items():
        if vocal_presence > 0.5:
            # Vocals present — prioritize front
            if gc.zone == "front":
                weights[name] = 1.0
            elif gc.zone == "mid":
                weights[name] = 0.7
            elif gc.zone == "back":
                weights[name] = 0.4
            else:  # overhead
                weights[name] = 0.5
        else:
            # No vocals — atmospheric
            if gc.zone == "front":
                weights[name] = 0.4
            elif gc.zone == "mid":
                weights[name] = 0.6
            elif gc.zone == "back":
                weights[name] = 1.0
            else:  # overhead
                weights[name] = 0.9

    return weights


def _group_activation_priority(gc: GroupClassification) -> int:
    """Activation priority: lower = activated first."""
    ROLE_PRIORITY = {
        "wash": 0, "key": 1, "texture": 2, "accent": 3,
    }
    if gc.lighting_role:
        return ROLE_PRIORITY.get(gc.lighting_role, 2)
    # Fallback: zone-based priority for unconfigured groups
    zone_priority = {"front": 0, "mid": 1, "overhead": 2, "back": 3}
    return zone_priority.get(gc.zone, 2)


# Role-based minimum energy thresholds and base weights
_ROLE_ENERGY_CONFIG = {
    #           (min_energy, low_weight, full_weight)
    "wash":     (0.00, 0.50, 1.0),   # Always active, at least half intensity
    "key":      (0.00, 0.30, 0.8),   # Always active, subtle, vocal-aware
    "texture":  (0.40, 0.50, 1.0),   # Gobos/prism at medium+ energy
    "accent":   (0.60, 0.70, 1.0),   # Only at peaks, punchy
}


def compute_richness_weights(
    group_classifications: Dict[str, GroupClassification],
    spectral_richness: float,
    spectral_flux: float = 0.5,
    relative_energy: float = 0.5,
) -> Dict[str, float]:
    """Compute intensity weight per group based on relative energy level.

    When fixture groups have lighting_role assigned, uses role-based
    activation thresholds (backbone always on, accent only at peaks).
    Falls back to tiered zone-based activation for unconfigured groups.

    Returns:
        {group_name: weight} where 0.0 = inactive, 0.1-1.0 = active
    """
    if not group_classifications:
        return {}

    has_roles = any(gc.lighting_role for gc in group_classifications.values())

    if has_roles:
        # Role-based activation: each role has its own energy threshold
        weights = {}
        for name, gc in group_classifications.items():
            role = gc.lighting_role
            if role and role in _ROLE_ENERGY_CONFIG:
                min_energy, low_weight, full_weight = _ROLE_ENERGY_CONFIG[role]
                if relative_energy < min_energy:
                    weights[name] = 0.0
                else:
                    # Interpolate from low_weight to full_weight as energy rises
                    # above the threshold toward 1.0
                    headroom = 1.0 - min_energy
                    if headroom > 0:
                        t = min(1.0, (relative_energy - min_energy) / headroom)
                    else:
                        t = 1.0
                    weights[name] = low_weight + t * (full_weight - low_weight)
            else:
                # No role assigned: use energy-proportional weight with zone fallback
                weights[name] = max(0.3, relative_energy) if relative_energy > 0.15 else 0.0
        return weights

    # Fallback: original zone-based tiered activation
    sorted_groups = sorted(
        group_classifications.items(),
        key=lambda x: _group_activation_priority(x[1])
    )

    total = len(sorted_groups)
    weights = {}

    if relative_energy < 0.15:
        for i, (name, gc) in enumerate(sorted_groups):
            weights[name] = 0.3 if i == 0 else 0.0
    elif relative_energy < 0.35:
        num_active = max(1, min(2, total))
        for i, (name, gc) in enumerate(sorted_groups):
            if i < num_active:
                weights[name] = 0.7 if i == 0 else 0.4
            else:
                weights[name] = 0.0
    elif relative_energy < 0.65:
        num_active = max(2, int(total * 0.75))
        for i, (name, gc) in enumerate(sorted_groups):
            if i < num_active:
                weights[name] = 1.0 - i * 0.1
            else:
                weights[name] = 0.0
    else:
        for name in group_classifications:
            weights[name] = 1.0

    return weights


def assign_group_roles(
    per_group_rudiments: Dict[str, tuple],
    relative_energy: float,
    group_classifications: Optional[Dict[str, 'GroupClassification']] = None,
) -> Dict[str, ActivationRole]:
    """Derive activation roles from rudiment assignments and lighting roles.

    When lighting_role is assigned, it overrides envelope-based logic:
    - wash → FULL always (carries both groove and fill)
    - key → GROOVE_ONLY (steady presence, no fill variation)
    - accent → FILL_ONLY at low/medium energy (punch-in for impact)
    - texture → use existing envelope-based logic

    When no roles are assigned, falls back to envelope category logic:
    - SPIKE / STOCHASTIC envelopes → fill character
    - FLAT / RAMP / ROLLING envelopes → groove character
    - OSCILLATING → versatile

    A safety check ensures at least one group always carries the groove.
    """
    from rudiments.registry import get_intensity_rudiments
    from rudiments.rudiment import EnvelopeCategory

    if not per_group_rudiments:
        return {}

    # High energy: everyone plays everything
    if relative_energy >= 0.65:
        return {g: ActivationRole.FULL for g in per_group_rudiments}

    intensity_rudiments = get_intensity_rudiments()

    FILL_CATEGORIES = {EnvelopeCategory.SPIKE, EnvelopeCategory.STOCHASTIC}
    GROOVE_CATEGORIES = {EnvelopeCategory.FLAT, EnvelopeCategory.RAMP, EnvelopeCategory.ROLLING}

    roles = {}
    for group_name, (groove_name, _fill_name) in per_group_rudiments.items():
        # Check for lighting role override first
        gc = group_classifications.get(group_name) if group_classifications else None
        role_str = gc.lighting_role if gc else ""

        if role_str == "wash":
            roles[group_name] = ActivationRole.FULL
            continue
        elif role_str == "key":
            roles[group_name] = ActivationRole.GROOVE_ONLY
            continue
        elif role_str == "accent":
            roles[group_name] = ActivationRole.FILL_ONLY
            continue
        # texture / empty → fall through to envelope logic

        rudiment = intensity_rudiments.get(groove_name)
        if not rudiment:
            roles[group_name] = ActivationRole.FULL
            continue

        category = rudiment.envelope.category
        is_fill_character = category in FILL_CATEGORIES

        if relative_energy < 0.35:
            if is_fill_character:
                roles[group_name] = ActivationRole.FILL_ONLY
            else:
                roles[group_name] = ActivationRole.GROOVE_ONLY
        else:
            if is_fill_character:
                roles[group_name] = ActivationRole.FILL_ONLY
            else:
                roles[group_name] = ActivationRole.FULL

    # Safety: ensure at least one group carries the groove
    has_groove = any(r != ActivationRole.FILL_ONLY for r in roles.values())
    if not has_groove and roles:
        first = next(iter(per_group_rudiments))
        roles[first] = (
            ActivationRole.GROOVE_ONLY if relative_energy < 0.35
            else ActivationRole.FULL
        )

    return roles


def get_gobo_prism_groups(
    group_classifications: Dict[str, GroupClassification],
    spectral_richness: float,
    gobo_threshold: float = 0.7,
    prism_threshold: float = 0.8,
) -> Dict[str, Dict[str, bool]]:
    """Determine which groups should have gobos/prisms activated.

    Returns:
        {group_name: {"gobo": bool, "prism": bool}}
    """
    result = {}
    for name, gc in group_classifications.items():
        result[name] = {
            "gobo": gc.has_gobos and spectral_richness >= gobo_threshold,
            "prism": gc.has_prism and spectral_richness >= prism_threshold,
        }
    return result


def ensure_default_spots(config: Configuration) -> List[str]:
    """Create default plane-center spots if none exist. Returns list of spot names.

    Creates center spots for sweep planes:
    - "Crowd" — center of audience area (y=0), moving heads sweep across with amplitude
    - "Stage" — center of stage area, for atmospheric sweeps
    User-defined spots are preserved and take priority.
    """
    if config.spots:
        return list(config.spots.keys())

    stage_w = config.stage_width if hasattr(config, 'stage_width') and config.stage_width else 8.0
    stage_d = config.stage_height if hasattr(config, 'stage_height') and config.stage_height else 6.0

    # Plane center spots — shapes sweep around these with amplitude controlling width
    default_spots = {
        "Crowd": Spot(name="Crowd", x=0.0, y=0.0, z=0.0),
        "Stage": Spot(name="Stage", x=0.0, y=stage_d * 0.5, z=0.0),
    }

    for name, spot in default_spots.items():
        config.spots[name] = spot

    return list(default_spots.keys())


def compute_stage_planes(config: Configuration) -> List[StagePlane]:
    """Compute the 6 faces of the stage bounding cuboid as target planes.

    Stage coordinate system:
    - X: left-right (centered at 0), range [-W/2, W/2]
    - Y: depth (0 = front/audience, D = back of stage)
    - Z: height (0 = floor, max_Z = highest fixture)

    Returns planes with inward-facing normals and tangent axes for
    projecting movement patterns onto each face.
    """
    w = config.stage_width if hasattr(config, 'stage_width') and config.stage_width else 10.0
    d = config.stage_height if hasattr(config, 'stage_height') and config.stage_height else 6.0

    # Compute max Z from fixtures
    max_z = 3.0  # default minimum
    for fixture in config.fixtures:
        group = primary_group(config, fixture)
        z = fixture.get_effective_z(group)
        if z > max_z:
            max_z = z

    hw = w / 2.0  # half width
    hd = d / 2.0  # half depth
    hz = max_z / 2.0  # half height

    return [
        StagePlane("Floor",   (0.0, hd, 0.0),     (0, 0, 1),   (1, 0, 0), (0, 1, 0)),
        StagePlane("Ceiling", (0.0, hd, max_z),    (0, 0, -1),  (1, 0, 0), (0, 1, 0)),
        StagePlane("Front",   (0.0, 0.0, hz),      (0, 1, 0),   (1, 0, 0), (0, 0, 1)),
        StagePlane("Back",    (0.0, d, hz),         (0, -1, 0),  (1, 0, 0), (0, 0, 1)),
        StagePlane("Left",    (-hw, hd, hz),        (1, 0, 0),   (0, 1, 0), (0, 0, 1)),
        StagePlane("Right",   (hw, hd, hz),         (-1, 0, 0),  (0, 1, 0), (0, 0, 1)),
    ]
