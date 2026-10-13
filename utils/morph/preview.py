# utils/morph/preview.py
"""Side-by-side preview stills for the morph screen (design doc 6).

Renders the SOURCE song on config A and the MORPHED song on config B,
as PNG stills the review page shows next to each other.

Constraint from the 2026-07-16 two-config audit: two live standalone
moderngl contexts on one thread are unsafe, so the two SIDES run
STRICTLY SEQUENTIALLY - create, render, clean up, then the next.

Within a side, ``render_strip`` batches every requested time into ONE
``capture_stills`` call, which matters far more than it looks:
``capture_stills`` walks the song once at render fps updating DMX on
every frame and only pays for a GL read on the frames it keeps, so the
cost tracks HOW FAR INTO THE SONG you go, not how many frames you ask
for. Measured on a real 4:39 song: one still at 90% costs 7.1 s, and
twenty spread across the whole song cost 7.3 s. Rendering one frame per
scrub position (the behaviour until 2026-08-08) paid that walk again
every time. Lowering the resolution barely helps - half size saved 1.5%
- because the walk, not the pixels, is the cost.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple


def _render_side(config, song, times: List[float], output_dir: str,
                 prefix: str, camera: str, width: int,
                 height: int) -> List[str]:
    """Render MANY times through ONE renderer, in one forward pass.

    This is the whole performance story. ``capture_stills`` walks the
    song once at render fps updating DMX every frame, and only pays for
    a GL read + encode on frames it keeps - so the cost is driven by how
    far into the song you go, NOT by how many frames you ask for.
    Measured on a 4:39 song: one still 90% in takes 7.1 s, and twenty
    stills spread across the whole song take 7.3 s. Asking per frame
    (the old behaviour) paid that 7 s over and over.
    """
    from utils.fixture_utils import load_fixture_definitions_from_qlc
    from utils.render.offline_renderer import OfflineRenderer

    models = {(f.manufacturer, f.model)
              for g in config.groups.values() for f in g.fixtures}
    definitions = load_fixture_definitions_from_qlc(models)
    renderer = OfflineRenderer(
        config, song, definitions, camera_preset_name=camera,
        output_path="", width=width, height=height)
    try:
        return renderer.capture_stills(times, output_dir, prefix=prefix)
    finally:
        cleanup = getattr(renderer, "_cleanup", None)
        if callable(cleanup):
            try:
                cleanup()
            except Exception:
                pass


def _render_still(config, song, time_s: float, output_dir: str,
                  prefix: str, camera: str, width: int,
                  height: int) -> Optional[str]:
    written = _render_side(config, song, [time_s], output_dir, prefix,
                           camera, width, height)
    return written[0] if written else None


def render_strip(source_config, source_song, target_config, morphed_song,
                 times: List[float], output_dir: str,
                 camera: str = "Front", width: int = 960,
                 height: int = 540
                 ) -> Tuple[Dict[float, str], Dict[float, str]]:
    """Both rigs at MANY show times: ({t: path}, {t: path}).

    Renders every source frame, tears that context down, then every
    morphed frame - two live standalone moderngl contexts on one thread
    are unsafe (2026-07-16 audit), so the sides stay strictly
    sequential even though the frames within a side are batched.

    ``times`` must already be inside the song; ``capture_stills`` sorts
    and de-duplicates, so results pair back by that same ordering.
    """
    os.makedirs(output_dir, exist_ok=True)
    targets = sorted({round(float(t), 3) for t in times})

    def side(config, song, prefix) -> Dict[float, str]:
        if song is None:
            return {}
        try:
            written = _render_side(config, song, targets, output_dir,
                                   prefix, camera, width, height)
        except Exception:
            return {}
        return dict(zip(targets, written))

    return (side(source_config, source_song, "src"),
            side(target_config, morphed_song, "dst"))


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
