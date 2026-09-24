"""Data structures for axis calibration."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Optional

import numpy as np

from src.models.types import ScaleType


_FLOAT_EPS_FACTOR = 64.0


@dataclass
class RefPoint:
    """A reference (anchor) point that maps a pixel position to a data value."""
    pixel: float
    data_value: float


@dataclass
class AxisCalibration:
    """Calibration for a single axis built from two or more reference points."""
    ref_points: list[RefPoint] = field(default_factory=list)
    scale: ScaleType = ScaleType.LINEAR

    # Computed by build(); slope/intercept of the linear fit in
    # the appropriate space (raw for LINEAR, log10 for LOG).
    _slope: Optional[float] = field(default=None, repr=False)
    _intercept: Optional[float] = field(default=None, repr=False)

    # The fit is performed in the statistically appropriate direction for
    # manually picked anchors: pixel = a * transformed_data + b.  Keep a
    # centred representation as well as the legacy inverse coefficients above
    # to avoid cancellation for axes with a large data offset.
    _pixel_per_value: Optional[float] = field(default=None, init=False, repr=False)
    _value_center: Optional[float] = field(default=None, init=False, repr=False)
    _pixel_center: Optional[float] = field(default=None, init=False, repr=False)

    # Fit diagnostics.  A residual is observed_pixel - fitted_pixel.
    rmse_pixels: Optional[float] = field(default=None, init=False)
    max_error_pixels: Optional[float] = field(default=None, init=False)
    residuals_pixels: list[float] = field(default_factory=list, init=False)

    @property
    def n_points(self) -> int:
        """Number of reference points supplied for this axis."""
        return len(self.ref_points)

    def _reset_fit(self) -> None:
        """Remove both coefficients and diagnostics from a previous build."""
        self._slope = None
        self._intercept = None
        self._pixel_per_value = None
        self._value_center = None
        self._pixel_center = None
        self.rmse_pixels = None
        self.max_error_pixels = None
        self.residuals_pixels = []

    @staticmethod
    def _span_tolerance(values: np.ndarray) -> float:
        """Numerical, rather than domain-specific, minimum usable span."""
        magnitude = max(1.0, float(np.max(np.abs(values))))
        return _FLOAT_EPS_FACTOR * np.finfo(float).eps * magnitude

    def build(self) -> None:
        """Fit the calibration and calculate pixel-space diagnostics.

        Reference-point uncertainty normally comes from locating a feature in
        the raster image.  Consequently the regression is fitted as
        ``pixel = a * transformed_data + b``.  ``transformed_data`` is the raw
        value for a linear scale and ``log10(value)`` for a logarithmic scale.

        ``_slope`` and ``_intercept`` retain their historical meaning:
        ``transformed_data = _slope * pixel + _intercept``.
        """
        self._reset_fit()

        if len(self.ref_points) < 2:
            raise ValueError("At least 2 reference points are required")

        try:
            pixels = np.asarray([rp.pixel for rp in self.ref_points], dtype=float)
            values = np.asarray([rp.data_value for rp in self.ref_points], dtype=float)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Reference points must contain real numeric values") from exc

        if not np.all(np.isfinite(pixels)):
            raise ValueError("Reference pixel positions must all be finite")
        if not np.all(np.isfinite(values)):
            raise ValueError("Reference data values must all be finite")

        if self.scale == ScaleType.LOG:
            if np.any(values <= 0):
                raise ValueError("LOG scale requires positive data values")
            values = np.log10(values)

        if not np.all(np.isfinite(values)):
            raise ValueError("Transformed reference data values must all be finite")
        if np.unique(pixels).size < 2:
            raise ValueError("At least 2 distinct reference pixel positions are required")
        if np.unique(values).size < 2:
            raise ValueError("At least 2 distinct transformed data values are required")

        pixel_span = float(np.ptp(pixels))
        value_span = float(np.ptp(values))
        if not math.isfinite(pixel_span) or pixel_span <= self._span_tolerance(pixels):
            raise ValueError("Reference pixel span is zero or too small for a stable calibration")
        if not math.isfinite(value_span) or value_span <= self._span_tolerance(values):
            raise ValueError("Transformed data span is zero or too small for a stable calibration")

        pixel_center = float(np.mean(pixels))
        value_center = float(np.mean(values))
        if not math.isfinite(pixel_center) or not math.isfinite(value_center):
            raise ValueError("Reference-point magnitude is too large for a stable calibration")

        # Scaling both centred variables makes the least-squares calculation
        # insensitive to units and large coordinate offsets while leaving the
        # fitted line unchanged.
        scaled_values = (values - value_center) / value_span
        scaled_pixels = (pixels - pixel_center) / pixel_span
        denominator = float(np.dot(scaled_values, scaled_values))
        if not math.isfinite(denominator) or denominator <= np.finfo(float).eps:
            raise ValueError("Transformed data span is ill-conditioned")

        normalised_slope = float(
            np.dot(scaled_values, scaled_pixels) / denominator
        )
        slope_tolerance = _FLOAT_EPS_FACTOR * np.finfo(float).eps
        if (
            not math.isfinite(normalised_slope)
            or abs(normalised_slope) <= slope_tolerance
        ):
            raise ValueError("Calibration slope is zero or ill-conditioned")

        pixel_per_value = normalised_slope * pixel_span / value_span
        if not math.isfinite(pixel_per_value) or pixel_per_value == 0.0:
            raise ValueError("Calibration slope is zero or outside the finite numeric range")

        legacy_slope = 1.0 / pixel_per_value
        legacy_intercept = value_center - legacy_slope * pixel_center
        if not math.isfinite(legacy_slope) or not math.isfinite(legacy_intercept):
            raise ValueError("Inverse calibration is ill-conditioned")

        fitted_pixels = pixel_center + pixel_per_value * (values - value_center)
        residuals = pixels - fitted_pixels
        if not np.all(np.isfinite(residuals)):
            raise ValueError("Calibration residuals are outside the finite numeric range")

        # Commit only after every validation succeeds, so a failed rebuild
        # cannot leave a partially valid or stale calibration behind.
        self._pixel_per_value = float(pixel_per_value)
        self._value_center = value_center
        self._pixel_center = pixel_center
        self._slope = float(legacy_slope)
        self._intercept = float(legacy_intercept)
        self.residuals_pixels = [float(v) for v in residuals]
        self.rmse_pixels = float(np.sqrt(np.mean(np.square(residuals))))
        self.max_error_pixels = float(np.max(np.abs(residuals)))

    def pixel_to_data(self, pixel: float) -> float:
        """Convert a pixel coordinate to data value along this axis."""
        if (
            self._slope is None
            or self._pixel_per_value is None
            or self._value_center is None
            or self._pixel_center is None
        ):
            raise RuntimeError("Call build() before pixel_to_data()")
        if not math.isfinite(pixel):
            raise ValueError("Pixel coordinate must be finite")

        val = self._value_center + (pixel - self._pixel_center) / self._pixel_per_value
        if not math.isfinite(val):
            raise ValueError("Converted data value is outside the finite numeric range")
        if self.scale == ScaleType.LOG:
            try:
                result = 10.0 ** val
            except OverflowError as exc:
                raise ValueError("Converted logarithmic value is outside the finite numeric range") from exc
            if not math.isfinite(result):
                raise ValueError("Converted logarithmic value is outside the finite numeric range")
            return float(result)
        return float(val)

    def data_to_pixel(self, data_value: float) -> float:
        """Convert a data value to pixel coordinate along this axis."""
        if (
            self._slope is None
            or self._pixel_per_value is None
            or self._value_center is None
            or self._pixel_center is None
        ):
            raise RuntimeError("Call build() before data_to_pixel()")
        if not math.isfinite(data_value):
            raise ValueError("Data value must be finite")

        val = data_value
        if self.scale == ScaleType.LOG:
            if data_value <= 0:
                raise ValueError("LOG scale requires positive data values")
            val = math.log10(data_value)

        pixel = self._pixel_center + self._pixel_per_value * (val - self._value_center)
        if not math.isfinite(pixel):
            raise ValueError("Converted pixel coordinate is outside the finite numeric range")
        return float(pixel)


@dataclass
class CalibrationResult:
    """Complete calibration for both axes of a 2-D chart."""
    x_axis: AxisCalibration = field(default_factory=AxisCalibration)
    y_axis: AxisCalibration = field(default_factory=AxisCalibration)

    def build(self) -> None:
        self.x_axis.build()
        self.y_axis.build()

    def pixel_to_data(self, px: float, py: float) -> tuple[float, float]:
        return self.x_axis.pixel_to_data(px), self.y_axis.pixel_to_data(py)

    def data_to_pixel(self, dx: float, dy: float) -> tuple[float, float]:
        return self.x_axis.data_to_pixel(dx), self.y_axis.data_to_pixel(dy)
