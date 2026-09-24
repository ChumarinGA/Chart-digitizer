"""Integration contract for the resizable/detachable workflow panel."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QPushButton,
    QScrollArea,
    QToolBar,
)

from src.gui.main_window import MainWindow
from src.gui.mode_panel import ModePanel


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def workspace_window(qapp: QApplication, tmp_path) -> MainWindow:
    image_path = tmp_path / "chart.png"
    assert cv2.imwrite(str(image_path), np.full((80, 120, 3), 255, np.uint8))

    window = MainWindow()
    window.resize(1200, 650)
    window._load_image(image_path)
    window.show()
    qapp.processEvents()
    yield window
    window.close()
    qapp.processEvents()


def _mode_dock(window: MainWindow) -> QDockWidget:
    dock = window.findChild(QDockWidget, "modePanelDock")
    assert dock is not None, "The workflow panel must be a named QDockWidget"
    return dock


def test_mode_panel_has_native_dock_contract(workspace_window: MainWindow) -> None:
    window = workspace_window
    dock = _mode_dock(window)

    assert dock.allowedAreas() & Qt.DockWidgetArea.RightDockWidgetArea
    assert dock.features() & QDockWidget.DockWidgetFeature.DockWidgetMovable
    assert dock.features() & QDockWidget.DockWidgetFeature.DockWidgetFloatable
    assert dock.features() & QDockWidget.DockWidgetFeature.DockWidgetClosable

    scroll = dock.widget()
    assert isinstance(scroll, QScrollArea)
    assert scroll.widgetResizable()
    panel = scroll.widget()
    assert isinstance(panel, ModePanel)
    # Hard 680/820 limits prevented VS Code-like resizing.
    assert panel.minimumWidth() < 680
    assert panel.maximumWidth() >= 1200

    toggle = dock.toggleViewAction()
    assert any(toggle in toolbar.actions() for toolbar in window.findChildren(QToolBar))


def test_hiding_and_floating_dock_release_space_to_canvas(
    workspace_window: MainWindow, qapp: QApplication
) -> None:
    window = workspace_window
    dock = _mode_dock(window)
    central = window.centralWidget()

    dock.setFloating(False)
    dock.show()
    window.resizeDocks([dock], [430], Qt.Orientation.Horizontal)
    qapp.processEvents()
    width_with_dock = central.width()

    dock.toggleViewAction().trigger()
    qapp.processEvents()
    assert not dock.isVisible()
    assert central.width() > width_with_dock

    dock.toggleViewAction().trigger()
    qapp.processEvents()
    assert dock.isVisible()
    width_with_dock = central.width()

    dock.setFloating(True)
    qapp.processEvents()
    assert dock.isFloating()
    assert central.width() > width_with_dock

    dock.setFloating(False)
    qapp.processEvents()
    assert not dock.isFloating()
    assert central.width() < window.width()


def test_dock_width_is_dynamically_resizable(
    workspace_window: MainWindow, qapp: QApplication
) -> None:
    window = workspace_window
    dock = _mode_dock(window)
    central = window.centralWidget()
    dock.setFloating(False)
    dock.show()

    window.resizeDocks([dock], [300], Qt.Orientation.Horizontal)
    qapp.processEvents()
    narrow_dock = dock.width()
    wide_canvas = central.width()

    window.resizeDocks([dock], [520], Qt.Orientation.Horizontal)
    qapp.processEvents()
    assert dock.width() > narrow_dock
    assert central.width() < wide_canvas


def test_short_window_can_scroll_to_bottom_controls(
    workspace_window: MainWindow, qapp: QApplication
) -> None:
    window = workspace_window
    dock = _mode_dock(window)
    scroll = dock.widget()
    assert isinstance(scroll, QScrollArea)

    window.resize(1000, 420)
    dock.setFloating(False)
    dock.show()
    qapp.processEvents()

    bar = scroll.verticalScrollBar()
    assert bar.maximum() > 0, "A short window must scroll instead of clipping controls"

    export = next(
        button
        for button in scroll.widget().findChildren(QPushButton)
        if button.text() == "Export to Excel"
    )
    scroll.ensureWidgetVisible(export, 0, 0)
    qapp.processEvents()
    export_top_left = export.mapTo(scroll.viewport(), QPoint(0, 0))
    assert scroll.viewport().rect().intersects(
        export.geometry().translated(export_top_left - export.pos())
    )


def test_loading_another_image_keeps_the_permanent_central_stack(
    workspace_window: MainWindow, qapp: QApplication
) -> None:
    """A replaced QMainWindow central widget is deleteLater-owned by Qt."""
    window = workspace_window
    image_path = window._project.image_path
    assert image_path is not None

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    window._load_image(image_path)
    qapp.processEvents()

    assert window.centralWidget() is window._central_stack
    assert window._central_stack.currentWidget() is window._workspace
    assert window._start_screen.parent() is window._central_stack
