"""Coarse plot-area detection strategies and their fallback order."""

from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from src.core.plot_area.frame_refinement import refine_frame_centerlines
from src.core.plot_area.geometry import Rect
from src.core.preprocessing import detect_edges, to_grayscale


def detect_plot_area(img: np.ndarray) -> Optional[Rect]:
    """Find a plot-area candidate and refine its four frame centre-lines.

    Strategies are attempted in a deliberate order: long Hough lines, a
    rectangular contour, then the bounding box of non-white pixels.  Every
    successful coarse candidate passes through the same sub-pixel refinement.
    """
    result = _hough_strategy(img)
    if result is None:
        result = _contour_strategy(img)
    if result is None:
        result = _density_fallback(img)
    if result is None:
        return None
    return refine_frame_centerlines(img, result)


def _hough_strategy(img: np.ndarray) -> Optional[tuple[int, int, int, int]]:
    """Find opposite long horizontal and vertical lines."""
    edges = detect_edges(img, low=50, high=150)
    height, width = edges.shape[:2]
    min_length = int(min(height, width) * 0.25)

    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=80,
        minLineLength=min_length,
        maxLineGap=10,
    )
    if lines is None:
        return None

    horizontal_lines: list[int] = []
    vertical_lines: list[int] = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        if abs(y2 - y1) < 5 and abs(x2 - x1) > min_length:
            horizontal_lines.append((y1 + y2) // 2)
        elif abs(x2 - x1) < 5 and abs(y2 - y1) > min_length:
            vertical_lines.append((x1 + x2) // 2)

    if len(horizontal_lines) < 2 or len(vertical_lines) < 2:
        return None

    top = min(horizontal_lines)
    bottom = max(horizontal_lines)
    left = min(vertical_lines)
    right = max(vertical_lines)
    if (bottom - top) < height * 0.15 or (right - left) < width * 0.15:
        return None
    return (left, top, right - left, bottom - top)


def _contour_strategy(img: np.ndarray) -> Optional[tuple[int, int, int, int]]:
    """Find the largest plausible rectangular foreground contour."""
    gray = to_grayscale(img)
    _, threshold = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(
        threshold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return None

    image_area = img.shape[0] * img.shape[1]
    best: Optional[tuple[int, int, int, int]] = None
    best_area = 0
    for contour in contours:
        perimeter = cv2.arcLength(contour, True)
        approximation = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approximation) == 4:
            x, y, width, height = cv2.boundingRect(approximation)
            area = width * height
            if area > best_area and area > image_area * 0.1:
                best = (x, y, width, height)
                best_area = area

    if best is not None:
        return best

    largest = max(contours, key=cv2.contourArea)
    x, y, width, height = cv2.boundingRect(largest)
    if width * height > image_area * 0.1:
        return (x, y, width, height)
    return None


def _density_fallback(img: np.ndarray) -> Optional[tuple[int, int, int, int]]:
    """Bound all sufficiently non-white pixels when no frame is detected."""
    gray = to_grayscale(img)
    coordinates = np.argwhere(gray < 240)
    if len(coordinates) < 100:
        return None
    y_min, x_min = coordinates.min(axis=0)
    y_max, x_max = coordinates.max(axis=0)
    margin = 5
    x_min = max(0, x_min - margin)
    y_min = max(0, y_min - margin)
    return (x_min, y_min, x_max - x_min, y_max - y_min)
