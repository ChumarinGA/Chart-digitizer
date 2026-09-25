"""Sub-pixel refinement of rough frame boundaries."""

from __future__ import annotations

import cv2
import numpy as np

from src.core.plot_area.geometry import Rect, normalise_rect
from src.core.preprocessing import to_grayscale


def refine_frame_centerlines(
    img: np.ndarray,
    rect: tuple[float, float, float, float],
    *,
    search_radius: float | None = None,
) -> Rect:
    """Refine a rough rectangle to the centre-lines of its frame strokes.

    Each side is refined independently from a local darkness profile measured
    along most of that side.  A darkness-weighted centroid allows the result
    to lie between source-pixel centres, which is required for even-width
    strokes.  The rough coordinate is retained whenever local evidence is
    insufficient.
    """
    rough = normalise_rect(rect)
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
        not all(np.isfinite(value) for value in refined)
        or refined[2] <= 1.0
        or refined[3] <= 1.0
    ):
        return rough
    return tuple(float(value) for value in refined)  # type: ignore[return-value]


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

    min_peak = baseline + 0.60 * contrast
    credible = [component for component in components if component[1] >= min_peak]
    if not credible:
        return target
    centre, _, _ = min(
        credible,
        key=lambda component: (abs(component[0] - target), -component[2]),
    )
    return centre
