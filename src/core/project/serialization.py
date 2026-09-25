"""Conversion of project model objects to JSON-compatible dictionaries."""

from __future__ import annotations

from typing import Any

from src.models.calibration_data import AxisCalibration, CalibrationResult
from src.models.project_data import AppSettings, ProjectState
from src.models.series_data import SeriesData


def _serialise(state: ProjectState) -> dict[str, Any]:
    return {
        "image_path": str(state.image_path) if state.image_path else None,
        "crop_rect": list(state.crop_rect) if state.crop_rect else None,
        "calibration": _ser_calibration(state.calibration),
        "series": [_ser_series(series) for series in state.series],
        "calibration_anchors": [
            {"x": x, "y": y, "x_value": x_value, "y_value": y_value, "axis": axis}
            for x, y, x_value, y_value, axis in state.calibration_anchors
        ],
        "scatter_points_px": [
            [[x, y] for x, y in points] for points in state.scatter_points_px
        ],
        "curve_points_px": [
            [[x, y] for x, y in points] for points in state.curve_points_px
        ],
        "scatter_point_styles": [
            [{"shape": shape, "size": size} for shape, size in styles]
            for styles in state.scatter_point_styles
        ],
        "curve_point_styles": [
            [{"shape": shape, "size": size} for shape, size in styles]
            for styles in state.curve_point_styles
        ],
        "curve_visual_styles": [
            {"color": color, "thickness": thickness, "line_style": line_style}
            for color, thickness, line_style in state.curve_visual_styles
        ],
        "scatter_default_point_style": {
            "shape": state.scatter_default_point_style[0],
            "size": state.scatter_default_point_style[1],
        },
        "curve_default_point_style": {
            "shape": state.curve_default_point_style[0],
            "size": state.curve_default_point_style[1],
        },
        "scatter_active_fill_opacity": state.scatter_active_fill_opacity,
        "curve_active_fill_opacity": state.curve_active_fill_opacity,
        "curve_default_thickness": state.curve_default_thickness,
        "combined_mode": state.combined_mode.name,
        "settings": _ser_settings(state.settings),
    }


def _ser_calibration(calibration: CalibrationResult | None) -> dict:
    if calibration is None:
        return {}
    return {
        "x_axis": _ser_axis(calibration.x_axis),
        "y_axis": _ser_axis(calibration.y_axis),
    }


def _ser_axis(axis: AxisCalibration) -> dict:
    return {
        "scale": axis.scale.name,
        "ref_points": [
            {"pixel": point.pixel, "data_value": point.data_value}
            for point in axis.ref_points
        ],
    }


def _ser_series(series: SeriesData) -> dict:
    return {
        "index": series.index,
        "name": series.name,
        "kind": series.kind.name,
        "mode": series.mode.name,
        "color_hint": list(series.color_hint) if series.color_hint else None,
        "points": [{"x": point.x, "y": point.y} for point in series.points],
    }


def _ser_settings(settings: AppSettings) -> dict:
    return {
        "x_scale": settings.x_scale.name,
        "y_scale": settings.y_scale.name,
        "n_calibration_points": settings.n_calibration_points,
        "segmentation_sensitivity": settings.segmentation_sensitivity,
        "min_curve_length": settings.min_curve_length,
        "max_line_thickness": settings.max_line_thickness,
        "skeletonize": settings.skeletonize,
        "curve_step_dx": settings.curve_step_dx,
        "min_marker_area": settings.min_marker_area,
        "max_marker_area": settings.max_marker_area,
        "marker_center_sensitivity": settings.marker_center_sensitivity,
        "arrow_step": settings.arrow_step,
        "ctrl_step": settings.ctrl_step,
        "shift_step": settings.shift_step,
        "snap_to_edge": settings.snap_to_edge,
        "magnifier_enabled": settings.magnifier_enabled,
    }


__all__ = [
    "_ser_axis",
    "_ser_calibration",
    "_ser_series",
    "_ser_settings",
    "_serialise",
]
