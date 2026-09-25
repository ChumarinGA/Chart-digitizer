"""Compatibility and composition contracts for the workspace refactor."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.gui.image_canvas import ImageCanvas
from src.gui.mode_panel import ModePanel as LegacyModePanel
from src.gui.workspace.calibration_mode import CalibrationMode
from src.gui.workspace.crop_mode import CropMode
from src.gui.workspace.curve_mode import CurveMode
from src.gui.workspace.data_mode import DataMode
from src.gui.workspace.export_tools import ExportTools
from src.gui.workspace.panel import ModePanel
from src.gui.workspace.precision_tools import PrecisionTools
from src.gui.workspace.project_session import ProjectSessionTools
from src.gui.workspace.scatter_mode import ScatterMode
from src.models.project_data import ProjectState


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_legacy_mode_panel_import_is_preserved() -> None:
    assert LegacyModePanel is ModePanel


def test_workspace_panel_is_composed_from_explicit_tools(qapp: QApplication) -> None:
    panel = ModePanel(ProjectState(), ImageCanvas())

    assert isinstance(panel._crop_mode, CropMode)
    assert isinstance(panel._calibration_mode, CalibrationMode)
    assert isinstance(panel._data_mode, DataMode)
    assert isinstance(panel._scatter_mode, ScatterMode)
    assert isinstance(panel._curve_mode, CurveMode)
    assert isinstance(panel._precision_tools, PrecisionTools)
    assert isinstance(panel._export_tools, ExportTools)
    assert isinstance(panel._session_tools, ProjectSessionTools)

    panel.close()
