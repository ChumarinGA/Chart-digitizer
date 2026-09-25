"""Shared active-point precision inspector and placement tools."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QGridLayout, QGroupBox, QLabel, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from src.core.marker_center import estimate_marker_center
from src.gui.overlays.point_overlay import DraggablePoint
from src.gui.workspace.contracts import HostBoundTool


class PrecisionTools(HostBoundTool):
    """Own active-point selection, loupe, pixel magnet and marker proposals."""

    def _build_precision_panel(self, root: QVBoxLayout) -> None:
        """Build the common Ref/Scatter/Curve active-point inspector."""
        self._precision_group = QGroupBox("Active point precision")
        self._precision_group.setCheckable(True)
        self._precision_group.setChecked(True)
        self._precision_group.setToolTip(
            "Clear the title checkbox to collapse this section and give the point table more room."
        )
        group_layout = QVBoxLayout(self._precision_group)
        group_layout.setContentsMargins(6, 6, 6, 6)

        # Keep the group's public identity stable for the existing workflow,
        # while putting all collapsible children into a single content widget.
        self._precision_content = QWidget()
        self._precision_layout = QGridLayout(self._precision_content)
        self._precision_layout.setContentsMargins(0, 0, 0, 0)
        self._precision_layout.setHorizontalSpacing(10)
        self._precision_layout.setVerticalSpacing(6)
        group_layout.addWidget(self._precision_content)

        self._loupe = QLabel("Select or create a point")
        self._loupe.setFixedSize(180, 180)
        self._loupe.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loupe.setStyleSheet("border: 1px solid #666; background: #222;")
        self._loupe.setToolTip(
            "Nearest-neighbour source pixels. The red cross is the exact stored centre "
            "of the active point, not the mouse cursor."
        )

        self._precision_tools_widget = QWidget()
        tools = QVBoxLayout(self._precision_tools_widget)
        tools.setContentsMargins(0, 0, 0, 0)
        self._loupe_coords = QLabel(
            "Create a point or select one in a table.\n"
            "The red cross will show its exact stored centre."
        )
        self._loupe_coords.setWordWrap(True)
        tools.addWidget(self._loupe_coords)

        self._data_precision_tools = QWidget()
        data_tools = QVBoxLayout(self._data_precision_tools)
        data_tools.setContentsMargins(0, 0, 0, 0)

        self._pixel_center_check = QCheckBox("Pixel-centre magnet")
        self._pixel_center_check.setToolTip(
            "While enabled, snaps the active/new data point after placement, dragging, "
            "arrow movement, or a coordinate-table edit to a source-pixel centre. "
            "Keep this OFF for an even-width stroke: its true centre may lie between pixels."
        )
        self._pixel_center_check.toggled.connect(self._on_pixel_magnet_toggled)
        data_tools.addWidget(self._pixel_center_check)

        snap_now = QPushButton("Snap active now")
        snap_now.clicked.connect(self._snap_active_to_pixel_center)
        data_tools.addWidget(snap_now)

        self._marker_auto_check = QCheckBox("Auto centre suggestion")
        self._marker_auto_check.setToolTip(
            "Analyses a local image patch, temporarily displays the candidate, and asks "
            "for confirmation. Nothing is accepted silently. A confirmed marker centre "
            "may be sub-pixel even while the separate pixel magnet remains armed."
        )
        data_tools.addWidget(self._marker_auto_check)

        marker_row = QGridLayout()
        self._marker_center_button = QPushButton("Find marker centre…")
        self._marker_center_button.clicked.connect(self._propose_active_marker_center)
        marker_row.addWidget(self._marker_center_button, 0, 0, 1, 2)
        marker_row.addWidget(QLabel("Search radius:"), 1, 0)
        self._marker_radius_spin = QSpinBox()
        self._marker_radius_spin.setRange(4, 40)
        self._marker_radius_spin.setValue(12)
        self._marker_radius_spin.setSuffix(" px")
        self._marker_radius_spin.setToolTip(
            "Local search radius. It should contain the marker but as little neighbouring "
            "curve/grid content as possible."
        )
        marker_row.addWidget(self._marker_radius_spin, 1, 1)
        marker_row.setColumnStretch(0, 1)
        data_tools.addLayout(marker_row)

        tools.addWidget(self._data_precision_tools)
        tools.addStretch()
        self._precision_compact: bool | None = None
        self._set_precision_compact(False)
        self._precision_group.toggled.connect(self._set_precision_expanded)
        self._precision_group.setVisible(False)
        magnifier = self._project.settings.magnifier_enabled
        self._loupe.setVisible(magnifier)
        self._loupe_coords.setVisible(magnifier)
        root.addWidget(self._precision_group)

    def _set_precision_expanded(self, expanded: bool) -> None:
        """Show or hide the inspector body without replacing its widgets."""
        self._precision_content.setVisible(expanded)

    def _set_precision_compact(self, compact: bool) -> None:
        """Stack the loupe above its tools when the dock becomes narrow."""
        if self._precision_compact == compact:
            return
        self._precision_compact = compact
        self._precision_layout.removeWidget(self._loupe)
        self._precision_layout.removeWidget(self._precision_tools_widget)
        if compact:
            self._precision_layout.addWidget(
                self._loupe,
                0,
                0,
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter,
            )
            self._precision_layout.addWidget(self._precision_tools_widget, 1, 0)
            self._precision_layout.setColumnStretch(0, 1)
            self._precision_layout.setColumnStretch(1, 0)
        else:
            self._precision_layout.addWidget(
                self._loupe, 0, 0, Qt.AlignmentFlag.AlignTop
            )
            self._precision_layout.addWidget(self._precision_tools_widget, 0, 1)
            self._precision_layout.setColumnStretch(0, 0)
            self._precision_layout.setColumnStretch(1, 1)
        self._precision_layout.invalidate()

    def _register_point(self, point: DraggablePoint) -> None:
        """Connect selection/drag lifecycle without disturbing position slots."""
        point.activated.connect(lambda p=point: self._activate_point(p))
        point.drag_finished.connect(lambda p=point: self._on_point_drag_finished(p))

    def _point_context(self, point: DraggablePoint) -> tuple[str, object, int] | None:
        if point in self._crop_corners:
            row = self._crop_corners.index(point)
            return (f"Crop corner {row + 1}", self._crop_corner_table, row)
        if point in self._ref_points:
            row = self._ref_points.index(point)
            return (f"Calibration anchor {row + 1}", self._ref_table, row)
        for si, points in enumerate(self._series_points):
            if point in points:
                row = points.index(point)
                table = self._series_tables[si] if si < len(self._series_tables) else None
                return (f"Scatter {si + 1}, point {row + 1}", table, row)
        for ci, points in enumerate(self._curve_points):
            if point in points:
                row = points.index(point)
                table = self._curve_tables[ci] if ci < len(self._curve_tables) else None
                return (f"Curve {ci + 1}, control point {row + 1}", table, row)
        return None

    def _is_data_point(self, point: DraggablePoint | None) -> bool:
        if point is None:
            return False
        return any(point in points for points in self._series_points) or any(
            point in points for points in self._curve_points
        )

    def _activate_point(self, point: DraggablePoint) -> None:
        context = self._point_context(point)
        if context is None:
            return
        if self._active_point is not point:
            if self._active_point is not None:
                try:
                    self._active_point.set_active_visual(False)
                except RuntimeError:
                    pass
            self._active_point = point
            point.set_active_visual(True)
        self._active_point_label = context[0]
        table, row = context[1], context[2]
        if table is not None and table.currentRow() != row:
            table.selectRow(row)
        self._refresh_active_loupe()

    def _clear_active_point(self) -> None:
        if self._active_point is not None:
            try:
                self._active_point.set_active_visual(False)
            except (RuntimeError, TypeError):
                pass
        self._active_point = None
        self._active_point_label = ""
        if hasattr(self, "_loupe"):
            self._loupe.clear()
            self._loupe.setText("Select or create a point")
            self._loupe_coords.setText(
                "Create a point or select one in a table.\n"
                "The red cross will show its exact stored centre."
            )

    def _refresh_active_loupe(self) -> None:
        point = self._active_point
        if point is None:
            return
        try:
            pos = point.pos()
        except RuntimeError:
            self._clear_active_point()
            return
        self._update_loupe(pos.x(), pos.y())

    def _refresh_loupe_if_active(self, point: DraggablePoint | None) -> None:
        if point is not None and point is self._active_point:
            self._refresh_active_loupe()

    def _sync_active_point_for_mode(self) -> None:
        mode = self._stack.currentIndex()
        candidates: list[DraggablePoint]
        table = None
        if mode == 1:
            candidates = self._ref_points
            table = self._ref_table
        elif mode == 2 and self._is_scatter_mode():
            si = self._active_series_index()
            candidates = self._series_points[si] if si < len(self._series_points) else []
            table = self._series_tables[si] if si < len(self._series_tables) else None
        elif mode == 2:
            ci = self._active_curve_index()
            candidates = self._curve_points[ci] if ci < len(self._curve_points) else []
            table = self._curve_tables[ci] if ci < len(self._curve_tables) else None
        else:
            return

        if self._active_point in candidates:
            self._activate_point(self._active_point)
            return
        row = table.selected_row() if table is not None else None
        if row is not None and 0 <= row < len(candidates):
            self._activate_point(candidates[row])
        elif candidates:
            self._activate_point(candidates[-1])
        else:
            self._clear_active_point()

    def _on_ref_row_selected(self, row: int) -> None:
        if 0 <= row < len(self._ref_points):
            self._activate_point(self._ref_points[row])

    def _on_data_row_selected(self, series: int, row: int) -> None:
        if (0 <= series < len(self._series_points)
                and 0 <= row < len(self._series_points[series])):
            self._activate_point(self._series_points[series][row])

    def _on_curve_row_selected(self, curve: int, row: int) -> None:
        if (0 <= curve < len(self._curve_points)
                and 0 <= row < len(self._curve_points[curve])):
            self._activate_point(self._curve_points[curve][row])

    def _pixel_center_coordinates(self, x: float, y: float) -> tuple[float, float]:
        """Return centres of the source pixels containing the scene position."""
        column = math.floor(x)
        row = math.floor(y)
        if self._project.image is not None:
            height, width = self._project.image.shape[:2]
            column = max(0, min(column, width - 1))
            row = max(0, min(row, height - 1))
        return column + 0.5, row + 0.5

    def _pixel_magnet_applies_to(self, point: DraggablePoint) -> bool:
        return (
            self._pixel_center_check.isChecked()
            and not self._restoring
            and not self._suspend_pixel_magnet
            and point is self._active_point
            and self._is_data_point(point)
        )

    def _redirect_position_to_pixel_center(
        self, point: DraggablePoint, x: float, y: float
    ) -> bool:
        """Enforce an armed magnet for any committed movement path.

        Returns true when ``setPos`` emitted a nested position update; the
        caller must then stop processing the obsolete unsnapped coordinates.
        """
        if not self._pixel_magnet_applies_to(point):
            return False
        target_x, target_y = self._pixel_center_coordinates(x, y)
        if math.isclose(x, target_x, abs_tol=1e-12) and math.isclose(
            y, target_y, abs_tol=1e-12
        ):
            return False
        before = QPointF(point.pos())
        point.setPos(target_x, target_y)
        after = point.pos()
        return not (
            math.isclose(before.x(), after.x(), abs_tol=1e-12)
            and math.isclose(before.y(), after.y(), abs_tol=1e-12)
        )

    def _set_point_pos_without_pixel_magnet(
        self, point: DraggablePoint, position: QPointF
    ) -> None:
        previous = self._suspend_pixel_magnet
        self._suspend_pixel_magnet = True
        try:
            point.setPos(position)
        finally:
            self._suspend_pixel_magnet = previous

    def _snap_point_to_pixel_center(
        self, point: DraggablePoint, *, report: bool = True
    ) -> bool:
        if not self._is_data_point(point):
            if report:
                self._status.setText("Pixel-centre magnet applies only to Scatter/Curve points.")
            return False
        old = QPointF(point.pos())
        target_x, target_y = self._pixel_center_coordinates(old.x(), old.y())
        point.setPos(target_x, target_y)
        new = point.pos()
        moved = not (
            math.isclose(old.x(), new.x(), abs_tol=1e-12)
            and math.isclose(old.y(), new.y(), abs_tol=1e-12)
        )
        self._refresh_loupe_if_active(point)
        if report:
            if moved:
                self._status.setText(
                    f"Active point snapped to pixel centre ({new.x():.3f}, {new.y():.3f})."
                )
            else:
                self._status.setText(
                    "Active point was already at a pixel centre, or its axis lock prevented movement."
                )
        return moved

    def _on_pixel_magnet_toggled(self, enabled: bool) -> None:
        if enabled and self._is_data_point(self._active_point):
            self._snap_point_to_pixel_center(self._active_point)

    def _snap_active_to_pixel_center(self) -> None:
        if self._active_point is None:
            self._status.setText("Select a Scatter/Curve point first.")
            return
        self._snap_point_to_pixel_center(self._active_point)

    def _on_point_drag_finished(self, point: DraggablePoint) -> None:
        self._activate_point(point)
        if self._pixel_center_check.isChecked() and self._is_data_point(point):
            self._snap_point_to_pixel_center(point, report=False)

    def _propose_active_marker_center(self) -> None:
        point = self._active_point
        if point is None or not self._is_data_point(point):
            self._status.setText("Select a Scatter/Curve point first.")
            return
        self._propose_marker_center(point, notify_failure=True)

    def _propose_marker_center(
        self,
        point: DraggablePoint,
        *,
        notify_failure: bool = False,
    ) -> bool:
        """Preview a detected centre and apply it only after confirmation."""
        if self._project.image is None:
            message = "Marker-centre search needs the source image loaded in this project."
            self._status.setText(message)
            if notify_failure:
                QMessageBox.information(self._host, "Marker centre", message)
            return False

        self._activate_point(point)
        original = QPointF(point.pos())
        try:
            result = estimate_marker_center(
                self._project.image,
                original.x(),
                original.y(),
                radius=float(self._marker_radius_spin.value()),
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            message = f"Marker-centre search failed: {exc}"
            self._status.setText(message)
            if notify_failure:
                QMessageBox.information(self._host, "Marker centre", message)
            return False

        try:
            configured_quality = float(
                self._project.settings.marker_center_sensitivity
            )
        except (TypeError, ValueError):
            configured_quality = 0.5
        if not math.isfinite(configured_quality):
            configured_quality = 0.5
        minimum_quality = max(0.48, min(1.0, configured_quality))
        if not result.applied or result.confidence < minimum_quality:
            reason = result.reason
            if result.applied:
                reason = (
                    f"quality {result.confidence:.2f} is below the configured "
                    f"minimum {minimum_quality:.2f}"
                )
            message = f"No reliable marker centre proposed: {reason}."
            self._status.setText(message)
            if notify_failure:
                QMessageBox.information(
                    self._host,
                    "Marker centre",
                    message + "\n\nThe active point was not changed.",
                )
            return False

        # Temporarily show the candidate in both the canvas and point-centred
        # loupe.  Rejecting the dialog restores the exact original coordinate.
        raw_candidate = QPointF(result.candidate_x, result.candidate_y)
        self._set_point_pos_without_pixel_magnet(point, raw_candidate)
        displayed = QPointF(point.pos())
        constraint_delta = math.hypot(
            displayed.x() - raw_candidate.x(), displayed.y() - raw_candidate.y()
        )
        if constraint_delta > 0.05:
            self._set_point_pos_without_pixel_magnet(point, original)
            message = (
                "Axis lock or crop bounds prevent applying the complete marker-centre "
                "candidate. Unlock/reposition the point and retry."
            )
            self._status.setText(message)
            if notify_failure:
                QMessageBox.information(self._host, "Marker centre", message)
            return False
        self._refresh_active_loupe()
        QApplication.processEvents()
        shift = math.hypot(displayed.x() - original.x(), displayed.y() - original.y())
        if shift <= 1e-12:
            self._status.setText("The detected marker centre already matches the point.")
            return False

        box = QMessageBox(self._host)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Confirm marker centre")
        box.setText(
            "A marker-centre candidate is now shown by the active crosshair"
            + (" and loupe." if self._project.settings.magnifier_enabled else ".")
        )
        box.setInformativeText(
            f"Original: ({original.x():.4f}, {original.y():.4f})\n"
            f"Candidate: ({displayed.x():.4f}, {displayed.y():.4f})\n"
            f"Shift: {shift:.3f} px; quality score: {100.0 * result.confidence:.0f}%\n\n"
            "Use it only if the crosshair visually matches the marker's geometric centre."
        )
        use_button = box.addButton("Use candidate", QMessageBox.ButtonRole.AcceptRole)
        keep_button = box.addButton("Keep original", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep_button)
        box.exec()

        if box.clickedButton() is use_button:
            self._status.setText(
                f"Confirmed marker centre at ({displayed.x():.4f}, {displayed.y():.4f})."
            )
            return True

        self._set_point_pos_without_pixel_magnet(point, original)
        self._refresh_active_loupe()
        self._status.setText("Marker-centre candidate rejected; original point restored.")
        return False

    # ------------------------------------------------------------------
    # canvas click dispatch
    # ------------------------------------------------------------------

    def _update_loupe(self, sx: float, sy: float) -> None:
        """Render the loupe at a stored point centre (never at the cursor)."""
        pixmap = self._canvas.loupe_pixmap(sx, sy, radius=8, size=180)
        if not pixmap.isNull():
            self._loupe.setPixmap(pixmap)
        else:
            self._loupe.clear()
            self._loupe.setText("Image preview unavailable")
        def raster_location(value: float, axis: str) -> str:
            boundary = round(value)
            if math.isclose(value, boundary, abs_tol=1e-9):
                return f"{axis}: boundary between pixels {boundary - 1} and {boundary}"
            return f"{axis}: pixel {math.floor(value)} (centre {math.floor(value) + 0.5:g})"

        self._loupe_coords.setText(
            f"{self._active_point_label or 'Active point'}\n"
            f"stored centre: x = {sx:.4f}, y = {sy:.4f}\n"
            f"{raster_location(sx, 'x')}\n{raster_location(sy, 'y')}\n\n"
            "Red cross = exact stored centre. Pixel centres are at n + 0.5; "
            "an even-width stroke centre can lie between them."
        )
