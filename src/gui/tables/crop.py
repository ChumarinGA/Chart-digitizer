"""Fixed four-row table for the plot-area corners."""

from __future__ import annotations

from PySide6.QtGui import QBrush
from PySide6.QtWidgets import QWidget

from src.gui.tables.base import _BasePointTable
from src.gui.tables.colors import point_color


class CropCornerTable(_BasePointTable):
    """Pixel coordinates of the four plot-area corners.

    Row 0 = leftdown (bottom-left)
    Row 1 = rightdown (bottom-right)
    Row 2 = leftup (top-left)
    Row 3 = rightup (top-right)
    """

    HEADERS = ["Corner", "x_wind", "y_wind"]
    CORNER_NAMES = ["leftdown", "rightdown", "leftup", "rightup"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(self.HEADERS, parent)
        self._updating = True
        for index, name in enumerate(self.CORNER_NAMES):
            self.insertRow(index)
            name_item = self._make_ro_item(name)
            name_item.setBackground(QBrush(point_color(index)))
            self.setItem(index, 0, name_item)
            self.setItem(index, 1, self._make_rw_item("0.0000"))
            self.setItem(index, 2, self._make_rw_item("0.0000"))
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


__all__ = ["CropCornerTable"]
