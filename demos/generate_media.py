#!/usr/bin/env python3
"""Automated README media (stills + motion) from a demo show.

Renders the 3D visualizer for a saved demo show — headlessly, no window — into:
  * PNG stills from one or more camera angles (README screenshots),
  * an animated GIF walkthrough (repo-friendly: downscaled + palettized), and
  * optionally a full-res MP4 (needs ``imageio-ffmpeg``; carries audio).

All come from the same offline render path the app uses
(``utils.render.offline_renderer.OfflineRenderer``), so re-running this after
editing a demo show — or for a future release — regenerates the media
deterministically. Stills and GIF need only a working OpenGL driver; the MP4
additionally needs ``pip install imageio-ffmpeg``.

By default the debug orientation-axis triads on moving heads are hidden (clean
README media); pass ``--show-gizmos`` to keep them.

Run (from the project root):
    python -m demos.generate_media dj_edm                 # rig name -> demos/shows/dj_edm.yaml
    python -m demos.generate_media demos/shows/dj_edm.yaml
    python -m demos.generate_media dj_edm --stills --cameras "Front,Wide,Top-Down"
    python -m demos.generate_media dj_edm --gif --gif-width 720 --gif-fps 15
    python -m demos.generate_media dj_edm --mp4               # full-res video w/ audio
    python -m demos.generate_media dj_edm --times "8,16,24"   # explicit still moments

Output:
    demos/media/<rig>/stills/<camera-slug>__<time>s.png
    demos/media/<rig>/<rig>.gif
    demos/media/<rig>/<rig>.mp4
"""

from __future__ import annotations

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config.models import Configuration  # noqa: E402
from timeline.song_structure import SongStructure  # noqa: E402
from utils.fixture_utils import load_fixture_definitions_from_qlc  # noqa: E402
from utils.render.camera_presets import CAMERA_PRESETS  # noqa: E402
from utils.render.offline_renderer import OfflineRenderer  # noqa: E402

SHOWS_DIR = os.path.join(PROJECT_ROOT, "demos", "shows")
MEDIA_DIR = os.path.join(PROJECT_ROOT, "demos", "media")
DEFAULT_CAMERAS = ["Front", "Front-Left 45", "Wide"]


def resolve_config_path(target: str) -> str:
    """Accept either a path to a config YAML or a bare rig name."""
    if os.path.exists(target):
        return os.path.abspath(target)
    candidate = os.path.join(SHOWS_DIR, f"{target}.yaml")
    if os.path.exists(candidate):
        return candidate
    raise SystemExit(f"error: no config at '{target}' or '{candidate}'")


def pick_show(config: Configuration, name: str = None):
    """Pick the show to render: explicit --show name, else 'Demo', else the first."""
    if not config.songs:
        raise SystemExit("error: config has no shows to render")
    if name:
        if name not in config.songs:
            raise SystemExit(f"error: show '{name}' not in config. Have: {', '.join(config.songs)}")
        return config.songs[name]
    if "Demo" in config.songs:
        return config.songs["Demo"]
    return next(iter(config.songs.values()))


def default_still_times(show) -> list[float]:
    """One still at the midpoint of each song part — spreads shots across the show."""
    structure = SongStructure()
    structure.load_from_show_parts(show.parts)
    return [round(p.start_time + p.duration / 2.0, 1) for p in show.parts]


def _slug(name: str) -> str:
    return name.lower().replace(" ", "-")


def _progress(cur, total, msg):
    print(f"    [{cur}/{total}] {msg}", end="\r", flush=True)


