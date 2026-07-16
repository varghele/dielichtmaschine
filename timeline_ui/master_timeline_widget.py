# timeline_ui/master_timeline_widget.py
# Master timeline widget showing song structure, playhead, and grid
# Adapted from midimaker_and_show_structure/ui/master_timeline_widget.py

from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                             QScrollArea, QStyle, QStyleOption)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QRectF
from PyQt6.QtGui import QPainter, QPen, QColor, QPolygon, QBrush
from .timeline_widget import TimelineWidget, iter_grid_steps, HEADER_COLUMN_WIDTH


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


# Height of the compact parts band (timeline v3 regions row, screen 06b).
PARTS_BAND_HEIGHT = 26
# ~0.2-alpha tint of the part colour across a parts-band region.
PARTS_BAND_TINT_ALPHA = 51
# Width of the dark separator between adjacent parts-band regions.
PARTS_BAND_SEPARATOR_PX = 2


class MasterTimelineWidget(TimelineWidget):
    """Master timeline widget with enhanced playhead and song structure display.

    Two looks share this class:

    - default (Structure tab): the North Star region bands (3px part-color
      top bar over a ~0.18 tint, stacked name + BPM readout, red playhead
      with the grab triangle) at the taller row height.
    - ``parts_band=True`` (Shows tab, timeline v3 stage T4): the 26px
      PARTS band from screen 06b - regions tinted in the part colour at
      ~0.2 alpha, part name in condensed caps with a small mono BPM tag
      inline, 2px dark separators between regions, and the unified 2px
      accent playhead line.
    """

    playhead_moved = pyqtSignal(float)  # Emits new playhead position in seconds

    def __init__(self, parent=None, parts_band=False):
        # Initialize attributes before calling super()
        self.song_structure = None
        self.playhead_position = 0.0
        self.dragging_playhead = False
        self.zoom_factor = 1.0
        self.base_pixels_per_second = 60
        self.min_zoom = 0.1
        self.max_zoom = 5.0
        self.parts_band = parts_band

        super().__init__(parent)

        # Unified accent playhead is part of the v3 parts-band look.
        self.playhead_accent = parts_band
        self.setMinimumHeight(PARTS_BAND_HEIGHT if parts_band else 40)
        self.setMinimumWidth(2000)
        # Background and border come from the active theme via the
        # `MasterTimelineWidget` selector — no inline stylesheet here.

    def set_playhead_position(self, position: float):
        """Set playhead position and repaint ONLY the playhead strips.

        Same dirty-rect discipline as TimelineWidget (the playback
        visual tick calls this at ~30 FPS; a full update() was part of
        the 2026-07-16 playback-lag finding). The strip is wider here:
        the ruler carries the grab handle polygon at the line's top.
        """
        old = self.playhead_position
        self.playhead_position = position
        if old != position:
            height = self.height()
            for pos in (old, position):
                x = round(self.time_to_pixel(pos))
                self.update(x - 12, 0, 25, height)

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
        # Cull to the exposed region: playback invalidates narrow
        # playhead strips at ~30 FPS (2026-07-16 lag fix), and the
        # ruler is the full song wide.
        painter.setClipRect(event.rect())
        clip = event.rect()

        # Draw song structure parts as colored backgrounds
        if self.song_structure and hasattr(self.song_structure, 'parts') and self.song_structure.parts:
            try:
                self.draw_song_structure(painter, width, height)
            except Exception as e:
                print(f"Error drawing song structure: {e}")

        # Draw grid
        self.draw_grid(painter, width, height, clip)

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
        if self.parts_band:
            self._draw_parts_band(painter, width, height)
            return
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

    def _bpm_tag_text(self, part) -> str:
        """"192 BPM" mono tag; "120->140 BPM" across a gradual ramp."""
        bpm = f"{part.bpm:g}"
        if getattr(part, "transition", "instant") == "gradual":
            prev_bpm = self.get_previous_part_bpm(part)
            if prev_bpm != part.bpm:
                return f"{prev_bpm:g}->{bpm} BPM"
        return f"{bpm} BPM"

    def _draw_parts_band(self, painter, width, height):
        """Timeline v3 parts band (mock 06b regions row): each region is
        a ~0.2-alpha tint of the part colour with the part name in
        condensed caps and a small mono BPM tag inline, separated from
        the next region by a 2px window-dark hairline. Labels elide and
        the BPM tag drops before anything paints outside its region."""
        from PyQt6.QtGui import QFont
        from gui.typography import display_font, mono_font
        from .light_block_widget import active_tokens, elided

        tokens = active_tokens()
        name_color = QColor(tokens["text"])
        separator_color = QColor(tokens["window"])
        # Steel gray reads on the near-background tint in both themes
        # (same value the block sub-row labels use).
        bpm_color = QColor(141, 146, 153)

        try:
            parts = self.song_structure.parts
            for index, part in enumerate(parts):
                start_x = self.time_to_pixel(part.start_time)
                end_x = self.time_to_pixel(part.start_time + part.duration)
                if end_x < 0 or start_x > width:
                    continue

                x = int(start_x)
                band_width = int(end_x - start_x)
                tint = QColor(part.color)
                tint.setAlpha(PARTS_BAND_TINT_ALPHA)
                painter.fillRect(x, 0, band_width, height, tint)

                # 2px dark separator between adjacent regions (none after
                # the last - the band simply ends, per the mock).
                if index < len(parts) - 1:
                    painter.fillRect(int(end_x) - PARTS_BAND_SEPARATOR_PX, 0,
                                     PARTS_BAND_SEPARATOR_PX, height,
                                     separator_color)

                # Part name in condensed caps, vertically centered.
                label_left = start_x + 8
                label_avail = end_x - 8 - label_left
                if label_avail <= 12:
                    continue
                painter.setFont(display_font(9, QFont.Weight.Bold))
                metrics = painter.fontMetrics()
                name_text = elided(metrics, (part.name or "").upper(),
                                   label_avail)
                if not name_text:
                    continue
                painter.setPen(QPen(name_color, 1))
                painter.drawText(
                    QRectF(label_left, 0, label_avail, height),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    name_text)

                # Small mono BPM tag inline after the name.
                bpm_left = label_left + metrics.horizontalAdvance(name_text) + 8
                bpm_avail = end_x - 8 - bpm_left
                if bpm_avail <= 12:
                    continue
                painter.setFont(mono_font(7))
                bpm_text = elided(painter.fontMetrics(),
                                  self._bpm_tag_text(part), bpm_avail)
                if not bpm_text:
                    continue
                painter.setPen(QPen(bpm_color, 1))
                painter.drawText(
                    QRectF(bpm_left, 0, bpm_avail, height),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    bpm_text)
        except Exception as e:
            print(f"Error in _draw_parts_band: {e}")

    def draw_grid(self, painter, width, height, clip=None):
        """Draw time-based grid with beat lines and optional sub-beat
        lines, culled to the exposed x-range (``clip``; None = all)."""
        has_structure = (self.song_structure and
                        hasattr(self.song_structure, 'parts') and self.song_structure.parts)
        clip_left = clip.left() - 2 if clip is not None else 0
        clip_right = clip.right() + 2 if clip is not None else width
        if has_structure:
            try:
                # Semi-transparent gray reads on both dark and light themes.
                sub_pen = QPen(QColor(127, 127, 127, 60), 1, Qt.PenStyle.DotLine)
                bar_pen = QPen(QColor(127, 127, 127, 200), 1)
                beat_pen = QPen(QColor(127, 127, 127, 100), 1)

                subdivision = getattr(self, "grid_subdivision", 1.0)
                swing = getattr(self, "swing_amount", 0.0)
                min_px = getattr(self, "min_subdivision_pixels", 12)

                num_parts = len(self.song_structure.parts)
                for part_idx, part in enumerate(self.song_structure.parts):
                    beats_per_bar = self._get_beats_per_bar(part.signature)
                    total_beats_in_part = int(part.num_bars * beats_per_bar)
                    seconds_per_beat = 60.0 / part.bpm

                    start_x = round(self.time_to_pixel(part.start_time))
                    if start_x > clip_right:
                        break            # parts are time-ordered
                    end_x = round(self.time_to_pixel(
                        part.start_time
                        + total_beats_in_part * seconds_per_beat))
                    if end_x < clip_left:
                        continue

                    is_last_part = (part_idx == num_parts - 1)
                    for step_time, kind in iter_grid_steps(
                            part.start_time, seconds_per_beat, beats_per_bar,
                            total_beats_in_part, subdivision, swing,
                            is_last_part, self.pixels_per_second, min_px):
                        step_x_rounded = round(self.time_to_pixel(step_time))
                        if step_x_rounded > clip_right:
                            break        # steps are time-ordered
                        if step_x_rounded < clip_left or \
                                not (0 <= step_x_rounded <= width):
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
        """Draw the playhead.

        Parts-band mode uses the base class's unified 2px accent line
        (timeline v3: one playhead look across master + audio + lanes);
        the default look keeps the legacy red line + grab triangle.
        """
        if self.parts_band:
            super().draw_playhead(painter, width, height)
            return
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
    """Container for master timeline with label and info display.

    ``compact=True`` (Shows tab, timeline v3 stage T4) turns the master
    row into the 26px PARTS band: the timeline widget renders in
    parts-band mode and ``detach_pieces`` returns a single "PARTS"
    header cell instead of the 2-row title + info stack.
    ``embedded_row_height`` tells TimelineGrid the row height to pin.
    """

    playhead_moved = pyqtSignal(float)
    scroll_position_changed = pyqtSignal(int)
    zoom_changed = pyqtSignal(float)

    def __init__(self, parent=None, compact=False):
        super().__init__(parent)
        self._compact = compact
        self.embedded_row_height = PARTS_BAND_HEIGHT if compact else None
        self.setup_ui()

    def _info_style(self, point_size: int) -> str:
        """Info-readout stylesheet with the color sourced from the active
        theme (text_secondary), not a hardcoded #333 that only reads on a
        light background. Custom-styled QLabels can't reach a QSS role, so
        we sniff the brand tokens the same way the block painter does."""
        from .light_block_widget import active_tokens
        return (f"color: {active_tokens()['text_secondary']}; "
                f"font-size: {point_size}px;")

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setMinimumHeight(95)
        self.setMaximumHeight(100)

        # Top row with timeline label and info
        top_row_layout = QHBoxLayout()

        # Timeline label (matches lane control width)
        timeline_label = QWidget()
        timeline_label.setFixedWidth(HEADER_COLUMN_WIDTH)
        label_layout = QHBoxLayout(timeline_label)
        master_label = QLabel("Master Timeline")
        master_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        label_layout.addWidget(master_label)
        label_layout.addStretch()

        # Info display widget. The master no longer carries its own
        # Snap/Grid controls: the toolbar's global SNAP / GRID / SWING
        # (fanned out via TimelineGrid) drive the master's grid drawing,
        # and per-lane snap lives on each lane's own checkbox.
        self.info_widget = QLabel()
        self.info_widget.setStyleSheet(self._info_style(10))
        self.info_widget.setText("Time: 0.00s | BPM: 120.0 | Zoom: 1.0x")

        # NOTE: this top_row_layout is what shows BEFORE detach_pieces() runs
        # (e.g., if MasterTimelineContainer is used standalone). Once embedded
        # in TimelineGrid, detach_pieces() rebuilds the header into a 2-row
        # stack (title row + info row).
        top_row_layout.addWidget(timeline_label)
        top_row_layout.addWidget(self.info_widget, 1)

        # Bottom row with scrollable timeline
        bottom_row_layout = QHBoxLayout()

        # Empty space to align with lane controls
        spacer_widget = QWidget()
        spacer_widget.setFixedWidth(HEADER_COLUMN_WIDTH)

        # Scrollable timeline area
        self.timeline_scroll = QScrollArea()
        self.timeline_widget = MasterTimelineWidget(parts_band=self._compact)
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
        """Set snap to grid for the master ruler's playhead.

        Driven by the toolbar's global SNAP chip via TimelineGrid; the
        master no longer owns a snap control of its own.
        """
        self.timeline_widget.set_snap_to_grid(snap)

    def set_grid_subdivision(self, subdivision: float):
        """Set the master timeline's grid drawing resolution.

        Driven by the toolbar's global GRID chips via TimelineGrid; the
        master no longer owns a grid combobox of its own.
        """
        self.timeline_widget.set_grid_subdivision(subdivision)

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

        Inside TimelineGrid the header is constrained to the shared
        HEADER_COLUMN_WIDTH column to match the lane controls. The
        header is a 2-row stack:

            ┌─ MasterTimelineHeader (header-column wide) ────┐
            │ Master                                         │  ← title
            │ Time: 0.00s | BPM: 120.0 | Zoom: 1.0x          │  ← info
            └────────────────────────────────────────────────┘

        The master's own Snap/Grid controls were removed - the toolbar's
        global SNAP / GRID / SWING drive the master ruler's grid drawing
        via TimelineGrid. Signals on ``self`` remain wired (they pass
        through ``timeline_widget``), so callers keep using
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

        if self._compact:
            # Timeline v3 parts band: the header cell is just "PARTS" in
            # tracked mono micro caps (mock 06b). Position readouts live
            # in the toolbar's BAR chip, so the info widget stays hidden
            # (the attribute survives - update_info_display keeps
            # feeding it and callers keep their references).
            from gui.typography import MicroLabel
            row = QHBoxLayout(header)
            row.setContentsMargins(12, 0, 8, 0)
            row.setSpacing(6)
            row.addWidget(MicroLabel("Parts", point_size=8))
            row.addStretch()
            if hasattr(self, "info_widget") and self.info_widget is not None:
                self.info_widget.hide()
                self.info_widget.setParent(header)
            if hasattr(self, "timeline_scroll") and self.timeline_scroll is not None:
                self.timeline_scroll.takeWidget()
                self.timeline_scroll.setParent(None)
                self.timeline_scroll = None
            return header, self.timeline_widget

        outer = QVBoxLayout(header)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(2)

        # Row 1 — title only.
        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(6)
        master_label = QLabel("Master")
        master_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        controls_row.addWidget(master_label)
        controls_row.addStretch()
        outer.addLayout(controls_row)

        # Row 2 — info display (Time/BPM/Zoom/Part).
        if hasattr(self, "info_widget") and self.info_widget is not None:
            self.info_widget.setParent(header)
            self.info_widget.setStyleSheet(self._info_style(9))
            outer.addWidget(self.info_widget)

        # Detach the timeline from the scrollarea so TimelineGrid can take it.
        if hasattr(self, "timeline_scroll") and self.timeline_scroll is not None:
            self.timeline_scroll.takeWidget()
            self.timeline_scroll.setParent(None)
            self.timeline_scroll = None

        return header, self.timeline_widget
