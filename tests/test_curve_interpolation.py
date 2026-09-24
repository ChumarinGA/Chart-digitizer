import numpy as np
import pytest

from src.core.curve_interpolation import (
    CurveInterpolationError,
    CurveInterpolator,
    SampleLimitError,
)
from src.models.types import ScaleType


@pytest.mark.parametrize(
    ("dx", "expected_x"),
    [
        (0.3, [0.0, 0.3, 0.6, 0.9, 1.0]),
        (10.0, [0.0, 1.0]),
    ],
)
def test_export_sampling_always_includes_both_endpoints(dx, expected_x):
    curve = CurveInterpolator([1.0, 0.0], [1.0, 0.0])

    x, y = curve.sample_for_export(dx)

    np.testing.assert_allclose(x, expected_x)
    np.testing.assert_allclose(y, expected_x)
    assert x[0] == 0.0
    assert x[-1] == 1.0


def test_duplicate_x_is_rejected_after_sorting():
    with pytest.raises(CurveInterpolationError, match="duplicate transformed X"):
        CurveInterpolator([1.0, 0.0, 1.0], [1.0, 0.0, 2.0])


def test_log_axes_are_interpolated_in_log10_space():
    curve = CurveInterpolator(
        [100.0, 1.0, 10.0],
        [10_000.0, 1.0, 100.0],
        scale_x=ScaleType.LOG,
        scale_y=ScaleType.LOG,
    )

    preview_x, preview_y = curve.sample_for_preview(5)
    evaluated = curve.evaluate([np.sqrt(10.0), 10.0 * np.sqrt(10.0)])

    np.testing.assert_allclose(preview_x, [1.0, np.sqrt(10.0), 10.0, 10.0 * np.sqrt(10.0), 100.0])
    np.testing.assert_allclose(preview_y, preview_x**2)
    np.testing.assert_allclose(evaluated, [10.0, 1_000.0])


@pytest.mark.parametrize("axis", ["x", "y"])
def test_log_axis_rejects_nonpositive_values(axis):
    kwargs = {"scale_x": ScaleType.LOG} if axis == "x" else {"scale_y": ScaleType.LOG}
    x = [0.0, 1.0] if axis == "x" else [1.0, 2.0]
    y = [1.0, 2.0] if axis == "x" else [0.0, 1.0]

    with pytest.raises(CurveInterpolationError, match="positive"):
        CurveInterpolator(x, y, **kwargs)


def test_pchip_is_monotone_and_does_not_overshoot_control_range():
    curve = CurveInterpolator([3.0, 0.0, 2.0, 1.0], [4.0, 0.0, 3.0, 2.0])

    _, y = curve.sample_for_preview(2001)

    assert np.all(np.diff(y) >= 0.0)
    assert y.min() >= 0.0
    assert y.max() <= 4.0


def test_export_sampling_checks_limit_before_allocation():
    curve = CurveInterpolator([0.0, 100.0], [0.0, 1.0])

    with pytest.raises(SampleLimitError, match=r"requires 10001 points.*max_samples=10000"):
        curve.sample_for_export(0.01, max_samples=10_000)


def test_extrapolation_is_rejected():
    curve = CurveInterpolator([0.0, 1.0], [0.0, 1.0])

    with pytest.raises(CurveInterpolationError, match="cannot extrapolate"):
        curve.evaluate([-0.01, 0.5])


@pytest.mark.parametrize(
    ("x", "y"),
    [([0.0, np.nan], [0.0, 1.0]), ([0.0, 1.0], [0.0, np.inf])],
)
def test_nonfinite_control_values_are_rejected(x, y):
    with pytest.raises(CurveInterpolationError, match="finite"):
        CurveInterpolator(x, y)