def _validate_cameras(cameras):
    unknown = [c for c in cameras if c not in CAMERA_PRESETS]
    if unknown:
        raise SystemExit(f"error: unknown camera(s) {unknown}. Options: {', '.join(CAMERA_PRESETS)}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render README media (stills + GIF/MP4) from a demo show.")
    parser.add_argument("target", help="A demo rig name (demos/shows/<name>.yaml) or a path to a config YAML.")
    parser.add_argument("--show", default=None, help="Name of the show to render (default: 'Demo' or first).")
    parser.add_argument("--stills", action="store_true", help="Render PNG stills.")
    parser.add_argument("--gif", action="store_true", help="Render an animated GIF walkthrough.")
    parser.add_argument("--mp4", action="store_true", help="Render a full-res MP4 (needs imageio-ffmpeg).")
    parser.add_argument("--cameras", default=",".join(DEFAULT_CAMERAS),
                        help=f"Comma-separated camera presets for stills. Options: {', '.join(CAMERA_PRESETS)}")
    parser.add_argument("--times", default=None,
                        help="Comma-separated still times in seconds (default: midpoint of each part).")
    parser.add_argument("--motion-camera", default="Front", help="Camera preset for GIF/MP4 (default: Front).")
    parser.add_argument("--fps", type=int, default=30, help="Render fps (stills/MP4).")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--gif-fps", type=int, default=12)
    parser.add_argument("--gif-width", type=int, default=640, help="Max GIF width (downscaled to fit).")
    parser.add_argument("--gif-colors", type=int, default=128, help="GIF palette size (fewer = smaller file).")
    parser.add_argument("--show-gizmos", action="store_true",
                        help="Keep the moving-head orientation-axis triads (hidden by default).")
    parser.add_argument("--out", default=MEDIA_DIR, help="Output root (default: demos/media).")
    args = parser.parse_args(argv)

    # Default to stills + GIF when the user specifies no output kind.
    any_selected = args.stills or args.gif or args.mp4
    do_stills = args.stills or not any_selected
    do_gif = args.gif or not any_selected
    do_mp4 = args.mp4

    config_path = resolve_config_path(args.target)
    rig_name = os.path.splitext(os.path.basename(config_path))[0]

    config = Configuration.load(config_path)
    # Let the offline renderer resolve the bundled audio (audiofiles/ sits next
    # to the config); the MP4 mux needs it, stills/GIF don't.
    config.shows_directory = os.path.dirname(config_path)
    show = pick_show(config, args.show)

    models = {(f.manufacturer, f.model) for g in config.groups.values() for f in g.fixtures}
    fixture_definitions = load_fixture_definitions_from_qlc(models)

    cameras = [c.strip() for c in args.cameras.split(",") if c.strip()]
    _validate_cameras(cameras + [args.motion_camera])
    show_gizmos = args.show_gizmos

    out_dir = os.path.join(args.out, rig_name)
    os.makedirs(out_dir, exist_ok=True)
    print(f"Rendering media for '{rig_name}' (show: {show.name}, gizmos: {show_gizmos})  "
          f"-> {os.path.relpath(out_dir, PROJECT_ROOT)}")

    def _renderer(camera, output_path=""):
        return OfflineRenderer(
            config, show, fixture_definitions,
            camera_preset_name=camera, output_path=output_path,
            width=args.width, height=args.height, fps=args.fps,
            progress_callback=_progress, show_gizmos=show_gizmos,
        )

    if do_stills:
        times = [float(t) for t in args.times.split(",")] if args.times else default_still_times(show)
        stills_root = os.path.join(out_dir, "stills")
        print(f"  Stills @ {times}  from cameras {cameras}")
        for cam in cameras:
            written = _renderer(cam).capture_stills(times, stills_root, prefix=_slug(cam))
            print(f"\n    {cam:16s} -> {len(written)} PNG(s)")

    if do_gif:
        gif_path = os.path.join(out_dir, f"{rig_name}.gif")
        print(f"  GIF ({args.motion_camera}, {args.gif_width}px @ {args.gif_fps}fps) "
              f"-> {os.path.relpath(gif_path, PROJECT_ROOT)}")
        ok = _renderer(args.motion_camera).render_gif(
            gif_path, gif_fps=args.gif_fps, max_width=args.gif_width, colors=args.gif_colors)
        print(f"\n    {'done' if ok else 'FAILED'}")

    if do_mp4:
        try:
            import imageio_ffmpeg  # noqa: F401
        except ImportError:
            print("  MP4 SKIPPED: install FFmpeg support with  pip install imageio-ffmpeg")
            return
        mp4_path = os.path.join(out_dir, f"{rig_name}.mp4")
        print(f"  MP4 ({args.motion_camera}) -> {os.path.relpath(mp4_path, PROJECT_ROOT)}")
        ok = _renderer(args.motion_camera, output_path=mp4_path).render()
        print(f"\n    {'done' if ok else 'FAILED'}")


if __name__ == "__main__":
    main()
