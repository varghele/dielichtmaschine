#!/usr/bin/env python3
"""Deterministic generator for the bundled demo SHOWS.

For each demo rig (see ``demos/generate_rigs.py``) this loads the rig,
auto-generates a full light show from a supplied audio clip using the project's
own autogen pipeline (``autogen.generator.generate_show``), and writes the
result — rig + one generated show — as a ``Configuration`` YAML under
``demos/shows/``. The audio clip is copied next to the shows in
``demos/shows/audiofiles/`` and referenced by basename, so a demo config loads
and plays on any machine.

The song structure is built proportionally to the clip: canonical
intro/verse/chorus/bridge/outro sections sized from the clip's duration and
tempo, so the autogen matcher has real per-section energy to react to. BPM is
auto-detected (librosa) unless ``--bpm`` is given.

Run:
    python -m demos.generate_shows path/to/clip.wav          # from project root
    python -m demos.generate_shows clip.wav --bpm 128
    python -m demos.generate_shows clip.wav --rig dj_edm     # single rig
Output:
    demos/shows/<rig>.yaml
    demos/shows/audiofiles/<clip basename>
"""

from __future__ import annotations

import argparse
import copy
import os
import random
import shutil
import sys
from fractions import Fraction

import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config.models import Configuration, Song, ShowPart, TimelineData  # noqa: E402
from timeline.song_structure import SongStructure  # noqa: E402
from autogen.generator import generate_show  # noqa: E402

RIGS_DIR = os.path.join(PROJECT_ROOT, "demos", "rigs")
OUT_DIR = os.path.join(PROJECT_ROOT, "demos", "shows")

RIG_NAMES = ["club_band", "band_midsize", "festival_mainstage", "dj_edm", "theatre_static"]

# (display name, structure-UI colour, relative bar weight). The first word of
# the name is the section *type* the autogen colour/rudiment logic keys on, so
# keep them canonical: intro / verse / chorus / bridge / outro.
SECTION_TEMPLATE = [
    ("Intro",    "#3a3a55", 1),
    ("Verse 1",  "#2e6fb0", 2),
    ("Chorus 1", "#c0522a", 2),
    ("Verse 2",  "#2e6fb0", 2),
    ("Chorus 2", "#c0522a", 2),
    ("Bridge",   "#6a3d9a", 1),
    ("Outro",    "#3a3a55", 1),
]

DEFAULT_SIGNATURE = "4/4"
SEED = 0  # fixed so re-running the generator reproduces the same show


def _beats_per_bar(signature: str) -> int:
    try:
        return int(signature.split("/")[0])
    except (ValueError, IndexError):
        return 4


def probe_audio(audio_path: str, bpm_override: float | None):
    """Return (duration_seconds, bpm) for the clip. BPM auto-detected if needed."""
    import librosa

    duration = float(librosa.get_duration(path=audio_path))
    if bpm_override is not None:
        return duration, float(bpm_override)

    y, sr = librosa.load(audio_path, mono=True)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(np.atleast_1d(tempo)[0])
    # Keep the demo tempo sane if detection returns something extreme.
    if not (40.0 <= bpm <= 220.0):
        bpm = 120.0
    return duration, round(bpm, 1)


