"""Editable point tables for reference and data points with bidirectional sync."""

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

POINT_PALETTE = [
    QColor(230, 70, 70),
    QColor(70, 180, 70),
    QColor(70, 120, 230),
    QColor(230, 180, 40),
    QColor(180, 70, 220),
    QColor(40, 200, 200),
    QColor(230, 120, 50),
    QColor(140, 200, 60),
    QColor(200, 80, 140),
    QColor(100, 160, 220),
    QColor(220, 200, 80),
    QColor(160, 100, 60),
    QColor(80, 220, 160),
    QColor(220, 100, 180),
    QColor(100, 100, 180),
    QColor(180, 180, 100),
    QColor(120, 60, 160),
    QColor(60, 160, 120),
    QColor(200, 140, 100),
    QColor(100, 200, 220),
]


def point_color(index: int) -> QColor:
    return POINT_PALETTE[index % len(POINT_PALETTE)]


class _BasePointTable(QTableWidget):
    """Common base for both ref-point and data-point tables."""

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

    def _make_ro_item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _make_rw_item(self, text: str) -> QTableWidgetItem:
        return QTableWidgetItem(text)

    def _fmt(self, v: float) -> str:
        return f"{v:.4f}"

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
        for r in range(self.rowCount()):
            item = self.item(r, 0)
            if item:
                item.setText(str(r + 1))
                item.setBackground(QBrush(point_color(r)))
        self._updating = False

    def selected_row(self) -> int | None:
        rows = self.selectionModel().selectedRows()
        if rows:
            return rows[0].row()
        return None

    def selected_rows(self) -> list[int]:
        return sorted({idx.row() for idx in self.selectionModel().selectedRows()})

    def select_all_rows(self) -> None:
        self.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.selectAll()
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            row = self.selected_row()
            if row is not None:
                step = 1.0
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    step = 10.0
                elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    step = 0.1
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


