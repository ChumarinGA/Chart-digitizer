"""Automatic detection of the rectangular plotting area inside a chart image."""

from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from src.core.preprocessing import detect_edges, to_grayscale


Rect = tuple[float, float, float, float]


def detect_plot_area(img: np.ndarray) -> Optional[Rect]:
    """Try to find the rectangular plot area.

    Returns (x, y, w, h) in pixel coordinates or *None* on failure.
    Three strategies are tried in order:
      1. Long Hough lines -> clustering
      2. Contour detection -> largest rectangle
      3. Non-white pixel bounding box (fallback)
    """
    result = _hough_strategy(img)
    if result is None:
        result = _contour_strategy(img)
    if result is None:
        result = _density_fallback(img)
    if result is None:
        return None
    return refine_frame_centerlines(img, result)


def crop_to_plot_area(img: np.ndarray, rect: Rect) -> np.ndarray:
    """Crop between frame centre-lines, accepting sub-pixel rectangles."""
    x, y, w, h = rect
    x0 = max(0, int(round(x)))
    y0 = max(0, int(round(y)))
    x1 = min(img.shape[1], int(round(x + w)) + 1)
    y1 = min(img.shape[0], int(round(y + h)) + 1)
    return img[y0:y1, x0:x1].copy()


def refine_frame_centerlines(
    img: np.ndarray,
    rect: tuple[float, float, float, float],
    *,
    search_radius: float | None = None,
) -> Rect:
    """Refine a rough plot rectangle to the centre-lines of its frame.

    ``rect`` supplies approximate ``(left, top, width, height)`` coordinates.
    Each side is refined independently from a local darkness profile measured
    along most of that side.  Taking the darkness-weighted centroid of the
    detected stroke produces half-pixel coordinates for even-width strokes.

    The rough coordinate is retained whenever the local profile has
    insufficient contrast.  This makes the function safe for frameless plots
    and for rectangles returned by the density fallback.
    """
    rough = _normalise_rect(rect)
    if not all(np.isfinite(value) for value in rough):
        return rough
    if img is None or not isinstance(img, np.ndarray) or img.size == 0:
        return rough

    try:
        gray = to_grayscale(img)
    except (cv2.error, ValueError):
        return rough
    if gray.ndim != 2 or gray.size == 0:
        return rough

    gray_f = gray.astype(np.float64, copy=False)
    finite = np.isfinite(gray_f)
    if not np.any(finite):
        return rough

    # OpenCV images normally use 0..255.  Supporting 0..1 floating images is
    # useful for callers of the core API and costs nothing here.
    hi = float(np.nanpercentile(gray_f[finite], 99.5))
    scale = 1.0 if hi <= 1.5 else 255.0
    darkness = 1.0 - np.clip(gray_f / scale, 0.0, 1.0)
    darkness[~finite] = 0.0

    left0, top0, width0, height0 = rough
    right0 = left0 + width0
    bottom0 = top0 + height0
    short_side = max(1.0, min(abs(width0), abs(height0)))
    radius = (
        float(search_radius)
        if search_radius is not None
        else min(96.0, max(8.0, short_side * 0.08))
    )
    if not np.isfinite(radius) or radius <= 0:
        return rough

    # First pass establishes better spans for the perpendicular profiles;
    # the second pass removes the small corner bias caused by thick frames.
    left = _refine_side(darkness, left0, top0, bottom0, radius, vertical=True)
    right = _refine_side(darkness, right0, top0, bottom0, radius, vertical=True)
    top = _refine_side(darkness, top0, left, right, radius, vertical=False)
    bottom = _refine_side(darkness, bottom0, left, right, radius, vertical=False)
    left = _refine_side(darkness, left, top, bottom, radius, vertical=True)
    right = _refine_side(darkness, right, top, bottom, radius, vertical=True)

    refined = (left, top, right - left, bottom - top)
    if (
        not all(np.isfinite(v) for v in refined)
        or refined[2] <= 1.0
        or refined[3] <= 1.0
    ):
        return rough
    return tuple(float(v) for v in refined)  # type: ignore[return-value]


