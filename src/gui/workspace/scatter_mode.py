"""Scatter-mode controls, series tabs and point editing."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QRadioButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from src.gui.overlays.point_overlay import DragConstraint, DraggablePoint, PointShape
from src.gui.dialogs.point_style import PointStyleDialog
from src.gui.tables.colors import point_color
from src.gui.tables.data import DataPointTable
from src.gui.workspace.contracts import HostBoundTool


class ScatterMode(HostBoundTool):
    """Own Scatter controls, series collections and point/table synchronisation."""

    def _build_scatter_subpage(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        scatter_guide = QLabel(
            "Scatter stores independent marker centres. Zoom until individual pixels are visible; "
            "put the point crosshair at the marker's geometric centre."
        )
        scatter_guide.setWordWrap(True)
        lay.addWidget(scatter_guide)

        snap_row = QGridLayout()
        self._snap_free = QRadioButton("Free")
        self._snap_x = QRadioButton("Lock X")
        self._snap_y = QRadioButton("Lock Y")
        self._snap_xy = QRadioButton("Lock X+Y")
        self._snap_free.setChecked(True)
        for rb in (self._snap_x, self._snap_y, self._snap_xy):
            rb.setToolTip("Snap to a nearby calibration anchor within the distance below.")
        for index, rb in enumerate(
            (self._snap_free, self._snap_x, self._snap_y, self._snap_xy)
        ):
            snap_row.addWidget(rb, index // 2, index % 2)
        lay.addLayout(snap_row)

        snap_options = QHBoxLayout()
        snap_options.addWidget(QLabel("Max anchor distance (px):"))
        self._snap_threshold_spin = QDoubleSpinBox()
        self._snap_threshold_spin.setRange(0.5, 1000.0)
        self._snap_threshold_spin.setValue(12.0)
        self._snap_threshold_spin.setDecimals(1)
        self._snap_threshold_spin.setToolTip(
            "No snap is applied when the nearest calibration anchor is farther away."
        )
        snap_options.addWidget(self._snap_threshold_spin)
        lay.addLayout(snap_options)

        tool_row = QHBoxLayout()
        btn_style = QPushButton("Style Points")
        btn_style.setToolTip(
            "Set shape/size for Scatter points and the translucent fill of the active point."
        )
        btn_style.clicked.connect(self._open_style_dialog)
        tool_row.addWidget(btn_style)
        tool_row.addStretch()
        lay.addLayout(tool_row)

        series_row = QHBoxLayout()
        series_row.addWidget(QLabel("Series count:"))
        self._series_spin = QSpinBox()
        self._series_spin.setRange(1, 20)
        self._series_spin.setValue(1)
        self._series_spin.valueChanged.connect(self._rebuild_series_tabs)
        series_row.addWidget(self._series_spin)
        lay.addLayout(series_row)

        self._data_tabs = QTabWidget()
        self._data_tabs.currentChanged.connect(self._on_series_tab_changed)
        lay.addWidget(self._data_tabs, stretch=1)

        btn_del = QPushButton("Delete selected data point")
        btn_del.clicked.connect(self._data_delete_selected)
        lay.addWidget(btn_del)

        self._data_status = QLabel("")
        lay.addWidget(self._data_status)

        self._rebuild_series_tabs(1)
        self._data_submode_stack.addWidget(page)

    def _open_style_dialog(self) -> None:
        if self._style_dialog is None:
            self._style_dialog = PointStyleDialog(self._host)
            self._style_dialog.shape_changed.connect(self._on_style_shape)
            self._style_dialog.size_changed.connect(self._on_style_size)
            self._style_dialog.active_fill_opacity_changed.connect(
                self._on_scatter_active_fill_opacity
            )
        self._style_dialog.set_shape(self._current_shape)
        self._style_dialog.set_size(self._current_size)
        self._style_dialog.set_active_fill_opacity(
            self._scatter_active_fill_opacity
        )
        self._style_dialog.show()
        self._style_dialog.raise_()
        self._style_dialog.activateWindow()

    def _on_style_shape(self, shape: PointShape) -> None:
        self._current_shape = shape
        self._apply_style_to_selected()

    def _on_style_size(self, size: float) -> None:
        self._current_size = size
        self._apply_style_to_selected()

    def _on_scatter_active_fill_opacity(self, percent: int) -> None:
        self._scatter_active_fill_opacity = self._normalise_active_fill_opacity(
            percent
        )
        for points in self._series_points:
            for point in points:
                point.set_active_fill_opacity(self._scatter_active_fill_opacity)

    def _apply_style_to_selected(self) -> None:
        si = self._active_series_index()
        if si >= len(self._series_tables):
            return
        table = self._series_tables[si]
        rows = table.selected_rows()
        if not rows:
            return
        pts = self._series_points[si] if si < len(self._series_points) else []
        for r in rows:
            if 0 <= r < len(pts):
                pts[r].set_point_shape(self._current_shape)
                pts[r].set_point_size(self._current_size)

    def _make_series_tab_widget(self, si: int) -> QWidget:
        container = QWidget()
        vlay = QVBoxLayout(container)
        vlay.setContentsMargins(0, 0, 0, 0)

        table = DataPointTable()
        self._configure_table(table)
        table.point_wind_changed.connect(
            lambda row, x, y, s=si: self._data_table_wind_changed(s, row, x, y)
        )
        table.key_move.connect(
            lambda row, dx, dy, s=si: self._data_key_move(s, row, dx, dy)
        )
        table.currentCellChanged.connect(
            lambda row, _column, _old_row, _old_column, s=si:
                self._on_data_row_selected(s, row)
        )
        vlay.addWidget(table, stretch=1)

        btn_row = QHBoxLayout()
        btn_sel = QPushButton("Select all")
        btn_sel.clicked.connect(lambda checked=False, t=table: t.select_all_rows())
        btn_row.addWidget(btn_sel)

        btn_clear = QPushButton("Clear all points")
        btn_clear.clicked.connect(lambda checked=False, s=si: self._data_clear_series(s))
        btn_row.addWidget(btn_clear)
        vlay.addLayout(btn_row)

        container._table = table  # type: ignore[attr-defined]
        return container

    def _rebuild_series_tabs(self, n: int) -> None:
        while self._data_tabs.count() > n:
            idx = self._data_tabs.count() - 1
            self._data_tabs.removeTab(idx)
            if idx < len(self._series_tables):
                self._series_tables.pop(idx)
            if idx < len(self._series_points):
                for pt in self._series_points[idx]:
                    self._safe_remove_point(pt)
                self._series_points.pop(idx)

        while self._data_tabs.count() < n:
            idx = self._data_tabs.count()
            container = self._make_series_tab_widget(idx)
            self._series_tables.append(container._table)  # type: ignore[attr-defined]
            self._series_points.append([])
            self._data_tabs.addTab(container, f"Series {idx + 1}")

    def _active_series_index(self) -> int:
        return max(0, self._data_tabs.currentIndex())

    def _on_series_tab_changed(self, idx: int) -> None:
        if self._stack.currentIndex() == 2 and self._is_scatter_mode():
            self._refresh_data_visibility()
            self._sync_active_point_for_mode()

    # ------------------------------------------------------------------
    # curve series tabs management
    # ------------------------------------------------------------------

    def _restore_data_point(self, sx: float, sy: float) -> None:
        if self._calibration is not None:
            self._add_data_point(sx, sy)
            return
        si = self._active_series_index()
        if si >= len(self._series_tables):
            return
        color = point_color(len(self._series_points[si]))
        point = DraggablePoint(sx, sy, color=color)
        self._configure_point(point)
        self._register_point(point)
        point.set_bounds(self._crop_bounds_rectf())
        point.set_point_shape(self._current_shape)
        point.set_point_size(self._current_size)
        point.set_active_fill_opacity(self._scatter_active_fill_opacity)
        self._canvas.add_overlay(point)
        self._series_points[si].append(point)
        table = self._series_tables[si]
        row = table.add_row(sx, sy, 0.0, 0.0, color=color)
        table.clear_fig_values()
        point.position_changed.connect(
            lambda x, y, s=si, r=row: self._on_data_dragged(s, r, x, y)
        )
        table.selectRow(row)
        self._activate_point(point)
        self._update_data_status()

    def _add_data_point(self, sx: float, sy: float) -> None:
        if self._calibration is None:
            QMessageBox.warning(self._host, "Data", "Build calibration first (Ref Points tab).")
            return

        si = self._active_series_index()
        if si >= len(self._series_tables):
            return

        if self._pixel_center_check.isChecked() and not self._restoring:
            sx, sy = self._pixel_center_coordinates(sx, sy)

        constraint = DragConstraint.FREE
        x_fig_override: Optional[float] = None
        y_fig_override: Optional[float] = None

        if self._snap_xy.isChecked():
            sx, x_fig_override = self._snap_to_x_grid(sx)
            sy, y_fig_override = self._snap_to_y_grid(sy)
            if x_fig_override is not None and y_fig_override is not None:
                constraint = DragConstraint.FIXED
            elif x_fig_override is not None:
                constraint = DragConstraint.VERTICAL_ONLY
            elif y_fig_override is not None:
                constraint = DragConstraint.HORIZONTAL_ONLY
        elif self._snap_x.isChecked():
            sx, x_fig_override = self._snap_to_x_grid(sx)
            if x_fig_override is not None:
                constraint = DragConstraint.VERTICAL_ONLY
        elif self._snap_y.isChecked():
            sy, y_fig_override = self._snap_to_y_grid(sy)
            if y_fig_override is not None:
                constraint = DragConstraint.HORIZONTAL_ONLY

        try:
            xf = (x_fig_override if x_fig_override is not None
                  else self._calibration.x_axis.pixel_to_data(sx))
            yf = (y_fig_override if y_fig_override is not None
                  else self._calibration.y_axis.pixel_to_data(sy))
        except Exception as exc:
            QMessageBox.warning(self._host, "Data", f"Cannot convert this point: {exc}")
            return

        idx = len(self._series_points[si])
        color = point_color(idx)
        pt = DraggablePoint(sx, sy, color=color)
        self._configure_point(pt)
        self._register_point(pt)
        pt.set_constraint(constraint)
        pt.set_bounds(self._crop_bounds_rectf())
        pt.set_point_shape(self._current_shape)
        pt.set_point_size(self._current_size)
        pt.set_active_fill_opacity(self._scatter_active_fill_opacity)
        self._canvas.add_overlay(pt)
        self._series_points[si].append(pt)

        table = self._series_tables[si]
        row = table.add_row(sx, sy, xf, yf, color=color)
        pt.position_changed.connect(
            lambda x, y, s=si, r=row: self._on_data_dragged(s, r, x, y)
        )
        table.selectRow(row)
        self._activate_point(pt)
        self._update_data_status()
        if self._marker_auto_check.isChecked() and not self._restoring:
            self._propose_marker_center(pt)

    def _on_data_dragged(self, si: int, row: int, x: float, y: float) -> None:
        point = None
        if 0 <= si < len(self._series_points) and 0 <= row < len(self._series_points[si]):
            point = self._series_points[si][row]
            if self._redirect_position_to_pixel_center(point, x, y):
                return
        if si < len(self._series_tables):
            self._series_tables[si].update_wind(row, x, y)
            if self._calibration:
                try:
                    xf = self._calibration.x_axis.pixel_to_data(x)
                    yf = self._calibration.y_axis.pixel_to_data(y)
                    self._series_tables[si].update_fig(row, xf, yf)
                except Exception:
                    pass
        self._refresh_loupe_if_active(point)

    def _data_table_wind_changed(self, si: int, row: int, x: float, y: float) -> None:
        if 0 <= si < len(self._series_points) and 0 <= row < len(self._series_points[si]):
            point = self._series_points[si][row]
            point.set_pos_silent(x, y)
            if self._pixel_magnet_applies_to(point):
                self._snap_point_to_pixel_center(point, report=False)
            actual = point.pos()
            x, y = actual.x(), actual.y()
            if si < len(self._series_tables):
                self._series_tables[si].update_wind(row, x, y)
            self._refresh_loupe_if_active(point)
        if self._calibration:
            try:
                xf = self._calibration.x_axis.pixel_to_data(x)
                yf = self._calibration.y_axis.pixel_to_data(y)
                if si < len(self._series_tables):
                    self._series_tables[si].update_fig(row, xf, yf)
            except Exception:
                pass

    def _data_key_move(self, si: int, row: int, dx: float, dy: float) -> None:
        if 0 <= si < len(self._series_points) and 0 <= row < len(self._series_points[si]):
            self._series_points[si][row].moveBy(dx, dy)

    def _data_delete_selected(self) -> None:
        si = self._active_series_index()
        if si >= len(self._series_tables):
            return
        table = self._series_tables[si]
        row = table.remove_selected_row()
        if row is not None and 0 <= row < len(self._series_points[si]):
            pt = self._series_points[si].pop(row)
            self._safe_remove_point(pt)
            self._reconnect_data_signals(si)
            self._update_data_status()
            self._sync_active_point_for_mode()

    def _data_clear_series(self, si: int) -> None:
        if si >= len(self._series_points):
            return
        for pt in self._series_points[si]:
            self._safe_remove_point(pt)
        self._series_points[si].clear()
        if si < len(self._series_tables):
            self._series_tables[si].setRowCount(0)
        self._update_data_status()
        self._sync_active_point_for_mode()

    def _reconnect_data_signals(self, si: int) -> None:
        if si >= len(self._series_points):
            return
        for i, pt in enumerate(self._series_points[si]):
            try:
                pt.position_changed.disconnect()
            except RuntimeError:
                pass
            pt.position_changed.connect(
                lambda x, y, s=si, r=i: self._on_data_dragged(s, r, x, y)
            )

    def _update_data_status(self) -> None:
        total = sum(len(pts) for pts in self._series_points)
        self._data_status.setText(f"{total} point(s) total across {len(self._series_points)} series")

    # ------------------------------------------------------------------
    # CURVE DATA POINTS
    # ------------------------------------------------------------------
