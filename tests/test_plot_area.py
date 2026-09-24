from __future__ import annotations

import cv2
import numpy as np
import pytest

from src.core.plot_area import detect_plot_area, refine_frame_centerlines


def _frame_image(thickness: int, *, noisy: bool = False) -> tuple[np.ndarray, tuple[float, ...]]:
    height, width = 180, 240
    image = np.full((height, width, 3), 255, dtype=np.uint8)

    # Pixel centres are integer coordinates.  An even-width stroke therefore
    # has a half-integer geometric centre.
    offset = 0.5 if thickness % 2 == 0 else 0.0
    left, top = 35.0 + offset, 25.0 + offset
    right, bottom = 205.0 + offset, 150.0 + offset

    def band(centre: float) -> slice:
        start = int(round(centre - (thickness - 1) / 2))
        return slice(start, start + thickness)

    image[:, band(left)] = 0
    image[:, band(right)] = 0
    image[band(top), :] = 0
    image[band(bottom), :] = 0

    # Long internal grid lines and a plotted curve exercise the selection of
    # the boundary closest to the rough rectangle.
    cv2.line(image, (80, 26), (80, 149), (55, 55, 55), 2)
    cv2.line(image, (36, 85), (204, 85), (70, 70, 70), 2)
    cv2.line(image, (45, 140), (195, 38), (20, 20, 20), 2)

    if noisy:
        rng = np.random.default_rng(20260923)
        noise = rng.normal(0.0, 5.0, image.shape[:2])
        image = np.clip(image.astype(np.float64) + noise[..., None], 0, 255).astype(np.uint8)
        ys = rng.integers(0, height, 500)
        xs = rng.integers(0, width, 500)
        image[ys, xs] = rng.integers(0, 120, size=(500, 1))

    return image, (left, top, right - left, bottom - top)


def _assert_rect_close(actual: tuple[float, ...], expected: tuple[float, ...]) -> None:
    actual_sides = (actual[0], actual[1], actual[0] + actual[2], actual[1] + actual[3])
    expected_sides = (
        expected[0],
        expected[1],
        expected[0] + expected[2],
        expected[1] + expected[3],
    )
    assert np.max(np.abs(np.subtract(actual_sides, expected_sides))) <= 0.75


@pytest.mark.parametrize("thickness", [1, 4, 7])
def test_detect_plot_area_returns_frame_centerlines(thickness: int) -> None:
    image, expected = _frame_image(thickness)
    result = detect_plot_area(image)
    assert result is not None
    _assert_rect_close(result, expected)


def test_refinement_is_robust_to_noise_and_internal_lines() -> None:
    image, expected = _frame_image(4, noisy=True)
    left, top, width, height = expected
    rough = (left - 3.5, top - 3.5, width + 7.0, height + 7.0)
    result = refine_frame_centerlines(image, rough)
    _assert_rect_close(result, expected)


def test_refinement_falls_back_on_blank_image() -> None:
    image = np.full((80, 100), 255, dtype=np.uint8)
    rough = (10, 12, 70, 50)
    assert refine_frame_centerlines(image, rough) == tuple(float(v) for v in rough)
