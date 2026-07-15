# utils/morph/preview.py
"""Side-by-side preview stills for the morph wizard (design doc 6).

Renders the SOURCE song on config A and the MORPHED song on config B at
the same show time, as two PNG stills the wizard's review page shows
next to each other. Constraint from the 2026-07-16 two-config audit:
two live standalone moderngl contexts on one thread are unsafe, so the
two renders run STRICTLY SEQUENTIALLY - create, render, clean up, then
the next. Scrubbing re-renders; slow but safe, and venue-day honest.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple


def _render_still(config, song, time_s: float, output_dir: str,
                  prefix: str, camera: str, width: int,
                  height: int) -> Optional[str]:
    from utils.fixture_utils import load_fixture_definitions_from_qlc
    from utils.render.offline_renderer import OfflineRenderer

    models = {(f.manufacturer, f.model)
              for g in config.groups.values() for f in g.fixtures}
    definitions = load_fixture_definitions_from_qlc(models)
    renderer = OfflineRenderer(
        config, song, definitions, camera_preset_name=camera,
        output_path="", width=width, height=height)
    try:
        written = renderer.capture_stills([time_s], output_dir,
                                          prefix=prefix)
    finally:
        cleanup = getattr(renderer, "_cleanup", None)
        if callable(cleanup):
            try:
                cleanup()
            except Exception:
                pass
    return written[0] if written else None


def render_pair(source_config, source_song, target_config, morphed_song,
                time_s: float, output_dir: str, camera: str = "Front",
                width: int = 960, height: int = 540
                ) -> Tuple[Optional[str], Optional[str]]:
    """(source still path, morphed still path) at the same show time.

    Either side comes back None when its render fails (no GL, empty
    song) - the wizard shows a placeholder rather than dying."""
    os.makedirs(output_dir, exist_ok=True)
    try:
        a = _render_still(source_config, source_song, time_s, output_dir,
                          "src", camera, width, height)
    except Exception:
        a = None
    try:
        b = _render_still(target_config, morphed_song, time_s, output_dir,
                          "dst", camera, width, height)
    except Exception:
        b = None
    return a, b
