# timeline_ui/master_timeline_widget.py
# Master timeline widget showing song structure, playhead, and grid
# Adapted from midimaker_and_show_structure/ui/master_timeline_widget.py

from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                             QScrollArea, QStyle, QStyleOption, QComboBox,
                             QCheckBox)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QRectF
from PyQt6.QtGui import QPainter, QPen, QColor, QPolygon, QBrush
from .timeline_widget import TimelineWidget, iter_grid_steps


# Grid interval choices. First tuple element is the LABEL (grid interval in
# beats, as shown on the chip/combobox); second is steps-per-beat (float).
# "4" -> a line every 4 beats -> 0.25 steps/beat; "1/16" -> 16 steps/beat.
SUBDIVISION_CHOICES = [
    ("4", 0.25),
    ("2", 0.5),
    ("1", 1.0),
    ("1/2", 2.0),
    ("1/4", 4.0),
    ("1/8", 8.0),
    ("1/16", 16.0),
]


class MasterTimelineWidget(TimelineWidget):
    """Master timeline widget with enhanced playhead and song structure display."""

    playhead_moved = pyqtSignal(float)  # Emits new playhead position in seconds

    def __init__(self, parent=None):
        # Initialize attributes before calling super()
        self.song_structure = None
        self.playhead_position = 0.0
        self.dragging_playhead = False
        self.zoom_factor = 1.0
        self.base_pixels_per_second = 60
        self.min_zoom = 0.1
        self.max_zoom = 5.0

        super().__init__(parent)

        self.setMinimumHeight(40)
        self.setMinimumWidth(2000)
        # Background and border come from the active theme via the
        # `MasterTimelineWidget` selector — no inline stylesheet here.

    def set_playhead_position(self, position: float):
        """Set playhead position and update display."""
        self.playhead_position = position
        self.update()

        # Auto-scroll to keep playhead visible
        self.ensure_playhead_visible()

    def ensure_playhead_visible(self):
        """Ensure playhead is visible by scrolling if necessary."""
        if hasattr(self.parent(), 'ensureWidgetVisible'):
            playhead_x = int(self.time_to_pixel(self.playhead_position))
            margin = 100
            self.parent().ensureVisible(playhead_x, 0, margin, self.height())

    def get_previous_part_bpm(self, current_part) -> float:
        """Get BPM of the previous part."""
        try:
            if self.song_structure and self.song_structure.parts:
                part_index = self.song_structure.parts.index(current_part)
                if part_index > 0:
                    return self.song_structure.parts[part_index - 1].bpm
        except (ValueError, IndexError, AttributeError):
            pass
        return current_part.bpm

    def paintEvent(self, event):
        """Draw the master timeline."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Render the QSS background/border for `MasterTimelineWidget` via
        # the canonical Qt pattern. We can't call super().paintEvent here
        # because TimelineWidget's paintEvent also draws grid/playhead and
        # we'd double-paint. drawPrimitive(PE_Widget) just paints the QSS
        # box decoration so the theme actually shows up.
        opt = QStyleOption()
        opt.initFrom(self)
        self.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_Widget, opt, painter, self,
        )

        width = self.width()
        height = self.height()

        # Draw song structure parts as colored backgrounds
        if self.song_structure and hasattr(self.song_structure, 'parts') and self.song_structure.parts:
            try:
                self.draw_song_structure(painter, width, height)
            except Exception as e:
                print(f"Error drawing song structure: {e}")

        # Draw grid
        self.draw_grid(painter, width, height)

        # Draw playhead
        self.draw_playhead(painter, width, height)

    def draw_song_structure(self, painter, width, height):
        """Draw song parts as North Star region bands (card 4a): each
        band is a 3px part-color bar along the top edge over a
        ~0.18-alpha tint of the same color, the part name in condensed
        caps, hard corners, no border box. The tint keeps the theme
        background readable, so labels render in the part color itself
        (BPM readout in steel-gray tracked mono)."""
        # Deferred import: the gui package imports timeline_ui at module
        # load, so a top-level import here would be circular.
        from gui.typography import display_font, mono_font
        try:
            for part in self.song_structure.parts:
                start_x = self.time_to_pixel(part.start_time)
                end_x = self.time_to_pixel(part.start_time + part.duration)

                if end_x < 0 or start_x > width:
                    continue

                x = int(start_x)
                band_width = int(end_x - start_x)
                band_color = QColor(part.color)

                # ~0.18-alpha tint of the part color across the band.
                tint = QColor(band_color)
                tint.setAlpha(46)
                painter.fillRect(x, 0, band_width, height, tint)

                # 3px part-color bar along the top edge.
                painter.fillRect(x, 0, band_width, 3, band_color)

                # Part name in tracked condensed caps if there's space.
                if end_x - start_x > 50:
                    painter.setPen(QPen(band_color, 1))
                    painter.setFont(display_font(9))
                    text_rect = QRectF(start_x + 6, 7, end_x - start_x - 12, 16)
                    painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft,
                                     (part.name or "").upper())

                    # BPM readout: mono, steel gray (#8D9299 reads on
                    # the near-background tint in both themes).
                    painter.setPen(QPen(QColor(141, 146, 153), 1))
                    painter.setFont(mono_font(7))
                    bpm_text = f"{part.bpm} BPM"
                    if part.transition == "gradual":
                        prev_bpm = self.get_previous_part_bpm(part)
                        if prev_bpm != part.bpm:
                            bpm_text = f"{prev_bpm}->{part.bpm} BPM"

                    bpm_rect = QRectF(start_x + 6, 25, end_x - start_x - 12, 14)
                    painter.drawText(bpm_rect, Qt.AlignmentFlag.AlignLeft, bpm_text)
        except Exception as e:
            print(f"Error in draw_song_structure: {e}")

    def draw_grid(self, painter, width, height):
        """Draw time-based grid with beat lines and optional sub-beat lines."""
        has_structure = (self.song_structure and
                        hasattr(self.song_structure, 'parts') and self.song_structure.parts)
        if has_structure:
            try:
                # Semi-transparent gray reads on both dark and light themes.
                sub_pen = QPen(QColor(127, 127, 127, 60), 1, Qt.PenStyle.DotLine)
                bar_pen = QPen(QColor(127, 127, 127, 200), 1)
                beat_pen = QPen(QColor(127, 127, 127, 100), 1)

                subdivision = getattr(self, "grid_subdivision", 1.0)
                swing = getattr(self, "swing_enabled", False)
                min_px = getattr(self, "min_subdivision_pixels", 12)

                num_parts = len(self.song_structure.parts)
                for part_idx, part in enumerate(self.song_structure.parts):
                    beats_per_bar = self._get_beats_per_bar(part.signature)
                    total_beats_in_part = int(part.num_bars * beats_per_bar)
                    seconds_per_beat = 60.0 / part.bpm

                    is_last_part = (part_idx == num_parts - 1)
                    for step_time, kind in iter_grid_steps(
                            part.start_time, seconds_per_beat, beats_per_bar,
                            total_beats_in_part, subdivision, swing,
                            is_last_part, self.pixels_per_second, min_px):
                        step_x_rounded = round(self.time_to_pixel(step_time))
                        if not (0 <= step_x_rounded <= width):
                            continue
                        if kind == "bar":
                            painter.setPen(bar_pen)
                        elif kind == "beat":
                            painter.setPen(beat_pen)
                        else:
                            painter.setPen(sub_pen)
                        painter.drawLine(step_x_rounded, 0, step_x_rounded, height)

            except Exception as e:
                import traceback
                print(f"Error in draw_grid: {e}")
                traceback.print_exc()
                self.draw_basic_grid(painter, width, height)
        else:
            self.draw_basic_grid(painter, width, height)

    def draw_playhead(self, painter, width, height):
        """Draw enhanced playhead with triangle."""
        try:
            playhead_x = self.time_to_pixel(self.playhead_position)
            playhead_x_rounded = round(playhead_x)

            if 0 <= playhead_x_rounded <= width:
                # Playhead line
                playhead_pen = QPen(QColor("#FF4444"), 2)
                painter.setPen(playhead_pen)
                painter.drawLine(playhead_x_rounded, 0, playhead_x_rounded, height)

                # Playhead triangle at top
                triangle_size = 8
                triangle = QPolygon([
                    QPoint(playhead_x_rounded, 0),
                    QPoint(playhead_x_rounded - triangle_size, triangle_size),
                    QPoint(playhead_x_rounded + triangle_size, triangle_size)
                ])

                painter.setBrush(QBrush(QColor("#FF4444")))
                painter.drawPolygon(triangle)
        except (AttributeError, TypeError):
            super().draw_playhead(painter, width, height)

    def _get_beats_per_bar(self, signature: str) -> float:
        """Calculate beats per bar from time signature."""
        try:
            numerator, denominator = map(int, signature.split('/'))
            return (numerator * 4) / denominator
        except (ValueError, ZeroDivisionError):
            return 4.0


class MasterTimelineContainer(QWidget):
    """Container for master timeline with label and info display."""

    playhead_moved = pyqtSignal(float)
    scroll_position_changed = pyqtSignal(int)
    zoom_changed = pyqtSignal(float)
    subdivision_changed = pyqtSignal(float)  # Steps-per-beat (see SUBDIVISION_CHOICES)
    snap_changed = pyqtSignal(bool)  # Master snap toggle — fan out to all lanes

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setMinimumHeight(95)
        self.setMaximumHeight(100)

        # Top row with timeline label and info
        top_row_layout = QHBoxLayout()

        # Timeline label (matches lane control width)
        timeline_label = QWidget()
        timeline_label.setFixedWidth(320)
        label_layout = QHBoxLayout(timeline_label)
        master_label = QLabel("Master Timeline")
        master_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        label_layout.addWidget(master_label)
        label_layout.addStretch()

        # Info display widget
        self.info_widget = QLabel()
        self.info_widget.setStyleSheet("color: #333; font-size: 10px; font-weight: bold;")
        self.info_widget.setText("Time: 0.00s | BPM: 120.0 | Zoom: 1.0x")

        # Master snap toggle — when off, the playhead can be dragged to
        # arbitrary times and lane block edits ignore the grid. The toggle
        # fans out to every lane via TimelineGrid so all snapping stays in
        # sync with what the user sees on the master ruler.
        self.snap_checkbox = QCheckBox("Snap")
        self.snap_checkbox.setChecked(True)
        self.snap_checkbox.setToolTip(
            "Snap playhead and block edits to the grid set in 'Grid' below."
        )
        self.snap_checkbox.toggled.connect(self._on_snap_toggled)

        # Grid subdivision picker — controls how fine snap-to-grid is.
        self.subdivision_label = QLabel("Grid:")
        self.subdivision_label.setStyleSheet("font-size: 10px;")
        self.subdivision_combo = QComboBox()
        self.subdivision_combo.setToolTip(
            "Grid resolution. 4/2 = a line every 4/2 beats; 1 = on the beat; "
            "1/2 ... 1/16 = sub-beat lines."
        )
        for label, value in SUBDIVISION_CHOICES:
            self.subdivision_combo.addItem(label, value)
        # Default to the on-beat entry (value 1.0) to match the whole-beat
        # default grid, not the first catalog entry.
        default_index = next(
            i for i, (_label, v) in enumerate(SUBDIVISION_CHOICES) if v == 1.0)
        self.subdivision_combo.setCurrentIndex(default_index)
        self.subdivision_combo.currentIndexChanged.connect(self._on_subdivision_changed)

        # NOTE: this top_row_layout is what shows BEFORE detach_pieces() runs
        # (e.g., if MasterTimelineContainer is used standalone). Once embedded
        # in TimelineGrid, detach_pieces() rebuilds the header into a 2-row
        # stack so the controls don't fight the info_widget for space inside
        # the 320 px header column.
        top_row_layout.addWidget(timeline_label)
        top_row_layout.addWidget(self.info_widget, 1)
        top_row_layout.addWidget(self.snap_checkbox)
        top_row_layout.addWidget(self.subdivision_label)
        top_row_layout.addWidget(self.subdivision_combo)

        # Bottom row with scrollable timeline
        bottom_row_layout = QHBoxLayout()

        # Empty space to align with lane controls
        spacer_widget = QWidget()
        spacer_widget.setFixedWidth(320)

        # Scrollable timeline area
        self.timeline_scroll = QScrollArea()
        self.timeline_widget = MasterTimelineWidget()
        self.timeline_widget.playhead_moved.connect(self.playhead_moved.emit)
        self.timeline_widget.zoom_changed.connect(self.zoom_changed.emit)
        self.timeline_widget.playhead_moved.connect(self.update_info_display)

        self.timeline_scroll.setWidget(self.timeline_widget)
        self.timeline_scroll.setWidgetResizable(False)
        self.timeline_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.timeline_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Connect scroll events
        self.timeline_scroll.horizontalScrollBar().valueChanged.connect(
            self.scroll_position_changed.emit)

        bottom_row_layout.addWidget(spacer_widget)
        bottom_row_layout.addWidget(self.timeline_scroll, 1)

        # Add both rows to the main layout
        layout.addLayout(top_row_layout)
        layout.addLayout(bottom_row_layout)

    def update_info_display(self, position: float):
        """Update the info display with current values."""
        current_bpm = self.timeline_widget.get_current_bpm()
        zoom_factor = self.timeline_widget.zoom_factor

        # Get current song part if available
        part_info = ""
        if self.timeline_widget.song_structure:
            current_part = self.timeline_widget.song_structure.get_part_at_time(position)
            if current_part:
                part_info = f" | Part: {current_part.name}"

        info_text = f"Time: {position:.2f}s | BPM: {current_bpm:.1f} | Zoom: {zoom_factor:.1f}x{part_info}"
        self.info_widget.setText(info_text)

    def set_bpm(self, bpm: float):
        """Set BPM for timeline calculations."""
        self.timeline_widget.set_bpm(bpm)

    def set_playhead_position(self, position: float):
        """Set playhead position."""
        self.timeline_widget.set_playhead_position(position)
        self.update_info_display(position)

    def set_snap_to_grid(self, snap: bool):
        """Set snap to grid for playhead. Also syncs the snap checkbox so
        programmatic toggles match the UI without re-emitting snap_changed.
        """
        self.timeline_widget.set_snap_to_grid(snap)
        if hasattr(self, "snap_checkbox") and self.snap_checkbox is not None:
            self.snap_checkbox.blockSignals(True)
            self.snap_checkbox.setChecked(snap)
            self.snap_checkbox.blockSignals(False)

    def _on_snap_toggled(self, checked: bool):
        """User flipped the master Snap checkbox."""
        self.timeline_widget.set_snap_to_grid(checked)
        self.snap_changed.emit(checked)

    def set_grid_subdivision(self, subdivision: float):
        """Set the master timeline's grid subdivision and sync the combobox."""
        self.timeline_widget.set_grid_subdivision(subdivision)
        # Reflect on combobox without re-emitting subdivision_changed. Compare
        # against the stored catalog value (both come from SUBDIVISION_CHOICES,
        # so the float match is exact) rather than doing any arithmetic.
        for i in range(self.subdivision_combo.count()):
            if self.subdivision_combo.itemData(i) == subdivision:
                self.subdivision_combo.blockSignals(True)
                self.subdivision_combo.setCurrentIndex(i)
                self.subdivision_combo.blockSignals(False)
                break

    def _on_subdivision_changed(self, _index: int):
        """Combobox handler — pushes the new subdivision into the master
        timeline and re-emits the value for the surrounding tab to fan out
        to other lanes via TimelineGrid.
        """
        value = float(self.subdivision_combo.currentData())
        self.timeline_widget.set_grid_subdivision(value)
        self.subdivision_changed.emit(value)

    def sync_scroll_position(self, position: int):
        """Sync scroll position with other timelines."""
        self.timeline_scroll.horizontalScrollBar().setValue(position)

    def set_zoom_factor(self, zoom_factor: float):
        """Set zoom factor for timeline."""
        self.timeline_widget.zoom_factor = zoom_factor
        self.timeline_widget.update_timeline_width()
        self.timeline_widget.update()

    def detach_pieces(self):
        """Return (header_widget, stripe_widget) for embedding in TimelineGrid.

        Inside TimelineGrid the header is constrained to a 320 px column to
        match the lane controls. Stuffing title + info_widget + Snap + Grid
        on a single row overflows that budget — the rightmost controls get
        pushed off-screen. This method builds a 2-row stack instead:

            ┌─ MasterTimelineHeader (320 px wide) ───────────┐
            │ Master Timeline      Snap ✓   Grid: [1 ▾]      │  ← controls
            │ Time: 0.00s | BPM: 120.0 | Zoom: 1.0x          │  ← info
            └────────────────────────────────────────────────┘

        Signals on ``self`` remain wired (they pass through ``timeline_widget``
        and the controls themselves), so callers keep using
        ``self.set_playhead_position``, ``self.playhead_moved``, etc.
        """
        from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel
        header = QWidget()
        # Object-name + WA_StyledBackground so the active theme's
        # `QWidget#MasterTimelineHeader` rule paints the bg. Without these
        # the header inherits the QScrollArea viewport's default light-gray
        # bg in both themes.
        header.setObjectName("MasterTimelineHeader")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        outer = QVBoxLayout(header)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(2)

        # Row 1 — title and snap/grid controls.
        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(6)
        master_label = QLabel("Master")
        master_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        controls_row.addWidget(master_label)
        controls_row.addStretch()
        if hasattr(self, "snap_checkbox") and self.snap_checkbox is not None:
            self.snap_checkbox.setParent(header)
            self.snap_checkbox.setStyleSheet("font-size: 11px;")
            controls_row.addWidget(self.snap_checkbox)
        if hasattr(self, "subdivision_label") and self.subdivision_label is not None:
            self.subdivision_label.setParent(header)
            controls_row.addWidget(self.subdivision_label)
        if hasattr(self, "subdivision_combo") and self.subdivision_combo is not None:
            self.subdivision_combo.setParent(header)
            # A compact combobox keeps the controls row inside the 320 px
            # column even when the dropdown items are wider than the field.
            self.subdivision_combo.setMinimumWidth(70)
            self.subdivision_combo.setMaximumWidth(110)
            controls_row.addWidget(self.subdivision_combo)
        outer.addLayout(controls_row)

        # Row 2 — info display (Time/BPM/Zoom/Part).
        if hasattr(self, "info_widget") and self.info_widget is not None:
            self.info_widget.setParent(header)
            self.info_widget.setStyleSheet("font-size: 9px; color: gray;")
            outer.addWidget(self.info_widget)

        # Detach the timeline from the scrollarea so TimelineGrid can take it.
        if hasattr(self, "timeline_scroll") and self.timeline_scroll is not None:
            self.timeline_scroll.takeWidget()
            self.timeline_scroll.setParent(None)
            self.timeline_scroll = None

        return header, self.timeline_widget
