"""
EmbeddedVisualizer — in-process 3D preview for the Stage and Shows tabs.

Wraps :class:`visualizer.renderer.engine.RenderEngine` (a ``QOpenGLWidget``)
so the same renderer used by the standalone visualizer subprocess can sit
inline inside a tab. The standalone path keeps working unchanged — the
embedded view is additive.

Two preview modes:

- **"build"**: synthesise a sane DMX buffer per universe (RGB(W) full,
  pan/tilt mid, shutter open, gobo/strobe/etc. off) so every fixture is
  visibly lit while the user is positioning them on the 2D Stage view.
  Live ``feed_dmx`` calls are ignored in this mode.
- **"live"**: pass through DMX from whoever is feeding us. Used while
  playback is running so the embedded preview mirrors the show.
"""

from typing import Callable, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
)


# Per-channel-function defaults applied in build mode. Anything not in the
# table stays 0. Keeps colored fixtures lit white, mover targets centred on
# stage, no gobo/prism/strobe artefacts.
_BUILD_MODE_DEFAULTS = {
    "dimmer": 255,
    "red": 255,
    "green": 255,
    "blue": 255,
    "white": 255,
    "amber": 255,
    "pan": 128,
    "tilt": 128,
    "pan_fine": 128,
    "tilt_fine": 128,
    "shutter": 255,  # most fixtures: 255 = open / no strobe
    "focus": 128,
    "zoom": 128,
}


