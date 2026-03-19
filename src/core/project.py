"""Save / load digitisation sessions to a JSON-based project file."""

from __future__ import annotations

import json
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
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


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
        "combined_mode": state.combined_mode.name,
        "settings": _ser_settings(state.settings),
    }


def _ser_calibration(cal: CalibrationResult) -> dict:
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
    if cal.x_axis.ref_points and cal.y_axis.ref_points:
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
