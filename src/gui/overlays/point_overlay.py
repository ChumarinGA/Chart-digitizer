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
    activated = Signal()
    drag_finished = Signal()

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
        self._precision_style = False
        self._active_visual = False
        # ``None`` preserves the hollow legacy active visual used by Crop/Ref.
        # Scatter/Curve opt in with a percentage supplied by ModePanel.
        self._active_fill_opacity: int | None = None
        self._drag_start_pos: Optional[QPointF] = None
        self._arrow_step = 1.0
        self._ctrl_step = 10.0
        self._shift_step = 0.1

    # --- shape / size ---

    def point_shape(self) -> PointShape:
        return self._shape

    def point_size(self) -> float:
        return self._size

    def color(self) -> QColor:
        return QColor(self._color)

    def set_color(self, color: QColor) -> None:
        if color.isValid():
            self._color = QColor(color)
            self.update()

    def set_point_shape(self, shape: PointShape) -> None:
        self.prepareGeometryChange()
        self._shape = shape
        self.update()

    def set_point_size(self, size: float) -> None:
        self.prepareGeometryChange()
        self._size = max(1.0, size)
        self.update()

    def set_precision_style(self, enabled: bool = True) -> None:
        """Use a hollow marker and a high-contrast centre crosshair.

        This style is intended for calibration anchors: it leaves the source
        stroke visible instead of covering it with an opaque marker.
        """
        self._precision_style = enabled
        self.update()

    def set_active_visual(self, enabled: bool = True) -> None:
        """Highlight this point as the current precision-editing target.

        Selection is intentionally controlled by the owner rather than by the
        graphics scene.  This lets tables and newly created points activate a
        marker through the same API as a direct click.
        """
        enabled = bool(enabled)
        if self._active_visual == enabled:
            return
        self.prepareGeometryChange()
        self._active_visual = enabled
        self.update()

    def is_active_visual(self) -> bool:
        return self._active_visual

    def set_active_fill_opacity(self, percent: int | None) -> None:
        """Set fill opacity for the active data-point target, in percent.

        Passing ``None`` keeps the hollow black/white legacy highlight used by
        calibration and crop handles.  A numeric value opts Scatter/Curve
        points into the coloured active-target rendering.
        """
        value = None if percent is None else max(0, min(100, int(percent)))
        if self._active_fill_opacity == value:
            return
        self._active_fill_opacity = value
        self.update()

    def active_fill_opacity(self) -> int | None:
        return self._active_fill_opacity

    def set_nudge_steps(self, arrow: float, ctrl: float, shift: float) -> None:
        self._arrow_step = float(arrow)
        self._ctrl_step = float(ctrl)
        self._shift_step = float(shift)

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
        r = self._size + (8 if self._active_visual else 4)
        return QRectF(-r, -r, 2 * r, 2 * r)

    def paint(self, painter, option, widget=None) -> None:
        coloured_active = (
            self._active_visual
            and not self._precision_style
            and self._active_fill_opacity is not None
        )
        path = build_shape_path(self._shape, self._size)

        if coloured_active:
            # The larger selection ring is the footprint the user is actively
            # positioning.  Tint it first so the exact crosshair and the
            # marker-shape outline remain fully opaque on top.
            ring_radius = self._size + 3
            ring_rect = QRectF(
                -ring_radius, -ring_radius,
                2 * ring_radius, 2 * ring_radius,
            )
            fill = QColor(self._color)
            fill.setAlpha(round(255 * self._active_fill_opacity / 100))
            ring_pen = QPen(self._color, 2.0)
            ring_pen.setCosmetic(True)
            painter.setPen(ring_pen)
            painter.setBrush(QBrush(fill))
            painter.drawEllipse(ring_rect)

        outline = QPen(
            self._color
            if self._precision_style or coloured_active
            else Qt.GlobalColor.black,
            1.5,
        )
        outline.setCosmetic(True)
        painter.setPen(outline)
        painter.setBrush(
            Qt.BrushStyle.NoBrush
            if self._precision_style or self._active_visual
            else QBrush(self._color)
        )
        painter.drawPath(path)

        r = self._size + (7 if self._active_visual else 3)
        # Every marker gets a double-stroked, solid centre cross.  A single
        # coloured dotted line disappeared on similarly coloured plots and
        # made the exact saved centre ambiguous.  The active marker remains
        # distinct through its longer arms and outer ring.
        underlay = QPen(Qt.GlobalColor.black, 3)
        underlay.setCosmetic(True)
        painter.setPen(underlay)
        painter.drawLine(QPointF(-r, 0), QPointF(r, 0))
        painter.drawLine(QPointF(0, -r), QPointF(0, r))
        pen = QPen(Qt.GlobalColor.white, 1.25 if self._active_visual else 1.0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLine(QPointF(-r, 0), QPointF(r, 0))
        painter.drawLine(QPointF(0, -r), QPointF(0, r))

        if self._active_visual and not coloured_active:
            # A double-stroked outer ring makes the selected marker obvious on
            # both dark and light plots without covering the source pixel at
            # the exact centre of the crosshair.
            ring_radius = self._size + 3
            ring_rect = QRectF(
                -ring_radius, -ring_radius,
                2 * ring_radius, 2 * ring_radius,
            )
            ring_underlay = QPen(Qt.GlobalColor.black, 3)
            ring_underlay.setCosmetic(True)
            painter.setPen(ring_underlay)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(ring_rect)
            ring = QPen(Qt.GlobalColor.white, 1, Qt.PenStyle.DashLine)
            ring.setCosmetic(True)
            painter.setPen(ring)
            painter.drawEllipse(ring_rect)

    # --- interaction ---

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = QPointF(self.pos())
            self.activated.emit()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        was_left_drag = (
            event.button() == Qt.MouseButton.LeftButton
            and self._drag_start_pos is not None
        )
        start_pos = self._drag_start_pos
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)
        if was_left_drag and start_pos is not None:
            pos = self.pos()
            if (abs(pos.x() - start_pos.x()) > 1e-12
                    or abs(pos.y() - start_pos.y()) > 1e-12):
                self.drag_finished.emit()

    def focusInEvent(self, event) -> None:
        self.activated.emit()
        super().focusInEvent(event)

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
        step = self._arrow_step
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            step = self._ctrl_step
        elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            step = self._shift_step

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
