"""
GroupRowDelegate — keeps per-row group tints visible when a row is selected.

Qt's default QStyledItemDelegate fills selected cells with the palette's
``Highlight`` brush (whatever ``selection-background-color`` resolves to),
which fully covers any tint applied via ``QTableWidgetItem.setBackground``.
Worse, Qt's QSS rendering pipeline doesn't honor ``rgba(...)`` alpha on
``selection-background-color`` — it paints the selection opaque against
the table base, not blended against the cell background.

This delegate paints the cell as if it weren't selected so the
``BackgroundRole`` tint survives. The selection indicator itself (a
continuous outline around the entire row) is drawn at the table level by
``RowOutlineTableWidget`` so it spans cells that host widgets via
``setCellWidget`` (where delegate ``paint()`` is never invoked).

It also strips ``State_HasFocus`` so Qt never draws its dotted per-cell
focus rectangle (``PE_FrameFocusRect``) on the current cell. The only
selection affordance is then the row outline; keyboard focus and
navigation are untouched (we clear the flag on the paint option, not on
the view's focus policy).
"""

from PyQt6.QtCore import QModelIndex
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem


class GroupRowDelegate(QStyledItemDelegate):
    """Item delegate that suppresses Qt's default selection fill so the
    cell's :class:`Qt.ItemDataRole.BackgroundRole` tint stays visible,
    and suppresses the dotted focus rectangle on the current cell. The
    selection outline is painted by ``RowOutlineTableWidget``."""

    def initStyleOption(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        super().initStyleOption(option, index)
        # Strip State_Selected so Qt doesn't fill the cell with the opaque
        # selection brush (the BackgroundRole tint then survives), and
        # State_HasFocus so it doesn't draw the dotted focus rectangle on
        # the current cell. Clearing the flags here (rather than on the
        # view) keeps keyboard focus and navigation working.
        option.state &= ~QStyle.StateFlag.State_Selected
        option.state &= ~QStyle.StateFlag.State_HasFocus

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        opt = QStyleOptionViewItem(option)
        opt.state &= ~QStyle.StateFlag.State_Selected
        opt.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, opt, index)
