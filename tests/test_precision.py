import numpy as np
import pytest

from src.core.precision import snap_to_stroke_center


def test_even_width_vertical_stroke_returns_geometric_scene_centre() -> None:
    image = np.full((61, 81), 255, dtype=np.uint8)
    image[5:56, 40:44] = 0  # pixel squares [40, 44), centre scene x=42

    result = snap_to_stroke_center(image, 38.7, 30.0, "vertical")

    assert result.applied
    assert result.coordinate == pytest.approx(42.0, abs=0.05)
    assert (result.low_edge, result.high_edge) == pytest.approx((40.0, 44.0))


def test_crossing_frame_line_does_not_shift_horizontal_centre() -> None:
    image = np.full((81, 81), 255, dtype=np.uint8)
    image[20:24, 5:76] = 0
    image[5:76, 48:52] = 0

    result = snap_to_stroke_center(image, 50.0, 18.0, "horizontal")

    assert result.applied
    assert result.coordinate == pytest.approx(22.0, abs=0.05)


def test_flat_background_is_not_snapped() -> None:
    image = np.full((31, 31), 255, dtype=np.uint8)
    result = snap_to_stroke_center(image, 12.25, 15.0, "vertical")
    assert not result.applied
    assert result.coordinate == 12.25