class EmbeddedVisualizer(QWidget):
    """Compact in-tab 3D preview wrapping ``RenderEngine``."""

    # Marshals DMX frames from any thread onto the Qt main / GL thread.
    # ``feed_dmx`` is called from the live DMX worker at 30 Hz; the
    # RenderEngine's GL paint reads fixture state on the main thread,
    # so direct mutation would race. The queued connection on the slot
    # in :meth:`_setup_ui` does the thread hop.
    _dmx_frame = pyqtSignal(int, object)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._config = None
        self._preview_mode = "live"
        self._pop_out_callback: Optional[Callable[[], None]] = None
        self._setup_ui()

    # ── UI scaffolding ────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        # Importing inside the method so the heavy moderngl/visualizer
        # graph is only pulled in when this widget is actually constructed.
        from visualizer.renderer.engine import RenderEngine

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Compact toolbar row.
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(4, 2, 4, 2)
        toolbar.setSpacing(6)

        self._reset_btn = QPushButton("Reset Camera")
        self._reset_btn.setToolTip("Recenter the orbit camera")
        toolbar.addWidget(self._reset_btn)

        self._popout_btn = QPushButton("Pop Out")
        self._popout_btn.setToolTip("Launch the standalone visualizer subprocess")
        toolbar.addWidget(self._popout_btn)

        toolbar.addStretch()

        self._fps_label = QLabel("FPS: --")
        self._fps_label.setStyleSheet("font-family: monospace; font-size: 10px;")
        toolbar.addWidget(self._fps_label)

        layout.addLayout(toolbar)

        # The actual GL surface.
        self._engine = RenderEngine(self)
        layout.addWidget(self._engine, 1)

        # FPS poll — light-touch, half-second cadence.
        self._fps_timer = QTimer(self)
        self._fps_timer.timeout.connect(self._update_fps_label)
        self._fps_timer.start(500)

        self._reset_btn.clicked.connect(self._engine.reset_camera)
        self._popout_btn.clicked.connect(self._on_popout_clicked)

        # Queued connection: emit-from-DMX-thread → slot-runs-on-main.
        self._dmx_frame.connect(
            self._apply_dmx_frame, Qt.ConnectionType.QueuedConnection,
        )

    # ── Public API ────────────────────────────────────────────────────

    def set_config(self, config) -> None:
        """Apply a Configuration: stage dims + fixtures + (build-mode) lights.

        Idempotent — call this whenever fixture positions/orientations change
        and the embedded view will catch up. ``set_stage_size`` /
        ``set_grid_size`` are forwarded; fixtures use the same payload shape
        the standalone visualizer receives over TCP, but built directly via
        :func:`utils.tcp.protocol.VisualizerProtocol.build_fixtures_payload`
        so we skip the JSON round-trip.
        """
        self._config = config
        if config is None:
            return

        from utils.tcp.protocol import VisualizerProtocol

        self._engine.set_stage_size(config.stage_width, config.stage_height)
        if hasattr(config, "grid_size") and config.grid_size:
            self._engine.set_grid_size(config.grid_size)

        payload = VisualizerProtocol.build_fixtures_payload(config)
        self._engine.update_fixtures(payload)

        # Re-push the build-mode buffer so newly-added fixtures light up.
        if self._preview_mode == "build":
            self._push_build_mode_dmx()

    def set_highlighted_plane(self, name, rig_height: float = 3.0) -> None:
        """Highlight one stage bounding-cuboid face in the 3D preview
        (None clears). Forwarded to the engine, which buffers it if GL
        hasn't initialized yet (inactive tab)."""
        self._engine.set_highlighted_plane(name, rig_height)

    def feed_dmx(self, universe: int, dmx_bytes: bytes) -> None:
        """Forward a DMX frame to the engine.

        Always forwards — earlier versions gated this on
        ``preview_mode == "live"`` to "protect" the synthetic build-mode
        buffer from being overwritten, but that had two problems: a race
        between starting the DMX thread and flipping the preview mode
        could drop frames at the start of a show, and Live (Auto) mode
        users observed the visualizer freezing on the build-mode full-on
        buffer instead of mirroring the wire. The build/live distinction
        is now purely about what gets pushed when *no* live source is
        feeding: ``set_preview_mode("build")`` synthesises a full-on
        buffer; live frames overwrite it the instant a controller starts
        sending.

        Thread-safe: emits a queued signal so the actual GL-state
        mutation runs on the main thread even if this is called from
        the DMX worker.
        """
        if dmx_bytes is None:
            return
        self._dmx_frame.emit(universe, dmx_bytes)

    def _apply_dmx_frame(self, universe: int, dmx_bytes: bytes) -> None:
        """Slot for the :pyattr:`_dmx_frame` queued signal — runs on the
        Qt main thread, safely mutates renderer state."""
        self._engine.update_dmx(universe, dmx_bytes)

    def set_preview_mode(self, mode: str) -> None:
        """Switch between ``"build"`` and ``"live"``.

        Build mode immediately pushes a synthetic full-on buffer per
        universe so every fixture lights up. Live mode does nothing on
        switch — whoever is calling :meth:`feed_dmx` will fill it in.
        """
        if mode not in ("build", "live"):
            return
        if mode == self._preview_mode:
            return
        self._preview_mode = mode
        if mode == "build":
            self._push_build_mode_dmx()

    def preview_mode(self) -> str:
        return self._preview_mode

    def set_pop_out_callback(self, callback: Optional[Callable[[], None]]) -> None:
        """Wire the Pop Out button to the standalone-visualizer launcher
        provided by the hosting tab."""
        self._pop_out_callback = callback

    def cleanup(self) -> None:
        """Stop the FPS timer. The engine's GL teardown happens through Qt's
        normal child-deletion when the widget itself is destroyed."""
        if hasattr(self, "_fps_timer") and self._fps_timer is not None:
            self._fps_timer.stop()

    # ── Internals ─────────────────────────────────────────────────────

    def _on_popout_clicked(self) -> None:
        if self._pop_out_callback is not None:
            self._pop_out_callback()

    def _update_fps_label(self) -> None:
        try:
            fps = self._engine.get_fps()
        except Exception:
            return
        self._fps_label.setText(f"FPS: {fps:.0f}")

    def _push_build_mode_dmx(self) -> None:
        """Synthesise per-universe DMX buffers using sane defaults per
        channel function and push them through the engine."""
        if self._config is None:
            return

        # Lazy import to keep startup cheap and avoid a hard dependency
        # circle during module import.
        from utils.tcp.protocol import _parse_qxf_for_visualizer

        # Group fixtures by their universe so we send one buffer per universe.
        per_universe: dict = {}
        for fixture in self._config.fixtures:
            per_universe.setdefault(fixture.universe, []).append(fixture)

        for universe, fixtures in per_universe.items():
            buffer = bytearray(512)
            for fixture in fixtures:
                qxf = _parse_qxf_for_visualizer(
                    fixture.manufacturer, fixture.model, fixture.current_mode,
                )
                channel_mapping = qxf.get("channel_mapping", {})
                # QLC+ addresses are 1-based; bytes are 0-based.
                base_addr = max(0, fixture.address - 1)
                for ch_num, func in channel_mapping.items():
                    try:
                        idx = base_addr + int(ch_num)
                    except (TypeError, ValueError):
                        continue
                    if 0 <= idx < 512:
                        buffer[idx] = _BUILD_MODE_DEFAULTS.get(func, 0)
            self._engine.update_dmx(universe, bytes(buffer))
