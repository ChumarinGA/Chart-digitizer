"""Integration checks for the point-centred precision workflow."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMessageBox, QScrollArea

from src.core.project import load_project, save_project
from src.gui.image_canvas import ImageCanvas
from src.gui.mode_panel import ModePanel
from src.gui.overlays.point_overlay import PointShape
from src.gui.style_dialog import PointStyleDialog
from src.models.project_data import ProjectState


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _panel(qapp: QApplication) -> ModePanel:
    project = ProjectState(
        image=np.full((101, 101, 3), 255, dtype=np.uint8),
        crop_rect=(0.0, 0.0, 100.0, 100.0),
    )
    panel = ModePanel(project, ImageCanvas())
    panel._crop_confirmed = True
    panel._create_ref_point(0.0, 100.0, axis="X", x_ref=0.0)
    panel._create_ref_point(100.0, 100.0, axis="X", x_ref=10.0)
    panel._create_ref_point(0.0, 100.0, axis="Y", y_ref=0.0)
    panel._create_ref_point(0.0, 0.0, axis="Y", y_ref=10.0)
    panel._rebuild_calibration()
    assert panel._calibration is not None
    return panel


def test_mode_panel_reflows_scrolls_and_collapses_on_small_viewport(
    qapp: QApplication,
) -> None:
    panel = _panel(qapp)
    panel._switch_mode(2)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(panel)
    scroll.resize(400, 300)
    scroll.show()
    qapp.processEvents()

    assert panel.minimumWidth() == 0
    assert panel.maximumWidth() > 1_000_000
    assert panel._precision_compact
    assert panel._precision_group.isCheckable()
    assert panel._precision_group.isChecked()
    assert panel._precision_content.isVisible()
    expanded_scroll_range = scroll.verticalScrollBar().maximum()
    assert expanded_scroll_range > 0

    panel._precision_group.setChecked(False)
    qapp.processEvents()
    assert panel._precision_content.isHidden()
    assert scroll.verticalScrollBar().maximum() < expanded_scroll_range

    scroll.ensureWidgetVisible(panel._btn_export)
    qapp.processEvents()
    assert scroll.verticalScrollBar().value() > 0

    scroll.resize(760, 500)
    qapp.processEvents()
    assert not panel._precision_compact
    scroll.close()


def test_confirmed_yellow_frame_remains_visible_without_fill(
    qapp: QApplication,
) -> None:
    panel = _panel(qapp)
    panel._show_crop_overlay(5.0, 6.0, 80.0, 70.0)
    panel._crop_confirm()

    panel._switch_mode(1)
    assert panel._crop_overlay is not None
    assert panel._crop_overlay.isVisible()
    assert panel._crop_overlay._rect_item.brush().color().alpha() == 0
    assert panel._crop_overlay._rect_item.pen().color().yellow() > 150
    assert panel._crop_overlay._rect_item.pen().isCosmetic()
    assert panel._crop_overlay.zValue() > panel._curve_paths[0].zValue()

    panel._switch_mode(2)
    assert panel._crop_overlay.isVisible()
    assert panel._crop_overlay._rect_item.brush().color().alpha() == 0


def test_loupe_tracks_active_point_not_mouse(qapp: QApplication) -> None:
    panel = _panel(qapp)
    panel._switch_mode(2)
    panel._add_data_point(20.25, 70.75)

    original_text = panel._loupe_coords.text()
    assert "20.2500" in original_text
    assert "70.7500" in original_text

    panel._canvas.mouse_moved.emit(91.0, 3.0)
    assert panel._loupe_coords.text() == original_text

    panel._series_points[0][0].setPos(21.125, 69.875)
    assert "21.1250" in panel._loupe_coords.text()
    assert "69.8750" in panel._loupe_coords.text()


def test_curve_table_selection_and_active_deletion_keep_loupe_consistent(
    qapp: QApplication,
) -> None:
    panel = _panel(qapp)
    panel._switch_mode(2)
    for x, y in ((10.0, 90.0), (20.0, 80.0), (30.0, 70.0)):
        panel._add_data_point(x, y)
    panel._series_tables[0].selectRow(1)
    panel._data_delete_selected()

    assert panel._active_point in panel._series_points[0]
    context = panel._point_context(panel._active_point)
    assert context is not None
    assert panel._active_point_label == context[0]
    for row, point in enumerate(panel._series_points[0]):
        assert panel._series_tables[0].item(row, 0).background().color() == point.color()

    panel._rb_curve.setChecked(True)
    panel._add_curve_point(40.0, 60.0)
    panel._add_curve_point(50.0, 50.0)
    panel._curve_tables[0].selectRow(0)
    assert panel._active_point is panel._curve_points[0][0]
    assert "40.0000" in panel._loupe_coords.text()


def test_pixel_magnet_changes_only_active_and_new_points(qapp: QApplication) -> None:
    panel = _panel(qapp)
    panel._switch_mode(2)
    panel._add_data_point(10.2, 80.8)
    panel._add_data_point(20.2, 70.8)
    first, second = panel._series_points[0]

    panel._series_tables[0].selectRow(0)
    panel._pixel_center_check.setChecked(True)
    assert (first.pos().x(), first.pos().y()) == pytest.approx((10.5, 80.5))
    assert (second.pos().x(), second.pos().y()) == pytest.approx((20.2, 70.8))

    panel._add_data_point(30.1, 60.9)
    third = panel._series_points[0][2]
    assert (third.pos().x(), third.pos().y()) == pytest.approx((30.5, 60.5))


def test_pixel_magnet_covers_table_and_keyboard_moves_for_curve(
    qapp: QApplication,
) -> None:
    panel = _panel(qapp)
    panel._switch_mode(2)
    panel._rb_curve.setChecked(True)
    panel._add_curve_point(20.2, 70.8)
    point = panel._curve_points[0][0]
    panel._pixel_center_check.setChecked(True)

    panel._curve_table_wind_changed(0, 0, 23.2, 67.8)
    assert (point.pos().x(), point.pos().y()) == pytest.approx((23.5, 67.5))

    point.moveBy(0.2, 0.2)
    assert (point.pos().x(), point.pos().y()) == pytest.approx((23.5, 67.5))

    panel._pixel_center_check.setChecked(False)
    point.moveBy(0.2, 0.2)
    assert (point.pos().x(), point.pos().y()) == pytest.approx((23.7, 67.7))


def test_curve_point_style_applies_to_selection_and_future_points(
    qapp: QApplication,
) -> None:
    panel = _panel(qapp)
    panel._switch_mode(2)
    panel._rb_curve.setChecked(True)
    panel._add_curve_point(20.0, 80.0)
    panel._add_curve_point(40.0, 60.0)
    first, second = panel._curve_points[0]

    panel._curve_tables[0].selectRow(0)
    panel._on_curve_point_style_shape(PointShape.SQUARE)
    panel._on_curve_point_style_size(8.0)
    assert first.point_shape() == PointShape.SQUARE
    assert first.point_size() == pytest.approx(8.0)
    assert second.point_shape() == PointShape.CIRCLE
    assert second.point_size() == pytest.approx(4.0)

    panel._add_curve_point(60.0, 40.0)
    third = panel._curve_points[0][2]
    assert third.point_shape() == PointShape.SQUARE
    assert third.point_size() == pytest.approx(8.0)


def test_point_style_dialog_controls_active_fill_opacity_as_percentage(
    qapp: QApplication,
) -> None:
    dialog = PointStyleDialog()
    assert dialog.current_active_fill_opacity() == 15

    values: list[int] = []
    dialog.active_fill_opacity_changed.connect(values.append)
    dialog.set_active_fill_opacity(37)
    assert dialog.current_active_fill_opacity() == 37
    assert values == []

    dialog.set_active_fill_opacity(42, emit=True)
    assert dialog.current_active_fill_opacity() == 42
    assert values == [42]


def test_scatter_and_curve_active_fill_opacity_are_independent_and_restored(
    qapp: QApplication, tmp_path
) -> None:
    panel = _panel(qapp)
    panel._switch_mode(2)
    panel._add_data_point(10.0, 90.0)
    scatter = panel._series_points[0][0]
    panel._on_scatter_active_fill_opacity(24)
    assert scatter.active_fill_opacity() == 24

    panel._rb_curve.setChecked(True)
    panel._add_curve_point(20.0, 80.0)
    curve = panel._curve_points[0][0]
    assert curve.active_fill_opacity() == 15
    panel._on_curve_active_fill_opacity(39)
    assert curve.active_fill_opacity() == 39
    assert scatter.active_fill_opacity() == 24

    panel.sync_project_state()
    assert panel._project.scatter_active_fill_opacity == 24
    assert panel._project.curve_active_fill_opacity == 39
    path = tmp_path / "active-fill.digitizer"
    save_project(panel._project, path)
    loaded = load_project(path)
    assert loaded.scatter_active_fill_opacity == 24
    assert loaded.curve_active_fill_opacity == 39

    restored = ModePanel(loaded, ImageCanvas())
    restored.set_project(loaded)
    assert restored._scatter_active_fill_opacity == 24
    assert restored._curve_active_fill_opacity == 39
    assert restored._series_points[0][0].active_fill_opacity() == 24
    assert restored._curve_points[0][0].active_fill_opacity() == 39


def test_curve_style_controls_active_curve(qapp: QApplication) -> None:
    panel = _panel(qapp)
    panel._switch_mode(2)
    panel._rb_curve.setChecked(True)
    color = QColor(10, 120, 230)

    panel._on_curve_style_color(color)
    panel._on_curve_style_thickness(3.5)
    panel._on_curve_style_line_pattern(Qt.PenStyle.DashDotLine)

    path = panel._curve_paths[0]
    assert path.color() == color
    assert path.thickness() == pytest.approx(3.5)
    assert path.line_style() == Qt.PenStyle.DashDotLine


def test_open_curve_style_dialog_resyncs_when_active_tab_changes(
    qapp: QApplication,
) -> None:
    panel = _panel(qapp)
    panel._switch_mode(2)
    panel._rb_curve.setChecked(True)
    panel._curve_series_spin.setValue(2)
    panel._curve_paths[0].set_thickness(2.0)
    panel._curve_paths[1].set_thickness(4.0)
    panel._curve_tabs.setCurrentIndex(0)
    panel._open_curve_style_dialog()
    assert panel._curve_style_dialog is not None
    assert panel._curve_style_dialog.windowTitle() == "Curve 1 Style"

    panel._curve_tabs.setCurrentIndex(1)
    assert panel._curve_style_dialog.windowTitle() == "Curve 2 Style"
    assert panel._curve_style_dialog.current_thickness() == pytest.approx(4.0)
    panel._curve_style_dialog.set_line_style(Qt.PenStyle.DashDotDotLine)
    assert panel._curve_paths[1].line_style() == Qt.PenStyle.DashDotDotLine
    assert panel._curve_paths[0].line_style() == Qt.PenStyle.SolidLine


def test_marker_centre_candidate_is_applied_only_after_confirmation(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    panel = _panel(qapp)
    panel._project.image[:] = 255
    # Eight pixels per side -> exact scene centre (39, 49), between pixels.
    panel._project.image[45:53, 35:43] = 0
    panel._switch_mode(2)
    panel._add_data_point(37.2, 50.6)
    point = panel._series_points[0][0]

    original_add_button = QMessageBox.addButton

    def remember_accept_button(self, text, role):
        button = original_add_button(self, text, role)
        if role == QMessageBox.ButtonRole.AcceptRole:
            self._test_accept_button = button
        return button

    monkeypatch.setattr(QMessageBox, "addButton", remember_accept_button)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(
        QMessageBox, "clickedButton", lambda self: self._test_accept_button
    )

    assert panel._propose_marker_center(point)
    assert (point.pos().x(), point.pos().y()) == pytest.approx((39.0, 49.0), abs=0.1)


def test_rejected_marker_candidate_restores_exact_point_with_magnet_armed(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    panel = _panel(qapp)
    panel._project.image[:] = 255
    panel._project.image[45:53, 35:43] = 0
    panel._switch_mode(2)
    panel._add_data_point(37.5, 50.5)
    point = panel._series_points[0][0]
    original = (point.pos().x(), point.pos().y())
    panel._pixel_center_check.setChecked(True)

    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: None)

    assert not panel._propose_marker_center(point)
    assert (point.pos().x(), point.pos().y()) == pytest.approx(original)


def test_visual_styles_roundtrip_and_load_bypasses_pixel_magnet(
    qapp: QApplication, tmp_path
) -> None:
    panel = _panel(qapp)
    panel._switch_mode(2)
    panel._add_data_point(10.2, 80.8)
    scatter = panel._series_points[0][0]
    scatter.set_point_shape(PointShape.STAR)
    scatter.set_point_size(7.5)
    panel._current_shape = PointShape.DIAMOND_45
    panel._current_size = 6.5

    panel._rb_curve.setChecked(True)
    panel._curve_series_spin.setValue(2)
    panel._curve_tabs.setCurrentIndex(0)
    panel._add_curve_point(20.2, 70.8)
    panel._curve_points[0][0].set_point_shape(PointShape.SQUARE)
    panel._curve_points[0][0].set_point_size(8.0)
    panel._set_curve_color(0, QColor(20, 80, 180))
    panel._curve_paths[0].set_thickness(3.5)
    panel._curve_paths[0].set_line_style(Qt.PenStyle.DashLine)
    panel._curve_tabs.setCurrentIndex(1)
    panel._add_curve_point(30.3, 60.7)
    panel._set_curve_color(1, QColor(180, 70, 30))
    panel._curve_paths[1].set_thickness(4.5)
    panel._curve_paths[1].set_line_style(Qt.PenStyle.DotLine)
    panel._curve_point_shape = PointShape.TRIANGLE_UP
    panel._curve_point_size = 9.0
    panel._curve_thickness = 5.5

    panel.sync_project_state()
    path = tmp_path / "styles.digitizer"
    save_project(panel._project, path)
    loaded = load_project(path)

    # Restore into an independent panel, both to prove that defaults really
    # came from the file and to simulate a previously armed magnet.
    restored = ModePanel(loaded, ImageCanvas())
    restored._current_shape = PointShape.TRIANGLE_DOWN
    restored._current_size = 2.0
    restored._curve_point_shape = PointShape.TRIANGLE_DOWN
    restored._curve_point_size = 2.0
    restored._curve_thickness = 1.0
    restored._pixel_center_check.setChecked(True)
    restored.set_project(loaded)

    assert not restored._pixel_center_check.isChecked()
    assert (restored._series_points[0][0].pos().x(), restored._series_points[0][0].pos().y()) \
        == pytest.approx((10.2, 80.8))
    assert restored._series_points[0][0].point_shape() == PointShape.STAR
    assert restored._series_points[0][0].point_size() == pytest.approx(7.5)
    assert restored._current_shape == PointShape.DIAMOND_45
    assert restored._current_size == pytest.approx(6.5)

    assert restored._curve_points[0][0].point_shape() == PointShape.SQUARE
    assert restored._curve_points[0][0].point_size() == pytest.approx(8.0)
    assert restored._curve_paths[0].color() == QColor(20, 80, 180)
    assert restored._curve_paths[0].thickness() == pytest.approx(3.5)
    assert restored._curve_paths[0].line_style() == Qt.PenStyle.DashLine
    assert restored._curve_paths[1].color() == QColor(180, 70, 30)
    assert restored._curve_paths[1].thickness() == pytest.approx(4.5)
    assert restored._curve_paths[1].line_style() == Qt.PenStyle.DotLine
    assert restored._curve_point_shape == PointShape.TRIANGLE_UP
    assert restored._curve_point_size == pytest.approx(9.0)
    assert restored._curve_thickness == pytest.approx(5.5)
    assert restored._curve_thick_spin.maximum() == pytest.approx(50.0)
    assert restored._crop_overlay is not None and restored._crop_overlay.isVisible()


def test_legacy_project_without_style_fields_uses_safe_defaults(
    qapp: QApplication, tmp_path
) -> None:
    panel = _panel(qapp)
    panel._switch_mode(2)
    panel._add_data_point(12.25, 78.75)
    panel.sync_project_state()
    path = tmp_path / "legacy.digitizer"
    save_project(panel._project, path)

    raw = json.loads(path.read_text(encoding="utf-8"))
    for key in (
        "scatter_point_styles",
        "curve_point_styles",
        "curve_visual_styles",
        "scatter_default_point_style",
        "curve_default_point_style",
        "curve_default_thickness",
        "scatter_active_fill_opacity",
        "curve_active_fill_opacity",
    ):
        raw.pop(key, None)
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = load_project(path)
    restored = ModePanel(loaded, ImageCanvas())
    restored.set_project(loaded)
    point = restored._series_points[0][0]
    assert point.point_shape() == PointShape.CIRCLE
    assert point.point_size() == pytest.approx(5.0)
    assert restored._curve_paths[0].line_style() == Qt.PenStyle.SolidLine
    assert loaded.scatter_active_fill_opacity == 15
    assert loaded.curve_active_fill_opacity == 15


def test_damaged_style_entries_do_not_shift_later_styles(tmp_path) -> None:
    state = ProjectState(
        scatter_point_styles=[
            [("STAR", 3.0), ("DIAMOND_45", 4.0), ("SQUARE", 8.0)]
        ],
        curve_visual_styles=[
            ("#ffff0000", 2.0, "DashLine"),
            ("#ff00ff00", 3.0, "DotLine"),
            ("#ff0000ff", 4.0, "DashDotLine"),
        ],
    )
    path = tmp_path / "damaged-styles.digitizer"
    save_project(state, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["scatter_point_styles"][0][1] = None
    raw["curve_visual_styles"][1] = None
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = load_project(path)

    assert loaded.scatter_point_styles[0] == [
        ("STAR", 3.0), ("CIRCLE", 5.0), ("SQUARE", 8.0)
    ]
    assert loaded.curve_visual_styles == [
        ("#ffff0000", 2.0, "DashLine"),
        ("#ffff5050", 2.0, "SolidLine"),
        ("#ff0000ff", 4.0, "DashDotLine"),
    ]
