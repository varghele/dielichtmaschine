# timeline_ui/timeline_widget.py
# Base timeline widget with grid drawing and snap functionality
# Adapted from midimaker_and_show_structure/ui/lane_widget.py

import json
import math
from PyQt6.QtWidgets import QWidget, QMenu
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QColor, QWheelEvent, QBrush


# Standard triplet-swing ratio: the off-beat lands at 2/3 of the beat.
SWING_RATIO = 2.0 / 3.0
# Epsilon guards. Subdivision is now a float (steps per beat): coarse grids
# are fractions (0.25 = a line every 4 beats), fine grids are >1 (16 = 1/16).
_SUBDIVISION_EPS = 1e-6
_STEP_EPS = 1e-9


def swing_warp(f: float, ratio: float = SWING_RATIO) -> float:
    """Warp a within-beat fraction ``f`` in [0, 1) to a triplet (2:1) feel.

    ``swing_warp(0) == 0`` (beat/bar lines are unaffected), ``swing_warp(0.5)``
    lands on ``ratio`` (2/3), and the function is monotonic increasing on
    [0, 1) with ``swing_warp(f) -> 1`` as ``f -> 1``. Two linear pieces map
    the first and second half of the beat onto [0, ratio] and [ratio, 1].
    """
    if f < 0.5:
        return (f / 0.5) * ratio
    return ratio + ((f - 0.5) / 0.5) * (1.0 - ratio)


def _is_multiple(value: float, base: float, eps: float = 1e-6) -> bool:
    """True if ``value`` is (approximately) an integer multiple of ``base``."""
    if base <= 0:
        return False
    r = value % base
    return r < eps or (base - r) < eps


def iter_grid_steps(part_start, seconds_per_beat, beats_per_bar, total_beats,
                    subdivision, swing, is_last_part,
                    pixels_per_second, min_subdivision_pixels):
    """Yield ``(step_time, kind)`` grid lines for one part.

    ``kind`` is ``"bar"`` (bar boundary), ``"beat"`` (beat boundary) or
    ``"sub"`` (finer sub-beat line). ``subdivision`` is steps-per-beat as a
    float: values <= 1 give sparse coarse grids (a line every 1/subdivision
    beats) that are always drawn; values > 1 give fine sub-beat lines that
    are hidden when they get denser than ``min_subdivision_pixels``. When
    ``swing`` is on, sub-beat fractions are warped by :func:`swing_warp`;
    beat/bar lines (fraction 0) are never moved.
    """
    subdivision = max(_SUBDIVISION_EPS, float(subdivision))
    seconds_per_step = seconds_per_beat / subdivision
    pixels_per_step = seconds_per_step * pixels_per_second
    # Fine sub-lines become visual noise below the density floor: fall back
    # to a beat-resolution grid. Coarse grids (<= 1) are sparse: always drawn.
    if subdivision > 1.0 and pixels_per_step < min_subdivision_pixels:
        sub = 1.0
    else:
        sub = subdivision

    upper = total_beats + _STEP_EPS if is_last_part else total_beats - _STEP_EPS
    step_index = 0
    while True:
        beat_pos = step_index / sub
        if beat_pos > upper:
            break
        beat_index = int(math.floor(beat_pos + _STEP_EPS))
        frac = beat_pos - beat_index
        if frac < _STEP_EPS:
            frac = 0.0
        warped = swing_warp(frac) if (swing and frac > 0.0) else frac
        step_time = part_start + (beat_index + warped) * seconds_per_beat
        if frac == 0.0:
            kind = "bar" if _is_multiple(beat_index, beats_per_bar) else "beat"
        else:
            kind = "sub"
        yield step_time, kind
        step_index += 1


def _snap_in_frame(target, frame_start, seconds_per_beat, subdivision, swing):
    """Snap ``target`` to the grid within a single-tempo frame.

    ``frame_start`` is the reference (part start or 0); ``subdivision`` is
    steps-per-beat (float). Without swing (or for coarse grids <= 1) this is
    plain nearest-step rounding. With swing on and a fine grid, candidate
    positions are the swing-warped sub-beat fractions of the nearby beats.
    """
    seconds_per_step = seconds_per_beat / subdivision
    if not swing or subdivision <= 1.0:
        step = round((target - frame_start) / seconds_per_step)
        return frame_start + step * seconds_per_step

    steps_per_beat = max(1, int(round(subdivision)))
    beat = (target - frame_start) / seconds_per_beat
    base_beat = int(math.floor(beat))
    best = None
    for b in (base_beat - 1, base_beat, base_beat + 1):
        for k in range(steps_per_beat):
            f = k / steps_per_beat
            cand = frame_start + (b + swing_warp(f)) * seconds_per_beat
            if best is None or abs(cand - target) < abs(best - target):
                best = cand
    return best


