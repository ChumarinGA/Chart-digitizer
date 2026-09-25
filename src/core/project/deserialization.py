"""Restoration of project model objects from JSON-compatible dictionaries."""

from __future__ import annotations

from pathlib import Path

from src.core.project.validation import _bounded_finite_float, _bounded_percent
from src.models.calibration_data import AxisCalibration, CalibrationResult, RefPoint
from src.models.project_data import AppSettings, ProjectState
from src.models.series_data import ExtractedPoint, SeriesData
from src.models.types import CombinedMode, ExtractionMode, ScaleType, SeriesKind


def _deserialise(data: dict) -> ProjectState:
    state = ProjectState()
    if data.get("image_path"):
        state.image_path = Path(data["image_path"])
    if data.get("crop_rect"):
        state.crop_rect = tuple(data["crop_rect"])
    state.calibration = _deser_calibration(data.get("calibration", {}))
    state.series = [_deser_series(series) for series in data.get("series", [])]
    state.calibration_anchors = [
        (
            float(anchor["x"]),
            float(anchor["y"]),
            None if anchor.get("x_value") is None else float(anchor["x_value"]),
            None if anchor.get("y_value") is None else float(anchor["y_value"]),
            str(anchor.get("axis", "Both")),
        )
        for anchor in data.get("calibration_anchors", [])
    ]
    state.scatter_points_px = [
        [(float(point[0]), float(point[1])) for point in points]
        for points in data.get("scatter_points_px", [])
    ]
    state.curve_points_px = [
        [(float(point[0]), float(point[1])) for point in points]
        for points in data.get("curve_points_px", [])
    ]
    state.scatter_point_styles = _deser_point_styles(
        data.get("scatter_point_styles", []), ("CIRCLE", 5.0)
    )
    state.curve_point_styles = _deser_point_styles(
        data.get("curve_point_styles", []), ("CIRCLE", 4.0)
    )
    state.curve_visual_styles = _deser_curve_visual_styles(
        data.get("curve_visual_styles", [])
    )
    state.scatter_default_point_style = _deser_default_point_style(
        data.get("scatter_default_point_style"), ("CIRCLE", 5.0)
    )
    state.curve_default_point_style = _deser_default_point_style(
        data.get("curve_default_point_style"), ("CIRCLE", 4.0)
    )
    state.scatter_active_fill_opacity = _bounded_percent(
        data.get("scatter_active_fill_opacity", 15), 15
    )
    state.curve_active_fill_opacity = _bounded_percent(
        data.get("curve_active_fill_opacity", 15), 15
    )
    try:
        state.curve_default_thickness = _bounded_finite_float(
            data.get("curve_default_thickness", 2.0), 2.0, 0.5, 50.0
        )
    except (TypeError, ValueError):
        state.curve_default_thickness = 2.0
    state.combined_mode = CombinedMode[data.get("combined_mode", "UNION_X")]
    if data.get("settings"):
        state.settings = _deser_settings(data["settings"])
    return state


def _deser_calibration(data: dict) -> CalibrationResult:
    calibration = CalibrationResult()
    if "x_axis" in data:
        calibration.x_axis = _deser_axis(data["x_axis"])
    if "y_axis" in data:
        calibration.y_axis = _deser_axis(data["y_axis"])
    if (
        len(calibration.x_axis.ref_points) >= 2
        and len(calibration.y_axis.ref_points) >= 2
    ):
        calibration.build()
    return calibration


def _deser_axis(data: dict) -> AxisCalibration:
    return AxisCalibration(
        scale=ScaleType[data.get("scale", "LINEAR")],
        ref_points=[
            RefPoint(pixel=point["pixel"], data_value=point["data_value"])
            for point in data.get("ref_points", [])
        ],
    )


