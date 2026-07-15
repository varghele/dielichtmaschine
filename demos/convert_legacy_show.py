#!/usr/bin/env python3
"""Convert a config's legacy effects-based shows to modern timeline blocks.

Thin CLI over :func:`utils.legacy_show_converter.convert_show_in_place`. Every
show that still has legacy ``effects`` but no ``timeline_data`` is upgraded, so
the config opens, plays, and renders in the current app. The conversion is
best-effort and lossy — see ``utils/legacy_show_converter.py``.

Run (from the project root):
    python -m demos.convert_legacy_show demos/reference/SBD_touring.yaml \
        --audio-show SBD_monsters_in_my_head \
        --audio light_track_shoo_bee_doom_monsters_in_my_head.mp3
"""

from __future__ import annotations

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config.models import Configuration  # noqa: E402
from utils.legacy_show_converter import convert_show_in_place  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Upgrade legacy effects shows to modern timeline blocks.")
    parser.add_argument("config", help="Path to a config YAML with legacy shows.")
    parser.add_argument("--audio-show", default=None,
                        help="Name of the show to attach --audio to (basename, resolved from audiofiles/).")
    parser.add_argument("--audio", default=None, help="Audio filename to set on --audio-show.")
    parser.add_argument("--out", default=None, help="Output path (default: overwrite the input).")
    args = parser.parse_args(argv)

    if not os.path.exists(args.config):
        parser.error(f"config not found: {args.config}")

    config = Configuration.load(args.config)
    converted = []
    for name, show in config.songs.items():
        if show.effects and show.timeline_data is None:
            audio = args.audio if name == args.audio_show else None
            convert_show_in_place(show, audio_file_path=audio)
            n = sum(len(l.light_blocks) for l in show.timeline_data.lanes)
            converted.append((name, len(show.timeline_data.lanes), n))

    out = args.out or args.config
    config.save(out)

    print(f"Converted {len(converted)} legacy show(s) -> {os.path.relpath(out, PROJECT_ROOT)}")
    for name, lanes, blocks in converted:
        tag = "  (audio: %s)" % args.audio if name == args.audio_show and args.audio else ""
        print(f"  {name:28s} {lanes} lanes  {blocks:3d} blocks{tag}")


if __name__ == "__main__":
    main()
