"""Sub-pixel helpers for precise manual point placement.

The scene coordinate system treats image pixels as unit squares.  Pixel
``i`` therefore has its centre at ``i + 0.5``.  Returning continuous scene
coordinates (instead of integer array indices) is important for even-width
strokes: the centre of a four-pixel line lies between its two middle pixels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np


@dataclass(frozen=True)
class StrokeSnapResult:
    """Result of a local centreline search."""

    coordinate: float
    low_edge: float
    high_edge: float
    confidence: float
    applied: bool


def _gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    if image.ndim == 3 and image.shape[2] in (3, 4):
        code = cv2.COLOR_BGRA2GRAY if image.shape[2] == 4 else cv2.COLOR_BGR2GRAY
        return cv2.cvtColor(image, code)
    raise ValueError("image must be a grayscale, BGR, or BGRA array")


def snap_to_stroke_center(
    image: np.ndarray,
    x: float,
    y: float,
    orientation: Literal["vertical", "horizontal"],
    *,
    search_radius: int = 10,
    sample_half_length: int = 8,
) -> StrokeSnapResult:
    """Snap one coordinate to the centre of a nearby dark stroke.

    ``vertical`` searches along X for a vertical tick/grid line; ``horizontal`
    searches along Y.  A short profile perpendicular to the requested stroke
    suppresses a crossing frame line, so the helper also works at plot-frame
    intersections.  If there is not enough local contrast, ``applied`` is
    false and the original coordinate is returned.
    """

    if orientation not in ("vertical", "horizontal"):
        raise ValueError("orientation must be 'vertical' or 'horizontal'")
    if search_radius < 2 or sample_half_length < 1:
        raise ValueError("search window is too small")
    if not np.isfinite([x, y]).all():
        raise ValueError("coordinates must be finite")

    gray = _gray(np.asarray(image))
    height, width = gray.shape
    cx = int(np.floor(x))
    cy = int(np.floor(y))

    if orientation == "vertical":
        lo = max(0, cx - search_radius)
        hi = min(width, cx + search_radius + 1)
        top = max(0, cy - sample_half_length)
        bottom = min(height, cy + sample_half_length + 1)
        patch = gray[top:bottom, lo:hi]
        positions = np.arange(lo, hi, dtype=float) + 0.5
        profile = (255.0 - patch.astype(float)).mean(axis=0) if patch.size else np.array([])
        original = x
    else:
        lo = max(0, cy - search_radius)
        hi = min(height, cy + search_radius + 1)
        left = max(0, cx - sample_half_length)
        right = min(width, cx + sample_half_length + 1)
        patch = gray[lo:hi, left:right]
        positions = np.arange(lo, hi, dtype=float) + 0.5
        profile = (255.0 - patch.astype(float)).mean(axis=1) if patch.size else np.array([])
        original = y

    if profile.size < 3 or not np.isfinite(profile).all():
        return StrokeSnapResult(original, original, original, 0.0, False)

    baseline = float(np.percentile(profile, 20))
    contrast = profile - baseline
    peak_contrast = float(np.max(contrast))
    if peak_contrast < 12.0:
        return StrokeSnapResult(original, original, original, 0.0, False)

    # Prefer a strong peak close to the click when several grid/curve strokes
    # fall inside the search window.
    distance_penalty = np.abs(positions - original) / max(float(search_radius), 1.0)
    score = contrast - peak_contrast * 0.22 * distance_penalty
    peak = int(np.argmax(score))
    threshold = max(10.0, float(contrast[peak]) * 0.48)

    first = peak
    while first > 0 and contrast[first - 1] >= threshold:
        first -= 1
    last = peak
    while last + 1 < contrast.size and contrast[last + 1] >= threshold:
        last += 1

    # An extremely broad region is normally a filled object/background rather
    # than a line whose centre can be identified reliably.
    run_width = last - first + 1
    if run_width > max(12, search_radius + 2):
        return StrokeSnapResult(original, original, original, 0.0, False)

    weights = np.clip(contrast[first:last + 1], 0.0, None)
    if float(weights.sum()) <= 0.0:
        centre = float((positions[first] + positions[last]) / 2.0)
    else:
        centre = float(np.average(positions[first:last + 1], weights=weights))

    low_edge = float(positions[first] - 0.5)
    high_edge = float(positions[last] + 0.5)
    local_contrast = float(contrast[peak])
    confidence = float(np.clip(local_contrast / 180.0, 0.0, 1.0))
    return StrokeSnapResult(centre, low_edge, high_edge, confidence, True)
