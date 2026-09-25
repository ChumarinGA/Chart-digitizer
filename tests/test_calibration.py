"""Focused tests for linear and logarithmic axis calibration."""

from __future__ import annotations

import math

import pytest

from src.core.calibration import build_calibration
from src.models.calibration_data import AxisCalibration, RefPoint
from src.models.types import ScaleType


def _axis(points: list[tuple[float, float]], scale: ScaleType = ScaleType.LINEAR) -> AxisCalibration:
    calibration = AxisCalibration(
        ref_points=[RefPoint(pixel=pixel, data_value=value) for pixel, value in points],
        scale=scale,
    )
    calibration.build()
    return calibration


def test_linear_fit_and_legacy_coefficients() -> None:
    axis = _axis([(10.0, 0.0), (60.0, 5.0), (110.0, 10.0)])

    assert axis.n_points == 3
    assert axis.is_built
    assert axis.transformed_units_per_pixel == pytest.approx(0.1)
    assert axis.pixel_to_data(35.0) == pytest.approx(2.5)
    assert axis.data_to_pixel(7.5) == pytest.approx(85.0)
    assert axis._slope == pytest.approx(0.1)
    assert axis._intercept == pytest.approx(-1.0)
    assert axis.rmse_pixels == pytest.approx(0.0, abs=1e-12)
    assert axis.max_error_pixels == pytest.approx(0.0, abs=1e-12)
    assert axis.residuals_pixels == pytest.approx([0.0, 0.0, 0.0], abs=1e-12)


def test_fit_is_least_squares_in_pixel_space_and_reports_residuals() -> None:
    # For values 0, 1, 2 the pixel-space OLS fit is p = 2*v + 4/3.
    axis = _axis([(1.0, 0.0), (4.0, 1.0), (5.0, 2.0)])

    expected_residuals = [-1.0 / 3.0, 2.0 / 3.0, -1.0 / 3.0]
    assert axis.data_to_pixel(0.0) == pytest.approx(4.0 / 3.0)
    assert axis.data_to_pixel(2.0) == pytest.approx(16.0 / 3.0)
    assert axis.residuals_pixels == pytest.approx(expected_residuals)
    assert axis.rmse_pixels == pytest.approx(math.sqrt(2.0 / 9.0))
    assert axis.max_error_pixels == pytest.approx(2.0 / 3.0)


def test_logarithmic_fit_and_roundtrip() -> None:
    axis = _axis(
        [(20.0, 0.1), (120.0, 1.0), (220.0, 10.0), (320.0, 100.0)],
        ScaleType.LOG,
    )

    assert axis.pixel_to_data(170.0) == pytest.approx(math.sqrt(10.0))
    assert axis.data_to_pixel(10.0) == pytest.approx(220.0)
    for value in (0.1, 0.25, 1.0, 7.5, 100.0):
        assert axis.pixel_to_data(axis.data_to_pixel(value)) == pytest.approx(value)


def test_complete_calibration_roundtrip() -> None:
    calibration = build_calibration(
        [(10.0, -5.0), (210.0, 15.0)],
        [(300.0, 0.01), (100.0, 100.0)],
        ScaleType.LINEAR,
        ScaleType.LOG,
    )

    assert calibration.is_built
    pixel = calibration.data_to_pixel(2.5, 1.0)
    assert pixel == pytest.approx((85.0, 200.0))
    assert calibration.pixel_to_data(*pixel) == pytest.approx((2.5, 1.0))


@pytest.mark.parametrize(
    ("points", "message"),
    [
        ([(1.0, 0.0)], "At least 2 reference points"),
        ([(1.0, 0.0), (1.0, 2.0)], "distinct reference pixel positions"),
        ([(1.0, 2.0), (3.0, 2.0)], "distinct transformed data values"),
        ([(1.0, 0.0), (1.0 + 1e-15, 1.0)], "pixel span"),
        ([(0.0, 0.0), (1.0, 1.0), (0.0, 2.0)], "slope is zero"),
    ],
)
def test_degenerate_calibrations_are_rejected(
    points: list[tuple[float, float]], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _axis(points)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_reference_pixels_are_rejected(bad: float) -> None:
    with pytest.raises(ValueError, match="pixel positions must all be finite"):
        _axis([(0.0, 0.0), (bad, 1.0)])


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_reference_values_are_rejected(bad: float) -> None:
    with pytest.raises(ValueError, match="data values must all be finite"):
        _axis([(0.0, 0.0), (1.0, bad)])


@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_logarithmic_calibration_requires_positive_values(bad: float) -> None:
    with pytest.raises(ValueError, match="LOG scale requires positive"):
        _axis([(0.0, 1.0), (1.0, bad)], ScaleType.LOG)


def test_failed_rebuild_clears_previous_fit_and_diagnostics() -> None:
    axis = _axis([(0.0, 0.0), (10.0, 1.0)])
    axis.ref_points = [RefPoint(pixel=0.0, data_value=0.0)]

    with pytest.raises(ValueError):
        axis.build()

    assert axis._slope is None
    assert axis._intercept is None
    assert not axis.is_built
    assert axis.rmse_pixels is None
    assert axis.max_error_pixels is None
    assert axis.residuals_pixels == []
    with pytest.raises(RuntimeError, match="Call build"):
        axis.pixel_to_data(0.0)
    with pytest.raises(RuntimeError, match="Call build"):
        _ = axis.transformed_units_per_pixel