def _normalise_rect(rect: tuple[float, float, float, float]) -> Rect:
    """Return a finite, consistently oriented floating-point rectangle."""
    try:
        x, y, w, h = (float(v) for v in rect)
    except (TypeError, ValueError):
        return (0.0, 0.0, 0.0, 0.0)
    if not all(np.isfinite(v) for v in (x, y, w, h)):
        return (x, y, w, h)
    x2, y2 = x + w, y + h
    left, right = sorted((x, x2))
    top, bottom = sorted((y, y2))
    return (left, top, right - left, bottom - top)


def _refine_side(
    darkness: np.ndarray,
    target: float,
    span_start: float,
    span_end: float,
    radius: float,
    *,
    vertical: bool,
) -> float:
    """Locate one dark, near-continuous stroke close to ``target``."""
    image_h, image_w = darkness.shape
    axis_limit = image_w if vertical else image_h
    span_limit = image_h if vertical else image_w
    if axis_limit < 2 or span_limit < 2:
        return float(target)

    lo = max(0, int(np.floor(target - radius)))
    hi = min(axis_limit - 1, int(np.ceil(target + radius)))
    if hi < lo:
        return float(target)

    span_lo, span_hi = sorted((float(span_start), float(span_end)))
    # Ignore corners and tick ends.  A frame side remains present throughout
    # this central interval, while labels, curves and crossing grid lines do
    # not dominate its profile.
    trim = min((span_hi - span_lo) * 0.12, 24.0)
    sample_lo = max(0, int(np.ceil(span_lo + trim)))
    sample_hi = min(span_limit - 1, int(np.floor(span_hi - trim)))
    if sample_hi - sample_lo < 4:
        sample_lo = max(0, int(np.ceil(span_lo)))
        sample_hi = min(span_limit - 1, int(np.floor(span_hi)))
    if sample_hi < sample_lo:
        return float(target)

    if vertical:
        samples = darkness[sample_lo : sample_hi + 1, lo : hi + 1]
        mean_profile = np.mean(samples, axis=0)
        median_profile = np.median(samples, axis=0)
    else:
        samples = darkness[lo : hi + 1, sample_lo : sample_hi + 1]
        mean_profile = np.mean(samples, axis=1)
        median_profile = np.median(samples, axis=1)

    # Median rewards a side that is continuous; mean retains sensitivity to
    # anti-aliased or partially occluded frame pixels.
    profile = 0.65 * mean_profile + 0.35 * median_profile
    coordinates = np.arange(lo, hi + 1, dtype=np.float64)
    return _stroke_centroid(coordinates, profile, float(target))


def _stroke_centroid(
    coordinates: np.ndarray,
    profile: np.ndarray,
    target: float,
) -> float:
    """Return the sub-pixel centre of the best profile component."""
    if profile.size == 0 or not np.all(np.isfinite(profile)):
        return target
    baseline = float(np.percentile(profile, 25.0))
    peak = float(np.max(profile))
    contrast = peak - baseline
    if contrast < 0.04:
        return target

    active = profile >= baseline + 0.35 * contrast
    components: list[tuple[float, float, float]] = []
    start = 0
    while start < active.size:
        if not active[start]:
            start += 1
            continue
        end = start + 1
        while end < active.size and active[end]:
            end += 1
        local_profile = profile[start:end]
        weights = np.maximum(local_profile - baseline, 0.0)
        mass = float(np.sum(weights))
        if mass > 0:
            centre = float(np.sum(coordinates[start:end] * weights) / mass)
            component_peak = float(np.max(local_profile))
            components.append((centre, component_peak, mass))
        start = end

    if not components:
        return target

    # Discard weak clutter first, then prefer the component nearest the rough
    # boundary.  Thus a full-height internal grid line cannot steal the frame
    # when both have comparable darkness.
    min_peak = baseline + 0.60 * contrast
    credible = [component for component in components if component[1] >= min_peak]
    if not credible:
        return target
    centre, _, _ = min(
        credible,
        key=lambda component: (
            abs(component[0] - target),
            -component[2],
        ),
    )
    return centre


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
