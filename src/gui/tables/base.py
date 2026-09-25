"""Common behaviour shared by all editable point tables."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)


class _BasePointTable(QTableWidget):
    """Common base for reference, data, and crop-corner tables."""

    point_wind_changed = Signal(int, float, float)
    key_move = Signal(int, float, float)

    def __init__(self, headers: list[str], parent: QWidget | None = None) -> None:
        super().__init__(0, len(headers), parent)
        self.setHorizontalHeaderLabels(headers)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.verticalHeader().setVisible(False)
        self._updating = False
        self._arrow_step = 1.0
        self._ctrl_step = 10.0
        self._shift_step = 0.1

    def set_nudge_steps(self, arrow: float, ctrl: float, shift: float) -> None:
        self._arrow_step = float(arrow)
        self._ctrl_step = float(ctrl)
        self._shift_step = float(shift)

    def _make_ro_item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _make_rw_item(self, text: str) -> QTableWidgetItem:
        return QTableWidgetItem(text)

    def _fmt(self, v: float) -> str:
        """Format a value without discarding useful scientific precision."""
        return f"{v:.12g}"

    def remove_selected_row(self) -> int | None:
        rows = self.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        self.removeRow(row)
        self._renumber()
        return row

    def _renumber(self) -> None:
        self._updating = True
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item:
                item.setText(str(row + 1))
                # Preserve the existing marker colour after an earlier row is
                # deleted; recolouring only the table would desynchronise it.
        self._updating = False

    def selected_row(self) -> int | None:
        rows = self.selectionModel().selectedRows()
        if rows:
            return rows[0].row()
        return None

    def selected_rows(self) -> list[int]:
        return sorted({index.row() for index in self.selectionModel().selectedRows()})

    def set_row_color(self, row: int, color: QColor) -> None:
        if 0 <= row < self.rowCount():
            item = self.item(row, 0)
            if item is not None:
                item.setBackground(QBrush(color))

    def select_all_rows(self) -> None:
        self.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.selectAll()
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        arrow_keys = (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
        )
        if key in arrow_keys:
            row = self.selected_row()
            if row is not None:
                step = self._arrow_step
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    step = self._ctrl_step
                elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    step = self._shift_step
                dx, dy = 0.0, 0.0
                if key == Qt.Key.Key_Left:
                    dx = -step
                elif key == Qt.Key.Key_Right:
                    dx = step
                elif key == Qt.Key.Key_Up:
                    dy = -step
                elif key == Qt.Key.Key_Down:
                    dy = step
                self.key_move.emit(row, dx, dy)
                return
        super().keyPressEvent(event)


# A non-private spelling is convenient for new code, while the old private
# name remains available through the compatibility facade.
BasePointTable = _BasePointTable

__all__ = ["BasePointTable", "_BasePointTable"]
