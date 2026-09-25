"""Rectangle types and geometry helpers shared by plot-area algorithms."""

from __future__ import annotations

import numpy as np


Rect = tuple[float, float, float, float]


def crop_to_plot_area(img: np.ndarray, rect: Rect) -> np.ndarray:
    """Crop between frame centre-lines, accepting sub-pixel rectangles."""
    x, y, width, height = rect
    x0 = max(0, int(round(x)))
    y0 = max(0, int(round(y)))
    x1 = min(img.shape[1], int(round(x + width)) + 1)
    y1 = min(img.shape[0], int(round(y + height)) + 1)
    return img[y0:y1, x0:x1].copy()


def normalise_rect(rect: tuple[float, float, float, float]) -> Rect:
    """Return a finite, consistently oriented floating-point rectangle."""
    try:
        x, y, width, height = (float(value) for value in rect)
    except (TypeError, ValueError):
        return (0.0, 0.0, 0.0, 0.0)
    if not all(np.isfinite(value) for value in (x, y, width, height)):
        return (x, y, width, height)
    x2, y2 = x + width, y + height
    left, right = sorted((x, x2))
    top, bottom = sorted((y, y2))
    return (left, top, right - left, bottom - top)
