# utils/render/offline_renderer.py
# Headless offline rendering of shows to MP4 video files

import os
import subprocess
import numpy as np
import time
from typing import Dict, List, Optional, Callable, Any

import moderngl
import glm

from config.models import Configuration, Song
from utils import user_warnings
from utils.fixture_utils import load_fixture_definitions_from_qlc
from utils.target_resolver import resolve_targets_unique
from utils.artnet.dmx_manager import DMXManager
from utils.render.camera_presets import CAMERA_PRESETS
from timeline.song_structure import SongStructure


class OfflineRenderer:
    """Renders a show to an MP4 video file using headless OpenGL + FFmpeg."""

    def __init__(
        self,
        config: Configuration,
        show: Song,
        fixture_definitions: Dict[str, Any],
        camera_preset_name: str = "Front",
        output_path: str = "output.mp4",
        width: int = 1920,
        height: int = 1080,
        fps: int = 30,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        show_gizmos: bool = True,
    ):
        self.config = config
        self.show = show
        self.fixture_definitions = fixture_definitions
        self.camera_preset_name = camera_preset_name
        self.output_path = output_path
        self.width = width
        self.height = height
        self.fps = fps
        self.progress_callback = progress_callback
        # When False, per-fixture debug axis triads (moving-head chassis) are
        # suppressed — for clean README stills/clips. See _init_renderers.
        self.show_gizmos = show_gizmos

        self._ctx = None
        self._fbo = None
        self._stage_renderer = None
        self._fixture_manager = None
        self._dmx_manager = None
        self._cancelled = False

    def cancel(self):
        """Cancel the rendering."""
        self._cancelled = True

    def render(self) -> bool:
        """Execute the full render pipeline.

        Returns:
            True if completed successfully, False if cancelled or failed.
        """
        try:
            self._report_progress(0, 1, "Initializing renderer...")

            # Calculate show duration
            song_structure = SongStructure()
            song_structure.load_from_show_parts(self.show.parts)
            duration = song_structure.get_total_duration()
            if duration <= 0:
                user_warnings.warn("Show has no duration, nothing to render", category="render")
                return False

            total_frames = int(duration * self.fps)
            print(f"Rendering {self.show.name}: {duration:.1f}s, {total_frames} frames at {self.fps}fps")

            # Initialize OpenGL context and renderers
            self._init_gl_context()
            self._init_renderers()

            # Initialize DMX manager
            self._init_dmx(song_structure)

            # Set up camera
            mvp = self._setup_camera()

            # Resolve audio path
            audio_path = self._resolve_audio_path()

            # Start FFmpeg process
            ffmpeg_proc = self._start_ffmpeg(audio_path)
            if ffmpeg_proc is None:
                return False

            self._report_progress(0, total_frames, "Rendering frames...")

            try:
                for frame_idx in range(total_frames):
                    if self._cancelled:
                        print("Render cancelled")
                        ffmpeg_proc.stdin.close()
                        ffmpeg_proc.terminate()
                        return False

                    time_s = frame_idx / self.fps

                    # Compute DMX for this time
                    self._update_dmx_at_time(time_s, song_structure)

                    # Apply DMX to fixture visuals
                    self._apply_dmx_to_fixtures()

                    # Render frame
                    self._render_frame(mvp)

                    # Read pixels and pipe to FFmpeg
                    pixels = self._fbo.read(components=3)
                    # Flip vertically (OpenGL origin is bottom-left, video is top-left)
                    pixel_array = np.frombuffer(pixels, dtype=np.uint8).reshape(self.height, self.width, 3)
                    pixel_array = np.flipud(pixel_array)
                    ffmpeg_proc.stdin.write(pixel_array.tobytes())

                    # Report progress periodically
                    if frame_idx % self.fps == 0 or frame_idx == total_frames - 1:
                        elapsed_s = time_s
                        self._report_progress(
                            frame_idx + 1, total_frames,
                            f"Frame {frame_idx + 1}/{total_frames} ({elapsed_s:.1f}s / {duration:.1f}s)"
                        )

                # Finalize
                ffmpeg_proc.stdin.close()
                # Timeout scales with video length: at least 60s, plus 1s per second of video
                finalize_timeout = max(60, int(duration) + 60)
                self._report_progress(total_frames, total_frames, f"Encoding final output ({finalize_timeout}s timeout)...")
                ffmpeg_proc.wait(timeout=finalize_timeout)

                if ffmpeg_proc.returncode != 0:
                    user_warnings.warn(f"FFmpeg failed (exit code {ffmpeg_proc.returncode}); no video was written", category="render")
                    return False

                self._report_progress(total_frames, total_frames, "Done!")
                print(f"Render complete: {self.output_path}")
                return True

            except BrokenPipeError:
                user_warnings.warn("FFmpeg pipe broken; encoding may have failed", category="render")
                return False

        except Exception as e:
            user_warnings.warn(f"Render failed: {e}", category="render")
            import traceback
            traceback.print_exc()
            return False

        finally:
            self._cleanup()

    def capture_stills(self, times: List[float], output_dir: str, prefix: str = "still") -> List[str]:
        """Render PNG stills at the given show times. No FFmpeg required.

        Uses a single monotonic forward pass at ``self.fps`` so the stateful
        per-block DMX tracking matches real-time playback exactly, grabbing a
        frame at the pass frame nearest each requested time.

        Returns the list of written file paths (sorted by time).
        """
        from PIL import Image

        os.makedirs(output_dir, exist_ok=True)

        song_structure = SongStructure()
        song_structure.load_from_show_parts(self.show.parts)
        duration = song_structure.get_total_duration()
        if duration <= 0:
            user_warnings.warn("Show has no duration, nothing to capture", category="render")
            return []

        # Clamp + de-duplicate targets, keep them ordered.
        targets = sorted({max(0.0, min(t, duration - 1e-3)) for t in times})
        total_frames = max(1, int(duration * self.fps))

        try:
            self._init_gl_context()
            self._init_renderers()
            self._init_dmx(song_structure)
            mvp = self._setup_camera()

            written: List[str] = []
            ti = 0
            for frame_idx in range(total_frames):
                if self._cancelled:
                    break
                time_s = frame_idx / self.fps
                self._update_dmx_at_time(time_s, song_structure)
                self._apply_dmx_to_fixtures()

                # Only pay for a GL read + encode on frames we actually keep.
                while ti < len(targets) and targets[ti] <= time_s:
                    self._render_frame(mvp)
                    pixels = self._fbo.read(components=3)
                    arr = np.frombuffer(pixels, dtype=np.uint8).reshape(self.height, self.width, 3)
                    arr = np.flipud(arr)
                    path = os.path.join(output_dir, f"{prefix}_{targets[ti]:06.1f}s.png")
                    Image.fromarray(arr, "RGB").save(path)
                    written.append(path)
                    self._report_progress(len(written), len(targets), f"Still at {targets[ti]:.1f}s")
                    ti += 1
                if ti >= len(targets):
                    break
            return written
        finally:
            self._cleanup()

    def render_gif(
        self,
        output_path: str,
        gif_fps: int = 15,
        max_width: int = 640,
        colors: int = 128,
    ) -> bool:
        """Render the whole show to an optimized animated GIF. No FFmpeg needed.

        GIFs stay small (repo-friendly) by downscaling to ``max_width``, sampling
        at ``gif_fps`` (a fraction of the render fps), and quantizing every frame
        to a single shared ``colors``-entry palette. One global palette (rather
        than a per-frame one) lets GIF frame-diffing + ``optimize`` compress the
        mostly-static dark stage far better.

        Returns True on success.
        """
        from PIL import Image

        song_structure = SongStructure()
        song_structure.load_from_show_parts(self.show.parts)
        duration = song_structure.get_total_duration()
        if duration <= 0:
            user_warnings.warn("Show has no duration, nothing to render", category="render")
            return False

        step = max(1, round(self.fps / max(1, gif_fps)))
        total_frames = max(1, int(duration * self.fps))
        # Preserve aspect ratio; only ever downscale.
        scale = min(1.0, max_width / self.width)
        out_w = max(1, int(round(self.width * scale)))
        out_h = max(1, int(round(self.height * scale)))

        try:
            self._init_gl_context()
            self._init_renderers()
            self._init_dmx(song_structure)
            mvp = self._setup_camera()

            rgb_frames = []
            for frame_idx in range(total_frames):
                if self._cancelled:
                    return False
                time_s = frame_idx / self.fps
                self._update_dmx_at_time(time_s, song_structure)
                self._apply_dmx_to_fixtures()
                if frame_idx % step != 0:
                    continue

                self._render_frame(mvp)
                pixels = self._fbo.read(components=3)
                arr = np.frombuffer(pixels, dtype=np.uint8).reshape(self.height, self.width, 3)
                arr = np.flipud(arr)
                img = Image.fromarray(arr, "RGB")
                if scale < 1.0:
                    img = img.resize((out_w, out_h), Image.LANCZOS)
                rgb_frames.append(img)

                if (frame_idx // step) % gif_fps == 0:
                    self._report_progress(frame_idx + 1, total_frames,
                                          f"GIF frame {len(rgb_frames)} ({time_s:.1f}s / {duration:.1f}s)")

            if not rgb_frames:
                return False

            # Build ONE global palette from frames sampled across the whole show
            # (colours drift section to section), then map every frame onto it.
            sample = rgb_frames[:: max(1, len(rgb_frames) // 24)]
            stack = Image.new("RGB", (out_w, out_h * len(sample)))
            for i, f in enumerate(sample):
                stack.paste(f, (0, i * out_h))
            palette_img = stack.quantize(colors=colors, method=Image.MEDIANCUT)
            # No dithering: on a dark stage it just adds high-frequency noise that
            # wrecks GIF/LZW compression. disposal=1 (leave prior frame) lets PIL's
            # optimizer emit only the changed bounding box per frame — a big win for
            # the mostly-static background with moving beams.
            p_frames = [f.quantize(palette=palette_img, dither=Image.NONE) for f in rgb_frames]

            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            p_frames[0].save(
                output_path, save_all=True, append_images=p_frames[1:],
                duration=int(round(1000 / gif_fps)), loop=0, optimize=True, disposal=1,
            )
            size_mb = os.path.getsize(output_path) / 1e6
            self._report_progress(total_frames, total_frames, "Done!")
            print(f"GIF complete: {output_path}  ({len(p_frames)} frames, {out_w}x{out_h}, "
                  f"{colors} colors, {size_mb:.1f} MB)")
            return True
        finally:
            self._cleanup()

    def _report_progress(self, current: int, total: int, message: str):
        """Report progress via callback."""
        if self.progress_callback:
            self.progress_callback(current, total, message)

    def _init_gl_context(self):
        """Create standalone ModernGL context and FBO."""
        self._ctx = moderngl.create_context(standalone=True)
        # Create color and depth textures for the FBO
        color_tex = self._ctx.texture((self.width, self.height), 3)
        depth_tex = self._ctx.depth_renderbuffer((self.width, self.height))
        self._fbo = self._ctx.framebuffer(
            color_attachments=[color_tex],
            depth_attachment=depth_tex
        )

    def _init_renderers(self):
        """Initialize stage and fixture renderers using the headless context."""
        from visualizer.renderer.stage import StageRenderer
        from visualizer.renderer.fixtures import FixtureManager

        # Optionally suppress the debug coordinate-axis triads that some chassis
        # geometries draw for orientation. It's a class-level global, but this
        # renderer runs in its own one-shot (headless) process, so flipping it
        # here doesn't leak into a running GUI. Covers any chassis exposing the
        # documented ``show_axes`` attribute, present and future.
        if not self.show_gizmos:
            import inspect
            import visualizer.renderer.chassis as chassis_mod
            for _name, cls in inspect.getmembers(chassis_mod, inspect.isclass):
                if hasattr(cls, "show_axes"):
                    cls.show_axes = False

        # Stage
        self._stage_renderer = StageRenderer(
            self._ctx,
            width=self.config.stage_width,
            depth=self.config.stage_height
        )

        # Fixtures — build fixture data dicts (same format as TCP protocol)
        from utils.tcp.protocol import VisualizerProtocol
        import json
        fixtures_msg = VisualizerProtocol.create_fixtures_message(self.config)
        fixtures_data = json.loads(fixtures_msg.strip())['fixtures']

        self._fixture_manager = FixtureManager(self._ctx)
        self._fixture_manager.update_fixtures(fixtures_data)

    def _init_dmx(self, song_structure: SongStructure):
        """Initialize DMX manager and resolve lane fixtures."""
        self._dmx_manager = DMXManager(self.config, self.fixture_definitions, song_structure)

        # Pre-resolve fixtures for each lane (cached)
        self._lane_fixtures = {}
        self._light_lanes = []

        if self.show.timeline_data:
            for lane in self.show.timeline_data.lanes:
                if lane.muted:
                    continue
                targets = getattr(lane, 'fixture_targets', [])
                if not targets and hasattr(lane, 'fixture_group') and lane.fixture_group:
                    targets = [lane.fixture_group]
                if targets:
                    resolved = resolve_targets_unique(targets, self.config)
                    if resolved:
                        lane_key = f"{id(lane)}_{lane.name}" if lane.name else f"{id(lane)}"
                        self._lane_fixtures[lane_key] = (lane, resolved)
                        self._light_lanes.append((lane_key, lane, resolved))

        # Track active block IDs per lane (same structure as ShowsArtNetController)
        self._active_block_ids = {}

    def _update_dmx_at_time(self, time_s: float, song_structure: SongStructure):
        """Compute DMX state at a given time by processing all lane blocks.

        Maintains persistent block tracking across frames (same as real-time controller).
        DMX state is NOT cleared — active blocks continuously write their values via update_dmx().
        """
        for lane_key, lane, resolved_fixtures in self._light_lanes:
            if lane_key not in self._active_block_ids:
                self._active_block_ids[lane_key] = {
                    'dimmer': set(), 'colour': set(), 'movement': set(), 'special': set()
                }

            currently_active = {
                'dimmer': set(), 'colour': set(), 'movement': set(), 'special': set()
            }

            for light_block in lane.light_blocks:
                # Dimmer blocks
                for block in light_block.dimmer_blocks:
                    block_id = id(block)
                    if block.start_time <= time_s < block.end_time:
                        currently_active['dimmer'].add(block_id)
                        if block_id not in self._active_block_ids[lane_key]['dimmer']:
                            self._dmx_manager.block_started(lane_key, resolved_fixtures, block, 'dimmer', time_s)
                            self._active_block_ids[lane_key]['dimmer'].add(block_id)

                # Colour blocks
                for block in light_block.colour_blocks:
                    block_id = id(block)
                    if block.start_time <= time_s < block.end_time:
                        currently_active['colour'].add(block_id)
                        if block_id not in self._active_block_ids[lane_key]['colour']:
                            self._dmx_manager.block_started(lane_key, resolved_fixtures, block, 'colour', time_s)
                            self._active_block_ids[lane_key]['colour'].add(block_id)

                # Movement blocks
                for block in light_block.movement_blocks:
                    block_id = id(block)
                    if block.start_time <= time_s < block.end_time:
                        currently_active['movement'].add(block_id)
                        if block_id not in self._active_block_ids[lane_key]['movement']:
                            self._dmx_manager.block_started(lane_key, resolved_fixtures, block, 'movement', time_s)
                            self._active_block_ids[lane_key]['movement'].add(block_id)

                # Special blocks
                for block in light_block.special_blocks:
                    block_id = id(block)
                    if block.start_time <= time_s < block.end_time:
                        currently_active['special'].add(block_id)
                        if block_id not in self._active_block_ids[lane_key]['special']:
                            self._dmx_manager.block_started(lane_key, resolved_fixtures, block, 'special', time_s)
                            self._active_block_ids[lane_key]['special'].add(block_id)

            # End blocks no longer active
            for sublane_type in ['dimmer', 'colour', 'movement', 'special']:
                ended = self._active_block_ids[lane_key][sublane_type] - currently_active[sublane_type]
                if ended and not currently_active[sublane_type]:
                    self._dmx_manager.block_ended(lane_key, sublane_type)
                self._active_block_ids[lane_key][sublane_type] = currently_active[sublane_type]

        # Compute final DMX values
        self._dmx_manager.update_dmx(time_s)

    def _apply_dmx_to_fixtures(self):
        """Apply current DMX state to fixture renderers."""
        for universe_id, dmx_data in self._dmx_manager.dmx_state.items():
            self._fixture_manager.update_dmx(universe_id, bytes(dmx_data))

    def _setup_camera(self) -> glm.mat4:
        """Set up camera MVP matrix from preset."""
        preset = CAMERA_PRESETS.get(self.camera_preset_name, CAMERA_PRESETS["Front"])
        params = preset["get_params"](self.config.stage_width, self.config.stage_height)

        from visualizer.renderer.camera import OrbitCamera
        camera = OrbitCamera()
        camera.azimuth = params["azimuth"]
        camera.elevation = params["elevation"]
        camera.distance = params["distance"]
        camera.target = glm.vec3(*params["target"])
        camera.aspect = self.width / self.height

        return camera.get_view_projection_matrix()

    def _render_frame(self, mvp: glm.mat4):
        """Render a single frame to the FBO."""
        self._fbo.use()
        self._ctx.viewport = (0, 0, self.width, self.height)
        self._ctx.enable(moderngl.DEPTH_TEST)
        self._ctx.enable(moderngl.BLEND)
        self._ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)

        # Clear to dark background
        self._fbo.clear(0.05, 0.05, 0.08, 1.0)

        # Render stage floor and grid
        self._stage_renderer.render(mvp)

        # Render fixtures
        self._fixture_manager.render(mvp)

    def _resolve_audio_path(self) -> Optional[str]:
        """Resolve the audio file path for the show."""
        if not self.show.timeline_data or not self.show.timeline_data.audio_file_path:
            return None

        audio_file = self.show.timeline_data.audio_file_path
        if os.path.isabs(audio_file) and os.path.exists(audio_file):
            return audio_file

        # Relative path — look in shows_directory/audiofiles/
        if self.config.shows_directory:
            path = os.path.join(self.config.shows_directory, "audiofiles", audio_file)
            if os.path.exists(path):
                return path

        return None

    def _start_ffmpeg(self, audio_path: Optional[str]) -> Optional[subprocess.Popen]:
        """Start FFmpeg subprocess for encoding."""
        try:
            import imageio_ffmpeg
            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            user_warnings.warn("imageio-ffmpeg is not installed; cannot render video (pip install imageio-ffmpeg)", category="render", once_key="imageio-missing")
            return None

        cmd = [
            ffmpeg_path,
            '-y',                           # Overwrite output
            '-f', 'rawvideo',               # Input format
            '-pix_fmt', 'rgb24',            # Pixel format
            '-s', f'{self.width}x{self.height}',
            '-r', str(self.fps),            # Input FPS
            '-i', 'pipe:0',                 # Read video from stdin
        ]

        if audio_path:
            cmd.extend(['-i', audio_path])  # Audio input

        cmd.extend([
            '-c:v', 'libx264',
            '-preset', 'fast',              # Fast encoding to keep up with frame pipe
            '-crf', '20',                   # Good quality (slightly lower than 18 for speed)
            '-pix_fmt', 'yuv420p',          # Compatible pixel format
            '-threads', '0',                # Use all available CPU cores
        ])

        if audio_path:
            cmd.extend([
                '-c:a', 'aac',
                '-b:a', '192k',
                '-shortest',                # End at shorter stream
            ])

        cmd.append(self.output_path)

        print(f"Starting FFmpeg: {' '.join(cmd[:10])}...")
        # stderr goes to DEVNULL to prevent pipe buffer filling up and blocking FFmpeg
        return subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _cleanup(self):
        """Release OpenGL resources."""
        if self._fixture_manager:
            for fix in self._fixture_manager.fixtures.values():
                try:
                    fix.release()
                except Exception:
                    pass

        if self._stage_renderer:
            try:
                self._stage_renderer.release()
            except Exception:
                pass

        if self._fbo:
            try:
                self._fbo.release()
            except Exception:
                pass

        if self._ctx:
            try:
                self._ctx.release()
            except Exception:
                pass
