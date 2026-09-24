"""Zoomable, pannable image canvas built on QGraphicsView."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPixmap, QWheelEvent
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

        # Keep the source pixels crisp while zooming.  Bilinear smoothing is
        # attractive for viewing, but it invents intermediate edge positions
        # and makes sub-pixel placement on thick plot frames ambiguous.
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMouseTracking(True)

        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._overlays: list[QGraphicsItem] = []
        self._panning = False
        self._zoom = 1.0

    # ---- public API ----

    def set_image(self, path: Path) -> None:
        if self._pixmap_item is not None:
            self._scene.removeItem(self._pixmap_item)
        pm = QPixmap(str(path))
        self._pixmap_item = self._scene.addPixmap(pm)
        self._pixmap_item.setTransformationMode(Qt.TransformationMode.FastTransformation)
        self._pixmap_item.setZValue(-100)
        self.setSceneRect(self._scene.itemsBoundingRect())
        self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = 1.0

    def set_smooth_scaling(self, enabled: bool) -> None:
        """Toggle interpolation when zooming the source image."""
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, enabled)
        if self._pixmap_item is not None:
            mode = (Qt.TransformationMode.SmoothTransformation if enabled
                    else Qt.TransformationMode.FastTransformation)
            self._pixmap_item.setTransformationMode(mode)
        self.viewport().update()

    def loupe_pixmap(self, scene_x: float, scene_y: float, *,
                     radius: int = 7, size: int = 150) -> QPixmap:
        """Return a nearest-neighbour pixel loupe with an exact crosshair."""
        if self._pixmap_item is None or radius < 1 or size < 20:
            return QPixmap()
        source = self._pixmap_item.pixmap()
        nominal_left = math.floor(scene_x) - radius
        nominal_top = math.floor(scene_y) - radius
        patch_side = 2 * radius + 1
        left = max(0, nominal_left)
        top = max(0, nominal_top)
        right = min(source.width(), nominal_left + patch_side)
        bottom = min(source.height(), nominal_top + patch_side)
        if right <= left or bottom <= top:
            return QPixmap()

        # Keep a fixed square field at image edges.  Stretching a clipped
        # rectangle to a square made pixels rectangular and distorted the very
        # marker/frame geometry that the loupe is meant to verify.
        patch = QPixmap(patch_side, patch_side)
        patch.fill(QColor(32, 32, 32))
        patch_painter = QPainter(patch)
        patch_painter.drawPixmap(
            left - nominal_left,
            top - nominal_top,
            source.copy(left, top, right - left, bottom - top),
        )
        patch_painter.end()
        result = patch.scaled(
            size, size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        painter = QPainter(result)
        cx = (scene_x - nominal_left) / patch_side * size
        cy = (scene_y - nominal_top) / patch_side * size
        outer = QPen(QColor(0, 0, 0, 220), 3)
        outer.setCosmetic(True)
        painter.setPen(outer)
        painter.drawLine(QPointF(cx, 0.0), QPointF(cx, float(size)))
        painter.drawLine(QPointF(0.0, cy), QPointF(float(size), cy))
        inner = QPen(QColor(255, 70, 70), 1)
        inner.setCosmetic(True)
        painter.setPen(inner)
        painter.drawLine(QPointF(cx, 0.0), QPointF(cx, float(size)))
        painter.drawLine(QPointF(0.0, cy), QPointF(float(size), cy))
        painter.end()
        return result

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
        next_zoom = self._zoom * factor
        if not 0.03 <= next_zoom <= 80.0:
            return
        self.scale(factor, factor)
        self._zoom = next_zoom

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
            viewport_pos = event.position().toPoint()
            item = self.itemAt(viewport_pos)
            # Draggable points and crop handles block click-through.  A point
            # constrained in both axes is focusable but no longer movable;
            # treating only movable items as interactive created a duplicate
            # point whenever a fixed marker was clicked for selection.
            is_interactive = (
                item is not None
                and item.flags()
                & (
                    QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                    | QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
                )
            )
            if not is_interactive:
                scene_pos = self.mapToScene(viewport_pos)
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
