"""Automatic detection of the rectangular plotting area inside a chart image."""

from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from src.core.preprocessing import detect_edges, to_grayscale


def detect_plot_area(img: np.ndarray) -> Optional[tuple[int, int, int, int]]:
    """Try to find the rectangular plot area.

    Returns (x, y, w, h) in pixel coordinates or *None* on failure.
    Three strategies are tried in order:
      1. Long Hough lines -> clustering
      2. Contour detection -> largest rectangle
      3. Non-white pixel bounding box (fallback)
    """
    result = _hough_strategy(img)
    if result is not None:
        return result
    result = _contour_strategy(img)
    if result is not None:
        return result
    return _density_fallback(img)


def crop_to_plot_area(img: np.ndarray, rect: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = rect
    return img[y : y + h, x : x + w].copy()


# ---- Strategy 1: Hough lines ----

def _hough_strategy(img: np.ndarray) -> Optional[tuple[int, int, int, int]]:
    edges = detect_edges(img, low=50, high=150)
    h, w = edges.shape[:2]
    min_len = int(min(h, w) * 0.25)

    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80,
                             minLineLength=min_len, maxLineGap=10)
    if lines is None:
        return None

    h_lines: list[int] = []
    v_lines: list[int] = []

    for line in lines:
        x1, y1, x2, y2 = line[0]
        if abs(y2 - y1) < 5 and abs(x2 - x1) > min_len:
            h_lines.append((y1 + y2) // 2)
        elif abs(x2 - x1) < 5 and abs(y2 - y1) > min_len:
            v_lines.append((x1 + x2) // 2)

    if len(h_lines) < 2 or len(v_lines) < 2:
        return None

    top = min(h_lines)
    bottom = max(h_lines)
    left = min(v_lines)
    right = max(v_lines)

    if (bottom - top) < h * 0.15 or (right - left) < w * 0.15:
        return None

    return (left, top, right - left, bottom - top)


# ---- Strategy 2: Contour detection ----

def _contour_strategy(img: np.ndarray) -> Optional[tuple[int, int, int, int]]:
    gray = to_grayscale(img)
    _, thresh = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return None

    img_area = img.shape[0] * img.shape[1]
    best: Optional[tuple[int, int, int, int]] = None
    best_area = 0

    for cnt in contours:
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
        if len(approx) == 4:
            x, y, w, h = cv2.boundingRect(approx)
            area = w * h
            if area > best_area and area > img_area * 0.1:
                best = (x, y, w, h)
                best_area = area

    if best is not None:
        return best

    # Fallback: largest contour bounding rect
    largest = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(largest)
    if w * h > img_area * 0.1:
        return (x, y, w, h)
    return None


# ---- Strategy 3: density fallback ----

def _density_fallback(img: np.ndarray) -> Optional[tuple[int, int, int, int]]:
    gray = to_grayscale(img)
    non_white = gray < 240
    coords = np.argwhere(non_white)
    if len(coords) < 100:
        return None
    y_min, x_min = coords.min(axis=0)
    y_max, x_max = coords.max(axis=0)
    margin = 5
    x_min = max(0, x_min - margin)
    y_min = max(0, y_min - margin)
    return (x_min, y_min, x_max - x_min, y_max - y_min)
