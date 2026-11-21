"""Song-level color palette system for algorithmic show generation.

Generates a cohesive palette of 1-3 colors (+ optional white) for the
entire song. Different sections use different combinations of these colors.
"""

import colorsys
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional

from audio.spectral_analysis import SongAnalysis


@dataclass
class SongPalette:
    """Song-wide color palette (max 3 colors + optional white)."""
    primary: Tuple[int, int, int] = (255, 0, 0)
    secondary: Optional[Tuple[int, int, int]] = None
    tertiary: Optional[Tuple[int, int, int]] = None
    include_white: bool = True

    @property
    def num_colors(self) -> int:
        count = 1
        if self.secondary:
            count += 1
        if self.tertiary:
            count += 1
        return count

    def get_colors(self) -> List[Tuple[int, int, int]]:
        """Get all non-None colors including white if enabled."""
        colors = [self.primary]
        if self.secondary:
            colors.append(self.secondary)
        if self.tertiary:
            colors.append(self.tertiary)
        if self.include_white:
            colors.append((255, 255, 255))
        return colors


@dataclass
class SectionColorAssignment:
    """Color assignment for a specific section."""
    colors: List[Tuple[int, int, int]]  # Colors to use for this section


# ──────────────────────────────────────────────
# Preset palettes
# ──────────────────────────────────────────────

PRESET_PALETTES: Dict[str, SongPalette] = {
    "Warm": SongPalette(
        primary=(255, 50, 0), secondary=(255, 160, 0), include_white=True
    ),
    "Cool": SongPalette(
        primary=(0, 80, 255), secondary=(100, 0, 200), include_white=True
    ),
    "Fire": SongPalette(
        primary=(255, 30, 0), secondary=(255, 120, 0), include_white=True
    ),
    "Ocean": SongPalette(
        primary=(0, 100, 255), secondary=(0, 200, 180), include_white=True
    ),
    "Forest": SongPalette(
        primary=(0, 180, 50), secondary=(0, 150, 120), include_white=True
    ),
    "Sunset": SongPalette(
        primary=(255, 80, 0), secondary=(200, 0, 120), include_white=True
    ),
    "Monochrome": SongPalette(
        primary=(0, 100, 255), secondary=None, include_white=True
    ),
    "Red/Blue": SongPalette(
        primary=(255, 0, 0), secondary=(0, 0, 255), include_white=True
    ),
    "Purple Haze": SongPalette(
        primary=(150, 0, 255), secondary=(255, 0, 100), include_white=True
    ),
    "Arctic": SongPalette(
        primary=(0, 180, 255), secondary=(200, 220, 255), include_white=True
    ),
}


def get_preset_names() -> List[str]:
    """Return list of available preset palette names."""
    return list(PRESET_PALETTES.keys())


def get_preset_palette(name: str) -> Optional[SongPalette]:
    """Get a preset palette by name."""
    return PRESET_PALETTES.get(name)


# ──────────────────────────────────────────────
# Auto-generate palette from audio analysis
# ──────────────────────────────────────────────

def _mood_to_hue(mood: float) -> float:
    """Map mood (-1 cool to +1 warm) to base hue (0-360)."""
    if mood >= 0:
        return 30 - mood * 30  # Warm: orange to red
    else:
        return 150 + abs(mood) * 120  # Cool: teal to purple


def _key_mood(key_signature: Optional[str]) -> float:
    if not key_signature:
        return 0.0
    k = key_signature.lower()
    if "major" in k or "maj" in k:
        return 0.5
    elif "minor" in k or "min" in k:
        return -0.5
    return 0.0