class TimelineWidget(QWidget):
    """Base timeline widget with grid drawing and snap functionality.

    Provides time-based grid drawing, zoom, scroll, and playhead functionality.
    Can be subclassed for specific use cases (master timeline, lane timelines).
    """

    zoom_changed = pyqtSignal(float)  # Emits new zoom factor
    playhead_moved = pyqtSignal(float)  # Emits playhead position in seconds
    paste_requested = pyqtSignal(float)  # Emits time position when paste requested
    riff_dropped = pyqtSignal(str, float)  # Emits (riff_path, drop_time) when riff dropped

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bpm = 120.0
        self.zoom_factor = 1.0
        self.base_pixels_per_second = 60  # Base: 60 pixels per second
        self.pixels_per_second = self.base_pixels_per_second
        self.snap_to_grid = True
        # Grid steps per beat, as a float. 1.0=on-beat; fractions give coarse
        # grids (0.25 = a line every 4 beats, 0.5 = every 2 beats); values > 1
        # give fine sub-beat lines (2=1/2, 4=1/4, 8=1/8, 16=1/16). Fine lines
        # render fainter than beat lines and are zoom-gated (hidden when too
        # small to read — see draw_*_grid); coarse grids are always drawn.
        self.grid_subdivision = 1.0
        # Below this many pixels per subdivision step, the extra fine grid
        # lines become visual noise rather than guidance. Snap targets stay
        # active.
        self.min_subdivision_pixels = 12
        # Triplet swing for the off-beat grid. When True, sub-beat lines and
        # snap targets are warped so the eighth-note off-beat sits at 2/3 of
        # the beat instead of 1/2. Beat/bar lines are never moved.
        self.swing_enabled = False
        self.playhead_position = 0.0  # Position in seconds
        self.dragging_playhead = False
        self.min_zoom = 0.1
        self.max_zoom = 5.0
        self.song_structure = None

        # Sublane support
        self.num_sublanes = 1  # Number of sublanes (1-4)
        self.sublane_height = 60  # Height per sublane in pixels
        self.capabilities = None  # FixtureGroupCapabilities (for label drawing)

        # Drag-drop support for riffs
        self.setAcceptDrops(True)
        self._drag_preview_time = None  # Time position for drag preview
        self._drag_preview_length = None  # Length of riff being dragged (in beats)

        self.setMinimumHeight(60)
        self.update_timeline_width()
        # Background and border come from the active theme via the
        # `TimelineWidget` selector. No inline setStyleSheet here — it
        # would override the theme. WA_StyledBackground is required for
        # QSS background rules to render on plain QWidget subclasses;
        # without it, super().paintEvent() leaves the widget transparent.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def update_timeline_width(self):
        """Update timeline width based on zoom level and song structure."""
        self.pixels_per_second = self.base_pixels_per_second * self.zoom_factor

        # Check if we have song structure to calculate width
        if self.song_structure and hasattr(self.song_structure, 'parts') and self.song_structure.parts:
            try:
                total_duration = self.song_structure.get_total_duration()
                new_width = max(2000, int(total_duration * self.pixels_per_second) + 100)
            except (AttributeError, ZeroDivisionError, TypeError):
                new_width = max(2000, int(60 * self.pixels_per_second))
        else:
            new_width = max(2000, int(60 * self.pixels_per_second))

        self.setMinimumWidth(new_width)

    def time_to_pixel(self, time: float) -> float:
        """Convert time in seconds to pixel position."""
        return time * self.pixels_per_second

    def pixel_to_time(self, pixel: float) -> float:
        """Convert pixel position to time in seconds."""
        return pixel / self.pixels_per_second

    def set_song_structure(self, song_structure):
        """Set song structure for this timeline."""
        self.song_structure = song_structure
        self.update_timeline_width()
        self.update()

    def set_bpm(self, bpm: float):
        """Set BPM for grid calculations."""
        self.bpm = bpm
        self.update()

    def set_zoom_factor(self, zoom_factor: float):
        """Set zoom factor externally."""
        self.zoom_factor = zoom_factor
        self.update_timeline_width()
        self.update()

    def set_snap_to_grid(self, snap: bool):
        """Enable/disable snap to grid."""
        self.snap_to_grid = snap

    def set_grid_subdivision(self, subdivision: float):
        """Set how many grid steps fit in one beat (float, steps per beat).

        0.25/0.5 give coarse grids (a line every 4/2 beats); 1 is on-beat;
        2/4/8/16 give fine sub-beat grids. Values outside the UI catalog still
        work mathematically.
        """
        self.grid_subdivision = max(_SUBDIVISION_EPS, float(subdivision))
        self.update()

    def set_swing(self, enabled: bool):
        """Enable/disable triplet swing on the sub-beat grid and repaint."""
        self.swing_enabled = bool(enabled)
        self.update()

    def set_playhead_position(self, position: float):
        """Set playhead position and update display."""
        self.playhead_position = position
        self.update()

    def get_current_bpm(self) -> float:
        """Get BPM at current playhead position."""
        if self.song_structure and hasattr(self.song_structure, 'get_bpm_at_time'):
            try:
                return self.song_structure.get_bpm_at_time(self.playhead_position)
            except (AttributeError, TypeError):
                pass
        return self.bpm

    def wheelEvent(self, event: QWheelEvent):
        """Handle mouse wheel events for zooming."""
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            # Shift + wheel = zoom
            delta = event.angleDelta().y()
            zoom_in = delta > 0

            # Get mouse position for zoom center
            mouse_x = event.position().x()

            # Calculate time position at mouse cursor before zoom
            time_at_mouse = self.pixel_to_time(mouse_x)

            # Apply zoom
            old_zoom = self.zoom_factor
            if zoom_in:
                self.zoom_factor = min(self.max_zoom, self.zoom_factor * 1.2)
            else:
                self.zoom_factor = max(self.min_zoom, self.zoom_factor / 1.2)

            if self.zoom_factor != old_zoom:
                self.update_timeline_width()
                self.zoom_changed.emit(self.zoom_factor)

                # Maintain mouse position after zoom
                new_mouse_x = self.time_to_pixel(time_at_mouse)
                scroll_offset = new_mouse_x - mouse_x

                # Notify parent scroll area to adjust position
                if hasattr(self.parent(), 'horizontalScrollBar'):
                    current_scroll = self.parent().horizontalScrollBar().value()
                    self.parent().horizontalScrollBar().setValue(int(current_scroll + scroll_offset))

                self.update()

            event.accept()
        else:
            # Normal wheel = scroll horizontally
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        """Handle mouse press for playhead dragging."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging_playhead = True
            self.update_playhead_from_mouse(event.pos().x())

    def mouseMoveEvent(self, event):
        """Handle mouse move for playhead dragging."""
        if self.dragging_playhead:
            self.update_playhead_from_mouse(event.pos().x())

    def mouseReleaseEvent(self, event):
        """Handle mouse release to stop playhead dragging."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging_playhead = False

    def contextMenuEvent(self, event):
        """Handle right-click context menu for paste."""
        from timeline_ui.effect_clipboard import has_clipboard_data, has_multi_clipboard_data, get_multi_clipboard_count

        menu = QMenu(self)

        # Calculate time at click position
        click_time = self.pixel_to_time(event.pos().x())
        if self.snap_to_grid:
            click_time = self.find_nearest_beat_time(click_time)

        # Add paste action if clipboard has data
        if has_clipboard_data():
            # Show count if multiple effects in clipboard
            if has_multi_clipboard_data():
                count = get_multi_clipboard_count()
                paste_label = f"Paste {count} Effects"
            else:
                paste_label = "Paste Effect"
            paste_action = menu.addAction(paste_label)
            paste_action.triggered.connect(lambda: self.paste_requested.emit(click_time))
        else:
            paste_action = menu.addAction("Paste Effect (no effect copied)")
            paste_action.setEnabled(False)

        menu.exec(event.globalPos())

    def update_playhead_from_mouse(self, x_pos: int):
        """Update playhead position based on mouse position."""
        time_position = self.pixel_to_time(x_pos)

        # Apply snap to grid if enabled
        if self.snap_to_grid:
            time_position = self.find_nearest_beat_time(time_position)

        time_position = max(0.0, time_position)
        self.playhead_position = time_position
        self.playhead_moved.emit(time_position)
        self.update()

    def find_nearest_beat_time(self, target_time: float) -> float:
        """Find the nearest snap position using song structure if available.

        Honours ``self.grid_subdivision`` (float steps-per-beat, so coarse and
        fine grids snap uniformly) and ``self.swing_enabled`` (off-beat targets
        warp to the triplet feel), whether or not a song structure is loaded.
        Snapping is done in-widget rather than delegating to SongStructure so
        the float/swing behaviour matches the drawn grid exactly.
        """
        subdivision = max(_SUBDIVISION_EPS, float(getattr(self, "grid_subdivision", 1.0)))
        swing = bool(getattr(self, "swing_enabled", False))

        ss = self.song_structure
        if ss and hasattr(ss, 'parts') and ss.parts:
            part = ss.get_part_at_time(target_time)
            if part is None:
                # Before the first part or past the last: no grid to snap to.
                if target_time < 0:
                    return 0.0
                return target_time
            if getattr(part, "transition", "instant") != "instant":
                # Gradual transitions have no stable beat grid; punt (matches
                # SongStructure.find_nearest_beat_time).
                return target_time
            seconds_per_beat = 60.0 / part.bpm
            return _snap_in_frame(target_time, part.start_time,
                                  seconds_per_beat, subdivision, swing)

        # Fallback: bare-BPM snap with no song structure.
        seconds_per_beat = 60.0 / self.bpm
        return _snap_in_frame(target_time, 0.0, seconds_per_beat, subdivision, swing)

    def draw_grid(self, painter, width, height):
        """Draw grid with song structure awareness."""
        if self.song_structure and hasattr(self.song_structure, 'parts') and self.song_structure.parts:
            try:
                self.draw_song_structure_grid(painter, width, height)
            except Exception as e:
                print(f"Error drawing song structure grid: {e}")
                self.draw_basic_grid(painter, width, height)
        else:
            self.draw_basic_grid(painter, width, height)

    def draw_song_structure_grid(self, painter, width, height):
        """Draw grid based on song structure, with optional sub-beat lines."""
        # Semi-transparent neutral gray reads on both dark and light themes
        # without needing explicit theme detection.
        sub_pen = QPen(QColor(127, 127, 127, 40), 1, Qt.PenStyle.DotLine)
        beat_pen = QPen(QColor(127, 127, 127, 80), 1)
        bar_pen = QPen(QColor(127, 127, 127, 160), 2)
        part_pen = QPen(QColor(127, 127, 127, 220), 3)

        subdivision = getattr(self, "grid_subdivision", 1.0)
        swing = getattr(self, "swing_enabled", False)
        min_px = getattr(self, "min_subdivision_pixels", 12)

        num_parts = len(self.song_structure.parts)
        for part_idx, part in enumerate(self.song_structure.parts):
            beats_per_bar = self._get_beats_per_bar(part.signature)
            total_beats_in_part = int(part.num_bars * beats_per_bar)
            seconds_per_beat = 60.0 / part.bpm

            # Draw part boundary
            start_x = round(self.time_to_pixel(part.start_time))
            if 0 <= start_x <= width:
                painter.setPen(part_pen)
                painter.drawLine(start_x, 0, start_x, height)

            is_last_part = (part_idx == num_parts - 1)
            for step_time, kind in iter_grid_steps(
                    part.start_time, seconds_per_beat, beats_per_bar,
                    total_beats_in_part, subdivision, swing, is_last_part,
                    self.pixels_per_second, min_px):
                step_x = round(self.time_to_pixel(step_time))
                if not (0 <= step_x <= width):
                    continue
                if kind == "bar":
                    painter.setPen(bar_pen)
                elif kind == "beat":
                    painter.setPen(beat_pen)
                else:
                    painter.setPen(sub_pen)
                painter.drawLine(step_x, 0, step_x, height)

    def draw_basic_grid(self, painter, width, height):
        """Draw basic grid without song structure (time-based)."""
        sub_pen = QPen(QColor(127, 127, 127, 40), 1, Qt.PenStyle.DotLine)
        beat_pen = QPen(QColor(127, 127, 127, 80), 1)
        bar_pen = QPen(QColor(127, 127, 127, 160), 2)

        subdivision = getattr(self, "grid_subdivision", 1.0)
        swing = getattr(self, "swing_enabled", False)
        min_px = getattr(self, "min_subdivision_pixels", 12)
        seconds_per_beat = 60.0 / self.bpm

        # Cover the visible width; treat it as one 4/4 "part".
        max_time = width / self.pixels_per_second
        total_beats = int(math.ceil(max_time / seconds_per_beat)) + 1
        for step_time, kind in iter_grid_steps(
                0.0, seconds_per_beat, 4.0, total_beats, subdivision, swing,
                True, self.pixels_per_second, min_px):
            x = round(self.time_to_pixel(step_time))
            if not (0 <= x <= width):
                continue
            if kind == "bar":
                painter.setPen(bar_pen)
            elif kind == "beat":
                painter.setPen(beat_pen)
            else:
                painter.setPen(sub_pen)
            painter.drawLine(x, 0, x, height)

    def draw_playhead(self, painter, width, height):
        """Draw playhead at time position."""
        playhead_x = round(self.time_to_pixel(self.playhead_position))

        if 0 <= playhead_x <= width:
            playhead_pen = QPen(QColor("#FF4444"), 2)
            painter.setPen(playhead_pen)
            painter.drawLine(playhead_x, 0, playhead_x, height)

    def draw_song_structure_background(self, painter, width, height):
        """Draw song structure parts as subtle colored backgrounds."""
        if not (self.song_structure and hasattr(self.song_structure, 'parts') and self.song_structure.parts):
            return

        try:
            for part in self.song_structure.parts:
                start_x = self.time_to_pixel(part.start_time)
                end_x = self.time_to_pixel(part.start_time + part.duration)

                if end_x < 0 or start_x > width:
                    continue

                # Draw colored background with lower alpha for subtle effect
                color = QColor(part.color)
                color.setAlpha(40)
                painter.fillRect(int(start_x), 0, int(end_x - start_x), height, color)

        except Exception as e:
            print(f"Error drawing song structure background: {e}")

    def draw_sublane_separators(self, painter, width, height):
        """Draw horizontal lines separating sublanes."""
        if self.num_sublanes <= 1:
            return

        separator_pen = QPen(QColor(127, 127, 127, 200), 1, Qt.PenStyle.DashLine)
        painter.setPen(separator_pen)

        for i in range(1, self.num_sublanes):
            y = i * self.sublane_height
            painter.drawLine(0, int(y), width, int(y))

    def draw_sublane_labels(self, painter, width, height):
        """Draw the faint sub-lane purpose labels at the start of each row.

        Restyled to the brand: a faint low-alpha neutral chip with hard
        corners (radius 0) and disabled-text mono caps, colors sniffed from
        the active theme (custom painters can't reach a QSS role). These are
        distinct from the DIM/COL/MOV/SPC micro-label column in the lane
        header; a hidden deep setting
        (``timeline/show_sublane_labels``, default True) suppresses them
        while keeping the code path.
        """
        if self.num_sublanes <= 1 or not self.capabilities:
            return

        from utils.app_settings import app_settings
        if not app_settings().value(
                "timeline/show_sublane_labels", True, type=bool):
            return

        from PyQt6.QtCore import QRect
        from gui.typography import mono_font
        from .light_block_widget import token_qcolor

        # Sub-lane purpose names in row order.
        sublane_types = []
        if self.capabilities.has_dimmer:
            sublane_types.append("Dimmer")
        if self.capabilities.has_colour:
            sublane_types.append("Colour")
        if self.capabilities.has_movement:
            sublane_types.append("Movement")
        if self.capabilities.has_special:
            sublane_types.append("Special")

        painter.setFont(mono_font(7, tracking_em=0.08))
        metrics = painter.fontMetrics()

        # Faint neutral chip + disabled-text glyphs, both from brand tokens.
        chip_fill = token_qcolor("raised", 40)
        chip_border = token_qcolor("border", 90)
        text_color = token_qcolor("text_disabled")

        for i, label in enumerate(sublane_types):
            y_offset = i * self.sublane_height
            text_width = metrics.horizontalAdvance(label)
            text_height = metrics.height()

            x_pos = 4
            y_pos = y_offset + (self.sublane_height + text_height) // 2 - 3
            padding = 3

            # Hard-corner faint chip (radius 0).
            bg_rect = QRect(x_pos - padding, y_offset + 2,
                            text_width + 2 * padding, text_height + padding)
            painter.setBrush(chip_fill)
            painter.setPen(QPen(chip_border, 1))
            painter.drawRect(bg_rect)

            painter.setPen(QPen(text_color))
            painter.drawText(x_pos, y_pos, label)

    def paintEvent(self, event):
        """Draw the timeline."""
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()

        # Draw song structure backgrounds first (subtle colors)
        self.draw_song_structure_background(painter, width, height)

        # Draw grid
        self.draw_grid(painter, width, height)

        # Draw sublane separators
        self.draw_sublane_separators(painter, width, height)

        # Draw sublane labels
        self.draw_sublane_labels(painter, width, height)

        # Draw drag preview (if dragging a riff)
        self.draw_drag_preview(painter, width, height)

        # Draw playhead
        self.draw_playhead(painter, width, height)

    def _get_beats_per_bar(self, signature: str) -> float:
        """Calculate beats per bar from time signature."""
        try:
            numerator, denominator = map(int, signature.split('/'))
            return (numerator * 4) / denominator
        except (ValueError, ZeroDivisionError):
            return 4.0

    # =========================================================================
    # DRAG-DROP SUPPORT FOR RIFFS
    # =========================================================================

    def dragEnterEvent(self, event):
        """Handle drag enter - accept riff drops."""
        if event.mimeData().hasFormat("application/x-qlc-riff"):
            event.acceptProposedAction()

            # Parse riff data for preview
            try:
                riff_data = json.loads(event.mimeData().data("application/x-qlc-riff").data().decode())
                self._drag_preview_length = riff_data.get("length_beats", 4.0)
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._drag_preview_length = 4.0

            self._update_drag_preview(event.position().x())
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        """Handle drag move - update preview position."""
        if event.mimeData().hasFormat("application/x-qlc-riff"):
            event.acceptProposedAction()
            self._update_drag_preview(event.position().x())
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        """Handle drag leave - clear preview."""
        self._drag_preview_time = None
        self._drag_preview_length = None
        self.update()

    def dropEvent(self, event):
        """Handle drop - emit riff_dropped signal."""
        if event.mimeData().hasFormat("application/x-qlc-riff"):
            try:
                riff_data = json.loads(event.mimeData().data("application/x-qlc-riff").data().decode())
                riff_path = riff_data.get("path", "")

                # Calculate drop time with snap
                drop_time = self.pixel_to_time(event.position().x())
                if self.snap_to_grid:
                    drop_time = self.find_nearest_beat_time(drop_time)
                drop_time = max(0.0, drop_time)

                # Emit signal for parent to handle
                self.riff_dropped.emit(riff_path, drop_time)

                event.acceptProposedAction()
            except (json.JSONDecodeError, UnicodeDecodeError, KeyError) as e:
                print(f"Error processing dropped riff: {e}")
                event.ignore()
        else:
            event.ignore()

        # Clear preview
        self._drag_preview_time = None
        self._drag_preview_length = None
        self.update()

    def _update_drag_preview(self, x_pos: float):
        """Update drag preview position."""
        drop_time = self.pixel_to_time(x_pos)
        if self.snap_to_grid:
            drop_time = self.find_nearest_beat_time(drop_time)
        self._drag_preview_time = max(0.0, drop_time)
        self.update()

    def _get_riff_duration_seconds(self, length_beats: float) -> float:
        """Calculate riff duration in seconds based on current BPM."""
        bpm = self.get_current_bpm()
        return length_beats * 60.0 / bpm

    def draw_drag_preview(self, painter, width, height):
        """Draw preview rectangle during riff drag."""
        if self._drag_preview_time is None or self._drag_preview_length is None:
            return

        # Calculate preview rectangle
        start_x = self.time_to_pixel(self._drag_preview_time)
        duration_secs = self._get_riff_duration_seconds(self._drag_preview_length)
        end_x = self.time_to_pixel(self._drag_preview_time + duration_secs)

        # Draw semi-transparent blue rectangle
        preview_color = QColor(0, 120, 215, 80)
        border_color = QColor(0, 120, 215, 200)

        painter.setBrush(QBrush(preview_color))
        painter.setPen(QPen(border_color, 2, Qt.PenStyle.DashLine))
        painter.drawRect(int(start_x), 2, int(end_x - start_x), height - 4)
