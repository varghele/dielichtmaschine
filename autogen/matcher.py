"""Rudiment matching engine for algorithmic show generation.

Implements three-dimensional rudiment matching (Section 2.5) and
dual-criteria scoring (Section 5, Steps 4-7) from the theory.
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from audio.spectral_analysis import SectionAnalysis
from rudiments.rudiment import (
    Rudiment, EnvelopeCategory, CycleMode,
)
from rudiments.registry import get_intensity_rudiments


@dataclass
class MatchScore:
    """Scoring result for a rudiment candidate."""
    rudiment_name: str
    envelope_similarity: float = 0.0  # 0.0 to 1.0
    repetition_rate_fit: float = 0.0  # 0.0 to 1.0 (cycling only)
    flux_level_fit: float = 0.0       # 0.0 to 1.0
    fidelity_score: float = 0.0       # Weighted parameter fidelity
    coherence_score: float = 0.0      # Musical coherence
    total_score: float = 0.0


@dataclass
class AutogenConfig:
    """Configuration for automatic show generation."""
    groove_fill_ratio: float = 0.75
    phrase_length_bars: int = 4
    fidelity_weight: float = 0.6
    coherence_weight: float = 0.4
    tolerance_band_width: float = 0.2
    spectral_richness_gobo_threshold: float = 0.7
    spectral_richness_prism_threshold: float = 0.8
    cross_section_contrast_min: float = 0.3
    color_complementary_range: Tuple[float, float] = (30.0, 120.0)


# ──────────────────────────────────────────────
# Envelope comparison
# ──────────────────────────────────────────────

def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors. Returns 0.0-1.0."""
    if len(a) != len(b) or len(a) == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return max(0.0, dot / (mag_a * mag_b))


def score_envelope_similarity(
    rudiment_envelope: List[float],
    target_envelope: List[float],
) -> float:
    """Compare rudiment envelope shape to target flux contour.

    Uses cosine similarity on normalized vectors.
    """
    return cosine_similarity(rudiment_envelope, target_envelope)


# ──────────────────────────────────────────────
# Transient character filtering
# ──────────────────────────────────────────────

# Percussive audio favors these envelope categories
PERCUSSIVE_CATEGORIES = {
    EnvelopeCategory.SPIKE,
    EnvelopeCategory.OSCILLATING,
    EnvelopeCategory.STOCHASTIC,
}

# Sustained audio favors these
SUSTAINED_CATEGORIES = {
    EnvelopeCategory.FLAT,
    EnvelopeCategory.RAMP,
    EnvelopeCategory.OSCILLATING,
    EnvelopeCategory.ROLLING,
}


def _transient_category_score(rudiment: Rudiment, transient_sharpness: float) -> float:
    """Score how well a rudiment's envelope category matches the transient character.

    Returns 0.0-1.0.
    """
    category = rudiment.envelope.category

    if transient_sharpness > 0.6:
        # Percussive — prefer spike/oscillating/stochastic
        return 1.0 if category in PERCUSSIVE_CATEGORIES else 0.4
    elif transient_sharpness < 0.3:
        # Sustained — prefer flat/ramp/oscillating/rolling
        return 1.0 if category in SUSTAINED_CATEGORIES else 0.4
    else:
        # Mixed — all categories acceptable
        return 0.8


# ──────────────────────────────────────────────
# Repetition rate scoring
# ──────────────────────────────────────────────

