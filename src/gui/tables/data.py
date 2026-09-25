"""Table for digitized Scatter points and Curve control points."""

from __future__ import annotations

from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QWidget

from src.gui.tables.base import _BasePointTable
from src.gui.tables.colors import point_color


class DataPointTable(_BasePointTable):
    """Table with pixel coordinates and their calibrated data values."""

    HEADERS = ["#", "x_wind", "y_wind", "x_fig", "y_fig"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(self.HEADERS, parent)
        self.cellChanged.connect(self._on_cell_changed)

    def add_row(
        self,
        x_wind: float,
        y_wind: float,
        x_fig: float = 0.0,
        y_fig: float = 0.0,
        color: QColor | None = None,
    ) -> int:
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
        for row in range(self.rowCount()):
            try:
                x_wind = float(self.item(row, 1).text())
                y_wind = float(self.item(row, 2).text())
                x_fig, y_fig = calibration.pixel_to_data(x_wind, y_wind)
                self.item(row, 3).setText(self._fmt(x_fig))
                self.item(row, 4).setText(self._fmt(y_fig))
            except Exception:
                self.item(row, 3).setText("?")
                self.item(row, 4).setText("?")
        self._updating = False

    def clear_fig_values(self) -> None:
        """Mark derived data coordinates stale while calibration is invalid."""
        self._updating = True
        for row in range(self.rowCount()):
            self.item(row, 3).setText("—")
            self.item(row, 4).setText("—")
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


__all__ = ["DataPointTable"]
