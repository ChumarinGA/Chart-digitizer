"""Graphics overlay for an already sampled Curve preview."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsPathItem


class CurvePathOverlay(QGraphicsPathItem):
    """Draw a styled curve path without owning its interpolation algorithm.

    The active Curve workflow samples :class:`CurveInterpolator` and passes
    the resulting pixel polyline to :meth:`update_from_polyline`.  Keeping the
    graphics item unaware of PCHIP makes preview and export share one
    mathematical implementation.
    """

    def __init__(self, color: QColor = QColor(255, 80, 80),
                 thickness: float = 2.0,
                 parent=None,
                 *,
                 line_style: Qt.PenStyle = Qt.PenStyle.SolidLine) -> None:
        super().__init__(parent)
        self._color = color
        self._thickness = max(0.5, thickness)
        self._line_style = line_style
        self.setZValue(10)
        self.setBrush(Qt.BrushStyle.NoBrush)
        self._update_pen()

    def set_color(self, color: QColor) -> None:
        self._color = color
        self._update_pen()

    def set_thickness(self, t: float) -> None:
        self._thickness = max(0.5, t)
        self._update_pen()

    def set_line_style(self, style: Qt.PenStyle) -> None:
        """Set the Qt pen pattern used to draw this curve.

        ``Qt.PenStyle.SolidLine`` remains the default, so existing projects
        and callers retain their previous appearance.
        """
        self._line_style = Qt.PenStyle(style)
        self._update_pen()

    def color(self) -> QColor:
        return self._color

    def thickness(self) -> float:
        return self._thickness

    def line_style(self) -> Qt.PenStyle:
        return self._line_style

    def _update_pen(self) -> None:
        pen = QPen(self._color, self._thickness)
        pen.setStyle(self._line_style)
        self.setPen(pen)

    def update_from_points(self, points: list[QPointF]) -> None:
        """Draw the legacy Catmull–Rom path used by older external callers.

        The application itself no longer calls this compatibility method;
        Curve preview uses :meth:`update_from_polyline` instead.
        """
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

    def update_from_polyline(self, points: list[QPointF]) -> None:
        """Draw samples produced by the shared preview/export curve engine.

        The interpolation itself deliberately lives outside this graphics
        item.  This keeps the on-screen preview mathematically identical to
        exported values, including on logarithmic axes.
        """
        path = QPainterPath()
        if points:
            path.moveTo(points[0])
            for point in points[1:]:
                path.lineTo(point)
        self.setPath(path)