def score_repetition_rate(
    rudiment: Rudiment,
    target_flux_frequency: float,
    bpm: float,
    speed_range: Tuple[float, float] = (0.25, 4.0),
) -> float:
    """Score how well the cycle rate matches audio flux frequency.

    Only applicable to cycling rudiments. One-shot rudiments get 1.0.

    Args:
        rudiment: The rudiment to score
        target_flux_frequency: Estimated rate of spectral flux changes (cycles/sec)
        bpm: Section BPM
        speed_range: Allowed speed multiplier range

    Returns:
        0.0-1.0 score
    """
    if rudiment.envelope.cycle_mode == CycleMode.ONE_SHOT:
        return 1.0

    if bpm <= 0 or target_flux_frequency <= 0:
        return 0.5

    beats_per_sec = bpm / 60.0

    # Check if any speed multiplier in range produces a matching cycle rate
    best_match = 0.0
    for speed in [0.25, 0.5, 1.0, 2.0, 4.0]:
        if speed < speed_range[0] or speed > speed_range[1]:
            continue
        # Cycles per second at this speed (assuming 1 cycle per beat)
        cycle_rate = beats_per_sec * speed
        # How close to the target?
        if target_flux_frequency > 0:
            ratio = cycle_rate / target_flux_frequency
            # Perfect match = ratio of 1.0, score decreases with distance
            log_ratio = abs(math.log2(max(0.01, ratio)))
            match = max(0.0, 1.0 - log_ratio * 0.5)
            best_match = max(best_match, match)

    return best_match


# ──────────────────────────────────────────────
# Flux level scoring
# ──────────────────────────────────────────────

def score_flux_level(
    rudiment: Rudiment,
    target_flux: float,
    tolerance: float = 0.2,
) -> float:
    """Score how well the rudiment's average flux matches the target.

    Args:
        rudiment: The rudiment to score
        target_flux: Target flux level (0.0-1.0)
        tolerance: Tolerance band width

    Returns:
        0.0-1.0 score (1.0 = within tolerance, decreases outside)
    """
    diff = abs(rudiment.average_flux - target_flux)
    if diff <= tolerance:
        return 1.0
    # Smooth falloff outside tolerance
    return max(0.0, 1.0 - (diff - tolerance) / 0.5)


# ──────────────────────────────────────────────
# Musical coherence scoring
# ──────────────────────────────────────────────

def score_musical_coherence(
    groove_rudiment: str,
    fill_rudiment: Optional[str],
    previous_section_rudiments: Optional[Dict[str, str]],
    section_type: str,
    previous_section_type: Optional[str],
    groove_flux: float,
    fill_flux: float,
    config: AutogenConfig,
) -> float:
    """Score musical coherence of a rudiment selection.

    Rewards:
    - Cross-section contrast (different types get different rudiments)
    - Fill flux > groove flux

    Penalizes:
    - Identical selections across different section types
    """
    score = 0.5  # Baseline

    # Fill must have higher flux than groove
    if fill_rudiment and fill_flux > groove_flux:
        score += 0.2
    elif fill_rudiment and fill_flux <= groove_flux:
        score -= 0.3  # Penalty

    # Cross-section contrast
    if previous_section_rudiments and previous_section_type:
        if section_type != previous_section_type:
            # Different section type — reward different rudiment selection
            prev_rudiments = set(previous_section_rudiments.values())
            if groove_rudiment not in prev_rudiments:
                score += 0.3  # Good contrast
            else:
                score -= 0.2  # Same rudiment across different section types

    return max(0.0, min(1.0, score))


# ──────────────────────────────────────────────
# Main matching function
# ──────────────────────────────────────────────

