"""High-level helpers for building and using axis calibrations."""

from __future__ import annotations

from src.models.calibration_data import (
    AxisCalibration,
    CalibrationResult,
    RefPoint,
)
from src.models.types import ScaleType


def build_calibration(
    ref_points_x: list[tuple[float, float]],
    ref_points_y: list[tuple[float, float]],
    scale_x: ScaleType = ScaleType.LINEAR,
    scale_y: ScaleType = ScaleType.LINEAR,
) -> CalibrationResult:
    """Build a CalibrationResult from raw reference point pairs.

    Parameters
    ----------
    ref_points_x : list of (pixel, data_value)
        At least 2 anchor points for the X axis.
    ref_points_y : list of (pixel, data_value)
        At least 2 anchor points for the Y axis.
    scale_x, scale_y : ScaleType
        Scale types for the respective axes.
    """
    x_axis = AxisCalibration(
        ref_points=[RefPoint(pixel=p, data_value=d) for p, d in ref_points_x],
        scale=scale_x,
    )
    y_axis = AxisCalibration(
        ref_points=[RefPoint(pixel=p, data_value=d) for p, d in ref_points_y],
        scale=scale_y,
    )
    cal = CalibrationResult(x_axis=x_axis, y_axis=y_axis)
    cal.build()
    return cal


def pixel_to_data(
    px: float,
    py: float,
    calibration: CalibrationResult,
) -> tuple[float, float]:
    """Convenience wrapper."""
    return calibration.pixel_to_data(px, py)


def data_to_pixel(
    dx: float,
    dy: float,
    calibration: CalibrationResult,
) -> tuple[float, float]:
    """Convenience wrapper."""
    return calibration.data_to_pixel(dx, dy)
