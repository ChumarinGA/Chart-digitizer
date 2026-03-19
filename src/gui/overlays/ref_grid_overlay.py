"""Reference grid overlay drawn at each calibration reference value."""

from __future__ import annotations

from PySide6.QtCore import QLineF, QRectF, Qt
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsLineItem, QGraphicsObject

from src.models.calibration_data import CalibrationResult


class RefGridOverlay(QGraphicsObject):
    """Draws dashed grid lines at each reference X and Y value.

    Lines are children of this object and managed via show/hide rather
    than add/remove to avoid C++ object lifetime issues when the parent
    is removed from the scene.
    """

    def __init__(self, parent: QGraphicsItem | None = None) -> None:
        super().__init__(parent)
        self._lines: list[QGraphicsLineItem] = []
        self.setZValue(5)

    def boundingRect(self) -> QRectF:
        return self.childrenBoundingRect()

    def paint(self, painter, option, widget=None) -> None:
        pass

    def update_grid(
        self,
        calibration: CalibrationResult,
        crop_rect: tuple[int, int, int, int],
        x_refs: list[float],
        y_refs: list[float],
    ) -> None:
        self._clear_lines()
        x0, y0, w, h = crop_rect
        v_pen = QPen(QColor(0, 200, 255, 100), 1, Qt.PenStyle.DashLine)
        h_pen = QPen(QColor(255, 100, 200, 100), 1, Qt.PenStyle.DashLine)

        try:
            for xr in x_refs:
                px = calibration.x_axis.data_to_pixel(xr)
                line = QGraphicsLineItem(QLineF(px, y0, px, y0 + h), self)
                line.setPen(v_pen)
                self._lines.append(line)

            for yr in y_refs:
                py = calibration.y_axis.data_to_pixel(yr)
                line = QGraphicsLineItem(QLineF(x0, py, x0 + w, py), self)
                line.setPen(h_pen)
                self._lines.append(line)
        except Exception:
            pass

    def _clear_lines(self) -> None:
        """Safely dispose of old line items."""
        for line in self._lines:
            try:
                line.setParentItem(None)
                sc = line.scene()
                if sc is not None:
                    sc.removeItem(line)
            except RuntimeError:
                pass
        self._lines.clear()

    def clear_grid(self) -> None:
        self._clear_lines()
