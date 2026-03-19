"""Zoomable, pannable image canvas built on QGraphicsView."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QWidget,
)


class ImageCanvas(QGraphicsView):
    """Central image display with zoom, pan and overlay support."""

    mouse_moved = Signal(float, float)
    scene_clicked = Signal(float, float)

    _ZOOM_FACTOR = 1.15

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self.setRenderHints(
            self.renderHints()
            | self.renderHints().__class__.Antialiasing
            | self.renderHints().__class__.SmoothPixmapTransform
        )
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMouseTracking(True)

        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._overlays: list[QGraphicsItem] = []
        self._panning = False

    # ---- public API ----

    def set_image(self, path: Path) -> None:
        if self._pixmap_item is not None:
            self._scene.removeItem(self._pixmap_item)
        pm = QPixmap(str(path))
        self._pixmap_item = self._scene.addPixmap(pm)
        self._pixmap_item.setZValue(-100)
        self.setSceneRect(self._scene.itemsBoundingRect())
        self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def add_overlay(self, item: QGraphicsItem) -> None:
        self._scene.addItem(item)
        self._overlays.append(item)

    def remove_overlay(self, item: QGraphicsItem) -> None:
        if item in self._overlays:
            self._scene.removeItem(item)
            self._overlays.remove(item)

    def clear_overlays(self) -> None:
        for item in list(self._overlays):
            self._scene.removeItem(item)
        self._overlays.clear()

    # ---- zoom / pan ----

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = self._ZOOM_FACTOR if event.angleDelta().y() > 0 else 1.0 / self._ZOOM_FACTOR
        self.scale(factor, factor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._panning = True
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            fake = QMouseEvent(
                event.type(), event.position(), Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton, event.modifiers(),
            )
            super().mousePressEvent(fake)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())
            # Only movable items (DraggablePoint, crop handles) should block
            # click-through.  Everything else (crop rect fill, grid lines,
            # pixmap, empty space) lets the click reach the canvas.
            is_interactive = (
                item is not None
                and item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            )
            if not is_interactive:
                scene_pos = self.mapToScene(event.pos())
                self.scene_clicked.emit(scene_pos.x(), scene_pos.y())

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._panning = False
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        scene_pos = self.mapToScene(event.pos())
        self.mouse_moved.emit(scene_pos.x(), scene_pos.y())
        super().mouseMoveEvent(event)
