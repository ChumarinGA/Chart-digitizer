"""Interactive draggable point overlays for calibration and manual picking."""

from __future__ import annotations

import math
from enum import Enum, auto
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainterPath, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject


class DragConstraint(Enum):
    FREE = auto()
    HORIZONTAL_ONLY = auto()
    VERTICAL_ONLY = auto()
    FIXED = auto()


class PointShape(Enum):
    CIRCLE = "Circle"
    SQUARE = "Square"
    TRIANGLE_UP = "Triangle ▲"
    TRIANGLE_DOWN = "Triangle ▼"
    TRIANGLE_LEFT = "Triangle ◀"
    TRIANGLE_RIGHT = "Triangle ▶"
    DIAMOND_0 = "Diamond ◇"
    DIAMOND_45 = "Diamond ⟡45°"
    DIAMOND_90 = "Diamond ⟡90°"
    DIAMOND_135 = "Diamond ⟡135°"
    STAR = "Star ★"


def _triangle_poly(size: float) -> QPolygonF:
    """Equilateral triangle (all angles 60°) inscribed in a circle of given radius."""
    r = size
    return QPolygonF([
        QPointF(0, -r),
        QPointF(-r * math.sqrt(3) / 2, r / 2),
        QPointF(r * math.sqrt(3) / 2, r / 2),
    ])


def _diamond_poly(size: float) -> QPolygonF:
    """Vertically elongated rhombus (1 : 1.6 aspect)."""
    sx, sy = size * 0.65, size
    return QPolygonF([
        QPointF(0, -sy),
        QPointF(sx, 0),
        QPointF(0, sy),
        QPointF(-sx, 0),
    ])


def _star_poly(size: float, n: int = 5) -> QPolygonF:
    outer = size
    inner = size * 0.38
    pts: list[QPointF] = []
    for i in range(2 * n):
        angle = -math.pi / 2 + i * math.pi / n
        r = outer if i % 2 == 0 else inner
        pts.append(QPointF(r * math.cos(angle), r * math.sin(angle)))
    return QPolygonF(pts)


def _rotate_poly(poly: QPolygonF, degrees: float) -> QPolygonF:
    t = QTransform()
    t.rotate(degrees)
    return t.map(poly)


def build_shape_path(shape: PointShape, size: float) -> QPainterPath:
    path = QPainterPath()
    if shape == PointShape.CIRCLE:
        path.addEllipse(QPointF(0, 0), size, size)
    elif shape == PointShape.SQUARE:
        path.addRect(-size, -size, 2 * size, 2 * size)
    elif shape in (PointShape.TRIANGLE_UP, PointShape.TRIANGLE_DOWN,
                   PointShape.TRIANGLE_LEFT, PointShape.TRIANGLE_RIGHT):
        poly = _triangle_poly(size)
        rot = {
            PointShape.TRIANGLE_UP: 0,
            PointShape.TRIANGLE_DOWN: 180,
            PointShape.TRIANGLE_LEFT: -90,
            PointShape.TRIANGLE_RIGHT: 90,
        }[shape]
        if rot:
            poly = _rotate_poly(poly, rot)
        path.addPolygon(poly)
        path.closeSubpath()
    elif shape in (PointShape.DIAMOND_0, PointShape.DIAMOND_45,
                   PointShape.DIAMOND_90, PointShape.DIAMOND_135):
        poly = _diamond_poly(size)
        rot = {
            PointShape.DIAMOND_0: 0,
            PointShape.DIAMOND_45: 45,
            PointShape.DIAMOND_90: 90,
            PointShape.DIAMOND_135: 135,
        }[shape]
        if rot:
            poly = _rotate_poly(poly, rot)
        path.addPolygon(poly)
        path.closeSubpath()
    elif shape == PointShape.STAR:
        poly = _star_poly(size)
        path.addPolygon(poly)
        path.closeSubpath()
    return path


