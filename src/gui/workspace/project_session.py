"""Project restoration, snapshot synchronisation and workspace reset."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from src.gui.overlays.point_overlay import DraggablePoint, PointShape
from src.gui.overlays.ref_grid_overlay import RefGridOverlay
from src.gui.workspace.colors import curve_series_color
from src.gui.workspace.contracts import HostBoundTool
from src.models.project_data import ProjectState
from src.models.types import CombinedMode, ScaleType, SeriesKind

class ProjectSessionTools(HostBoundTool):
    """Map serialisable project data to and from the live Qt workspace."""

    def set_project(self, project: ProjectState) -> None:
        self._project = project
        self._restoring = True
        try:
            self._load_style_defaults(project)
            for checkbox in (self._pixel_center_check, self._marker_auto_check):
                previous = checkbox.blockSignals(True)
                checkbox.setChecked(False)
                checkbox.blockSignals(previous)
            self._marker_radius_spin.setValue(12)
            self._clear_all()
            self._curve_dx = project.settings.curve_step_dx
            self._curve_dx_spin.setValue(self._curve_dx)
            self._combined_mode.setCurrentIndex({
                CombinedMode.UNION_X: 0,
                CombinedMode.UNIFORM_GRID: 1,
                CombinedMode.INTERPOLATION: 2,
            }.get(project.combined_mode, 0))

            calibration = project.calibration
            has_calibration = (
                calibration is not None
                and calibration.is_built
            )
            x_scale = calibration.x_axis.scale if has_calibration else project.settings.x_scale
            y_scale = calibration.y_axis.scale if has_calibration else project.settings.y_scale
            self._x_scale_combo.setCurrentIndex(1 if x_scale == ScaleType.LOG else 0)
            self._y_scale_combo.setCurrentIndex(1 if y_scale == ScaleType.LOG else 0)

            if project.crop_rect is not None:
                self._show_crop_overlay(*project.crop_rect)
                self._crop_confirmed = True
                if self._crop_overlay is not None:
                    self._crop_overlay.set_confirmed_style(self._opacity_slider.value())

            x0, y0, width, height = project.crop_rect or (0.0, 0.0, 1.0, 1.0)
            if project.calibration_anchors:
                for anchor_x, anchor_y, x_value, y_value, axis in project.calibration_anchors:
                    self._create_ref_point(
                        anchor_x, anchor_y, axis=axis, x_ref=x_value, y_ref=y_value
                    )
            elif has_calibration:
                for ref in calibration.x_axis.ref_points:
                    self._create_ref_point(
                        ref.pixel, y0 + height, axis="X", x_ref=ref.data_value
                    )
                for ref in calibration.y_axis.ref_points:
                    self._create_ref_point(
                        x0, ref.pixel, axis="Y", y_ref=ref.data_value
                    )

            if has_calibration:
                project.settings.x_scale = calibration.x_axis.scale
                project.settings.y_scale = calibration.y_axis.scale
                self._calibration = calibration
                self._update_grid()
                self._grid_overlay.setVisible(self._stack.currentIndex() in (1, 2))
                self._set_calibration_diagnostics_status()

            scatter_pixels = project.scatter_points_px
            curve_pixels = project.curve_points_px
            if not scatter_pixels and has_calibration:
                scatter_pixels = [
                    [calibration.data_to_pixel(point.x, point.y) for point in series.points]
                    for series in project.series if series.kind == SeriesKind.DISCRETE
                ]
            if not curve_pixels and has_calibration:
                curve_pixels = [
                    [calibration.data_to_pixel(point.x, point.y) for point in series.points]
                    for series in project.series if series.kind == SeriesKind.CONTINUOUS
                ]

            self._series_spin.setValue(max(1, len(scatter_pixels)))
            self._curve_series_spin.setValue(max(1, len(curve_pixels)))
            self._snap_free.setChecked(True)
            for si, points in enumerate(scatter_pixels):
                self._data_tabs.setCurrentIndex(si)
                for px, py in points:
                    self._restore_data_point(px, py)
            for ci, points in enumerate(curve_pixels):
                self._curve_tabs.setCurrentIndex(ci)
                for px, py in points:
                    self._restore_curve_point(px, py)
            self._restore_saved_styles(project)
            if scatter_pixels or curve_pixels:
                self._data_tabs.setCurrentIndex(0)
                self._curve_tabs.setCurrentIndex(0)
            if not has_calibration and project.series and not (scatter_pixels or curve_pixels):
                self._status.setText(
                    "Project contains data series but no valid calibration; points could not be restored."
                )
            elif not has_calibration and (scatter_pixels or curve_pixels):
                for table in [*self._series_tables, *self._curve_tables]:
                    table.clear_fig_values()
                self._ref_status.setText("Calibration draft restored — press Build before digitising/exporting.")
                self._ref_status.setStyleSheet("color: #ffcc66;")
                self._status.setText(
                    "Draft pixel points restored. Rebuild calibration to recover data coordinates."
                )
            if not has_calibration and project.calibration_anchors:
                self._ref_status.setText("Calibration draft restored — press Build to validate it.")
                self._ref_status.setStyleSheet("color: #ffcc66;")
            self.apply_settings()
        finally:
            self._restoring = False
            self._switch_mode(self._stack.currentIndex())

    def _load_style_defaults(self, project: ProjectState) -> None:
        scatter = getattr(project, "scatter_default_point_style", ("CIRCLE", 5.0))
        curve = getattr(project, "curve_default_point_style", ("CIRCLE", 4.0))
        if not isinstance(scatter, (tuple, list)):
            scatter = ("CIRCLE", 5.0)
        if not isinstance(curve, (tuple, list)):
            curve = ("CIRCLE", 4.0)
        self._current_shape = self._point_shape_from_name(
            scatter[0] if len(scatter) >= 1 else "CIRCLE", PointShape.CIRCLE
        )
        try:
            self._current_size = max(1.0, min(50.0, float(scatter[1])))
            if not math.isfinite(self._current_size):
                raise ValueError("non-finite point size")
        except (IndexError, TypeError, ValueError):
            self._current_size = DraggablePoint.DEFAULT_SIZE
        self._curve_point_shape = self._point_shape_from_name(
            curve[0] if len(curve) >= 1 else "CIRCLE", PointShape.CIRCLE
        )
        try:
            self._curve_point_size = max(1.0, min(50.0, float(curve[1])))
            if not math.isfinite(self._curve_point_size):
                raise ValueError("non-finite point size")
        except (IndexError, TypeError, ValueError):
            self._curve_point_size = 4.0
        self._scatter_active_fill_opacity = self._normalise_active_fill_opacity(
            getattr(project, "scatter_active_fill_opacity", 15)
        )
        self._curve_active_fill_opacity = self._normalise_active_fill_opacity(
            getattr(project, "curve_active_fill_opacity", 15)
        )
        try:
            self._curve_thickness = max(
                0.5, min(50.0, float(getattr(project, "curve_default_thickness", 2.0)))
            )
            if not math.isfinite(self._curve_thickness):
                raise ValueError("non-finite curve thickness")
        except (TypeError, ValueError):
            self._curve_thickness = 2.0

        previous = self._curve_size_spin.blockSignals(True)
        self._curve_size_spin.setValue(self._curve_point_size)
        self._curve_size_spin.blockSignals(previous)
        previous = self._curve_thick_spin.blockSignals(True)
        self._curve_thick_spin.setValue(self._curve_thickness)
        self._curve_thick_spin.blockSignals(previous)

    def _restore_saved_styles(self, project: ProjectState) -> None:
        for series, styles in zip(
            self._series_points, getattr(project, "scatter_point_styles", [])
        ):
            for point, style in zip(series, styles):
                if len(style) < 2:
                    continue
                point.set_point_shape(
                    self._point_shape_from_name(style[0], self._current_shape)
                )
                try:
                    size = float(style[1])
                    if math.isfinite(size):
                        point.set_point_size(min(50.0, size))
                except (TypeError, ValueError):
                    pass

        for curve, styles in zip(
            self._curve_points, getattr(project, "curve_point_styles", [])
        ):
            for point, style in zip(curve, styles):
                if len(style) < 2:
                    continue
                point.set_point_shape(
                    self._point_shape_from_name(style[0], self._curve_point_shape)
                )
                try:
                    size = float(style[1])
                    if math.isfinite(size):
                        point.set_point_size(min(50.0, size))
                except (TypeError, ValueError):
                    pass

        valid_pen_styles = Qt.PenStyle.__members__
        for ci, style in enumerate(
            getattr(project, "curve_visual_styles", [])
        ):
            if ci >= len(self._curve_paths) or len(style) < 3:
                break
            color = QColor(str(style[0]))
            if color.isValid():
                self._set_curve_color(ci, color)
            try:
                thickness = float(style[1])
                if math.isfinite(thickness):
                    self._curve_paths[ci].set_thickness(min(50.0, thickness))
            except (TypeError, ValueError):
                pass
            try:
                pen_name = str(style[2])
                if pen_name in valid_pen_styles:
                    self._curve_paths[ci].set_line_style(valid_pen_styles[pen_name])
            except (TypeError, ValueError, KeyError):
                pass

    def sync_project_state(self) -> None:
        """Copy the live GUI state to the serialisable project model."""
        if self._crop_overlay is not None and not self._crop_confirmed:
            raise ValueError("Confirm the modified plot boundaries before saving the project")
        self._project.calibration_anchors = list(self._ref_table.get_ref_data())
        self._project.scatter_points_px = [
            [(point.pos().x(), point.pos().y()) for point in points]
            for points in self._series_points
        ]
        self._project.curve_points_px = [
            [(point.pos().x(), point.pos().y()) for point in points]
            for points in self._curve_points
        ]
        self._project.scatter_point_styles = [
            [(point.point_shape().name, point.point_size()) for point in points]
            for points in self._series_points
        ]
        self._project.curve_point_styles = [
            [(point.point_shape().name, point.point_size()) for point in points]
            for points in self._curve_points
        ]
        self._project.curve_visual_styles = [
            (
                path.color().name(QColor.NameFormat.HexArgb),
                path.thickness(),
                path.line_style().name,
            )
            for path in self._curve_paths
        ]
        self._project.scatter_default_point_style = (
            self._current_shape.name,
            self._current_size,
        )
        self._project.curve_default_point_style = (
            self._curve_point_shape.name,
            self._curve_point_size,
        )
        self._project.scatter_active_fill_opacity = (
            self._scatter_active_fill_opacity
        )
        self._project.curve_active_fill_opacity = self._curve_active_fill_opacity
        self._project.curve_default_thickness = self._curve_thickness
        has_points = any(self._series_points) or any(self._curve_points)
        if has_points and self._calibration is not None:
            self._project.series = self._collect_series(sample_curves=False)
        else:
            self._project.series.clear()
        self._project.settings.curve_step_dx = self._curve_dx
        self._project.combined_mode = {
            0: CombinedMode.UNION_X,
            1: CombinedMode.UNIFORM_GRID,
            2: CombinedMode.INTERPOLATION,
        }.get(self._combined_mode.currentIndex(), CombinedMode.UNION_X)

    def _clear_all(self) -> None:
        # Ref points
        for pt in self._ref_points:
            self._safe_remove_point(pt)
        self._ref_points.clear()

        # Scatter points
        for pts_list in self._series_points:
            for pt in pts_list:
                self._safe_remove_point(pt)
        self._series_points = []
        self._series_tables.clear()
        while self._data_tabs.count():
            self._data_tabs.removeTab(0)
        self._series_spin.blockSignals(True)
        self._series_spin.setValue(1)
        self._series_spin.blockSignals(False)
        self._rebuild_series_tabs(1)

        # Curve points and paths
        for pts_list in self._curve_points:
            for pt in pts_list:
                self._safe_remove_point(pt)
        self._curve_points = []
        self._curve_tables.clear()
        for path in self._curve_paths:
            try:
                self._canvas.remove_overlay(path)
            except Exception:
                pass
        self._curve_paths.clear()
        self._curve_colors = [curve_series_color(0)]
        self._curve_errors.clear()
        while self._curve_tabs.count():
            self._curve_tabs.removeTab(0)
        self._curve_series_spin.blockSignals(True)
        self._curve_series_spin.setValue(1)
        self._curve_series_spin.blockSignals(False)
        self._rebuild_curve_tabs(1)

        self._ref_table.setRowCount(0)
        self._calibration = None

        try:
            self._grid_overlay.setVisible(False)
        except RuntimeError:
            pass
        try:
            self._canvas.remove_overlay(self._grid_overlay)
        except Exception:
            pass
        self._grid_overlay = RefGridOverlay()
        self._canvas.add_overlay(self._grid_overlay)
        self._grid_overlay.setVisible(False)

        for pt in self._crop_corners:
            self._safe_remove_point(pt)
        self._crop_corners.clear()

        if self._crop_overlay:
            try:
                self._canvas.remove_overlay(self._crop_overlay)
            except Exception:
                pass
            self._crop_overlay = None
        self._crop_confirmed = False
