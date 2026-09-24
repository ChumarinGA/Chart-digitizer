"""Reliable interpolation and sampling for manually digitised curves.

The interpolator is built once in *axis space*: linear axes are unchanged and
logarithmic axes use ``log10``.  Preview and export sampling therefore evaluate
the same PCHIP curve, avoiding differences between what is shown and exported.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from scipy.interpolate import PchipInterpolator

from src.models.types import ScaleType


class CurveInterpolationError(ValueError):
    """Invalid control data or sampling parameters."""


class SampleLimitError(CurveInterpolationError):
    """The requested export grid would exceed its configured size limit."""


class CurveInterpolator:
    """A shape-preserving ``y(x)`` interpolator for chart data.

    Parameters
    ----------
    x, y:
        Equal-length control-coordinate sequences.  At least two finite points
        are required.  Input order is irrelevant; points are sorted by X.
    scale_x, scale_y:
        Axis scale types.  Values on a logarithmic axis must be strictly
        positive.  Duplicate X coordinates in transformed axis space are
        rejected because they cannot define a single-valued ``y(x)`` curve.

    Notes
    -----
    ``sample_for_export(dx)`` interprets ``dx`` in the original data units of
    X, including for a logarithmic X axis.  ``sample_for_preview`` distributes
    points uniformly in transformed X space, which gives an even visual
    preview on either linear or logarithmic axes.
    """

    def __init__(
        self,
        x: Sequence[float] | np.ndarray,
        y: Sequence[float] | np.ndarray,
        scale_x: ScaleType = ScaleType.LINEAR,
        scale_y: ScaleType = ScaleType.LINEAR,
    ) -> None:
        self.scale_x = _validate_scale(scale_x, "scale_x")
        self.scale_y = _validate_scale(scale_y, "scale_y")

        control_x = _as_1d_float_array(x, "x")
        control_y = _as_1d_float_array(y, "y")
        if control_x.size != control_y.size:
            raise CurveInterpolationError("x and y must have the same length")
        if control_x.size < 2:
            raise CurveInterpolationError("at least 2 control points are required")

        transformed_x = _transform(control_x, self.scale_x, "x")
        transformed_y = _transform(control_y, self.scale_y, "y")

        order = np.argsort(transformed_x, kind="stable")
        transformed_x = transformed_x[order]
        transformed_y = transformed_y[order]
        control_x = control_x[order]
        control_y = control_y[order]

        spacing = np.diff(transformed_x)
        spacing_tolerance = (
            64.0 * np.finfo(float).eps
            * max(1.0, float(np.max(np.abs(transformed_x))))
        )
        if np.any(spacing <= spacing_tolerance):
            raise CurveInterpolationError(
                "duplicate transformed X values (or numerically indistinguishable values) are not allowed"
            )

        self._control_x = control_x
        self._control_y = control_y
        self._transformed_x = transformed_x
        self._interpolator = PchipInterpolator(
            transformed_x, transformed_y, extrapolate=False
        )

    @property
    def control_points(self) -> tuple[np.ndarray, np.ndarray]:
        """Return sorted control X/Y arrays as defensive copies."""
        return self._control_x.copy(), self._control_y.copy()

    @property
    def x_domain(self) -> tuple[float, float]:
        """Inclusive interpolation domain in original X units."""
        return float(self._control_x[0]), float(self._control_x[-1])

    def evaluate(self, x: Sequence[float] | np.ndarray) -> np.ndarray:
        """Evaluate inside the control-point domain; extrapolation is rejected."""
        values = _as_1d_float_array(x, "x")
        transformed_x = _transform(values, self.scale_x, "x")
        lo = self._transformed_x[0]
        hi = self._transformed_x[-1]
        if np.any((transformed_x < lo) | (transformed_x > hi)):
            raise CurveInterpolationError(
                f"cannot extrapolate outside X domain [{self._control_x[0]}, "
                f"{self._control_x[-1]}]"
            )
        transformed_y = np.asarray(self._interpolator(transformed_x), dtype=float)
        return _inverse_transform(transformed_y, self.scale_y)

    def sample_for_export(
        self,
        dx: float,
        max_samples: int = 1_000_000,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Sample at fixed data-X spacing and include both domain endpoints.

        A final interval shorter than ``dx`` is allowed so that the right
        endpoint is always present.  The required array size is checked before
        allocation; :class:`SampleLimitError` is raised when it is too large.
        """
        try:
            dx = float(dx)
        except (TypeError, ValueError) as exc:
            raise CurveInterpolationError("dx must be a finite positive number") from exc
        if not math.isfinite(dx) or dx <= 0.0:
            raise CurveInterpolationError("dx must be a finite positive number")
        if isinstance(max_samples, bool) or not isinstance(max_samples, int):
            raise CurveInterpolationError("max_samples must be an integer >= 2")
        if max_samples < 2:
            raise CurveInterpolationError("max_samples must be an integer >= 2")

        x_min, x_max = self.x_domain
        span = x_max - x_min
        ratio = span / dx
        if not math.isfinite(ratio):
            raise SampleLimitError(
                "requested export grid is too large to represent safely"
            )

        # Avoid a spurious extra interval when floating-point division lands a
        # few ulps above an integer (for example, 0.3 / 0.1).
        nearest = round(ratio)
        if math.isclose(ratio, nearest, rel_tol=1e-12, abs_tol=1e-12):
            ratio = float(nearest)
        intervals = int(math.ceil(ratio))
        required = intervals + 1
        if required > max_samples:
            raise SampleLimitError(
                f"export sampling requires {required} points, exceeding "
                f"max_samples={max_samples}"
            )

        # Generate only points strictly before x_max, then append the exact
        # endpoint.  This is robust for both dx > span and non-divisible spans.
        x_values = x_min + dx * np.arange(intervals, dtype=float)
        x_values = x_values[x_values < x_max]
        x_values = np.concatenate((x_values, np.array([x_max], dtype=float)))
        x_values[0] = x_min
        y_values = self.evaluate(x_values)
        y_values[[0, -1]] = self._control_y[[0, -1]]
        return x_values, y_values

    def sample_for_preview(self, n: int = 512) -> tuple[np.ndarray, np.ndarray]:
        """Return ``n`` samples uniformly spaced in transformed X space."""
        if isinstance(n, bool) or not isinstance(n, int) or n < 2:
            raise CurveInterpolationError("n must be an integer >= 2")
        transformed_x = np.linspace(
            self._transformed_x[0], self._transformed_x[-1], n, dtype=float
        )
        x_values = _inverse_transform(transformed_x, self.scale_x)
        transformed_y = np.asarray(self._interpolator(transformed_x), dtype=float)
        y_values = _inverse_transform(transformed_y, self.scale_y)
        # Preserve the user's exact endpoint values rather than round-tripped
        # log/power values.
        x_values[[0, -1]] = self._control_x[[0, -1]]
        y_values[[0, -1]] = self._control_y[[0, -1]]
        return x_values, y_values


