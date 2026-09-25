"""Calibration-mode UI, anchors, diagnostics and grid snapping."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from src.core.calibration import build_calibration
from src.core.precision import snap_to_stroke_center
from src.gui.overlays.point_overlay import DraggablePoint
from src.gui.tables.colors import point_color
from src.gui.tables.reference import RefPointTable
from src.gui.workspace.contracts import HostBoundTool
from src.models.calibration_data import CalibrationResult
from src.models.types import ScaleType


class CalibrationMode(HostBoundTool):
    """Own reference anchors, calibration validity and diagnostic feedback."""

    def _build_ref_page(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)

        guide = QLabel(
            "Calibration needs at least 2 X anchors and 2 Y anchors. "
            "Choose anchors far apart. For a thick line, place the crosshair "
            "at the geometric centre of the stroke (between the two middle "
            "pixels for a 4 px line). Both value cells are editable: filling "
            "the second coordinate automatically changes Axis to Both; clear "
            "one coordinate to use the point only for X or Y."
        )
        guide.setWordWrap(True)
        lay.addWidget(guide)

        form = QFormLayout()
        self._x_scale_combo = QComboBox()
        self._x_scale_combo.addItems(["Linear", "Logarithmic"])
        self._x_scale_combo.setCurrentIndex(
            1 if self._project.settings.x_scale == ScaleType.LOG else 0
        )
        form.addRow("X scale:", self._x_scale_combo)
        self._y_scale_combo = QComboBox()
        self._y_scale_combo.addItems(["Linear", "Logarithmic"])
        self._y_scale_combo.setCurrentIndex(
            1 if self._project.settings.y_scale == ScaleType.LOG else 0
        )
        form.addRow("Y scale:", self._y_scale_combo)
        self._ref_axis_combo = QComboBox()
        self._ref_axis_combo.addItems(["X anchor", "Y anchor", "Both (known intersection)"])
        self._ref_axis_combo.setToolTip(
            "Sets the initial role. You can later fill or clear either value "
            "cell in the table; Axis will update automatically."
        )
        form.addRow("Next click adds:", self._ref_axis_combo)
        lay.addLayout(form)

        self._centerline_snap_check = QCheckBox("Snap anchors to stroke centre (±10 px)")
        self._centerline_snap_check.setChecked(self._project.settings.snap_to_edge)
        self._centerline_snap_check.setToolTip(
            "Finds the two sides of a nearby dark tick/frame stroke and uses their sub-pixel centre."
        )
        lay.addWidget(self._centerline_snap_check)

        frame_group = QGroupBox("Fast calibration from frame centre-lines")
        frame_grid = QGridLayout(frame_group)
        self._frame_value_edits: dict[str, QLineEdit] = {}
        for row, (key, text) in enumerate((
            ("x_left", "X at left"), ("x_right", "X at right"),
            ("y_bottom", "Y at bottom"), ("y_top", "Y at top"),
        )):
            edit = QLineEdit()
            edit.setValidator(QDoubleValidator(edit))
            edit.setPlaceholderText("e.g. 1e-3")
            edit.setMaximumWidth(95)
            self._frame_value_edits[key] = edit
            frame_grid.addWidget(QLabel(text), row // 2, (row % 2) * 2)
            frame_grid.addWidget(edit, row // 2, (row % 2) * 2 + 1)
        btn_frame = QPushButton("Create anchors and build")
        btn_frame.setToolTip(
            "Uses opposite intersections of the confirmed crop rectangle; its edges must follow stroke centres."
        )
        btn_frame.clicked.connect(self._calibrate_from_frame)
        frame_grid.addWidget(btn_frame, 2, 0, 1, 4)
        lay.addWidget(frame_group)

        self._ref_table = RefPointTable()
        self._configure_table(self._ref_table)
        lay.addWidget(self._ref_table, stretch=1)

        btn_row = QHBoxLayout()
        btn_del = QPushButton("Delete")
        btn_del.clicked.connect(self._ref_delete_selected)
        btn_row.addWidget(btn_del)

        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self._ref_clear_all)
        btn_row.addWidget(btn_clear)

        btn_build = QPushButton("Build")
        btn_build.setObjectName("primary")
        btn_build.clicked.connect(self._rebuild_calibration)
        btn_row.addWidget(btn_build)
        lay.addLayout(btn_row)

        self._ref_status = QLabel("Need 2 X anchors and 2 Y anchors (3+ per axis enables an error estimate).")
        self._ref_status.setWordWrap(True)
        lay.addWidget(self._ref_status)

        self._ref_table.point_wind_changed.connect(self._ref_table_wind_changed)
        self._ref_table.ref_value_changed.connect(self._on_ref_value_changed)
        self._ref_table.key_move.connect(self._ref_key_move)
        self._ref_table.currentCellChanged.connect(
            lambda row, _column, _old_row, _old_column: self._on_ref_row_selected(row)
        )
        self._x_scale_combo.currentIndexChanged.connect(self._on_calibration_input_changed)
        self._y_scale_combo.currentIndexChanged.connect(self._on_calibration_input_changed)

        self._stack.addWidget(page)

    # ------------------------------------------------------------------
    # Data Points page (Scatter / Curve sub-modes)
    # ------------------------------------------------------------------

    def _add_ref_point(self, sx: float, sy: float) -> None:
        axis = ("X", "Y", "Both")[self._ref_axis_combo.currentIndex()]
        snap_messages: list[str] = []
        if self._centerline_snap_check.isChecked() and self._project.image is not None:
            if axis in ("X", "Both"):
                snapped = snap_to_stroke_center(
                    self._project.image, sx, sy, "vertical", search_radius=10
                )
                if snapped.applied:
                    snap_messages.append(f"X {sx:.3f}→{snapped.coordinate:.3f}")
                    sx = snapped.coordinate
            if axis in ("Y", "Both"):
                snapped = snap_to_stroke_center(
                    self._project.image, sx, sy, "horizontal", search_radius=10
                )
                if snapped.applied:
                    snap_messages.append(f"Y {sy:.3f}→{snapped.coordinate:.3f}")
                    sy = snapped.coordinate

        self._create_ref_point(sx, sy, axis=axis)
        self._invalidate_calibration("Anchor added — enter its known value, then rebuild.")
        if snap_messages:
            self._status.setText("Centre-line snap: " + ", ".join(snap_messages))

    def _create_ref_point(
        self,
        sx: float,
        sy: float,
        *,
        axis: str,
        x_ref: float | None = None,
        y_ref: float | None = None,
    ) -> None:
        idx = len(self._ref_points)
        color = point_color(idx)
        pt = DraggablePoint(sx, sy, color=color)
        self._configure_point(pt)
        self._register_point(pt)
        pt.set_precision_style(True)
        pt.set_bounds(self._crop_bounds_rectf())
        self._canvas.add_overlay(pt)
        self._ref_points.append(pt)
        self._ref_table.add_row(
            sx, sy, x_ref, y_ref, color=color, axis=axis
        )

        pt.position_changed.connect(
            lambda x, y, r=idx: self._on_ref_dragged(r, x, y)
        )
        self._ref_table.selectRow(idx)
        self._activate_point(pt)

    def _on_ref_dragged(self, row: int, x: float, y: float) -> None:
        self._ref_table.update_wind(row, x, y)
        if 0 <= row < len(self._ref_points):
            self._refresh_loupe_if_active(self._ref_points[row])
        self._invalidate_calibration("Anchor moved — rebuild calibration.")

    def _ref_table_wind_changed(self, row: int, x: float, y: float) -> None:
        if 0 <= row < len(self._ref_points):
            point = self._ref_points[row]
            point.set_pos_silent(x, y)
            actual = point.pos()
            self._ref_table.update_wind(row, actual.x(), actual.y())
            self._refresh_loupe_if_active(point)
            self._invalidate_calibration("Anchor coordinates changed — rebuild calibration.")

    def _on_ref_value_changed(self) -> None:
        self._invalidate_calibration("Anchor value changed — rebuild calibration.")

    def _on_calibration_input_changed(self, *_args) -> None:
        if self._restoring:
            return
        self._invalidate_calibration("Axis scale changed — rebuild calibration.")

    def _ref_key_move(self, row: int, dx: float, dy: float) -> None:
        if 0 <= row < len(self._ref_points):
            self._ref_points[row].moveBy(dx, dy)

    def _ref_delete_selected(self) -> None:
        row = self._ref_table.remove_selected_row()
        if row is not None and 0 <= row < len(self._ref_points):
            pt = self._ref_points.pop(row)
            self._safe_remove_point(pt)
            self._reconnect_ref_signals()
            self._invalidate_calibration("Anchor deleted — rebuild calibration.")
            self._sync_active_point_for_mode()

    def _ref_clear_all(self) -> None:
        self._clear_reference_items()
        self._sync_active_point_for_mode()
        self._invalidate_calibration(
            "Need 2 X anchors and 2 Y anchors (3+ per axis enables an error estimate)."
        )

    def _clear_reference_items(self) -> None:
        for pt in self._ref_points:
            self._safe_remove_point(pt)
        self._ref_points.clear()
        self._ref_table.setRowCount(0)

    def _invalidate_calibration(self, reason: str) -> None:
        """Prevent stale calibration from being used after any input change."""
        self._calibration = None
        self._project.calibration = CalibrationResult()
        self._grid_overlay.clear_grid()
        self._grid_overlay.setVisible(False)
        for table in [*self._series_tables, *self._curve_tables]:
            table.clear_fig_values()
        for ci, path in enumerate(self._curve_paths):
            path.update_from_polyline([])
            if ci < len(self._curve_points) and len(self._curve_points[ci]) >= 2:
                self._curve_errors[ci] = "calibration is stale"
        self._update_curve_status()
        self._ref_status.setText(reason)
        self._ref_status.setStyleSheet("color: #ffcc66;")

    def _calibrate_from_frame(self) -> None:
        rect = self._project.crop_rect
        if rect is None:
            QMessageBox.warning(
                self._host, "Calibration", "Confirm the plot frame centre-lines on the Crop tab first."
            )
            return
        try:
            values = {key: float(edit.text()) for key, edit in self._frame_value_edits.items()}
            if not all(math.isfinite(value) for value in values.values()):
                raise ValueError("all limits must be finite")
        except ValueError as exc:
            QMessageBox.warning(
                self._host, "Calibration", f"Enter four valid axis limits ({exc})."
            )
            return

        x0, y0, width, height = rect
        self._clear_reference_items()
        self._create_ref_point(
            x0, y0 + height, axis="Both",
            x_ref=values["x_left"], y_ref=values["y_bottom"],
        )
        self._create_ref_point(
            x0 + width, y0, axis="Both",
            x_ref=values["x_right"], y_ref=values["y_top"],
        )
        self._rebuild_calibration()

    def _reconnect_ref_signals(self) -> None:
        for i, pt in enumerate(self._ref_points):
            try:
                pt.position_changed.disconnect()
            except RuntimeError:
                pass
            pt.position_changed.connect(
                lambda x, y, r=i: self._on_ref_dragged(r, x, y)
            )

    def _set_calibration_diagnostics_status(self) -> None:
        if self._calibration is None:
            return
        x_axis = self._calibration.x_axis
        y_axis = self._calibration.y_axis
        def resolution(axis, label: str) -> str:
            if axis.scale == ScaleType.LOG:
                exponent = abs(axis.transformed_units_per_pixel)
                factor = 10.0 ** exponent if exponent <= 308.0 else math.inf
                return f"{label} ×{factor:.6g}/px"
            return f"{label} {abs(axis.transformed_units_per_pixel):.6g} units/px"
        resolution_note = f"{resolution(x_axis, 'X')}; {resolution(y_axis, 'Y')}"
        if x_axis.n_points == 2 and y_axis.n_points == 2:
            target = max(3, self._project.settings.n_calibration_points)
            note = (
                "2 anchors/axis: exact fit; error cannot be estimated. "
                f"Use {target}+ per axis to measure placement consistency. "
                f"Resolution: {resolution_note}."
            )
        else:
            rows = self._ref_table.get_ref_data()
            x_rows = [index + 1 for index, row in enumerate(rows) if row[2] is not None]
            y_rows = [index + 1 for index, row in enumerate(rows) if row[3] is not None]
            worst_x = x_rows[max(
                range(len(x_axis.residuals_pixels)),
                key=lambda i: abs(x_axis.residuals_pixels[i]),
            )]
            worst_y = y_rows[max(
                range(len(y_axis.residuals_pixels)),
                key=lambda i: abs(y_axis.residuals_pixels[i]),
            )]
            note = (
                f"X: {x_axis.n_points} anchors, RMS {x_axis.rmse_pixels:.3f} px, "
                f"max {x_axis.max_error_pixels:.3f} px (row {worst_x}); "
                f"Y: {y_axis.n_points} anchors, RMS {y_axis.rmse_pixels:.3f} px, "
                f"max {y_axis.max_error_pixels:.3f} px (row {worst_y}). "
                f"Resolution: {resolution_note}."
            )
        worst = max(x_axis.max_error_pixels or 0.0, y_axis.max_error_pixels or 0.0)
        color = "#66bb6a" if worst <= 0.75 else "#ffcc66"
        verdict = "Calibration OK" if worst <= 0.75 else "Calibration warning"
        self._ref_status.setText(f"{verdict} — {note}")
        self._ref_status.setStyleSheet(f"color: {color};")

    def _rebuild_calibration(self) -> None:
        try:
            data = self._ref_table.get_ref_data()
        except ValueError as exc:
            self._invalidate_calibration(f"Calibration input error — {exc}.")
            self._ref_status.setStyleSheet("color: #ff6666;")
            return
        x_pairs = [(xw, xr) for xw, _, xr, _, _ in data if xr is not None]
        y_pairs = [(yw, yr) for _, yw, _, yr, _ in data if yr is not None]

        unique_x = len({xr for _, xr in x_pairs})
        unique_y = len({yr for _, yr in y_pairs})

        if len(x_pairs) >= 2 and len(y_pairs) >= 2 and unique_x >= 2 and unique_y >= 2:
            scale_x = ScaleType.LOG if self._x_scale_combo.currentIndex() == 1 else ScaleType.LINEAR
            scale_y = ScaleType.LOG if self._y_scale_combo.currentIndex() == 1 else ScaleType.LINEAR
            try:
                self._calibration = build_calibration(x_pairs, y_pairs, scale_x, scale_y)
                self._project.calibration = self._calibration
                self._project.settings.x_scale = scale_x
                self._project.settings.y_scale = scale_y
                self._set_calibration_diagnostics_status()
                self._update_grid()
                self._grid_overlay.setVisible(True)
                for table in self._series_tables:
                    table.update_all_fig(self._calibration)
                for table in self._curve_tables:
                    table.update_all_fig(self._calibration)
                for ci in range(len(self._curve_paths)):
                    self._rebuild_curve_path(ci)
                self._update_curve_status()
                return
            except Exception as e:
                self._ref_status.setText(f"Calibration error: {e}")
                self._ref_status.setStyleSheet("color: #ff6666;")
                self._calibration = None
                self._project.calibration = CalibrationResult()
        else:
            need_x = max(0, 2 - unique_x)
            need_y = max(0, 2 - unique_y)
            parts = []
            if need_x:
                parts.append(f"{need_x} more distinct X ref(s)")
            if need_y:
                parts.append(f"{need_y} more distinct Y ref(s)")
            self._ref_status.setText(
                "Need " + " and ".join(parts)
                if parts else "Enter ref values and click Build."
            )
            self._ref_status.setStyleSheet("color: #cccccc;")
            self._calibration = None
            self._project.calibration = CalibrationResult()

        self._grid_overlay.clear_grid()
        self._grid_overlay.setVisible(False)

    def _update_grid(self) -> None:
        if self._calibration is None or self._project.crop_rect is None:
            self._grid_overlay.clear_grid()
            return
        data = self._ref_table.get_ref_data()
        x_refs = sorted({xr for _, _, xr, _, _ in data if xr is not None})
        y_refs = sorted({yr for _, _, _, yr, _ in data if yr is not None})
        self._grid_overlay.update_grid(self._calibration, self._project.crop_rect, x_refs, y_refs)

    # ------------------------------------------------------------------
    # SCATTER DATA POINTS
    # ------------------------------------------------------------------

    def _snap_to_x_grid(self, click_x: float) -> tuple[float, float | None]:
        if self._calibration is None:
            return click_x, None
        data = self._ref_table.get_ref_data()
        x_refs = sorted({xr for _, _, xr, _, _ in data if xr is not None})
        if not x_refs:
            return click_x, None
        best_ref = min(x_refs, key=lambda xr: abs(self._calibration.x_axis.data_to_pixel(xr) - click_x))
        pixel = self._calibration.x_axis.data_to_pixel(best_ref)
        if abs(pixel - click_x) > self._snap_threshold_spin.value():
            return click_x, None
        return pixel, best_ref

    def _snap_to_y_grid(self, click_y: float) -> tuple[float, float | None]:
        if self._calibration is None:
            return click_y, None
        data = self._ref_table.get_ref_data()
        y_refs = sorted({yr for _, _, _, yr, _ in data if yr is not None})
        if not y_refs:
            return click_y, None
        best_ref = min(y_refs, key=lambda yr: abs(self._calibration.y_axis.data_to_pixel(yr) - click_y))
        pixel = self._calibration.y_axis.data_to_pixel(best_ref)
        if abs(pixel - click_y) > self._snap_threshold_spin.value():
            return click_y, None
        return pixel, best_ref

    # ------------------------------------------------------------------
    # export
    # ------------------------------------------------------------------
