"""Smooth spline overlay drawn through ordered control points."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsPathItem


class CurvePathOverlay(QGraphicsPathItem):
    """Draws a Catmull-Rom spline (as cubic Bezier segments) through control points."""

    def __init__(self, color: QColor = QColor(255, 80, 80),
                 thickness: float = 2.0,
                 parent=None) -> None:
        super().__init__(parent)
        self._color = color
        self._thickness = thickness
        self.setZValue(10)
        self.setBrush(Qt.BrushStyle.NoBrush)
        self._update_pen()

    def set_color(self, color: QColor) -> None:
        self._color = color
        self._update_pen()

    def set_thickness(self, t: float) -> None:
        self._thickness = max(0.5, t)
        self._update_pen()

    def color(self) -> QColor:
        return self._color

    def thickness(self) -> float:
        return self._thickness

    def _update_pen(self) -> None:
        self.setPen(QPen(self._color, self._thickness))

    def update_from_points(self, points: list[QPointF]) -> None:
        """Rebuild the smooth path through *ordered* pixel-coordinate points."""
        path = QPainterPath()
        n = len(points)
        if n == 0:
            self.setPath(path)
            return
        path.moveTo(points[0])
        if n == 1:
            self.setPath(path)
            return
        if n == 2:
            path.lineTo(points[1])
            self.setPath(path)
            return

        for i in range(n - 1):
            p0 = points[max(0, i - 1)]
            p1 = points[i]
            p2 = points[i + 1]
            p3 = points[min(n - 1, i + 2)]

            cp1 = QPointF(
                p1.x() + (p2.x() - p0.x()) / 6.0,
                p1.y() + (p2.y() - p0.y()) / 6.0,
            )
            cp2 = QPointF(
                p2.x() - (p3.x() - p1.x()) / 6.0,
                p2.y() - (p3.y() - p1.y()) / 6.0,
            )
            path.cubicTo(cp1, cp2, p2)

        self.setPath(path)