def _deser_series(data: dict) -> SeriesData:
    series = SeriesData(
        index=data["index"],
        name=data.get("name", ""),
        kind=SeriesKind[data.get("kind", "CONTINUOUS")],
        mode=ExtractionMode[data.get("mode", "AUTO")],
    )
    if data.get("color_hint"):
        series.color_hint = tuple(data["color_hint"])
    series.points = [
        ExtractedPoint(x=point["x"], y=point["y"])
        for point in data.get("points", [])
    ]
    return series


def _deser_point_styles(
    raw: object, fallback: tuple[str, float]
) -> list[list[tuple[str, float]]]:
    result: list[list[tuple[str, float]]] = []
    if not isinstance(raw, list):
        return result
    for raw_series in raw:
        styles: list[tuple[str, float]] = []
        if isinstance(raw_series, list):
            for raw_style in raw_series:
                if not isinstance(raw_style, dict):
                    # Style arrays are positional. Keep a placeholder so one
                    # damaged entry cannot shift every following style.
                    styles.append(fallback)
                    continue
                size = _bounded_finite_float(
                    raw_style.get("size", fallback[1]),
                    fallback[1],
                    1.0,
                    50.0,
                )
                styles.append((str(raw_style.get("shape", fallback[0])), size))
        result.append(styles)
    return result


def _deser_default_point_style(
    raw: object, fallback: tuple[str, float]
) -> tuple[str, float]:
    if not isinstance(raw, dict):
        return fallback
    try:
        return (
            str(raw.get("shape", fallback[0])),
            _bounded_finite_float(
                raw.get("size", fallback[1]), fallback[1], 1.0, 50.0
            ),
        )
    except (TypeError, ValueError):
        return fallback


def _deser_curve_visual_styles(raw: object) -> list[tuple[str, float, str]]:
    result: list[tuple[str, float, str]] = []
    if not isinstance(raw, list):
        return result
    for style in raw:
        if not isinstance(style, dict):
            # Curve styles are positional. Keep a placeholder so a damaged
            # entry cannot shift a later curve's colour or pattern.
            result.append(("#ffff5050", 2.0, "SolidLine"))
            continue
        raw_line_style = style.get("line_style", "SolidLine")
        if isinstance(raw_line_style, str):
            line_style = raw_line_style
        else:
            # Backward compatibility with the short-lived numeric schema.
            try:
                line_style = {
                    1: "SolidLine",
                    2: "DashLine",
                    3: "DotLine",
                    4: "DashDotLine",
                    5: "DashDotDotLine",
                }.get(int(raw_line_style), "SolidLine")
            except (TypeError, ValueError):
                line_style = "SolidLine"
        if line_style not in {
            "SolidLine",
            "DashLine",
            "DotLine",
            "DashDotLine",
            "DashDotDotLine",
        }:
            line_style = "SolidLine"
        result.append(
            (
                str(style.get("color", "#ffff5050")),
                _bounded_finite_float(
                    style.get("thickness", 2.0), 2.0, 0.5, 50.0
                ),
                line_style,
            )
        )
    return result


def _deser_settings(data: dict) -> AppSettings:
    settings = AppSettings()
    if "x_scale" in data:
        settings.x_scale = ScaleType[data["x_scale"]]
    if "y_scale" in data:
        settings.y_scale = ScaleType[data["y_scale"]]
    for attr in (
        "n_calibration_points",
        "segmentation_sensitivity",
        "min_curve_length",
        "max_line_thickness",
        "skeletonize",
        "curve_step_dx",
        "min_marker_area",
        "max_marker_area",
        "marker_center_sensitivity",
        "arrow_step",
        "ctrl_step",
        "shift_step",
        "snap_to_edge",
        "magnifier_enabled",
    ):
        if attr in data:
            setattr(settings, attr, data[attr])
    return settings


__all__ = [
    "_deser_axis",
    "_deser_calibration",
    "_deser_curve_visual_styles",
    "_deser_default_point_style",
    "_deser_point_styles",
    "_deser_series",
    "_deser_settings",
    "_deserialise",
]
