"""Focused checks for active-point interaction signals and visuals."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QFocusEvent, QImage, QPainter, QPixmap
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QGraphicsSceneMouseEvent

from src.gui.image_canvas import ImageCanvas
from src.gui.overlays.point_overlay import DragConstraint, DraggablePoint


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_active_visual_enlarges_hit_geometry(qapp: QApplication) -> None:
    point = DraggablePoint(3.0, 4.0)
    normal = point.boundingRect()

    point.set_active_visual(True)

    assert point.is_active_visual()
    assert point.boundingRect().width() > normal.width()


def _paint_point(point: DraggablePoint) -> QImage:
    """Render at 1:1 so marker colours can be checked independently of a view."""
    image = QImage(81, 81, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.translate(40, 40)
    point.paint(painter, None)
    painter.end()
    return image


def test_active_marker_uses_series_colour_and_adjustable_translucent_fill(
    qapp: QApplication,
) -> None:
    colour = QColor(220, 40, 60)
    point = DraggablePoint(0.0, 0.0, colour)
    point.set_point_size(12.0)
    point.set_active_fill_opacity(25)
    point.set_active_visual(True)

    image = _paint_point(point)

    assert point.active_fill_opacity() == 25
    # Away from the crosshair and strokes, the whole active target is filled
    # with its series colour at the configured percentage.
    fill = image.pixelColor(44, 44)
    # ARGB32 premultiplication can round a channel by one at low alpha.
    assert (fill.red(), fill.green(), fill.blue()) == pytest.approx(
        colour.getRgb()[:3], abs=1
    )
    assert fill.alpha() == pytest.approx(round(255 * 0.25), abs=1)
    outer_fill = image.pixelColor(52, 45)  # outside shape, inside active ring
    assert outer_fill.getRgb() == pytest.approx(fill.getRgb(), abs=1)
    # Both the actual marker outline and the larger active ring are coloured.
    assert image.pixelColor(51, 43).red() > 180
    assert image.pixelColor(54, 42).red() > 180

    point.set_active_fill_opacity(-10)
    assert point.active_fill_opacity() == 0
    point.set_active_fill_opacity(150)
    assert point.active_fill_opacity() == 100


def test_inactive_marker_paint_is_unchanged_and_precision_anchor_stays_hollow(
    qapp: QApplication,
) -> None:
    colour = QColor(20, 150, 210)
    inactive = DraggablePoint(0.0, 0.0, colour)
    inactive.set_point_size(12.0)
    inactive.set_active_fill_opacity(15)
    inactive_image = _paint_point(inactive)

    fill = inactive_image.pixelColor(44, 44)
    assert fill == colour  # inactive data markers retain their opaque fill
    assert inactive_image.pixelColor(51, 43) == QColor(Qt.GlobalColor.black)

    anchor = DraggablePoint(0.0, 0.0, colour)
    anchor.set_point_size(12.0)
    anchor.set_precision_style(True)
    anchor.set_active_fill_opacity(80)
    anchor.set_active_visual(True)
    anchor_image = _paint_point(anchor)
    assert anchor_image.pixelColor(44, 44).alpha() == 0


def test_focus_emits_activation(qapp: QApplication) -> None:
    point = DraggablePoint(0.0, 0.0)
    spy = QSignalSpy(point.activated)

    point.focusInEvent(QFocusEvent(QEvent.Type.FocusIn))

    assert spy.count() == 1


def test_drag_finished_only_after_position_changed(qapp: QApplication) -> None:
    point = DraggablePoint(0.0, 0.0)
    spy = QSignalSpy(point.drag_finished)
    press = QGraphicsSceneMouseEvent(QEvent.Type.GraphicsSceneMousePress)
    press.setButton(Qt.MouseButton.LeftButton)
    press.setButtons(Qt.MouseButton.LeftButton)
    release = QGraphicsSceneMouseEvent(QEvent.Type.GraphicsSceneMouseRelease)
    release.setButton(Qt.MouseButton.LeftButton)
    release.setButtons(Qt.MouseButton.NoButton)

    point.mousePressEvent(press)
    point.mouseReleaseEvent(release)
    assert spy.count() == 0

    point.mousePressEvent(press)
    point.setPos(1.25, 2.5)
    point.mouseReleaseEvent(release)
    assert spy.count() == 1


def test_fixed_point_blocks_canvas_click_through(qapp: QApplication) -> None:
    canvas = ImageCanvas()
    canvas.resize(300, 300)
    pixmap = QPixmap(100, 100)
    pixmap.fill(Qt.GlobalColor.white)
    canvas._pixmap_item = canvas._scene.addPixmap(pixmap)
    canvas.setSceneRect(0.0, 0.0, 100.0, 100.0)
    point = DraggablePoint(50.0, 50.0)
    point.set_constraint(DragConstraint.FIXED)
    canvas.add_overlay(point)
    canvas.show()
    qapp.processEvents()

    canvas_clicks = QSignalSpy(canvas.scene_clicked)
    activations = QSignalSpy(point.activated)
    viewport_pos = canvas.mapFromScene(point.pos())
    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=viewport_pos)

    assert canvas_clicks.count() == 0
    assert activations.count() >= 1
