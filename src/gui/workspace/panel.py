"""Mode panel — 3-mode (Crop / Ref / Data) interface with tables and multi-series tabs."""

from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.gui.image_canvas import ImageCanvas
from src.gui.dialogs.curve_style import CurveStyleDialog
from src.gui.dialogs.point_style import PointStyleDialog
from src.gui.overlays.crop_overlay import CropOverlay
from src.gui.overlays.curve_path_overlay import CurvePathOverlay
from src.gui.overlays.point_overlay import DraggablePoint, PointShape
from src.gui.overlays.ref_grid_overlay import RefGridOverlay
from src.gui.tables.data import DataPointTable
from src.gui.workspace.crop_mode import CropMode
from src.gui.workspace.calibration_mode import CalibrationMode
from src.gui.workspace.precision_tools import PrecisionTools
from src.gui.workspace.scatter_mode import ScatterMode
from src.gui.workspace.curve_mode import CurveMode
from src.gui.workspace.data_mode import DataMode
from src.gui.workspace.export_tools import ExportTools
from src.gui.workspace.project_session import ProjectSessionTools
from src.gui.workspace.colors import curve_series_color
from src.models.calibration_data import CalibrationResult
from src.models.project_data import ProjectState
from src.models.series_data import SeriesData
from src.models.types import ScaleType

