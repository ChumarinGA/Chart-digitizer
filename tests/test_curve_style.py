from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from src.gui.curve_style_dialog import CurveStyleDialog
from src.gui.overlays.curve_path_overlay import CurvePathOverlay


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_curve_overlay_style_defaults_and_updates(qapp: QApplication) -> None:
    overlay = CurvePathOverlay()
    assert overlay.line_style() == Qt.PenStyle.SolidLine

    overlay.set_color(QColor("#123456"))
    overlay.set_thickness(3.5)
    overlay.set_line_style(Qt.PenStyle.DashDotLine)

    assert overlay.color() == QColor("#123456")
    assert overlay.thickness() == 3.5
    assert overlay.line_style() == Qt.PenStyle.DashDotLine
    assert overlay.pen().style() == Qt.PenStyle.DashDotLine
    assert overlay.pen().widthF() == 3.5


def test_curve_style_dialog_exposes_initial_values(qapp: QApplication) -> None:
    dialog = CurveStyleDialog(
        color=QColor("#abcdef"),
        thickness=4.5,
        line_style=Qt.PenStyle.DotLine,
    )
    assert dialog.current_color() == QColor("#abcdef")
    assert dialog.current_thickness() == 4.5
    assert dialog.current_line_style() == Qt.PenStyle.DotLine


def test_curve_style_dialog_emits_programmatic_colour(qapp: QApplication) -> None:
    dialog = CurveStyleDialog()
    received: list[QColor] = []
    dialog.color_changed.connect(received.append)

    dialog.set_color(QColor("#102030"), emit=True)

    assert received == [QColor("#102030")]
