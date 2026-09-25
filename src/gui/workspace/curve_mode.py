"""Curve-mode controls, styling, control points and preview interpolation."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from src.core.curve_interpolation import CurveInterpolationError, CurveInterpolator
from src.gui.dialogs.curve_style import CurveStyleDialog
from src.gui.dialogs.point_style import PointStyleDialog
from src.gui.overlays.curve_path_overlay import CurvePathOverlay
from src.gui.overlays.point_overlay import DraggablePoint, PointShape
from src.gui.tables.data import DataPointTable
from src.gui.workspace.colors import curve_series_color
from src.gui.workspace.contracts import HostBoundTool


class CurveMode(HostBoundTool):
    """Own Curve controls, styling, control points and PCHIP preview state."""

    def _build_curve_subpage(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        curve_guide = QLabel(
            "Curve represents a single-valued y(x). Control X values must be distinct. "
            "Preview and export use the same shape-preserving PCHIP interpolation; "
            "log axes are interpolated in log space."
        )
        curve_guide.setWordWrap(True)
        lay.addWidget(curve_guide)

        style_row = QHBoxLayout()
        btn_point_style = QPushButton("Style Points")
        btn_point_style.setToolTip(
            "Set shape/size for Curve points and the translucent fill of the active point."
        )
        btn_point_style.clicked.connect(self._open_curve_point_style_dialog)
        style_row.addWidget(btn_point_style)
        btn_curve_style = QPushButton("Curve Style")
        btn_curve_style.setToolTip(
            "Set colour, thickness and line pattern for the active curve."
        )
        btn_curve_style.clicked.connect(self._open_curve_style_dialog)
        style_row.addWidget(btn_curve_style)
        style_row.addStretch()
        lay.addLayout(style_row)

        # Controls row
        ctrl_form = QFormLayout()

        self._curve_size_spin = QDoubleSpinBox()
        self._curve_size_spin.setRange(1.0, 50.0)
        self._curve_size_spin.setValue(self._curve_point_size)
        self._curve_size_spin.setSingleStep(0.5)
        self._curve_size_spin.setDecimals(1)
        self._curve_size_spin.valueChanged.connect(self._on_curve_point_size)
        ctrl_form.addRow("Default point size:", self._curve_size_spin)

        self._curve_thick_spin = QDoubleSpinBox()
        self._curve_thick_spin.setRange(0.5, 50.0)
        self._curve_thick_spin.setValue(self._curve_thickness)
        self._curve_thick_spin.setSingleStep(0.5)
        self._curve_thick_spin.setDecimals(1)
        self._curve_thick_spin.valueChanged.connect(self._on_curve_thickness)
        ctrl_form.addRow("Set all curve thicknesses:", self._curve_thick_spin)

        self._curve_dx_spin = QDoubleSpinBox()
        self._curve_dx_spin.setRange(0.001, 10000.0)
        self._curve_dx_spin.setValue(self._curve_dx)
        self._curve_dx_spin.setSingleStep(0.01)
        self._curve_dx_spin.setDecimals(4)
        self._curve_dx_spin.valueChanged.connect(self._on_curve_dx)
        ctrl_form.addRow("Export dx:", self._curve_dx_spin)

        lay.addLayout(ctrl_form)

        # Series count
        cseries_row = QHBoxLayout()
        cseries_row.addWidget(QLabel("Curves count:"))
        self._curve_series_spin = QSpinBox()
        self._curve_series_spin.setRange(1, 20)
        self._curve_series_spin.setValue(1)
        self._curve_series_spin.valueChanged.connect(self._rebuild_curve_tabs)
        cseries_row.addWidget(self._curve_series_spin)
        lay.addLayout(cseries_row)

        self._curve_tabs = QTabWidget()
        self._curve_tabs.currentChanged.connect(self._on_curve_tab_changed)
        lay.addWidget(self._curve_tabs, stretch=1)

        btn_del = QPushButton("Delete selected control point")
        btn_del.clicked.connect(self._curve_delete_selected)
        lay.addWidget(btn_del)

        self._curve_status = QLabel("")
        lay.addWidget(self._curve_status)

        self._rebuild_curve_tabs(1)
        self._data_submode_stack.addWidget(page)

    def _open_curve_point_style_dialog(self) -> None:
        if self._curve_point_style_dialog is None:
            self._curve_point_style_dialog = PointStyleDialog(self._host)
            self._curve_point_style_dialog.setWindowTitle("Curve Point Style")
            self._curve_point_style_dialog.shape_changed.connect(
                self._on_curve_point_style_shape
            )
            self._curve_point_style_dialog.size_changed.connect(
                self._on_curve_point_style_size
            )
            self._curve_point_style_dialog.active_fill_opacity_changed.connect(
                self._on_curve_active_fill_opacity
            )
        self._curve_point_style_dialog.set_shape(self._curve_point_shape)
        self._curve_point_style_dialog.set_size(self._curve_point_size)
        self._curve_point_style_dialog.set_active_fill_opacity(
            self._curve_active_fill_opacity
        )
        self._curve_point_style_dialog.show()
        self._curve_point_style_dialog.raise_()
        self._curve_point_style_dialog.activateWindow()

    def _on_curve_point_style_shape(self, shape: PointShape) -> None:
        self._curve_point_shape = shape
        self._apply_curve_point_style_to_selected(shape=shape)

    def _on_curve_point_style_size(self, size: float) -> None:
        self._curve_point_size = size
        previous = self._curve_size_spin.blockSignals(True)
        self._curve_size_spin.setValue(size)
        self._curve_size_spin.blockSignals(previous)
        self._apply_curve_point_style_to_selected(size=size)

    def _on_curve_active_fill_opacity(self, percent: int) -> None:
        self._curve_active_fill_opacity = self._normalise_active_fill_opacity(
            percent
        )
        for points in self._curve_points:
            for point in points:
                point.set_active_fill_opacity(self._curve_active_fill_opacity)

    def _apply_curve_point_style_to_selected(
        self,
        *,
        shape: PointShape | None = None,
        size: float | None = None,
    ) -> None:
        ci = self._active_curve_index()
        if ci >= len(self._curve_tables) or ci >= len(self._curve_points):
            return
        rows = self._curve_tables[ci].selected_rows()
        for row in rows:
            if 0 <= row < len(self._curve_points[ci]):
                point = self._curve_points[ci][row]
                if shape is not None:
                    point.set_point_shape(shape)
                if size is not None:
                    point.set_point_size(size)

    def _open_curve_style_dialog(self) -> None:
        ci = self._active_curve_index()
        if ci >= len(self._curve_paths):
            return
        if self._curve_style_dialog is None:
            self._curve_style_dialog = CurveStyleDialog(self._host)
            self._curve_style_dialog.color_changed.connect(self._on_curve_style_color)
            self._curve_style_dialog.thickness_changed.connect(
                self._on_curve_style_thickness
            )
            self._curve_style_dialog.line_style_changed.connect(
                self._on_curve_style_line_pattern
            )
        self._sync_curve_style_dialog()
        self._curve_style_dialog.show()
        self._curve_style_dialog.raise_()
        self._curve_style_dialog.activateWindow()

    def _sync_curve_style_dialog(self) -> None:
        if self._curve_style_dialog is None:
            return
        ci = self._active_curve_index()
        if ci >= len(self._curve_paths):
            return
        path = self._curve_paths[ci]
        previous = self._curve_style_dialog.blockSignals(True)
        self._curve_style_dialog.set_color(path.color())
        self._curve_style_dialog.set_thickness(path.thickness())
        self._curve_style_dialog.set_line_style(path.line_style())
        self._curve_style_dialog.blockSignals(previous)
        self._curve_style_dialog.setWindowTitle(f"Curve {ci + 1} Style")

    def _on_curve_style_color(self, color: QColor) -> None:
        self._set_curve_color(self._active_curve_index(), color)

    def _on_curve_style_thickness(self, thickness: float) -> None:
        ci = self._active_curve_index()
        if ci < len(self._curve_paths):
            self._curve_paths[ci].set_thickness(thickness)

    def _on_curve_style_line_pattern(self, style: Qt.PenStyle) -> None:
        ci = self._active_curve_index()
        if ci < len(self._curve_paths):
            self._curve_paths[ci].set_line_style(style)

    # ------------------------------------------------------------------
    # scatter series tabs management
    # ------------------------------------------------------------------

    def _make_curve_tab_widget(self, ci: int) -> QWidget:
        container = QWidget()
        vlay = QVBoxLayout(container)
        vlay.setContentsMargins(0, 0, 0, 0)

        table = DataPointTable()
        self._configure_table(table)
        table.point_wind_changed.connect(
            lambda row, x, y, s=ci: self._curve_table_wind_changed(s, row, x, y)
        )
        table.key_move.connect(
            lambda row, dx, dy, s=ci: self._curve_key_move(s, row, dx, dy)
        )
        table.currentCellChanged.connect(
            lambda row, _column, _old_row, _old_column, s=ci:
                self._on_curve_row_selected(s, row)
        )
        vlay.addWidget(table, stretch=1)

        btn_row = QHBoxLayout()

        btn_sel = QPushButton("Select all")
        btn_sel.clicked.connect(lambda checked=False, t=table: t.select_all_rows())
        btn_row.addWidget(btn_sel)

        btn_color = QPushButton("Color")
        btn_color.clicked.connect(lambda checked=False, s=ci: self._curve_pick_color(s))
        btn_row.addWidget(btn_color)

        btn_clear = QPushButton("Clear curve")
        btn_clear.clicked.connect(lambda checked=False, s=ci: self._curve_clear_series(s))
        btn_row.addWidget(btn_clear)

        vlay.addLayout(btn_row)

        container._table = table  # type: ignore[attr-defined]
        return container

    def _rebuild_curve_tabs(self, n: int) -> None:
        while self._curve_tabs.count() > n:
            idx = self._curve_tabs.count() - 1
            self._curve_tabs.removeTab(idx)
            if idx < len(self._curve_tables):
                self._curve_tables.pop(idx)
            if idx < len(self._curve_points):
                for pt in self._curve_points[idx]:
                    self._safe_remove_point(pt)
                self._curve_points.pop(idx)
            if idx < len(self._curve_paths):
                path = self._curve_paths.pop(idx)
                try:
                    self._canvas.remove_overlay(path)
                except Exception:
                    pass
            if idx < len(self._curve_colors):
                self._curve_colors.pop(idx)
            self._curve_errors.pop(idx, None)

        while self._curve_tabs.count() < n:
            idx = self._curve_tabs.count()
            container = self._make_curve_tab_widget(idx)
            self._curve_tables.append(container._table)  # type: ignore[attr-defined]
            self._curve_points.append([])

            color = curve_series_color(idx)
            if idx < len(self._curve_colors):
                self._curve_colors[idx] = color
            else:
                self._curve_colors.append(color)

            path = CurvePathOverlay(color=color, thickness=self._curve_thickness)
            self._canvas.add_overlay(path)
            vis = (self._stack.currentIndex() == 2
                   and not self._is_scatter_mode()
                   and idx == self._active_curve_index())
            path.setVisible(vis)
            self._curve_paths.append(path)

            self._curve_tabs.addTab(container, f"Curve {idx + 1}")

    def _active_curve_index(self) -> int:
        return max(0, self._curve_tabs.currentIndex())

    def _on_curve_tab_changed(self, idx: int) -> None:
        self._sync_curve_style_dialog()
        if self._stack.currentIndex() == 2 and not self._is_scatter_mode():
            self._refresh_data_visibility()
            self._sync_active_point_for_mode()

    # ------------------------------------------------------------------
    # curve controls
    # ------------------------------------------------------------------

    def _on_curve_point_size(self, val: float) -> None:
        self._curve_point_size = val

    def _on_curve_thickness(self, val: float) -> None:
        self._curve_thickness = val
        for path in self._curve_paths:
            path.set_thickness(val)

    def _on_curve_dx(self, val: float) -> None:
        self._curve_dx = val

    def _curve_pick_color(self, ci: int) -> None:
        old = self._curve_colors[ci] if ci < len(self._curve_colors) else QColor(255, 80, 80)
        color = QColorDialog.getColor(old, self._host, "Curve Color")
        if not color.isValid():
            return
        self._set_curve_color(ci, color)

    def _set_curve_color(self, ci: int, color: QColor) -> None:
        if ci < 0 or not color.isValid():
            return
        if ci < len(self._curve_colors):
            self._curve_colors[ci] = QColor(color)
        if ci < len(self._curve_paths):
            self._curve_paths[ci].set_color(color)
        if ci < len(self._curve_points):
            for pt in self._curve_points[ci]:
                pt.set_color(color)
        if ci < len(self._curve_tables):
            for row in range(self._curve_tables[ci].rowCount()):
                self._curve_tables[ci].set_row_color(row, color)

    # ------------------------------------------------------------------
    # mode switching
    # ------------------------------------------------------------------

    def _restore_curve_point(self, sx: float, sy: float) -> None:
        if self._calibration is not None:
            self._add_curve_point(sx, sy)
            return
        ci = self._active_curve_index()
        if ci >= len(self._curve_tables):
            return
        color = self._curve_colors[ci]
        point = DraggablePoint(sx, sy, color=color)
        self._configure_point(point)
        self._register_point(point)
        point.set_bounds(self._crop_bounds_rectf())
        point.set_point_size(self._curve_point_size)
        point.set_point_shape(self._curve_point_shape)
        point.set_active_fill_opacity(self._curve_active_fill_opacity)
        self._canvas.add_overlay(point)
        self._curve_points[ci].append(point)
        table = self._curve_tables[ci]
        row = table.add_row(sx, sy, 0.0, 0.0, color=color)
        table.clear_fig_values()
        point.position_changed.connect(
            lambda x, y, s=ci, r=row: self._on_curve_dragged(s, r, x, y)
        )
        table.selectRow(row)
        self._activate_point(point)
        self._rebuild_curve_path(ci)
        self._update_curve_status()

    def _add_curve_point(self, sx: float, sy: float) -> None:
        if self._calibration is None:
            QMessageBox.warning(self._host, "Data", "Build calibration first (Ref Points tab).")
            return

        ci = self._active_curve_index()
        if ci >= len(self._curve_tables):
            return

        if self._pixel_center_check.isChecked() and not self._restoring:
            sx, sy = self._pixel_center_coordinates(sx, sy)

        try:
            xf, yf = self._calibration.pixel_to_data(sx, sy)
        except Exception as exc:
            QMessageBox.warning(self._host, "Curve", f"Cannot convert this control point: {exc}")
            return

        idx = len(self._curve_points[ci])
        color = self._curve_colors[ci] if ci < len(self._curve_colors) else QColor(255, 80, 80)
        pt = DraggablePoint(sx, sy, color=color)
        self._configure_point(pt)
        self._register_point(pt)
        pt.set_bounds(self._crop_bounds_rectf())
        pt.set_point_size(self._curve_point_size)
        pt.set_point_shape(self._curve_point_shape)
        pt.set_active_fill_opacity(self._curve_active_fill_opacity)
        self._canvas.add_overlay(pt)
        self._curve_points[ci].append(pt)

        table = self._curve_tables[ci]
        row = table.add_row(sx, sy, xf, yf, color=color)
        pt.position_changed.connect(
            lambda x, y, s=ci, r=row: self._on_curve_dragged(s, r, x, y)
        )
        table.selectRow(row)
        self._activate_point(pt)
        self._rebuild_curve_path(ci)
        self._update_curve_status()
        if self._marker_auto_check.isChecked() and not self._restoring:
            self._propose_marker_center(pt)

    def _on_curve_dragged(self, ci: int, row: int, x: float, y: float) -> None:
        point = None
        if 0 <= ci < len(self._curve_points) and 0 <= row < len(self._curve_points[ci]):
            point = self._curve_points[ci][row]
            if self._redirect_position_to_pixel_center(point, x, y):
                return
        if ci < len(self._curve_tables):
            self._curve_tables[ci].update_wind(row, x, y)
            if self._calibration:
                try:
                    xf = self._calibration.x_axis.pixel_to_data(x)
                    yf = self._calibration.y_axis.pixel_to_data(y)
                    self._curve_tables[ci].update_fig(row, xf, yf)
                except Exception:
                    pass
        self._refresh_loupe_if_active(point)
        self._rebuild_curve_path(ci)
        self._update_curve_status()

    def _curve_table_wind_changed(self, ci: int, row: int, x: float, y: float) -> None:
        if 0 <= ci < len(self._curve_points) and 0 <= row < len(self._curve_points[ci]):
            point = self._curve_points[ci][row]
            point.set_pos_silent(x, y)
            if self._pixel_magnet_applies_to(point):
                self._snap_point_to_pixel_center(point, report=False)
            actual = point.pos()
            x, y = actual.x(), actual.y()
            if ci < len(self._curve_tables):
                self._curve_tables[ci].update_wind(row, x, y)
            self._refresh_loupe_if_active(point)
        if self._calibration:
            try:
                xf = self._calibration.x_axis.pixel_to_data(x)
                yf = self._calibration.y_axis.pixel_to_data(y)
                if ci < len(self._curve_tables):
                    self._curve_tables[ci].update_fig(row, xf, yf)
            except Exception:
                pass
        self._rebuild_curve_path(ci)
        self._update_curve_status()

    def _curve_key_move(self, ci: int, row: int, dx: float, dy: float) -> None:
        if 0 <= ci < len(self._curve_points) and 0 <= row < len(self._curve_points[ci]):
            self._curve_points[ci][row].moveBy(dx, dy)
            self._rebuild_curve_path(ci)
            self._update_curve_status()

    def _curve_delete_selected(self) -> None:
        ci = self._active_curve_index()
        if ci >= len(self._curve_tables):
            return
        table = self._curve_tables[ci]
        row = table.remove_selected_row()
        if row is not None and 0 <= row < len(self._curve_points[ci]):
            pt = self._curve_points[ci].pop(row)
            self._safe_remove_point(pt)
            self._reconnect_curve_signals(ci)
            self._rebuild_curve_path(ci)
            self._update_curve_status()
            self._sync_active_point_for_mode()

    def _curve_clear_series(self, ci: int) -> None:
        if ci >= len(self._curve_points):
            return
        for pt in self._curve_points[ci]:
            self._safe_remove_point(pt)
        self._curve_points[ci].clear()
        self._curve_errors.pop(ci, None)
        if ci < len(self._curve_tables):
            self._curve_tables[ci].setRowCount(0)
        self._rebuild_curve_path(ci)
        self._update_curve_status()
        self._sync_active_point_for_mode()

    def _reconnect_curve_signals(self, ci: int) -> None:
        if ci >= len(self._curve_points):
            return
        for i, pt in enumerate(self._curve_points[ci]):
            try:
                pt.position_changed.disconnect()
            except RuntimeError:
                pass
            pt.position_changed.connect(
                lambda x, y, s=ci, r=i: self._on_curve_dragged(s, r, x, y)
            )

    def _rebuild_curve_path(self, ci: int) -> None:
        if ci >= len(self._curve_paths):
            return
        pts = self._curve_points[ci] if ci < len(self._curve_points) else []
        if len(pts) < 2:
            self._curve_errors.pop(ci, None)
            self._curve_paths[ci].update_from_polyline([pt.pos() for pt in pts])
            return
        if self._calibration is None:
            self._curve_errors[ci] = "calibration is stale"
            self._curve_paths[ci].update_from_polyline([])
            return

        try:
            controls = [self._calibration.pixel_to_data(pt.pos().x(), pt.pos().y()) for pt in pts]
            xs = [point[0] for point in controls]
            ys = [point[1] for point in controls]
            engine = CurveInterpolator(
                xs, ys,
                self._calibration.x_axis.scale,
                self._calibration.y_axis.scale,
            )
            preview_x, preview_y = engine.sample_for_preview(512)
            qpoints = [
                QPointF(*self._calibration.data_to_pixel(float(x), float(y)))
                for x, y in zip(preview_x, preview_y)
            ]
            self._curve_paths[ci].update_from_polyline(qpoints)
            self._curve_errors.pop(ci, None)
        except (CurveInterpolationError, ValueError, RuntimeError) as exc:
            self._curve_errors[ci] = str(exc)
            self._curve_paths[ci].update_from_polyline([])

    def _update_curve_status(self) -> None:
        total = sum(len(pts) for pts in self._curve_points)
        text = f"{total} control point(s) across {len(self._curve_points)} curve(s)"
        ci = self._active_curve_index()
        if ci in self._curve_errors:
            text += f"\nCurve {ci + 1} is not exportable: {self._curve_errors[ci]}"
            self._curve_status.setStyleSheet("color: #ff6666;")
        else:
            self._curve_status.setStyleSheet("")
        self._curve_status.setText(text)

    # ------------------------------------------------------------------
    # grid snap helpers
    # ------------------------------------------------------------------
