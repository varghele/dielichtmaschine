# timeline_ui/selection_overlay.py
# Transparent overlay widget for drawing selection rectangle

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QPoint, QRect, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush


class SelectionOverlay(QWidget):
    """Transparent overlay widget that draws the selection rectangle during drag.

    This widget is positioned over the lanes scroll area and handles
    drawing the rubber-band selection rectangle.
    """

    # Emitted when selection rectangle is finalized (start_point, end_point)
    selection_finished = pyqtSignal(QPoint, QPoint)

    # Selection rectangle style
    FILL_COLOR = QColor(0, 120, 215, 30)  # Semi-transparent blue
    BORDER_COLOR = QColor(0, 120, 215, 200)  # Solid blue
    BORDER_WIDTH = 2

    def __init__(self, parent=None):
        super().__init__(parent)

        # Make widget transparent and non-interactive by default
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")

        # Selection state
        self._is_selecting = False
        self._start_point = QPoint()
        self._current_point = QPoint()

    def start_selection(self, pos: QPoint) -> None:
        """Start drawing selection rectangle.

        Args:
            pos: Starting point (global coordinates relative to this widget)
        """
        self._is_selecting = True
        self._start_point = pos
        self._current_point = pos
        self.update()

    def update_selection(self, pos: QPoint) -> None:
        """Update selection rectangle end point.

        Args:
            pos: Current mouse position (relative to this widget)
        """
        if self._is_selecting:
            self._current_point = pos
            self.update()

    def finish_selection(self) -> QRect:
        """Finish selection and return the selection rectangle.

        Returns:
            QRect representing the selection area
        """
        if self._is_selecting:
            self._is_selecting = False
            rect = self._get_selection_rect()
            self.selection_finished.emit(self._start_point, self._current_point)
            self.update()
            return rect
        return QRect()

    def cancel_selection(self) -> None:
        """Cancel the current selection without emitting signal."""
        self._is_selecting = False
        self.update()

    def get_selection_rect(self) -> QRect:
        """Get the current selection rectangle.

        Returns:
            QRect representing the selection area (normalized)
        """
        return self._get_selection_rect()

    def _get_selection_rect(self) -> QRect:
        """Calculate normalized selection rectangle from start/end points.

        Returns:
            QRect with positive width/height
        """
        x1 = min(self._start_point.x(), self._current_point.x())
        y1 = min(self._start_point.y(), self._current_point.y())
        x2 = max(self._start_point.x(), self._current_point.x())
        y2 = max(self._start_point.y(), self._current_point.y())

        return QRect(x1, y1, x2 - x1, y2 - y1)

    def paintEvent(self, event):
        """Draw the selection rectangle."""
        if not self._is_selecting:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Get normalized rectangle
        rect = self._get_selection_rect()

        # Draw fill
        painter.setBrush(QBrush(self.FILL_COLOR))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(rect)

        # Draw border
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(self.BORDER_COLOR, self.BORDER_WIDTH))
        painter.drawRect(rect)