class DraggablePoint(QGraphicsObject):
    """A single draggable marker on the canvas with optional movement constraints."""

    position_changed = Signal(float, float)

    DEFAULT_SIZE = 5.0

    def __init__(self, x: float, y: float, color: QColor = QColor(255, 255, 0),
                 parent: QGraphicsItem | None = None) -> None:
        super().__init__(parent)
        self.setPos(x, y)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setZValue(20)
        self._color = color
        self._constraint = DragConstraint.FREE
        self._locked_x: float = x
        self._locked_y: float = y
        self._suppress_signal = False
        self._bounds: Optional[QRectF] = None
        self._shape = PointShape.CIRCLE
        self._size = self.DEFAULT_SIZE

    # --- shape / size ---

    def point_shape(self) -> PointShape:
        return self._shape

    def point_size(self) -> float:
        return self._size

    def set_point_shape(self, shape: PointShape) -> None:
        self.prepareGeometryChange()
        self._shape = shape
        self.update()

    def set_point_size(self, size: float) -> None:
        self.prepareGeometryChange()
        self._size = max(1.0, size)
        self.update()

    # --- constraint / bounds ---

    def set_constraint(self, constraint: DragConstraint) -> None:
        self._constraint = constraint
        pos = self.pos()
        self._locked_x = pos.x()
        self._locked_y = pos.y()
        movable = constraint != DragConstraint.FIXED
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, movable)

    def set_bounds(self, rect: QRectF | None) -> None:
        self._bounds = rect

    def set_pos_silent(self, x: float, y: float) -> None:
        self._suppress_signal = True
        self.setPos(x, y)
        if self._constraint in (DragConstraint.HORIZONTAL_ONLY, DragConstraint.FIXED):
            self._locked_y = y
        if self._constraint in (DragConstraint.VERTICAL_ONLY, DragConstraint.FIXED):
            self._locked_x = x
        self._suppress_signal = False

    # --- drawing ---

    def boundingRect(self) -> QRectF:
        r = self._size + 4
        return QRectF(-r, -r, 2 * r, 2 * r)

    def paint(self, painter, option, widget=None) -> None:
        painter.setPen(QPen(Qt.GlobalColor.black, 1))
        painter.setBrush(QBrush(self._color))
        path = build_shape_path(self._shape, self._size)
        painter.drawPath(path)

        r = self._size + 3
        pen = QPen(self._color, 1, Qt.PenStyle.DotLine)
        painter.setPen(pen)
        painter.drawLine(QPointF(-r, 0), QPointF(r, 0))
        painter.drawLine(QPointF(0, -r), QPointF(0, r))

    # --- interaction ---

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            new_pos: QPointF = value

            if self._constraint == DragConstraint.VERTICAL_ONLY:
                new_pos = QPointF(self._locked_x, new_pos.y())
            elif self._constraint == DragConstraint.HORIZONTAL_ONLY:
                new_pos = QPointF(new_pos.x(), self._locked_y)
            elif self._constraint == DragConstraint.FIXED:
                new_pos = QPointF(self._locked_x, self._locked_y)

            if self._bounds is not None:
                nx = max(self._bounds.left(), min(new_pos.x(), self._bounds.right()))
                ny = max(self._bounds.top(), min(new_pos.y(), self._bounds.bottom()))
                new_pos = QPointF(nx, ny)

            return new_pos
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            if not self._suppress_signal:
                self.position_changed.emit(value.x(), value.y())
        return super().itemChange(change, value)

    def keyPressEvent(self, event) -> None:
        step = 1.0
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            step = 10.0
        elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            step = 0.1

        key = event.key()
        dx, dy = 0.0, 0.0
        if key == Qt.Key.Key_Left:
            dx = -step
        elif key == Qt.Key.Key_Right:
            dx = step
        elif key == Qt.Key.Key_Up:
            dy = -step
        elif key == Qt.Key.Key_Down:
            dy = step
        else:
            super().keyPressEvent(event)
            return
        self.moveBy(dx, dy)
