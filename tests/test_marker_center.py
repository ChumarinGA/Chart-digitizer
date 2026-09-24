import cv2
import numpy as np
import pytest

from src.core.marker_center import estimate_marker_center


def _white_image(*, colour: bool = False) -> np.ndarray:
    shape = (81, 91, 3) if colour else (81, 91)
    return np.full(shape, 255, dtype=np.uint8)


def test_filled_circle_returns_pixel_centre_scene_coordinates() -> None:
    image = _white_image()
    cv2.circle(image, (43, 37), 5, 0, thickness=-1, lineType=cv2.LINE_8)

    result = estimate_marker_center(image, 45.4, 36.2, radius=13)

    assert result.applied
    assert result.candidate_x == pytest.approx(43.5, abs=0.12)
    assert result.candidate_y == pytest.approx(37.5, abs=0.12)
    assert 0.48 <= result.confidence <= 1.0
    assert "confirmation required" in result.reason


def test_even_sized_square_can_have_integer_scene_centre() -> None:
    image = _white_image()
    # Pixel squares [36, 44) and [29, 37) have scene centre (40, 33).
    image[29:37, 36:44] = 0

    result = estimate_marker_center(image, 38.1, 34.4, radius=12)

    assert result.applied
    assert result.candidate_x == pytest.approx(40.0, abs=0.08)
    assert result.candidate_y == pytest.approx(33.0, abs=0.08)


def test_open_circle_is_centred_despite_background_at_click() -> None:
    image = _white_image()
    cv2.circle(image, (46, 39), 6, 0, thickness=1, lineType=cv2.LINE_8)

    result = estimate_marker_center(image, 44.4, 40.6, radius=14)

    assert result.applied
    assert result.candidate_x == pytest.approx(46.5, abs=0.25)
    assert result.candidate_y == pytest.approx(39.5, abs=0.25)


def test_crossing_line_is_removed_before_centring_marker() -> None:
    image = _white_image()
    # Draw the curve first and then a hollow marker, as in a typical chart.
    cv2.line(image, (20, 44), (70, 38), 0, thickness=1, lineType=cv2.LINE_8)
    cv2.circle(image, (45, 41), 5, 0, thickness=1, lineType=cv2.LINE_8)

    result = estimate_marker_center(image, 47.3, 42.2, radius=15)

    assert result.applied
    assert result.candidate_x == pytest.approx(45.5, abs=0.45)
    assert result.candidate_y == pytest.approx(41.5, abs=0.45)
    assert "crossing line" in result.reason


def test_coloured_marker_and_mild_noise_use_local_background() -> None:
    rng = np.random.default_rng(402)
    image = _white_image(colour=True).astype(np.int16)
    image += rng.integers(-3, 4, size=image.shape, dtype=np.int16)
    image = np.clip(image, 0, 255).astype(np.uint8)
    cv2.circle(image, (51, 28), 4, (220, 40, 40), thickness=-1, lineType=cv2.LINE_8)

    result = estimate_marker_center(image, 49.7, 29.6, radius=12)

    assert result.applied
    assert result.candidate_x == pytest.approx(51.5, abs=0.20)
    assert result.candidate_y == pytest.approx(28.5, abs=0.20)


def test_noise_without_a_marker_is_not_proposed() -> None:
    rng = np.random.default_rng(17)
    image = np.clip(
        245 + rng.normal(0.0, 3.0, size=(81, 91)), 0, 255
    ).astype(np.uint8)
    for x, y in ((42, 38), (48, 43), (39, 45), (52, 36)):
        image[y, x] = 40

    result = estimate_marker_center(image, 45.0, 40.0, radius=13)

    assert not result.applied
    assert result.candidate_x == 45.0
    assert result.candidate_y == 40.0
    assert result.confidence == 0.0
    assert result.reason


def test_plain_curve_segment_is_rejected_as_line_like() -> None:
    image = _white_image()
    cv2.line(image, (28, 49), (65, 31), 0, thickness=2, lineType=cv2.LINE_8)

    result = estimate_marker_center(image, 46.2, 40.0, radius=14)

    assert not result.applied
    assert "line" in result.reason


def test_invalid_input_is_reported() -> None:
    with pytest.raises(ValueError, match="radius"):
        estimate_marker_center(_white_image(), 20.0, 20.0, radius=2)
    with pytest.raises(ValueError, match="image"):
        estimate_marker_center(np.empty((0, 0), dtype=np.uint8), 20.0, 20.0)


def test_nearby_larger_marker_cannot_steal_exact_target_click() -> None:
    image = np.full((121, 121), 255, np.uint8)
    cv2.circle(image, (45, 60), 3, 0, -1)
    cv2.circle(image, (58, 60), 7, 0, -1)

    result = estimate_marker_center(image, 45.5, 60.5, radius=24)

    assert result.applied
    assert result.candidate_x == pytest.approx(45.5, abs=0.2)
    assert result.candidate_y == pytest.approx(60.5, abs=0.2)


def test_grid_intersection_is_rejected_as_multiple_long_strokes() -> None:
    image = np.full((101, 101), 255, np.uint8)
    cv2.line(image, (25, 50), (75, 50), 0, 2)
    cv2.line(image, (50, 25), (50, 75), 0, 2)

    result = estimate_marker_center(image, 49.0, 52.0, radius=15)

    assert not result.applied
    assert "line" in result.reason or "stroke" in result.reason


def test_clipped_marker_is_rejected_not_recentred_toward_click() -> None:
    image = np.full((101, 101), 255, np.uint8)
    cv2.circle(image, (50, 50), 5, 0, -1)

    result = estimate_marker_center(image, 47.6, 52.3, radius=4)

    assert not result.applied
    assert result.candidate_x == pytest.approx(47.6)
    assert result.candidate_y == pytest.approx(52.3)


def test_photometrically_asymmetric_foreground_is_rejected() -> None:
    image = np.full((101, 101, 3), 255, np.uint8)
    cv2.circle(image, (50, 50), 7, (180, 180, 180), -1)
    image[43:58, 50:58] = 30

    result = estimate_marker_center(image, 49.0, 51.0, radius=16)

    assert not result.applied
    assert "asymmetric" in result.reason