class RefPointTable(_BasePointTable):
    """Table: # | x_wind | y_wind | x_ref | y_ref"""

    ref_value_changed = Signal()
    HEADERS = ["#", "x_wind", "y_wind", "x_ref", "y_ref"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(self.HEADERS, parent)
        self.cellChanged.connect(self._on_cell_changed)

    def add_row(self, x_wind: float, y_wind: float,
                x_ref: float = 0.0, y_ref: float = 0.0,
                color: QColor | None = None) -> int:
        self._updating = True
        row = self.rowCount()
        self.insertRow(row)
        num_item = self._make_ro_item(str(row + 1))
        if color is None:
            color = point_color(row)
        num_item.setBackground(QBrush(color))
        self.setItem(row, 0, num_item)
        self.setItem(row, 1, self._make_rw_item(self._fmt(x_wind)))
        self.setItem(row, 2, self._make_rw_item(self._fmt(y_wind)))
        self.setItem(row, 3, self._make_rw_item(self._fmt(x_ref)))
        self.setItem(row, 4, self._make_rw_item(self._fmt(y_ref)))
        self._updating = False
        return row

    def update_wind(self, row: int, x: float, y: float) -> None:
        if row < 0 or row >= self.rowCount():
            return
        self._updating = True
        self.item(row, 1).setText(self._fmt(x))
        self.item(row, 2).setText(self._fmt(y))
        self._updating = False

    def get_ref_data(self) -> list[tuple[float, float, float, float]]:
        result = []
        for r in range(self.rowCount()):
            try:
                xw = float(self.item(r, 1).text())
                yw = float(self.item(r, 2).text())
                xr = float(self.item(r, 3).text())
                yr = float(self.item(r, 4).text())
                result.append((xw, yw, xr, yr))
            except (ValueError, AttributeError):
                continue
        return result

    def _on_cell_changed(self, row: int, col: int) -> None:
        if self._updating:
            return
        if col in (1, 2):
            try:
                x = float(self.item(row, 1).text())
                y = float(self.item(row, 2).text())
                self.point_wind_changed.emit(row, x, y)
            except (ValueError, AttributeError):
                pass
        if col in (3, 4):
            self.ref_value_changed.emit()


class DataPointTable(_BasePointTable):
    """Table: # | x_wind | y_wind | x_fig | y_fig"""

    HEADERS = ["#", "x_wind", "y_wind", "x_fig", "y_fig"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(self.HEADERS, parent)
        self.cellChanged.connect(self._on_cell_changed)

    def add_row(self, x_wind: float, y_wind: float,
                x_fig: float = 0.0, y_fig: float = 0.0,
                color: QColor | None = None) -> int:
        self._updating = True
        row = self.rowCount()
        self.insertRow(row)
        num_item = self._make_ro_item(str(row + 1))
        if color is None:
            color = point_color(row)
        num_item.setBackground(QBrush(color))
        self.setItem(row, 0, num_item)
        self.setItem(row, 1, self._make_rw_item(self._fmt(x_wind)))
        self.setItem(row, 2, self._make_rw_item(self._fmt(y_wind)))
        self.setItem(row, 3, self._make_ro_item(self._fmt(x_fig)))
        self.setItem(row, 4, self._make_ro_item(self._fmt(y_fig)))
        self._updating = False
        return row

    def update_wind(self, row: int, x: float, y: float) -> None:
        if row < 0 or row >= self.rowCount():
            return
        self._updating = True
        self.item(row, 1).setText(self._fmt(x))
        self.item(row, 2).setText(self._fmt(y))
        self._updating = False

    def update_fig(self, row: int, x_fig: float, y_fig: float) -> None:
        if row < 0 or row >= self.rowCount():
            return
        self._updating = True
        self.item(row, 3).setText(self._fmt(x_fig))
        self.item(row, 4).setText(self._fmt(y_fig))
        self._updating = False

    def update_all_fig(self, calibration) -> None:
        self._updating = True
        for r in range(self.rowCount()):
            try:
                xw = float(self.item(r, 1).text())
                yw = float(self.item(r, 2).text())
                xf, yf = calibration.pixel_to_data(xw, yw)
                self.item(r, 3).setText(self._fmt(xf))
                self.item(r, 4).setText(self._fmt(yf))
            except Exception:
                self.item(r, 3).setText("?")
                self.item(r, 4).setText("?")
        self._updating = False

    def _on_cell_changed(self, row: int, col: int) -> None:
        if self._updating:
            return
        if col in (1, 2):
            try:
                x = float(self.item(row, 1).text())
                y = float(self.item(row, 2).text())
                self.point_wind_changed.emit(row, x, y)
            except (ValueError, AttributeError):
                pass


class CropCornerTable(_BasePointTable):
    """Fixed 4-row table for crop rectangle corners.

    Row 0 = leftdown  (bottom-left)
    Row 1 = rightdown (bottom-right)
    Row 2 = leftup    (top-left)
    Row 3 = rightup   (top-right)
    """

    HEADERS = ["Corner", "x_wind", "y_wind"]
    CORNER_NAMES = ["leftdown", "rightdown", "leftup", "rightup"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(self.HEADERS, parent)
        self._updating = True
        for i, name in enumerate(self.CORNER_NAMES):
            self.insertRow(i)
            name_item = self._make_ro_item(name)
            name_item.setBackground(QBrush(point_color(i)))
            self.setItem(i, 0, name_item)
            self.setItem(i, 1, self._make_rw_item("0.0000"))
            self.setItem(i, 2, self._make_rw_item("0.0000"))
        self._updating = False
        self.cellChanged.connect(self._on_cell_changed)

    def update_corner(self, row: int, x: float, y: float) -> None:
        if row < 0 or row >= 4:
            return
        self._updating = True
        self.item(row, 1).setText(self._fmt(x))
        self.item(row, 2).setText(self._fmt(y))
        self._updating = False

    def update_corner_x(self, row: int, x: float) -> None:
        if row < 0 or row >= 4:
            return
        self._updating = True
        self.item(row, 1).setText(self._fmt(x))
        self._updating = False

    def update_corner_y(self, row: int, y: float) -> None:
        if row < 0 or row >= 4:
            return
        self._updating = True
        self.item(row, 2).setText(self._fmt(y))
        self._updating = False

    def _on_cell_changed(self, row: int, col: int) -> None:
        if self._updating:
            return
        if col in (1, 2):
            try:
                x = float(self.item(row, 1).text())
                y = float(self.item(row, 2).text())
                self.point_wind_changed.emit(row, x, y)
            except (ValueError, AttributeError):
                pass
