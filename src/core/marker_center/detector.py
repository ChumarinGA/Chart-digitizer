"""High-level marker-centre detection pipeline."""

from __future__ import annotations

import cv2
import numpy as np

from src.core.marker_center.components import (
    choose_component,
    has_compact_marker_evidence,
    has_multiple_long_directions,
    outer_line_model,
    shape_quality,
)
from src.core.marker_center.image_features import border_mask, normalised_features
from src.core.marker_center.result import MarkerCenterResult, failure_result


def estimate_marker_center(
    image: np.ndarray,
    x_scene: float,
    y_scene: float,
    radius: float = 12.0,
) -> MarkerCenterResult:
    """Estimate the centre of a compact marker close to a scene position.

    Segmentation is relative to the robust local background rather than to a
    fixed black/white threshold, so coloured markers and mildly noisy scans
    are supported.  A long, approximately straight stroke connected to the
    marker is detected from the outer part of the search window and removed
    before measuring the centre.  This prevents a curve passing through a
    marker from pulling the estimate along the curve.

    The returned candidate is contrast-weighted and may be sub-pixel.  If the
    local foreground is weak, tiny, line-like, highly asymmetric, or clipped
    by the search window, ``applied`` is false and the original position is
    returned.  No point is ever changed by this function.

    Args:
        image: Grayscale, BGR, or BGRA image array.
        x_scene: Approximate X position in scene coordinates.
        y_scene: Approximate Y position in scene coordinates.
        radius: Radius of the local search window in scene pixels.  It should
            be comfortably larger than the expected marker radius.
    """

    x = float(x_scene)
    y = float(y_scene)
    search_radius = float(radius)
    if not np.isfinite([x, y, search_radius]).all():
        raise ValueError("coordinates and radius must be finite")
    if search_radius < 4.0:
        raise ValueError("radius must be at least 4 scene pixels")

    features = normalised_features(image)
    image_h, image_w = features.shape[:2]
    if not (0.0 <= x <= float(image_w) and 0.0 <= y <= float(image_h)):
        return failure_result(x, y, "click is outside the image")

    left = max(0, int(np.floor(x - search_radius)))
    right = min(image_w, int(np.ceil(x + search_radius)))
    top = max(0, int(np.floor(y - search_radius)))
    bottom = min(image_h, int(np.ceil(y + search_radius)))
    patch = features[top:bottom, left:right]
    if min(patch.shape[:2]) < 7:
        return failure_result(x, y, "search window is clipped at the image boundary")

    scene_x = np.arange(left, right, dtype=np.float64) + 0.5
    scene_y = np.arange(top, bottom, dtype=np.float64) + 0.5
    xx, yy = np.meshgrid(scene_x, scene_y)

    border = border_mask(patch.shape[0], patch.shape[1])
    border_values = patch[border]
    background = np.median(border_values, axis=0)
    difference = np.sqrt(np.mean(np.square(patch - background), axis=2))

    border_difference = difference[border]
    noise_floor = float(np.median(border_difference))
    noise_mad = float(np.median(np.abs(border_difference - noise_floor)))
    noise_sigma = 1.4826 * noise_mad
    threshold = max(7.0, noise_floor + max(4.0, 4.0 * noise_sigma))

    peak_difference = float(np.max(difference))
    if peak_difference < threshold + 5.0:
        return failure_result(x, y, "insufficient local foreground contrast")

    foreground = difference >= threshold
    # Reject isolated scan/compression noise without eroding one-pixel rings
    # or one-pixel curve strokes.
    neighbour_count = cv2.filter2D(
        foreground.astype(np.uint8),
        cv2.CV_16U,
        np.ones((3, 3), dtype=np.uint8),
        borderType=cv2.BORDER_CONSTANT,
    )
    foreground &= neighbour_count >= 2
    if not np.any(foreground):
        return failure_result(x, y, "no coherent foreground near the click")

    component = choose_component(
        foreground,
        xx,
        yy,
        x,
        y,
        search_radius,
    )
    if component is None:
        return failure_result(x, y, "no marker-sized foreground near the click")
    if not has_compact_marker_evidence(component, xx, yy, x, y, search_radius):
        return failure_result(
            x,
            y,
            "foreground has neither a closed outline nor a filled marker core",
        )
    if has_multiple_long_directions(component, xx, yy, x, y, search_radius):
        return failure_result(
            x,
            y,
            "foreground contains multiple long strokes, not one marker",
        )

    working = component.copy()
    line = outer_line_model(working, xx, yy, x, y, search_radius)
    line_removed = False
    if line is not None:
        origin, direction, half_width = line
        perpendicular = np.array([-direction[1], direction[0]])
        line_distance = np.abs(
            (xx - origin[0]) * perpendicular[0]
            + (yy - origin[1]) * perpendicular[1]
        )
        without_line = working & (line_distance > half_width)
        # A real compact symbol leaves foreground on several sides of the
        # removed stroke.  A bare curve/axis normally leaves nothing useful.
        if int(np.count_nonzero(without_line)) >= 5:
            working = without_line
            line_removed = True
        else:
            return failure_result(x, y, "foreground is a line, not a compact marker")

    # Test clipping before the radial trim below.  Trimming first erased the
    # evidence and could turn half of a marker into a high-scoring but badly
    # shifted candidate.
    rows, cols = np.nonzero(working)
    touches_boundary = bool(
        np.any(rows <= 0)
        or np.any(cols <= 0)
        or np.any(rows >= working.shape[0] - 1)
        or np.any(cols >= working.shape[1] - 1)
    )
    if touches_boundary:
        return failure_result(
            x,
            y,
            "marker/search window is clipped; increase the radius",
        )

    distance_from_click = np.hypot(xx - x, yy - y)
    working &= distance_from_click <= 0.92 * search_radius
    count = int(np.count_nonzero(working))
    if count < 6:
        return failure_result(x, y, "too little marker foreground remains")

    raw_contrast = difference[working]
    # Limit the leverage of an exceptionally dark curve crossing a coloured
    # marker while preserving antialiasing information at the marker edge.
    contrast_cap = float(np.percentile(raw_contrast, 85.0))
    weight_floor = min(noise_floor, threshold * 0.5)
    weights = np.clip(raw_contrast - weight_floor, 0.0, contrast_cap - weight_floor)
    if float(np.sum(weights)) <= 0.0:
        weights = np.ones_like(raw_contrast)

    marker_x = xx[working]
    marker_y = yy[working]
    # Geometry, not ink darkness, defines a marker's centre.  Contrast weights
    # can move a perfectly symmetric two-tone symbol by several pixels.
    candidate_x = float(np.mean(marker_x))
    candidate_y = float(np.mean(marker_y))
    weighted_x = float(np.average(marker_x, weights=weights))
    weighted_y = float(np.average(marker_y, weights=weights))
    if np.hypot(weighted_x - candidate_x, weighted_y - candidate_y) > 0.5:
        return failure_result(
            x,
            y,
            "marker foreground is photometrically asymmetric; manual confirmation is safer",
        )
    shift = float(np.hypot(candidate_x - x, candidate_y - y))
    if shift > min(6.0, 0.40 * search_radius):
        return failure_result(x, y, "candidate is too far from the click")

    geometry_weights = np.ones_like(weights)
    quality = shape_quality(
        marker_x,
        marker_y,
        geometry_weights,
        candidate_x,
        candidate_y,
    )
    if quality is None:
        return failure_result(
            x,
            y,
            "foreground is not a compact, two-dimensional marker",
        )
    isotropy, angular_coverage, central_symmetry = quality

    median_contrast = float(np.median(raw_contrast))
    contrast_score = float(
        np.clip((median_contrast - threshold + 12.0) / 90.0, 0.0, 1.0)
    )
    area_score = float(np.clip((count - 5.0) / 20.0, 0.0, 1.0))
    isotropy_score = float(np.clip((isotropy - 0.25) / 0.60, 0.0, 1.0))
    angular_score = float(np.clip((angular_coverage - 4.0) / 6.0, 0.0, 1.0))
    symmetry_score = float(np.clip((central_symmetry - 0.48) / 0.42, 0.0, 1.0))
    confidence = float(
        np.clip(
            0.25 * contrast_score
            + 0.20 * area_score
            + 0.20 * isotropy_score
            + 0.15 * angular_score
            + 0.20 * symmetry_score,
            0.0,
            1.0,
        )
    )
    if confidence < 0.48:
        return MarkerCenterResult(
            candidate_x,
            candidate_y,
            confidence,
            False,
            "marker candidate is too uncertain",
        )

    reason = "reliable marker-centre candidate; confirmation required"
    if line_removed:
        reason = (
            "marker-centre candidate after removing a crossing line; "
            "confirmation required"
        )
    return MarkerCenterResult(candidate_x, candidate_y, confidence, True, reason)
