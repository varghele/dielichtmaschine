# utils/morph/analysis_cache.py
"""Per-section audio metrics cached in the show (design doc 5.7).

The ``autogen`` regeneration strategy needs the song's analysis at
morph time - possibly on a machine that never saw the audio. Policy:
cache the per-section DERIVED metrics (every ``SectionAnalysis`` scalar
plus the 32-float ``spectral_flux_envelope`` the rudiment matcher
consumes - the 2026-07-16 audit's finding), keyed by an audio content
hash. Kilobytes, not frames. Resolution order: fresh cache -> recompute
from the bundled audio (seconds, acceptable on venue day) -> fail plan
validation with a clear downgrade message.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import asdict
from typing import Optional, Tuple

CACHE_VERSION = 1


def audio_content_hash(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def analysis_to_cache(analysis, audio_hash: str) -> dict:
    return {
        "version": CACHE_VERSION,
        "audio_hash": audio_hash,
        "duration": analysis.duration,
        "sample_rate": analysis.sample_rate,
        "global_flux_range": list(analysis.global_flux_range),
        "sections": [asdict(section) for section in analysis.sections],
    }


def cache_to_analysis(cache: dict):
    from audio.spectral_analysis import SectionAnalysis, SongAnalysis
    return SongAnalysis(
        sections=[SectionAnalysis(**s) for s in cache.get("sections", [])],
        global_flux_range=tuple(cache.get("global_flux_range", (0.0, 1.0))),
        sample_rate=cache.get("sample_rate", 22050),
        duration=cache.get("duration", 0.0),
    )


def _bundled_audio_path(song, config) -> Optional[str]:
    td = song.timeline_data
    name = getattr(td, "audio_file_path", None) if td else None
    if not name:
        return None
    if os.path.isabs(name) and os.path.exists(name):
        return name
    bundle = config.audio_bundle_dir()
    if bundle:
        candidate = os.path.join(bundle, name)
        if os.path.exists(candidate):
            return candidate
    return None


def store(song, analysis, audio_path: Optional[str]) -> None:
    """Write the cache onto the song (persists with the show YAML)."""
    audio_hash = audio_content_hash(audio_path) if audio_path else ""
    song.analysis_cache = analysis_to_cache(analysis, audio_hash)


def resolve(song, config) -> Tuple[Optional[object], str]:
    """The song's analysis for morph-time regeneration.

    Returns (SongAnalysis or None, source) with source one of "cache",
    "recomputed", "" (unavailable). A cache is trusted when the bundled
    audio is missing (nothing to check against - the cache IS the
    record) or when the content hash still matches; a stale cache is
    recomputed and refreshed."""
    cache = getattr(song, "analysis_cache", None) or {}
    audio_path = _bundled_audio_path(song, config)

    if cache.get("sections"):
        if not audio_path:
            return cache_to_analysis(cache), "cache"
        if cache.get("audio_hash") == audio_content_hash(audio_path):
            return cache_to_analysis(cache), "cache"

    if audio_path:
        from audio.spectral_analysis import analyze_song
        from timeline.song_structure import SongStructure
        structure = SongStructure()
        structure.load_from_show_parts(song.parts)
        analysis = analyze_song(audio_path, structure)
        store(song, analysis, audio_path)
        return analysis, "recomputed"

    return None, ""


def relative_energies(analysis) -> list:
    """Per-section relative energy (0-1), exactly the generator's
    formula (autogen/generator.py): 0.6 x RMS percentile rank + 0.4 x
    spectral contrast."""
    all_rms = sorted(s.rms_energy for s in analysis.sections)
    energies = []
    for section in analysis.sections:
        if len(all_rms) > 1:
            rank = all_rms.index(section.rms_energy) \
                if section.rms_energy in all_rms else 0
            rms_rank = rank / (len(all_rms) - 1)
        else:
            rms_rank = 0.5
        value = 0.6 * rms_rank + 0.4 * section.spectral_contrast_avg
        energies.append(max(0.0, min(1.0, value)))
    return energies
