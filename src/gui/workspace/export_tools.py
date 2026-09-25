"""Collection and Excel export of the current workspace data."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

from src.core.curve_interpolation import CurveInterpolationError, CurveInterpolator
from src.core.export import export_to_excel
from src.gui.workspace.contracts import HostBoundTool
from src.models.series_data import ExtractedPoint, SeriesData
from src.models.types import CombinedMode, ExtractionMode, SeriesKind

_MAX_TOTAL_EXPORT_POINTS = 1_000_000


class ExportTools(HostBoundTool):
    """Build export series from exact scene coordinates and write workbooks."""

    def _collect_series(self, *, sample_curves: bool) -> list[SeriesData]:
        if self._calibration is None:
            raise ValueError("Calibration is missing or stale")

        result: list[SeriesData] = []
        series_idx = 1
        total_points = 0

        # Read authoritative floating-point positions from the graphics model,
        # never from rounded table text.
        for points in self._series_points:
            sd = SeriesData(
                index=series_idx, kind=SeriesKind.DISCRETE,
                mode=ExtractionMode.MANUAL,
            )
            for point in points:
                x, y = self._calibration.pixel_to_data(point.pos().x(), point.pos().y())
                sd.points.append(ExtractedPoint(x=x, y=y))
            if sd.points:
                total_points += len(sd.points)
                if sample_curves and total_points > _MAX_TOTAL_EXPORT_POINTS:
                    raise CurveInterpolationError(
                        f"export exceeds the total limit of {_MAX_TOTAL_EXPORT_POINTS} points"
                    )
                sd.sort_by_x()
                result.append(sd)
                series_idx += 1

        for ci, points in enumerate(self._curve_points):
            if not points:
                continue
            controls = [
                self._calibration.pixel_to_data(point.pos().x(), point.pos().y())
                for point in points
            ]
            sd = SeriesData(
                index=series_idx, kind=SeriesKind.CONTINUOUS,
                mode=ExtractionMode.MANUAL,
            )
            if sample_curves and len(controls) >= 2:
                engine = CurveInterpolator(
                    [p[0] for p in controls], [p[1] for p in controls],
                    self._calibration.x_axis.scale,
                    self._calibration.y_axis.scale,
                )
                remaining = _MAX_TOTAL_EXPORT_POINTS - total_points
                if remaining < 2:
                    raise CurveInterpolationError(
                        f"export exceeds the total limit of {_MAX_TOTAL_EXPORT_POINTS} points"
                    )
                xs, ys = engine.sample_for_export(self._curve_dx, max_samples=remaining)
                sd.points.extend(
                    ExtractedPoint(x=float(x), y=float(y)) for x, y in zip(xs, ys)
                )
            else:
                sd.points.extend(ExtractedPoint(x=x, y=y) for x, y in controls)
            total_points += len(sd.points)
            result.append(sd)
            series_idx += 1
        return result

    def _do_export(self) -> None:
        scatter_total = sum(len(pts) for pts in self._series_points)
        curve_total = sum(len(pts) for pts in self._curve_points)
        if scatter_total == 0 and curve_total == 0:
            QMessageBox.warning(self._host, "Export", "No data points to export.")
            return
        if self._calibration is None:
            QMessageBox.warning(self._host, "Export", "No calibration built.")
            return

        try:
            self._project.series = self._collect_series(sample_curves=True)
        except (CurveInterpolationError, ValueError, RuntimeError) as exc:
            QMessageBox.critical(
                self._host, "Export", f"Cannot export curve data:\n{exc}\n\n"
                "Curve control X values must be distinct and the sampling step must be safe."
            )
            return

        if not self._project.series:
            QMessageBox.warning(self._host, "Export", "No valid points found.")
            return

        mode_map = {0: CombinedMode.UNION_X, 1: CombinedMode.UNIFORM_GRID, 2: CombinedMode.INTERPOLATION}
        self._project.combined_mode = mode_map.get(self._combined_mode.currentIndex(), CombinedMode.UNION_X)

        default = ""
        if self._project.image_path:
            default = self._project.image_path.stem + "_digitized.xlsx"
        path, _ = QFileDialog.getSaveFileName(self._host, "Save Excel", default, "Excel (*.xlsx)")
        if not path:
            return
        try:
            export_to_excel(self._project, Path(path))
            self._status.setText(f"Saved: {path}")
            QMessageBox.information(self._host, "Export", f"Saved:\n{path}")
        except PermissionError:
            QMessageBox.critical(self._host, "Error", "File may be open in Excel.")
        except Exception as e:
            QMessageBox.critical(self._host, "Error", str(e))

    # ------------------------------------------------------------------
    # bounds management
    # ------------------------------------------------------------------
