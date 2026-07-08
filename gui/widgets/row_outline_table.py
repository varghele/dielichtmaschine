"""
RowOutlineTableWidget — draws a single continuous selection outline around
the whole selected row, even when cells host widgets via ``setCellWidget``.

A per-cell ``QStyledItemDelegate`` cannot do this: Qt's delegate ``paint()``
is never called for cells that host a widget (gotcha #3 in
``docs/qt-gotchas.md``), so any per-cell border breaks visually wherever a
cell hosts a spinbox/combobox. The fix is a transparent overlay widget that
covers the viewport and paints the row rectangle *after* viewport children
have painted themselves.
"""

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QTableWidget, QWidget


# Glutorange selection outline per the design reference (screen 02
# outlines the selected patch row in the accent, 1px, not info-blue).
_OUTLINE_COLOR = QColor("#F0562E")
_OUTLINE_WIDTH = 1


class _RowOutlineOverlay(QWidget):
    """Transparent overlay child of the viewport. Paints the row outline
    for the table's currently-selected rows on top of all viewport
    children (including ``setCellWidget`` widgets)."""

    def __init__(self, table: "RowOutlineTableWidget") -> None:
        super().__init__(table.viewport())
        self._table = table
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.resize(table.viewport().size())

    def paintEvent(self, event) -> None:
        table = self._table
        sm = table.selectionModel()
        if sm is None:
            return
        rows = {idx.row() for idx in sm.selectedIndexes()}
        if not rows:
            return

        # Find the leftmost and rightmost visible columns so the outline
        # spans the full visible row regardless of hidden columns.
        cols = [c for c in range(table.columnCount()) if not table.isColumnHidden(c)]
        if not cols:
            return
        first_col, last_col = cols[0], cols[-1]
        model = table.model()
        if model is None:
            return

        painter = QPainter(self)
        try:
            pen = QPen(_OUTLINE_COLOR, _OUTLINE_WIDTH)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for row in rows:
                left_rect = table.visualRect(model.index(row, first_col))
                right_rect = table.visualRect(model.index(row, last_col))
                if not left_rect.isValid() or not right_rect.isValid():
                    continue
                # Inset 1 px so the 2-px pen sits cleanly inside the row
                # rather than getting clipped on the outer edges.
                row_rect = QRect(
                    left_rect.left() + 1,
                    left_rect.top() + 1,
                    (right_rect.right() - left_rect.left()) - 1,
                    left_rect.height() - 2,
                )
                painter.drawRect(row_rect)
        finally:
            painter.end()


class RowOutlineTableWidget(QTableWidget):
    """QTableWidget that draws a continuous outline around each selected
    row, including across cells that host widgets.

    Pair with ``GroupRowDelegate`` (which strips ``State_Selected`` so the
    cell's ``BackgroundRole`` tint survives) and
    ``setSelectionBehavior(SelectRows)`` so a single click selects the
    whole row at once.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._overlay = _RowOutlineOverlay(self)
        self._overlay.show()
        self._overlay.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Keep the overlay covering the full viewport, and on top of any
        # cell widgets that were stacked above it during the last layout.
        self._overlay.resize(self.viewport().size())
        self._overlay.raise_()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        # Schedule the overlay to repaint after viewport children render —
        # update() posts a paint event that Qt processes once the current
        # paint cycle (table cells + cell widgets) finishes.
        self._overlay.update()

    def setCellWidget(self, row: int, column: int, widget: QWidget) -> None:
        # Each new cell widget becomes a viewport child stacked above
        # existing siblings; re-raise the overlay so it stays on top.
        super().setCellWidget(row, column, widget)
        self._overlay.raise_()
