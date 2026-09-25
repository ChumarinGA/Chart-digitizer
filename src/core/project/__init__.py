"""Stable project persistence API and compatibility exports."""

from pathlib import Path
from typing import Any

from src.core.project.api import PROJECT_EXT, load_project, save_project
from src.core.project.deserialization import (
    _deser_axis,
    _deser_calibration,
    _deser_curve_visual_styles,
    _deser_default_point_style,
    _deser_point_styles,
    _deser_series,
    _deser_settings,
    _deserialise,
)
from src.core.project.serialization import (
    _ser_axis,
    _ser_calibration,
    _ser_series,
    _ser_settings,
    _serialise,
)
from src.core.project.validation import _bounded_finite_float, _bounded_percent
from src.models.calibration_data import AxisCalibration, CalibrationResult, RefPoint
from src.models.project_data import AppSettings, ProjectState
from src.models.series_data import ExtractedPoint, SeriesData
from src.models.types import CombinedMode, ExtractionMode, ScaleType, SeriesKind

__all__ = [
    "PROJECT_EXT",
    "Any",
    "AppSettings",
    "AxisCalibration",
    "CalibrationResult",
    "CombinedMode",
    "ExtractedPoint",
    "ExtractionMode",
    "Path",
    "ProjectState",
    "RefPoint",
    "ScaleType",
    "SeriesData",
    "SeriesKind",
    "_bounded_finite_float",
    "_bounded_percent",
    "_deser_axis",
    "_deser_calibration",
    "_deser_curve_visual_styles",
    "_deser_default_point_style",
    "_deser_point_styles",
    "_deser_series",
    "_deser_settings",
    "_deserialise",
    "_ser_axis",
    "_ser_calibration",
    "_ser_series",
    "_ser_settings",
    "_serialise",
    "load_project",
    "save_project",
]
