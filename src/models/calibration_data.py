"""Data structures for axis calibration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.models.types import ScaleType


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

    def build(self) -> None:
        """Compute the linear mapping from pixel to data space."""
        if len(self.ref_points) < 2:
            raise ValueError("At least 2 reference points are required")

        import numpy as np

        pixels = np.array([rp.pixel for rp in self.ref_points])
        values = np.array([rp.data_value for rp in self.ref_points])

        if self.scale == ScaleType.LOG:
            if np.any(values <= 0):
                raise ValueError("LOG scale requires positive data values")
            values = np.log10(values)

        # Least-squares fit: value = slope * pixel + intercept
        A = np.vstack([pixels, np.ones(len(pixels))]).T
        result = np.linalg.lstsq(A, values, rcond=None)
        self._slope, self._intercept = result[0]

    def pixel_to_data(self, pixel: float) -> float:
        """Convert a pixel coordinate to data value along this axis."""
        if self._slope is None:
            raise RuntimeError("Call build() before pixel_to_data()")
        val = self._slope * pixel + self._intercept
        if self.scale == ScaleType.LOG:
            return 10.0 ** val
        return val

    def data_to_pixel(self, data_value: float) -> float:
        """Convert a data value to pixel coordinate along this axis."""
        if self._slope is None:
            raise RuntimeError("Call build() before data_to_pixel()")
        val = data_value
        if self.scale == ScaleType.LOG:
            if data_value <= 0:
                raise ValueError("LOG scale requires positive data values")
            val = __import__("math").log10(data_value)
        return (val - self._intercept) / self._slope


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