def match_rudiments_to_section(
    section: SectionAnalysis,
    bpm: float,
    has_moving_heads: bool = False,
    previous_section_rudiments: Optional[Dict[str, str]] = None,
    section_type: str = "generic",
    previous_section_type: Optional[str] = None,
    config: Optional[AutogenConfig] = None,
) -> Dict[str, MatchScore]:
    """Select best intensity rudiment for a section.

    Applies the three-dimensional matching from theory Section 2.5:
    1. Filter by transient character
    2. Score envelope similarity
    3. Score repetition rate
    4. Score flux level

    Args:
        section: Audio analysis for this section
        bpm: Section BPM
        has_moving_heads: Whether fixture group has moving heads
        previous_section_rudiments: Rudiments used in previous section
        section_type: Section type (e.g., "verse", "chorus")
        previous_section_type: Previous section type
        config: Auto-generation configuration

    Returns:
        Dict of {rudiment_name: MatchScore} sorted by total_score descending
    """
    if config is None:
        config = AutogenConfig()

    intensity_rudiments = get_intensity_rudiments()
    target_flux = section.spectral_flux_avg
    target_envelope = section.spectral_flux_envelope
    transient = section.transient_sharpness

    # Estimate flux change frequency from envelope
    if len(target_envelope) > 1:
        # Count zero-crossings of derivative as proxy for frequency
        diffs = [target_envelope[i + 1] - target_envelope[i] for i in range(len(target_envelope) - 1)]
        zero_crossings = sum(1 for i in range(len(diffs) - 1) if diffs[i] * diffs[i + 1] < 0)
        section_duration = section.end_time - section.start_time
        target_flux_frequency = zero_crossings / max(0.1, section_duration) * 2
    else:
        target_flux_frequency = bpm / 60.0

    scores: Dict[str, MatchScore] = {}

    for name, rudiment in intensity_rudiments.items():
        ms = MatchScore(rudiment_name=name)

        # 1. Envelope shape similarity
        ms.envelope_similarity = score_envelope_similarity(
            rudiment.envelope.samples, target_envelope
        )

        # 2. Repetition rate fit
        ms.repetition_rate_fit = score_repetition_rate(
            rudiment, target_flux_frequency, bpm
        )

        # 3. Flux level fit
        ms.flux_level_fit = score_flux_level(
            rudiment, target_flux, config.tolerance_band_width
        )

        # Transient character bonus/penalty
        transient_score = _transient_category_score(rudiment, transient)

        # Fidelity score (weighted combination)
        ms.fidelity_score = (
            0.35 * ms.envelope_similarity
            + 0.25 * ms.repetition_rate_fit
            + 0.20 * ms.flux_level_fit
            + 0.20 * transient_score
        )

        # Coherence score
        ms.coherence_score = score_musical_coherence(
            groove_rudiment=name,
            fill_rudiment=None,
            previous_section_rudiments=previous_section_rudiments,
            section_type=section_type,
            previous_section_type=previous_section_type,
            groove_flux=rudiment.average_flux,
            fill_flux=0.0,
            config=config,
        )

        # Total score
        ms.total_score = (
            config.fidelity_weight * ms.fidelity_score
            + config.coherence_weight * ms.coherence_score
        )

        scores[name] = ms

    # Sort by total score descending
    scores = dict(sorted(scores.items(), key=lambda x: x[1].total_score, reverse=True))
    return scores



# Complementary envelope category pairs (these look good together)
COMPLEMENTARY_PAIRS = {
    EnvelopeCategory.SPIKE: {EnvelopeCategory.ROLLING, EnvelopeCategory.OSCILLATING},
    EnvelopeCategory.ROLLING: {EnvelopeCategory.SPIKE, EnvelopeCategory.FLAT},
    EnvelopeCategory.OSCILLATING: {EnvelopeCategory.FLAT, EnvelopeCategory.SPIKE},
    EnvelopeCategory.FLAT: {EnvelopeCategory.OSCILLATING, EnvelopeCategory.ROLLING},
    EnvelopeCategory.RAMP: {EnvelopeCategory.STOCHASTIC, EnvelopeCategory.OSCILLATING},
    EnvelopeCategory.STOCHASTIC: {EnvelopeCategory.RAMP, EnvelopeCategory.FLAT},
}