def generate_palette_from_audio(
    analysis: SongAnalysis,
    avg_bpm: float,
    key_signature: Optional[str] = None,
    num_colors: int = 2,
    include_white: bool = True,
) -> SongPalette:
    """Auto-generate a song palette from audio analysis.

    Derives mood from global audio characteristics and picks 1-3 cohesive colors.
    """
    num_colors = max(1, min(3, num_colors))

    # Global mood from all sections
    if analysis.sections:
        avg_centroid = sum(s.spectral_centroid_avg for s in analysis.sections) / len(analysis.sections)
        centroid_range = (
            min(s.spectral_centroid_avg for s in analysis.sections),
            max(s.spectral_centroid_avg for s in analysis.sections),
        )
    else:
        avg_centroid = 2000.0
        centroid_range = (500.0, 5000.0)

    # Compute mood
    key_m = _key_mood(key_signature)
    c_low, c_high = centroid_range
    centroid_m = ((avg_centroid - c_low) / max(1, c_high - c_low) - 0.5) * 0.6 if c_high > c_low else 0.0
    tempo_m = max(-0.2, min(0.2, (avg_bpm - 120) / 300))
    mood = max(-1.0, min(1.0, key_m + centroid_m + tempo_m))

    # Brightness from centroid
    brightness = max(0.3, min(0.8, 0.3 + (avg_centroid - 500) / 5000 * 0.5))

    base_hue = _mood_to_hue(mood)
    saturation = 0.7 + 0.3 * abs(mood)

    # Primary color
    r, g, b = colorsys.hls_to_rgb(base_hue / 360, brightness, saturation)
    primary = (int(r * 255), int(g * 255), int(b * 255))

    # Secondary: complementary offset
    secondary = None
    if num_colors >= 2:
        sec_hue = (base_hue + 60 + mood * 30) % 360
        r, g, b = colorsys.hls_to_rgb(sec_hue / 360, brightness * 0.9, saturation * 0.85)
        secondary = (int(r * 255), int(g * 255), int(b * 255))

    # Tertiary: wider offset
    tertiary = None
    if num_colors >= 3:
        ter_hue = (base_hue + 150) % 360
        r, g, b = colorsys.hls_to_rgb(ter_hue / 360, brightness * 0.7, saturation * 0.7)
        tertiary = (int(r * 255), int(g * 255), int(b * 255))

    return SongPalette(
        primary=primary, secondary=secondary, tertiary=tertiary,
        include_white=include_white,
    )


# ──────────────────────────────────────────────
# Section color assignment
# ──────────────────────────────────────────────

def assign_section_colors(
    palette: SongPalette,
    section_types: Dict[str, str],
) -> Dict[str, SectionColorAssignment]:
    """Assign colors from song palette to each section.

    Same section type always gets the same color assignment.
    Different section types get different combinations for contrast.

    Args:
        palette: Song-level palette
        section_types: {section_name: type_string} e.g. {"Verse 1": "verse", "Chorus": "chorus"}

    Returns:
        {section_name: SectionColorAssignment}
    """
    # Build unique section type list (preserving order of first occurrence)
    unique_types = []
    for name in section_types:
        stype = section_types[name]
        if stype not in unique_types:
            unique_types.append(stype)

    # Define color combinations based on palette size
    all_colors = palette.get_colors()
    white = (255, 255, 255)

    # Build assignment patterns based on how many colors + unique section types we have
    # Pattern: each section type gets a different combination
    type_assignments: Dict[str, List[Tuple[int, int, int]]] = {}

    if palette.num_colors == 1:
        # Monochrome: vary by including/excluding white
        patterns = [
            [palette.primary],
            [palette.primary, white] if palette.include_white else [palette.primary],
            [white] if palette.include_white else [palette.primary],
        ]
    elif palette.num_colors == 2:
        patterns = [
            [palette.primary],                                          # Verse: primary only
            [palette.primary, palette.secondary],                       # Chorus: both colors
            [palette.secondary] if palette.secondary else [palette.primary],  # Bridge: secondary
            [palette.secondary, white] if palette.include_white and palette.secondary else [palette.primary],
        ]
    else:  # 3 colors
        patterns = [
            [palette.primary],
            [palette.primary, palette.secondary] if palette.secondary else [palette.primary],
            [palette.secondary, palette.tertiary] if palette.secondary and palette.tertiary else [palette.primary],
            [palette.tertiary, white] if palette.tertiary and palette.include_white else [palette.primary],
        ]

    # Assign patterns to section types
    for i, stype in enumerate(unique_types):
        pattern_idx = i % len(patterns)
        type_assignments[stype] = patterns[pattern_idx]

    # Map back to section names
    result = {}
    for name, stype in section_types.items():
        colors = type_assignments.get(stype, [palette.primary])
        result[name] = SectionColorAssignment(colors=colors)

    return result
