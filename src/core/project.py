"""Save / load digitisation sessions to a JSON-based project file."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from src.models.calibration_data import (
    AxisCalibration,
    CalibrationResult,
    RefPoint,
)
from src.models.project_data import AppSettings, ProjectState
from src.models.series_data import ExtractedPoint, SeriesData
from src.models.types import (
    CombinedMode,
    ExtractionMode,
    ScaleType,
    SeriesKind,
)

PROJECT_EXT = ".digitizer"


def save_project(state: ProjectState, path: Path) -> None:
    data = _serialise(state)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )


def load_project(path: Path) -> ProjectState:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _deserialise(raw)


# ---- Serialisation ----

def _serialise(state: ProjectState) -> dict[str, Any]:
    return {
        "image_path": str(state.image_path) if state.image_path else None,
        "crop_rect": list(state.crop_rect) if state.crop_rect else None,
        "calibration": _ser_calibration(state.calibration),
        "series": [_ser_series(s) for s in state.series],
        "calibration_anchors": [
            {"x": x, "y": y, "x_value": xv, "y_value": yv, "axis": axis}
            for x, y, xv, yv, axis in state.calibration_anchors
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


def _ser_calibration(cal: CalibrationResult | None) -> dict:
    if cal is None:
        return {}
    return {
        "x_axis": _ser_axis(cal.x_axis),
        "y_axis": _ser_axis(cal.y_axis),
    }


def _ser_axis(ax: AxisCalibration) -> dict:
    return {
        "scale": ax.scale.name,
        "ref_points": [{"pixel": rp.pixel, "data_value": rp.data_value} for rp in ax.ref_points],
    }


def _ser_series(sd: SeriesData) -> dict:
    return {
        "index": sd.index,
        "name": sd.name,
        "kind": sd.kind.name,
        "mode": sd.mode.name,
        "color_hint": list(sd.color_hint) if sd.color_hint else None,
        "points": [{"x": p.x, "y": p.y} for p in sd.points],
    }


def _ser_settings(s: AppSettings) -> dict:
    return {
        "x_scale": s.x_scale.name,
        "y_scale": s.y_scale.name,
        "n_calibration_points": s.n_calibration_points,
        "segmentation_sensitivity": s.segmentation_sensitivity,
        "min_curve_length": s.min_curve_length,
        "max_line_thickness": s.max_line_thickness,
        "skeletonize": s.skeletonize,
        "curve_step_dx": s.curve_step_dx,
        "min_marker_area": s.min_marker_area,
        "max_marker_area": s.max_marker_area,
        "marker_center_sensitivity": s.marker_center_sensitivity,
        "arrow_step": s.arrow_step,
        "ctrl_step": s.ctrl_step,
        "shift_step": s.shift_step,
        "snap_to_edge": s.snap_to_edge,
        "magnifier_enabled": s.magnifier_enabled,
    }


# ---- Deserialisation ----

def _deserialise(data: dict) -> ProjectState:
    state = ProjectState()
    if data.get("image_path"):
        state.image_path = Path(data["image_path"])
    if data.get("crop_rect"):
        state.crop_rect = tuple(data["crop_rect"])
    state.calibration = _deser_calibration(data.get("calibration", {}))
    state.series = [_deser_series(s) for s in data.get("series", [])]
    state.calibration_anchors = [
        (
            float(anchor["x"]), float(anchor["y"]),
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


def _deser_calibration(d: dict) -> CalibrationResult:
    cal = CalibrationResult()
    if "x_axis" in d:
        cal.x_axis = _deser_axis(d["x_axis"])
    if "y_axis" in d:
        cal.y_axis = _deser_axis(d["y_axis"])
    if len(cal.x_axis.ref_points) >= 2 and len(cal.y_axis.ref_points) >= 2:
        cal.build()
    return cal


def _deser_axis(d: dict) -> AxisCalibration:
    return AxisCalibration(
        scale=ScaleType[d.get("scale", "LINEAR")],
        ref_points=[RefPoint(pixel=rp["pixel"], data_value=rp["data_value"]) for rp in d.get("ref_points", [])],
    )


def _deser_series(d: dict) -> SeriesData:
    sd = SeriesData(
        index=d["index"],
        name=d.get("name", ""),
        kind=SeriesKind[d.get("kind", "CONTINUOUS")],
        mode=ExtractionMode[d.get("mode", "AUTO")],
    )
    if d.get("color_hint"):
        sd.color_hint = tuple(d["color_hint"])
    sd.points = [ExtractedPoint(x=p["x"], y=p["y"]) for p in d.get("points", [])]
    return sd


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
                    # Style arrays are positional.  Keep a placeholder so one
                    # damaged entry cannot apply every following style to the
                    # wrong point.
                    styles.append(fallback)
                    continue
                size = _bounded_finite_float(
                    raw_style.get("size", fallback[1]), fallback[1], 1.0, 50.0
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
            _bounded_finite_float(raw.get("size", fallback[1]), fallback[1], 1.0, 50.0),
        )
    except (TypeError, ValueError):
        return fallback


def _deser_curve_visual_styles(raw: object) -> list[tuple[str, float, str]]:
    result: list[tuple[str, float, str]] = []
    if not isinstance(raw, list):
        return result
    for style in raw:
        if not isinstance(style, dict):
            # Curve styles are also positional; never shift a later curve's
            # colour/pattern onto an earlier one when a file is partly corrupt.
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
            "SolidLine", "DashLine", "DotLine", "DashDotLine", "DashDotDotLine"
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


def _bounded_finite_float(
    raw: object, default: float, lower: float, upper: float
) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return max(lower, min(value, upper))


def _bounded_percent(raw: object, default: int) -> int:
    """Read a persisted percentage without accepting NaN/Inf."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return int(round(max(0.0, min(100.0, value))))


def _deser_settings(d: dict) -> AppSettings:
    s = AppSettings()
    if "x_scale" in d:
        s.x_scale = ScaleType[d["x_scale"]]
    if "y_scale" in d:
        s.y_scale = ScaleType[d["y_scale"]]
    for attr in (
        "n_calibration_points", "segmentation_sensitivity", "min_curve_length",
        "max_line_thickness", "skeletonize", "curve_step_dx",
        "min_marker_area", "max_marker_area", "marker_center_sensitivity",
        "arrow_step", "ctrl_step", "shift_step", "snap_to_edge", "magnifier_enabled",
    ):
        if attr in d:
            setattr(s, attr, d[attr])
    return s