def _compute_diversity_adjustment(
    candidate_name: str,
    current_assignments: Dict[str, str],
    intensity_rudiments: Dict[str, Rudiment],
) -> float:
    """Compute scoring adjustment for diversity in a multi-group context.

    Penalizes same rudiment or same category as other groups.
    Rewards complementary categories.
    """
    if not current_assignments:
        return 0.0

    candidate = intensity_rudiments.get(candidate_name)
    if not candidate:
        return 0.0

    adjustment = 0.0
    other_names = set(current_assignments.values())
    other_categories = []
    for name in other_names:
        r = intensity_rudiments.get(name)
        if r:
            other_categories.append(r.envelope.category)

    # Penalty: same rudiment as another group
    if candidate_name in other_names:
        adjustment -= 0.15

    # Penalty: same envelope category as >50% of other groups
    if other_categories:
        same_cat_count = sum(1 for c in other_categories if c == candidate.envelope.category)
        if same_cat_count > len(other_categories) * 0.5:
            adjustment -= 0.1

    # Bonus: complementary to the most common category in other groups
    if other_categories:
        from collections import Counter
        most_common = Counter(other_categories).most_common(1)[0][0]
        complements = COMPLEMENTARY_PAIRS.get(candidate.envelope.category, set())
        if most_common in complements:
            adjustment += 0.1

    return adjustment


def select_rudiments_per_group(
    section: SectionAnalysis,
    bpm: float,
    group_names: List[str],
    config: Optional[AutogenConfig] = None,
    previous_section_rudiments: Optional[Dict[str, str]] = None,
    section_type: str = "generic",
    previous_section_type: Optional[str] = None,
    allowed_per_group: Optional[Dict[str, Set[str]]] = None,
) -> Dict[str, Tuple[str, str]]:
    """Select different groove+fill rudiments per fixture group.

    Uses iterative refinement: each round re-scores candidates with
    diversity penalties/bonuses based on what other groups are using.
    Iterates until stable or max 10 rounds.

    Args:
        allowed_per_group: Optional per-group constraint sets. If provided,
            each group's key maps to a set of allowed rudiment names.
            Groups not in the dict or with None/empty sets are unconstrained.

    Returns:
        {group_name: (groove_name, fill_name)}
    """
    if config is None:
        config = AutogenConfig()

    if not group_names:
        return {}

    # Base scores (audio matching, independent of group assignment)
    base_scores = match_rudiments_to_section(
        section, bpm,
        previous_section_rudiments=previous_section_rudiments,
        section_type=section_type,
        previous_section_type=previous_section_type,
        config=config,
    )

    intensity_rudiments = get_intensity_rudiments()
    ranked = list(base_scores.keys())

    def _ranked_for_group(group_name: str) -> List[str]:
        """Return ranked candidates filtered by group constraints."""
        if not allowed_per_group:
            return ranked
        allowed = allowed_per_group.get(group_name)
        if not allowed:
            return ranked
        return [r for r in ranked if r in allowed]

    # Initial greedy assignment (round 0)
    current_assignments: Dict[str, str] = {}
    for i, group_name in enumerate(group_names):
        group_ranked = _ranked_for_group(group_name)
        current_assignments[group_name] = group_ranked[i % len(group_ranked)]

    # Iterative refinement
    max_rounds = 10
    for round_num in range(max_rounds):
        changed = False

        for group_name in group_names:
            group_ranked = _ranked_for_group(group_name)

            # Score each candidate with diversity adjustment
            other_assignments = {k: v for k, v in current_assignments.items() if k != group_name}

            best_candidate = current_assignments[group_name]
            best_score = -1.0

            for candidate_name in group_ranked:
                base = base_scores[candidate_name].total_score
                diversity = _compute_diversity_adjustment(
                    candidate_name, other_assignments, intensity_rudiments
                )
                adjusted_score = base + diversity

                if adjusted_score > best_score:
                    best_score = adjusted_score
                    best_candidate = candidate_name

            if best_candidate != current_assignments[group_name]:
                current_assignments[group_name] = best_candidate
                changed = True

        if not changed:
            break

    # Assign fills: highest-scoring candidate with higher flux than groove
    result = {}
    for group_name in group_names:
        groove_name = current_assignments[group_name]
        groove_flux = intensity_rudiments[groove_name].average_flux
        group_ranked = _ranked_for_group(group_name)

        fill_name = groove_name  # Fallback
        for candidate in group_ranked:
            if candidate == groove_name:
                continue
            if intensity_rudiments[candidate].average_flux > groove_flux:
                fill_name = candidate
                break

        result[group_name] = (groove_name, fill_name)

    return result
