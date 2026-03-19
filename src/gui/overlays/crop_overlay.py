"""Resizable rectangle overlay for selecting the plot area."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsRectItem,
    QGraphicsEllipseItem,
    QWidget,
)


class _Handle(QGraphicsEllipseItem):
    """Small draggable circle at a corner or edge midpoint."""

    SIZE = 8.0

    def __init__(self, parent: "CropOverlay", role: str) -> None:
        super().__init__(-self.SIZE / 2, -self.SIZE / 2, self.SIZE, self.SIZE, parent)
        self._role = role
        self._parent_overlay = parent
        self.setBrush(QBrush(QColor(100, 180, 255)))
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setZValue(10)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self._parent_overlay.handle_moved(self._role, self.pos())


class CropOverlay(QGraphicsObject):
    """Rectangle with 8 resize handles drawn over the image."""

    rect_changed = Signal(float, float, float, float)

    def __init__(self, x: float, y: float, w: float, h: float,
                 parent: QGraphicsItem | None = None) -> None:
        super().__init__(parent)
        self._rect = QRectF(x, y, w, h)

        self._border_pen = QPen(QColor(0, 200, 100), 2, Qt.PenStyle.DashLine)
        self._fill_brush = QBrush(QColor(0, 200, 100, 25))

        self._rect_item = QGraphicsRectItem(self._rect, self)
        self._rect_item.setPen(self._border_pen)
        self._rect_item.setBrush(self._fill_brush)

        self._handles: dict[str, _Handle] = {}
        for role in ("tl", "tr", "bl", "br", "t", "b", "l", "r"):
            h = _Handle(self, role)
            self._handles[role] = h
        self._update_handles()

    def boundingRect(self) -> QRectF:
        return self._rect.adjusted(-10, -10, 10, 10)

    def paint(self, painter, option, widget=None) -> None:
        pass

    def get_rect(self) -> tuple[int, int, int, int]:
        r = self._rect
        return (int(r.x()), int(r.y()), int(r.width()), int(r.height()))

    def get_rectf(self) -> QRectF:
        return QRectF(self._rect)

    def set_rect(self, x: float, y: float, w: float, h: float) -> None:
        self._rect = QRectF(x, y, w, h)
        self._rect_item.setRect(self._rect)
        self._update_handles()
        self.rect_changed.emit(x, y, w, h)

    def set_interactive(self, interactive: bool) -> None:
        """Show/hide resize handles."""
        for h in self._handles.values():
            h.setVisible(interactive)

    def set_confirmed_style(self, opacity: int = 30) -> None:
        """Switch to semi-transparent yellow for confirmed state."""
        self._border_pen = QPen(QColor(220, 200, 0, 180), 2, Qt.PenStyle.DashLine)
        self._fill_brush = QBrush(QColor(255, 255, 0, opacity))
        self._rect_item.setPen(self._border_pen)
        self._rect_item.setBrush(self._fill_brush)

    def set_editing_style(self) -> None:
        """Switch to green dashed for editing state."""
        self._border_pen = QPen(QColor(0, 200, 100), 2, Qt.PenStyle.DashLine)
        self._fill_brush = QBrush(QColor(0, 200, 100, 25))
        self._rect_item.setPen(self._border_pen)
        self._rect_item.setBrush(self._fill_brush)

    def set_fill_opacity(self, opacity: int) -> None:
        """Change the fill alpha (0-255)."""
        color = self._fill_brush.color()
        color.setAlpha(opacity)
        self._fill_brush = QBrush(color)
        self._rect_item.setBrush(self._fill_brush)

    def handle_moved(self, role: str, pos) -> None:
        r = self._rect
        x, y, w, h = r.x(), r.y(), r.width(), r.height()
        px, py = pos.x(), pos.y()

        if "l" in role:
            new_x = min(px, x + w - 10)
            w = w + (x - new_x)
            x = new_x
        if "r" in role:
            w = max(px - x, 10)
        if "t" in role:
            new_y = min(py, y + h - 10)
            h = h + (y - new_y)
            y = new_y
        if "b" in role:
            h = max(py - y, 10)

        self.set_rect(x, y, w, h)

    def nudge(self, dx: float, dy: float) -> None:
        self.set_rect(
            self._rect.x() + dx,
            self._rect.y() + dy,
            self._rect.width(),
            self._rect.height(),
        )

    def _update_handles(self) -> None:
        r = self._rect
        positions = {
            "tl": (r.left(), r.top()),
            "tr": (r.right(), r.top()),
            "bl": (r.left(), r.bottom()),
            "br": (r.right(), r.bottom()),
            "t": (r.center().x(), r.top()),
            "b": (r.center().x(), r.bottom()),
            "l": (r.left(), r.center().y()),
            "r": (r.right(), r.center().y()),
        }
        for role, (hx, hy) in positions.items():
            self._handles[role].setPos(hx, hy)
