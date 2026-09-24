"""Headless integration checks for the accuracy-critical manual workflow."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.core.project import load_project, save_project
from src.gui.image_canvas import ImageCanvas
from src.gui.mode_panel import ModePanel
from src.gui.point_table import DataPointTable
from src.models.project_data import ProjectState


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _calibrated_panel(qapp: QApplication) -> tuple[ProjectState, ImageCanvas, ModePanel]:
    project = ProjectState(
        image=np.full((101, 101, 3), 255, dtype=np.uint8),
        crop_rect=(0.0, 0.0, 100.0, 100.0),
    )
    canvas = ImageCanvas()
    panel = ModePanel(project, canvas)
    panel._create_ref_point(0.0, 100.0, axis="X", x_ref=0.0)
    panel._create_ref_point(100.0, 100.0, axis="X", x_ref=10.0)
    panel._create_ref_point(0.0, 100.0, axis="Y", y_ref=0.0)
    panel._create_ref_point(0.0, 0.0, axis="Y", y_ref=10.0)
    panel._rebuild_calibration()
    assert panel._calibration is not None
    return project, canvas, panel


def test_one_visible_series_has_one_internal_collection(qapp: QApplication) -> None:
    panel = ModePanel(ProjectState(), ImageCanvas())
    assert panel._data_tabs.count() == len(panel._series_points) == 1
    assert panel._curve_tabs.count() == len(panel._curve_points) == 1


def test_independent_axis_anchors_build_and_edits_invalidate(qapp: QApplication) -> None:
    project, _, panel = _calibrated_panel(qapp)
    assert panel._calibration.pixel_to_data(50.0, 50.0) == pytest.approx((5.0, 5.0))

    # Column 4 is the X value in the new role-aware reference table.
    panel._ref_table.item(0, 4).setText("1")
    assert panel._calibration is None
    assert project.calibration.x_axis._slope is None
    assert "rebuild" in panel._ref_status.text().lower()


def test_entering_previously_blocked_value_promotes_anchor_and_invalidates_fit(
    qapp: QApplication,
) -> None:
    project, _, panel = _calibrated_panel(qapp)
    point = panel._ref_points[0]
    original_position = (point.pos().x(), point.pos().y())

    y_value = panel._ref_table.item(0, 5)
    assert y_value.flags() & Qt.ItemFlag.ItemIsEditable
    y_value.setText("0")

    assert panel._ref_table.item(0, 1).text() == "Both"
    assert panel._calibration is None
    assert project.calibration.x_axis._slope is None
    assert (point.pos().x(), point.pos().y()) == pytest.approx(original_position)
    assert "rebuild" in panel._ref_status.text().lower()


def test_invalid_new_reference_value_reports_its_row_on_build(
    qapp: QApplication,
) -> None:
    _, _, panel = _calibrated_panel(qapp)
    panel._ref_table.item(0, 5).setText("nan")

    panel._rebuild_calibration()

    assert panel._calibration is None
    assert "row 1" in panel._ref_status.text().lower()
    assert "y value" in panel._ref_status.text().lower()
    assert "#ff6666" in panel._ref_status.styleSheet()


def test_confirm_crop_without_prior_auto_detection(qapp: QApplication) -> None:
    project = ProjectState(image=np.full((20, 30, 3), 255, dtype=np.uint8))
    panel = ModePanel(project, ImageCanvas())
    panel._crop_confirm()
    assert panel._crop_overlay is not None
    assert project.crop_rect == pytest.approx((0.0, 0.0, 30.0, 20.0))


def test_out_of_bounds_table_edit_uses_clamped_marker_position(qapp: QApplication) -> None:
    _, _, panel = _calibrated_panel(qapp)
    panel._add_data_point(50.0, 50.0)
    panel._data_table_wind_changed(0, 0, -999.0, -888.0)

    point = panel._series_points[0][0]
    table = panel._series_tables[0]
    assert (point.pos().x(), point.pos().y()) == pytest.approx((0.0, 0.0))
    assert float(table.item(0, 1).text()) == pytest.approx(0.0)
    assert float(table.item(0, 2).text()) == pytest.approx(0.0)


def test_project_roundtrip_restores_calibration_and_live_points(
    qapp: QApplication, tmp_path
) -> None:
    project, _, panel = _calibrated_panel(qapp)
    panel._add_data_point(25.0, 75.0)
    panel._add_curve_point(20.0, 80.0)
    panel._add_curve_point(80.0, 20.0)
    panel.sync_project_state()

    path = tmp_path / "session.digitizer"
    save_project(project, path)
    loaded = load_project(path)
    restored = ModePanel(loaded, ImageCanvas())
    restored.set_project(loaded)

    assert restored._calibration is not None
    assert len(restored._ref_points) == 4
    assert len(restored._series_points[0]) == 1
    assert len(restored._curve_points[0]) == 2
    assert restored._calibration.pixel_to_data(25.0, 75.0) == pytest.approx((2.5, 2.5))


def test_project_roundtrip_preserves_stale_calibration_draft_and_pixel_points(
    qapp: QApplication, tmp_path
) -> None:
    project, _, panel = _calibrated_panel(qapp)
    panel._add_data_point(33.25, 66.75)
    panel._ref_table.item(1, 4).setText("20")  # valid edit, but calibration is now stale
    assert panel._calibration is None
    panel.sync_project_state()

    path = tmp_path / "draft.digitizer"
    save_project(project, path)
    loaded = load_project(path)
    restored = ModePanel(loaded, ImageCanvas())
    restored.set_project(loaded)

    assert restored._calibration is None
    assert len(restored._ref_points) == 4
    assert len(restored._series_points[0]) == 1
    assert restored._series_points[0][0].pos().x() == pytest.approx(33.25)
    assert restored._series_tables[0].item(0, 3).text() == "—"

    restored._rebuild_calibration()
    assert restored._calibration is not None
    assert float(restored._series_tables[0].item(0, 3).text()) == pytest.approx(6.65)


def test_small_values_are_not_displayed_as_zero(qapp: QApplication) -> None:
    table = DataPointTable()
    table.add_row(0.0, 0.0, 1e-6, 2e-9)
    assert float(table.item(0, 3).text()) == pytest.approx(1e-6)
    assert float(table.item(0, 4).text()) == pytest.approx(2e-9)