def build_structure(duration: float, bpm: float, signature: str = DEFAULT_SIGNATURE) -> list[ShowPart]:
    """Lay out the canonical sections proportionally across the clip duration."""
    bpb = _beats_per_bar(signature)
    sec_per_bar = bpb * 60.0 / bpm

    total_bars = max(len(SECTION_TEMPLATE), int(duration // sec_per_bar))
    weight_sum = sum(w for _, _, w in SECTION_TEMPLATE)

    # Proportional allocation, min 1 bar each; largest-remainder for the rest.
    raw = [(total_bars * w / weight_sum) for _, _, w in SECTION_TEMPLATE]
    bars = [max(1, int(r)) for r in raw]
    leftover = total_bars - sum(bars)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - int(raw[i]), reverse=True)
    i = 0
    while leftover > 0:
        bars[order[i % len(order)]] += 1
        leftover -= 1
        i += 1

    parts = []
    for (name, color, _weight), nbars in zip(SECTION_TEMPLATE, bars):
        parts.append(ShowPart(
            name=name, color=color, signature=signature,
            bpm=bpm, num_bars=nbars, transition="instant",
        ))
    return parts


def load_structure_parts(config_path: str, show_name: str = None, slice_spec: str = None):
    """Take the song structure (parts) from a show in an existing config.

    Returns (parts, label). Uses ``show_name`` if given, else the first show.
    ``slice_spec`` is an optional ``START:END`` index range (Python slice, by
    part position so duplicate part names stay unambiguous) to keep only a
    section — e.g. ``"4:6"`` for a short build-into-chorus demo excerpt.
    """
    cfg = Configuration.load(config_path)
    if not cfg.songs:
        raise SystemExit(f"error: {config_path} has no shows to take structure from")
    if show_name:
        if show_name not in cfg.songs:
            raise SystemExit(f"error: show '{show_name}' not in {config_path}. Have: {', '.join(cfg.songs)}")
        show = cfg.songs[show_name]
    else:
        show_name, show = next(iter(cfg.songs.items()))
    if not show.parts:
        raise SystemExit(f"error: show '{show_name}' has no parts")

    parts = copy.deepcopy(show.parts)
    if slice_spec:
        try:
            a, b = slice_spec.split(":")
            parts = parts[(int(a) if a else None):(int(b) if b else None)]
        except ValueError:
            raise SystemExit(f"error: --structure-slice must be START:END, got {slice_spec!r}")
        if not parts:
            raise SystemExit(f"error: --structure-slice {slice_spec} selected no parts")
        label = f"{show_name}[{slice_spec}]"
    else:
        label = show_name
    return parts, label


# Busy movement shapes -> a smooth stand-in when --calm-movement is on.
_CALM_SHAPE = {"figure_8": "circle", "lissajous": "circle"}


def _speed_to_str(mult: float) -> str:
    """Render a speed multiplier back to a "n" / "n/d" effect_speed string."""
    f = Fraction(mult).limit_denominator(16)
    return str(f.numerator) if f.denominator == 1 else f"{f.numerator}/{f.denominator}"


def calm_movement(lanes, speed_factor: float = 0.5):
    """Tone down autogen movement: slow effect_speed and smooth busy shapes.

    Halving the speed on top of the global 4x movement slowdown, plus swapping
    figure-8 / lissajous for a plain circle, keeps dense rigs (e.g. the festival
    front truss of 8 washes) from reading as frantic.
    """
    from effects.timing import parse_speed
    for lane in lanes:
        for lb in lane.light_blocks:
            for mb in lb.movement_blocks:
                mb.effect_speed = _speed_to_str(parse_speed(str(mb.effect_speed)) * speed_factor)
                mb.effect_type = _CALM_SHAPE.get(mb.effect_type, mb.effect_type)
    return lanes


def generate_for_rig(rig_name: str, audio_path: str, parts, audio_basename: str,
                     calm: bool = False) -> Configuration:
    """Load a rig, autogenerate a show against the clip using ``parts``, return the config."""
    cfg = Configuration.load(os.path.join(RIGS_DIR, f"{rig_name}.yaml"))

    # Fresh copy per rig: load_from_show_parts stamps start_time/duration in place.
    rig_parts = copy.deepcopy(parts)
    structure = SongStructure()
    structure.load_from_show_parts(rig_parts)

    # Deterministic output across runs.
    random.seed(SEED)
    np.random.seed(SEED)

    lanes, _report = generate_show(audio_path, structure, cfg)
    if calm:
        calm_movement(lanes)

    show = Song(
        name="Demo",
        parts=rig_parts,
        timeline_data=TimelineData(lanes=lanes, audio_file_path=audio_basename),
    )
    cfg.songs[show.name] = show
    return cfg


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate bundled demo shows from an audio clip.")
    parser.add_argument("audio", help="Path to a short royalty-free audio clip (wav/flac/mp3).")
    parser.add_argument("--bpm", type=float, default=None, help="Override BPM (else auto-detected).")
    parser.add_argument("--rig", choices=RIG_NAMES, default=None, help="Only generate this rig.")
    parser.add_argument("--structure-from", default=None,
                        help="Config YAML to take the song structure (parts) from, instead of a generic one.")
    parser.add_argument("--structure-show", default=None,
                        help="Show name within --structure-from (default: first show).")
    parser.add_argument("--structure-slice", default=None,
                        help="START:END part-index range of --structure-show to keep (e.g. 4:6 for a short excerpt).")
    parser.add_argument("--calm-movement", action="store_true",
                        help="Slow movement effect_speed 2x and smooth figure-8/lissajous to circle (dense rigs).")
    parser.add_argument("--out", default=OUT_DIR, help="Output directory (default: demos/shows).")
    args = parser.parse_args(argv)

    audio_path = os.path.abspath(args.audio)
    if not os.path.exists(audio_path):
        parser.error(f"audio clip not found: {audio_path}")

    if args.structure_from:
        parts, label = load_structure_parts(args.structure_from, args.structure_show, args.structure_slice)
        struct = SongStructure()
        struct.load_from_show_parts(parts)
        duration, bpm = struct.get_total_duration(), parts[0].bpm
        print(f"Structure: '{label}' from {os.path.relpath(args.structure_from, PROJECT_ROOT)} "
              f"({len(parts)} parts, {duration:.1f}s, {bpm:g} BPM)")
    else:
        duration, bpm = probe_audio(audio_path, args.bpm)
        parts = build_structure(duration, bpm)

    rigs = [args.rig] if args.rig else RIG_NAMES

    os.makedirs(args.out, exist_ok=True)
    audiofiles_dir = os.path.join(args.out, "audiofiles")
    os.makedirs(audiofiles_dir, exist_ok=True)
    bundled = os.path.join(audiofiles_dir, os.path.basename(audio_path))
    if os.path.abspath(bundled) != audio_path:
        shutil.copyfile(audio_path, bundled)

    print(f"Clip: {os.path.basename(audio_path)}  ({duration:.1f}s, {bpm:g} BPM)")
    for rig_name in rigs:
        cfg = generate_for_rig(rig_name, audio_path, parts, os.path.basename(audio_path), calm=args.calm_movement)
        out = os.path.join(args.out, f"{rig_name}.yaml")
        cfg.save(out)
        show = cfg.songs["Demo"]
        n_lanes = len(show.timeline_data.lanes)
        n_blocks = sum(len(l.light_blocks) for l in show.timeline_data.lanes)
        print(f"  {rig_name:22s} {len(show.parts)} parts  {n_lanes:2d} lanes  "
              f"{n_blocks:3d} blocks  -> {os.path.relpath(out, PROJECT_ROOT)}")


if __name__ == "__main__":
    print("Generating demo shows ...")
    main()