class ModePanel(QWidget):
    """Right-side panel with Crop / Ref Points / Data Points modes."""

    def __init__(self, project: ProjectState, canvas: ImageCanvas,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # The panel is hosted by a resizable dock.  Its horizontal size hint
        # must not stop the dock boundary from being dragged: the precision
        # inspector switches to a one-column layout when space is tight.
        self.setMinimumWidth(0)
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding
        )
        self._project = project
        self._canvas = canvas
        self._crop_mode = CropMode(self)
        self._calibration_mode = CalibrationMode(self)
        self._precision_tools = PrecisionTools(self)
        self._scatter_mode = ScatterMode(self)
        self._curve_mode = CurveMode(self)
        self._data_mode = DataMode(self)
        self._export_tools = ExportTools(self)
        self._session_tools = ProjectSessionTools(self)

        # --- Scatter state ---
        self._ref_points: list[DraggablePoint] = []
        self._series_points: list[list[DraggablePoint]] = []
        self._series_tables: list[DataPointTable] = []

        # --- Curve state ---
        self._curve_points: list[list[DraggablePoint]] = []
        self._curve_tables: list[DataPointTable] = []
        self._curve_paths: list[CurvePathOverlay] = []
        self._curve_colors: list[QColor] = [curve_series_color(0)]
        self._curve_errors: dict[int, str] = {}
        self._curve_point_shape = PointShape.CIRCLE
        self._curve_point_size: float = 4.0
        self._curve_thickness: float = 2.0
        self._curve_dx: float = project.settings.curve_step_dx

        self._crop_overlay: Optional[CropOverlay] = None
        self._grid_overlay = RefGridOverlay()
        self._canvas.add_overlay(self._grid_overlay)
        self._grid_overlay.setVisible(False)

        self._calibration: Optional[CalibrationResult] = None
        self._crop_confirmed = False
        self._restoring = False

        self._style_dialog: Optional[PointStyleDialog] = None
        self._curve_point_style_dialog: Optional[PointStyleDialog] = None
        self._curve_style_dialog: Optional[CurveStyleDialog] = None
        self._current_shape = PointShape.CIRCLE
        self._current_size = DraggablePoint.DEFAULT_SIZE
        self._scatter_active_fill_opacity = self._normalise_active_fill_opacity(
            getattr(project, "scatter_active_fill_opacity", 15)
        )
        self._curve_active_fill_opacity = self._normalise_active_fill_opacity(
            getattr(project, "curve_active_fill_opacity", 15)
        )

        # The loupe follows the stored centre of exactly one active point.  It
        # deliberately never follows the mouse cursor: that made it impossible
        # to verify where the selected marker was actually saved.
        self._active_point: Optional[DraggablePoint] = None
        self._active_point_label = ""
        self._suspend_pixel_magnet = False

        # Crop corner DraggablePoints (bl, br, tl, tr)
        self._crop_corners: list[DraggablePoint] = []
        self._propagating_corner = False

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        # --- Mode buttons ---
        mode_row = QHBoxLayout()
        self._btn_crop = QPushButton("Crop")
        self._btn_ref = QPushButton("Ref Points")
        self._btn_data = QPushButton("Data Points")
        for btn in (self._btn_crop, self._btn_ref, self._btn_data):
            btn.setCheckable(True)
            mode_row.addWidget(btn)
        self._btn_crop.setChecked(True)

        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self._btn_crop, 0)
        self._mode_group.addButton(self._btn_ref, 1)
        self._mode_group.addButton(self._btn_data, 2)
        self._mode_group.idClicked.connect(self._switch_mode)
        root.addLayout(mode_row)

        # --- Stacked pages ---
        self._stack = QStackedWidget()
        root.addWidget(self._stack, stretch=1)
        self._build_crop_page()
        self._build_ref_page()
        self._build_data_page()
        self._build_precision_panel(root)

        # --- Export ---
        export_row = QHBoxLayout()
        self._combined_mode = QComboBox()
        self._combined_mode.addItems(["Union X", "Uniform grid", "Interpolation"])
        export_row.addWidget(QLabel("Combined:"))
        export_row.addWidget(self._combined_mode, stretch=1)
        root.addLayout(export_row)

        self._btn_export = QPushButton("Export to Excel")
        self._btn_export.setObjectName("primary")
        self._btn_export.clicked.connect(self._do_export)
        root.addWidget(self._btn_export)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #66bb6a; font-size: 12px;")
        root.addWidget(self._status)

        self._canvas.scene_clicked.connect(self._on_canvas_click)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Reflow the precision inspector as the dock boundary is dragged."""
        super().resizeEvent(event)
        if hasattr(self, "_precision_layout"):
            # Horizontal saves substantial vertical room at the normal
            # 600-ish dock width; stack only once the tools would be cramped.
            self._set_precision_compact(event.size().width() < 560)

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    def set_project(self, project: ProjectState) -> None:
        return self._session_tools.set_project(project)

    def _configure_point(self, point: DraggablePoint) -> None:
        settings = self._project.settings
        point.set_nudge_steps(settings.arrow_step, settings.ctrl_step, settings.shift_step)

    @staticmethod
    def _point_shape_from_name(name: object, fallback: PointShape) -> PointShape:
        try:
            return PointShape[str(name)]
        except (KeyError, TypeError):
            return fallback

    @staticmethod
    def _normalise_active_fill_opacity(value: object) -> int:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 15
        if not math.isfinite(numeric):
            return 15
        return int(round(max(0.0, min(100.0, numeric))))

    def _load_style_defaults(self, project: ProjectState) -> None:
        return self._session_tools._load_style_defaults(project)

    def _restore_saved_styles(self, project: ProjectState) -> None:
        return self._session_tools._restore_saved_styles(project)

    def _configure_table(self, table) -> None:
        settings = self._project.settings
        table.set_nudge_steps(settings.arrow_step, settings.ctrl_step, settings.shift_step)

    def apply_settings(self) -> None:
        """Apply settings that affect live manual tools."""
        for table in [self._crop_corner_table, self._ref_table,
                      *self._series_tables, *self._curve_tables]:
            self._configure_table(table)
        for point in [*self._crop_corners, *self._ref_points,
                      *(p for group in self._series_points for p in group),
                      *(p for group in self._curve_points for p in group)]:
            self._configure_point(point)
        self._centerline_snap_check.setChecked(self._project.settings.snap_to_edge)
        magnifier = self._project.settings.magnifier_enabled
        self._loupe.setVisible(magnifier)
        self._loupe_coords.setVisible(magnifier)
        mode = self._stack.currentIndex()
        self._precision_group.setVisible(mode == 2 or (mode == 1 and magnifier))
        self._curve_dx_spin.setValue(self._project.settings.curve_step_dx)
        self._x_scale_combo.setCurrentIndex(
            1 if self._project.settings.x_scale == ScaleType.LOG else 0
        )
        self._y_scale_combo.setCurrentIndex(
            1 if self._project.settings.y_scale == ScaleType.LOG else 0
        )

    # ------------------------------------------------------------------
    # page builders
    # ------------------------------------------------------------------

    def _build_crop_page(self) -> None:
        return self._crop_mode._build_crop_page()

    def _build_ref_page(self) -> None:
        return self._calibration_mode._build_ref_page()

    def _build_data_page(self) -> None:
        return self._data_mode._build_data_page()

    def _build_precision_panel(self, root: QVBoxLayout) -> None:
        return self._precision_tools._build_precision_panel(root)

    @Slot(bool)
    def _set_precision_expanded(self, expanded: bool) -> None:
        return self._precision_tools._set_precision_expanded(expanded)

    def _set_precision_compact(self, compact: bool) -> None:
        return self._precision_tools._set_precision_compact(compact)

    def _build_scatter_subpage(self) -> None:
        return self._scatter_mode._build_scatter_subpage()

    def _build_curve_subpage(self) -> None:
        return self._curve_mode._build_curve_subpage()

    @Slot(bool)
    def _on_data_submode_toggled(self, scatter_checked: bool) -> None:
        return self._data_mode._on_data_submode_toggled(scatter_checked)

    def _is_scatter_mode(self) -> bool:
        return self._data_mode._is_scatter_mode()

    def _open_style_dialog(self) -> None:
        return self._scatter_mode._open_style_dialog()

    @Slot(PointShape)
    def _on_style_shape(self, shape: PointShape) -> None:
        return self._scatter_mode._on_style_shape(shape)

    @Slot(float)
    def _on_style_size(self, size: float) -> None:
        return self._scatter_mode._on_style_size(size)

    @Slot(int)
    def _on_scatter_active_fill_opacity(self, percent: int) -> None:
        return self._scatter_mode._on_scatter_active_fill_opacity(percent)

    def _apply_style_to_selected(self) -> None:
        return self._scatter_mode._apply_style_to_selected()

    def _open_curve_point_style_dialog(self) -> None:
        return self._curve_mode._open_curve_point_style_dialog()

    @Slot(PointShape)
    def _on_curve_point_style_shape(self, shape: PointShape) -> None:
        return self._curve_mode._on_curve_point_style_shape(shape)

    @Slot(float)
    def _on_curve_point_style_size(self, size: float) -> None:
        return self._curve_mode._on_curve_point_style_size(size)

    @Slot(int)
    def _on_curve_active_fill_opacity(self, percent: int) -> None:
        return self._curve_mode._on_curve_active_fill_opacity(percent)

    def _apply_curve_point_style_to_selected(
        self,
        *,
        shape: PointShape | None = None,
        size: float | None = None,
    ) -> None:
        return self._curve_mode._apply_curve_point_style_to_selected(shape=shape, size=size)

    def _open_curve_style_dialog(self) -> None:
        return self._curve_mode._open_curve_style_dialog()

    def _sync_curve_style_dialog(self) -> None:
        return self._curve_mode._sync_curve_style_dialog()

    @Slot(QColor)
    def _on_curve_style_color(self, color: QColor) -> None:
        return self._curve_mode._on_curve_style_color(color)

    @Slot(float)
    def _on_curve_style_thickness(self, thickness: float) -> None:
        return self._curve_mode._on_curve_style_thickness(thickness)

    @Slot(Qt.PenStyle)
    def _on_curve_style_line_pattern(self, style: Qt.PenStyle) -> None:
        return self._curve_mode._on_curve_style_line_pattern(style)

    def _make_series_tab_widget(self, si: int) -> QWidget:
        return self._scatter_mode._make_series_tab_widget(si)

    def _rebuild_series_tabs(self, n: int) -> None:
        return self._scatter_mode._rebuild_series_tabs(n)

    def _active_series_index(self) -> int:
        return self._scatter_mode._active_series_index()

    @Slot(int)
    def _on_series_tab_changed(self, idx: int) -> None:
        return self._scatter_mode._on_series_tab_changed(idx)

    def _make_curve_tab_widget(self, ci: int) -> QWidget:
        return self._curve_mode._make_curve_tab_widget(ci)

    def _rebuild_curve_tabs(self, n: int) -> None:
        return self._curve_mode._rebuild_curve_tabs(n)

    def _active_curve_index(self) -> int:
        return self._curve_mode._active_curve_index()

    @Slot(int)
    def _on_curve_tab_changed(self, idx: int) -> None:
        return self._curve_mode._on_curve_tab_changed(idx)

    @Slot(float)
    def _on_curve_point_size(self, val: float) -> None:
        return self._curve_mode._on_curve_point_size(val)

    @Slot(float)
    def _on_curve_thickness(self, val: float) -> None:
        return self._curve_mode._on_curve_thickness(val)

    @Slot(float)
    def _on_curve_dx(self, val: float) -> None:
        return self._curve_mode._on_curve_dx(val)

    def _curve_pick_color(self, ci: int) -> None:
        return self._curve_mode._curve_pick_color(ci)

    def _set_curve_color(self, ci: int, color: QColor) -> None:
        return self._curve_mode._set_curve_color(ci, color)

    @Slot(int)
    def _switch_mode(self, idx: int) -> None:
        self._stack.setCurrentIndex(idx)

        # Crop overlay + corner points
        if self._crop_overlay:
            self._crop_overlay.set_interactive(False)
            if idx == 0:
                self._crop_overlay.setVisible(True)
                if self._crop_confirmed:
                    self._crop_overlay.set_confirmed_style(self._opacity_slider.value())
                else:
                    self._crop_overlay.set_editing_style()
            else:
                # Keep the confirmed yellow work-area boundary visible through
                # calibration and digitisation, but remove its fill so it does
                # not tint source pixels used for precision picking.
                self._crop_overlay.setVisible(self._crop_confirmed)
                if self._crop_confirmed:
                    self._crop_overlay.set_confirmed_style(0)
        for pt in self._crop_corners:
            pt.setVisible(idx == 0 and self._crop_overlay is not None)

        self._grid_overlay.setVisible(idx in (1, 2) and self._calibration is not None)

        for pt in self._ref_points:
            pt.setVisible(idx == 1)

        # Hide everything first, then _refresh_data_visibility selectively shows
        for pts_list in self._series_points:
            for pt in pts_list:
                pt.setVisible(False)
        for pts_list in self._curve_points:
            for pt in pts_list:
                pt.setVisible(False)
        for path in self._curve_paths:
            path.setVisible(False)

        if idx == 2:
            self._refresh_data_visibility()

        self._precision_group.setVisible(
            idx == 2 or (idx == 1 and self._project.settings.magnifier_enabled)
        )
        self._data_precision_tools.setVisible(idx == 2)
        self._sync_active_point_for_mode()

    def _refresh_data_visibility(self) -> None:
        return self._data_mode._refresh_data_visibility()

    def _register_point(self, point: DraggablePoint) -> None:
        return self._precision_tools._register_point(point)

    def _point_context(self, point: DraggablePoint) -> tuple[str, object, int] | None:
        return self._precision_tools._point_context(point)

    def _is_data_point(self, point: DraggablePoint | None) -> bool:
        return self._precision_tools._is_data_point(point)

    def _activate_point(self, point: DraggablePoint) -> None:
        return self._precision_tools._activate_point(point)

    def _clear_active_point(self) -> None:
        return self._precision_tools._clear_active_point()

    def _refresh_active_loupe(self) -> None:
        return self._precision_tools._refresh_active_loupe()

    def _refresh_loupe_if_active(self, point: DraggablePoint | None) -> None:
        return self._precision_tools._refresh_loupe_if_active(point)

    def _sync_active_point_for_mode(self) -> None:
        return self._precision_tools._sync_active_point_for_mode()

    def _on_ref_row_selected(self, row: int) -> None:
        return self._precision_tools._on_ref_row_selected(row)

    def _on_data_row_selected(self, series: int, row: int) -> None:
        return self._precision_tools._on_data_row_selected(series, row)

    def _on_curve_row_selected(self, curve: int, row: int) -> None:
        return self._precision_tools._on_curve_row_selected(curve, row)

    def _pixel_center_coordinates(self, x: float, y: float) -> tuple[float, float]:
        return self._precision_tools._pixel_center_coordinates(x, y)

    def _pixel_magnet_applies_to(self, point: DraggablePoint) -> bool:
        return self._precision_tools._pixel_magnet_applies_to(point)

    def _redirect_position_to_pixel_center(
        self, point: DraggablePoint, x: float, y: float
    ) -> bool:
        return self._precision_tools._redirect_position_to_pixel_center(point, x, y)

    def _set_point_pos_without_pixel_magnet(
        self, point: DraggablePoint, position: QPointF
    ) -> None:
        return self._precision_tools._set_point_pos_without_pixel_magnet(point, position)

    def _snap_point_to_pixel_center(
        self, point: DraggablePoint, *, report: bool = True
    ) -> bool:
        return self._precision_tools._snap_point_to_pixel_center(point, report=report)

    @Slot(bool)
    def _on_pixel_magnet_toggled(self, enabled: bool) -> None:
        return self._precision_tools._on_pixel_magnet_toggled(enabled)

    def _snap_active_to_pixel_center(self) -> None:
        return self._precision_tools._snap_active_to_pixel_center()

    def _on_point_drag_finished(self, point: DraggablePoint) -> None:
        return self._precision_tools._on_point_drag_finished(point)

    def _propose_active_marker_center(self) -> None:
        return self._precision_tools._propose_active_marker_center()

    def _propose_marker_center(
        self,
        point: DraggablePoint,
        *,
        notify_failure: bool = False,
    ) -> bool:
        return self._precision_tools._propose_marker_center(point, notify_failure=notify_failure)

    def _update_loupe(self, sx: float, sy: float) -> None:
        return self._precision_tools._update_loupe(sx, sy)

    @Slot(float, float)
    def _on_canvas_click(self, sx: float, sy: float) -> None:
        return self._data_mode._on_canvas_click(sx, sy)

    def _is_within_crop(self, sx: float, sy: float) -> bool:
        return self._crop_mode._is_within_crop(sx, sy)

    def _crop_bounds_rectf(self) -> Optional[QRectF]:
        return self._crop_mode._crop_bounds_rectf()

    def _crop_auto(self) -> None:
        return self._crop_mode._crop_auto()

    def _crop_confirm(self) -> None:
        return self._crop_mode._crop_confirm()

    def _show_crop_overlay(self, x: float, y: float, w: float, h: float) -> None:
        return self._crop_mode._show_crop_overlay(x, y, w, h)

    @Slot(int)
    def _on_opacity_changed(self, value: int) -> None:
        return self._crop_mode._on_opacity_changed(value)

    def _sync_crop_corners_from_rect(self, x: float, y: float, w: float, h: float) -> None:
        return self._crop_mode._sync_crop_corners_from_rect(x, y, w, h)

    def _on_crop_corner_dragged(self, idx: int, nx: float, ny: float) -> None:
        return self._crop_mode._on_crop_corner_dragged(idx, nx, ny)

    @Slot(int, float, float)
    def _crop_table_changed(self, row: int, x: float, y: float) -> None:
        return self._crop_mode._crop_table_changed(row, x, y)

    @Slot(int, float, float)
    def _crop_key_move(self, row: int, dx: float, dy: float) -> None:
        return self._crop_mode._crop_key_move(row, dx, dy)

    def _rebuild_rect_from_corners(self) -> None:
        return self._crop_mode._rebuild_rect_from_corners()

    def _add_ref_point(self, sx: float, sy: float) -> None:
        return self._calibration_mode._add_ref_point(sx, sy)

    def _create_ref_point(
        self,
        sx: float,
        sy: float,
        *,
        axis: str,
        x_ref: float | None = None,
        y_ref: float | None = None,
    ) -> None:
        return self._calibration_mode._create_ref_point(sx, sy, axis=axis, x_ref=x_ref, y_ref=y_ref)

    def _on_ref_dragged(self, row: int, x: float, y: float) -> None:
        return self._calibration_mode._on_ref_dragged(row, x, y)

    @Slot(int, float, float)
    def _ref_table_wind_changed(self, row: int, x: float, y: float) -> None:
        return self._calibration_mode._ref_table_wind_changed(row, x, y)

    @Slot()
    def _on_ref_value_changed(self) -> None:
        return self._calibration_mode._on_ref_value_changed()

    def _on_calibration_input_changed(self, *_args) -> None:
        return self._calibration_mode._on_calibration_input_changed(*_args)

    @Slot(int, float, float)
    def _ref_key_move(self, row: int, dx: float, dy: float) -> None:
        return self._calibration_mode._ref_key_move(row, dx, dy)

    def _ref_delete_selected(self) -> None:
        return self._calibration_mode._ref_delete_selected()

    def _ref_clear_all(self) -> None:
        return self._calibration_mode._ref_clear_all()

    def _clear_reference_items(self) -> None:
        return self._calibration_mode._clear_reference_items()

    def _invalidate_calibration(self, reason: str) -> None:
        return self._calibration_mode._invalidate_calibration(reason)

    def _calibrate_from_frame(self) -> None:
        return self._calibration_mode._calibrate_from_frame()

    def _reconnect_ref_signals(self) -> None:
        return self._calibration_mode._reconnect_ref_signals()

    def _set_calibration_diagnostics_status(self) -> None:
        return self._calibration_mode._set_calibration_diagnostics_status()

    def _rebuild_calibration(self) -> None:
        return self._calibration_mode._rebuild_calibration()

    def _update_grid(self) -> None:
        return self._calibration_mode._update_grid()

    def _restore_data_point(self, sx: float, sy: float) -> None:
        return self._scatter_mode._restore_data_point(sx, sy)

    def _add_data_point(self, sx: float, sy: float) -> None:
        return self._scatter_mode._add_data_point(sx, sy)

    def _on_data_dragged(self, si: int, row: int, x: float, y: float) -> None:
        return self._scatter_mode._on_data_dragged(si, row, x, y)

    @Slot(int, float, float)
    def _data_table_wind_changed(self, si: int, row: int, x: float, y: float) -> None:
        return self._scatter_mode._data_table_wind_changed(si, row, x, y)

    @Slot(int, float, float)
    def _data_key_move(self, si: int, row: int, dx: float, dy: float) -> None:
        return self._scatter_mode._data_key_move(si, row, dx, dy)

    def _data_delete_selected(self) -> None:
        return self._scatter_mode._data_delete_selected()

    def _data_clear_series(self, si: int) -> None:
        return self._scatter_mode._data_clear_series(si)

    def _reconnect_data_signals(self, si: int) -> None:
        return self._scatter_mode._reconnect_data_signals(si)

    def _update_data_status(self) -> None:
        return self._scatter_mode._update_data_status()

    def _restore_curve_point(self, sx: float, sy: float) -> None:
        return self._curve_mode._restore_curve_point(sx, sy)

    def _add_curve_point(self, sx: float, sy: float) -> None:
        return self._curve_mode._add_curve_point(sx, sy)

    def _on_curve_dragged(self, ci: int, row: int, x: float, y: float) -> None:
        return self._curve_mode._on_curve_dragged(ci, row, x, y)

    @Slot(int, float, float)
    def _curve_table_wind_changed(self, ci: int, row: int, x: float, y: float) -> None:
        return self._curve_mode._curve_table_wind_changed(ci, row, x, y)

    @Slot(int, float, float)
    def _curve_key_move(self, ci: int, row: int, dx: float, dy: float) -> None:
        return self._curve_mode._curve_key_move(ci, row, dx, dy)

    def _curve_delete_selected(self) -> None:
        return self._curve_mode._curve_delete_selected()

    def _curve_clear_series(self, ci: int) -> None:
        return self._curve_mode._curve_clear_series(ci)

    def _reconnect_curve_signals(self, ci: int) -> None:
        return self._curve_mode._reconnect_curve_signals(ci)

    def _rebuild_curve_path(self, ci: int) -> None:
        return self._curve_mode._rebuild_curve_path(ci)

    def _update_curve_status(self) -> None:
        return self._curve_mode._update_curve_status()

    def _snap_to_x_grid(self, click_x: float) -> tuple[float, float | None]:
        return self._calibration_mode._snap_to_x_grid(click_x)

    def _snap_to_y_grid(self, click_y: float) -> tuple[float, float | None]:
        return self._calibration_mode._snap_to_y_grid(click_y)

    def _collect_series(self, *, sample_curves: bool) -> list[SeriesData]:
        return self._export_tools._collect_series(sample_curves=sample_curves)

    def sync_project_state(self) -> None:
        return self._session_tools.sync_project_state()

    def _do_export(self) -> None:
        return self._export_tools._do_export()

    def _update_all_point_bounds(self) -> None:
        bounds = self._crop_bounds_rectf()
        for pt in self._ref_points:
            pt.set_bounds(bounds)
        for pts_list in self._series_points:
            for pt in pts_list:
                pt.set_bounds(bounds)
        for pts_list in self._curve_points:
            for pt in pts_list:
                pt.set_bounds(bounds)

    # ------------------------------------------------------------------
    # safe helpers
    # ------------------------------------------------------------------

    def _safe_remove_point(self, pt: DraggablePoint) -> None:
        if pt is self._active_point:
            self._clear_active_point()
        try:
            pt.position_changed.disconnect()
        except RuntimeError:
            pass
        for signal in (pt.activated, pt.drag_finished):
            try:
                signal.disconnect()
            except (RuntimeError, TypeError):
                pass
        try:
            self._canvas.remove_overlay(pt)
        except RuntimeError:
            pass

    def _safe_hide_point(self, pt: DraggablePoint) -> None:
        try:
            pt.setVisible(False)
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # housekeeping
    # ------------------------------------------------------------------

    def _clear_all(self) -> None:
        return self._session_tools._clear_all()