def _validate_scale(scale: ScaleType, name: str) -> ScaleType:
    if not isinstance(scale, ScaleType):
        raise CurveInterpolationError(f"{name} must be a ScaleType")
    return scale


def _as_1d_float_array(
    values: Sequence[float] | np.ndarray,
    name: str,
) -> np.ndarray:
    try:
        array = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise CurveInterpolationError(f"{name} must contain numeric values") from exc
    if array.ndim != 1:
        raise CurveInterpolationError(f"{name} must be a one-dimensional sequence")
    if not np.all(np.isfinite(array)):
        raise CurveInterpolationError(f"{name} must contain only finite values")
    return array.copy()


def _transform(values: np.ndarray, scale: ScaleType, name: str) -> np.ndarray:
    if scale == ScaleType.LOG:
        if np.any(values <= 0.0):
            raise CurveInterpolationError(
                f"{name} values must be positive for a logarithmic axis"
            )
        transformed = np.log10(values)
    else:
        transformed = values.copy()
    if not np.all(np.isfinite(transformed)):
        raise CurveInterpolationError(
            f"{name} contains values that are non-finite in axis space"
        )
    return transformed


def _inverse_transform(values: np.ndarray, scale: ScaleType) -> np.ndarray:
    if scale == ScaleType.LOG:
        with np.errstate(over="ignore", invalid="ignore"):
            result = np.asarray(np.power(10.0, values), dtype=float)
    else:
        result = np.asarray(values, dtype=float).copy()
    if not np.all(np.isfinite(result)):
        raise CurveInterpolationError("interpolated values exceed the finite numeric range")
    return result
