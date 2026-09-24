"""Local, confirmation-first marker-centre estimation.

The estimator in this module deliberately does not mutate a data point.  It
only returns a candidate which a UI may preview and ask the user to confirm.

Scene coordinates follow the convention used by :mod:`src.core.precision`:
an image pixel with array index ``i`` occupies ``[i, i + 1]`` and its centre
is therefore ``i + 0.5``.  Keeping that half-pixel offset is particularly
important for even-sized rasterised markers.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from scipy.spatial import cKDTree


@dataclass(frozen=True)
class MarkerCenterResult:
    """Result of :func:`estimate_marker_center`.

    ``applied`` means that the detector's reliability checks passed and that
    ``candidate_x``/``candidate_y`` may be offered to the user.  It does *not*
    mean that a point was moved: this core helper has no side effects and the
    caller must explicitly confirm and apply the candidate.
    """

    candidate_x: float
    candidate_y: float
    confidence: float
    applied: bool
    reason: str


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

    features = _normalised_features(image)
    image_h, image_w = features.shape[:2]
    if not (0.0 <= x <= float(image_w) and 0.0 <= y <= float(image_h)):
        return _failure(x, y, "click is outside the image")

    left = max(0, int(np.floor(x - search_radius)))
    right = min(image_w, int(np.ceil(x + search_radius)))
    top = max(0, int(np.floor(y - search_radius)))
    bottom = min(image_h, int(np.ceil(y + search_radius)))
    patch = features[top:bottom, left:right]
    if min(patch.shape[:2]) < 7:
        return _failure(x, y, "search window is clipped at the image boundary")

    scene_x = np.arange(left, right, dtype=np.float64) + 0.5
    scene_y = np.arange(top, bottom, dtype=np.float64) + 0.5
    xx, yy = np.meshgrid(scene_x, scene_y)

    border = _border_mask(patch.shape[0], patch.shape[1])
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
        return _failure(x, y, "insufficient local foreground contrast")

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
        return _failure(x, y, "no coherent foreground near the click")

    component = _choose_component(
        foreground,
        xx,
        yy,
        x,
        y,
        search_radius,
    )
    if component is None:
        return _failure(x, y, "no marker-sized foreground near the click")
    if not _has_compact_marker_evidence(component, xx, yy, x, y, search_radius):
        return _failure(x, y, "foreground has neither a closed outline nor a filled marker core")
    if _has_multiple_long_directions(component, xx, yy, x, y, search_radius):
        return _failure(x, y, "foreground contains multiple long strokes, not one marker")

    working = component.copy()
    line = _outer_line_model(working, xx, yy, x, y, search_radius)
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
            return _failure(x, y, "foreground is a line, not a compact marker")

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
        return _failure(x, y, "marker/search window is clipped; increase the radius")

    distance_from_click = np.hypot(xx - x, yy - y)
    working &= distance_from_click <= 0.92 * search_radius
    count = int(np.count_nonzero(working))
    if count < 6:
        return _failure(x, y, "too little marker foreground remains")

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
        return _failure(
            x,
            y,
            "marker foreground is photometrically asymmetric; manual confirmation is safer",
        )
    shift = float(np.hypot(candidate_x - x, candidate_y - y))
    if shift > min(6.0, 0.40 * search_radius):
        return _failure(x, y, "candidate is too far from the click")

    geometry_weights = np.ones_like(weights)
    quality = _shape_quality(
        marker_x,
        marker_y,
        geometry_weights,
        candidate_x,
        candidate_y,
    )
    if quality is None:
        return _failure(x, y, "foreground is not a compact, two-dimensional marker")
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
        reason = "marker-centre candidate after removing a crossing line; confirmation required"
    return MarkerCenterResult(candidate_x, candidate_y, confidence, True, reason)


def _failure(x: float, y: float, reason: str) -> MarkerCenterResult:
    return MarkerCenterResult(float(x), float(y), 0.0, False, reason)


def _normalised_features(image: np.ndarray) -> np.ndarray:
    """Return finite ``H x W x C`` colour features on a 0..255 scale."""
    array = np.asarray(image)
    if array.size == 0 or array.ndim not in (2, 3):
        raise ValueError("image must be a non-empty grayscale, BGR, or BGRA array")
    if array.ndim == 3 and array.shape[2] not in (1, 3, 4):
        raise ValueError("image must be a grayscale, BGR, or BGRA array")

    values = array.astype(np.float64, copy=False)
    if not np.all(np.isfinite(values)):
        raise ValueError("image must contain only finite values")
    if values.ndim == 2:
        values = values[:, :, None]
    elif values.shape[2] == 4:
        values = values[:, :, :3]

    minimum = float(np.min(values))
    maximum = float(np.max(values))
    if minimum < 0.0:
        raise ValueError("image values must be non-negative")
    if maximum <= 1.5:
        values = values * 255.0
    elif maximum > 255.0:
        # Use the observed image range: this supports both full-range uint16
        # scans and 10/12-bit data stored in a uint16 container.
        values = values * (255.0 / maximum)
    return np.clip(values, 0.0, 255.0)


def _border_mask(height: int, width: int) -> np.ndarray:
    band = max(2, int(round(min(height, width) * 0.12)))
    mask = np.zeros((height, width), dtype=bool)
    mask[:band, :] = True
    mask[-band:, :] = True
    mask[:, :band] = True
    mask[:, -band:] = True
    return mask


def _choose_component(
    foreground: np.ndarray,
    xx: np.ndarray,
    yy: np.ndarray,
    click_x: float,
    click_y: float,
    radius: float,
) -> np.ndarray | None:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        foreground.astype(np.uint8), connectivity=8
    )
    candidates: list[tuple[bool, float, int]] = []
    local_click = (
        float(click_x - xx[0, 0]),
        float(click_y - yy[0, 0]),
    )
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < 3:
            continue
        member = labels == label
        distances = np.hypot(xx[member] - click_x, yy[member] - click_y)
        nearest = float(np.min(distances))
        contours, _ = cv2.findContours(
            member.astype(np.uint8),
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        contains_click = any(
            cv2.pointPolygonTest(contour, local_click, False) >= 0
            for contour in contours
            if len(contour) >= 3
        )
        candidates.append((contains_click, nearest, label))

    if not candidates:
        return None
    containing = [candidate for candidate in candidates if candidate[0]]
    pool = containing if containing else candidates
    pool.sort(key=lambda candidate: candidate[1])

    # A click inside a hollow/filled external contour is strong ownership
    # evidence.  Otherwise require foreground genuinely close to the click;
    # a large neighbouring marker must never win merely through greater mass.
    if not containing and pool[0][1] > min(3.0, 0.25 * radius):
        return None
    if len(pool) > 1 and abs(pool[1][1] - pool[0][1]) < 0.75:
        # Two equally plausible local objects are safer to leave untouched.
        return None
    return labels == pool[0][2]


def _has_multiple_long_directions(
    component: np.ndarray,
    xx: np.ndarray,
    yy: np.ndarray,
    click_x: float,
    click_y: float,
    radius: float,
) -> bool:
    """Return true for cross/grid-like foreground reaching far in 2+ axes.

    Direction is folded modulo pi, so the two opposite arms of one passing
    curve form a single cluster.  A grid intersection forms two separated
    clusters.  Only the outer part of the search window participates; a
    compact marker comfortably inside the window cannot trigger this test.
    """
    dx = xx - click_x
    dy = yy - click_y
    radial = np.hypot(dx, dy)
    far = component & (radial >= 0.72 * radius)
    far_count = int(np.count_nonzero(far))
    if far_count < 8:
        return False

    bin_count = 18
    angles = np.mod(np.arctan2(dy[far], dx[far]), np.pi)
    bins = np.floor(angles * (bin_count / np.pi)).astype(int)
    histogram = np.bincount(np.clip(bins, 0, bin_count - 1), minlength=bin_count)
    minimum = max(2, int(np.ceil(0.04 * far_count)))
    active = histogram >= minimum
    # Bridge a one-bin raster/antialiasing gap within a single thick stroke.
    active = active | (np.roll(active, 1) & np.roll(active, -1))
    if bool(np.all(active)):
        return True
    cluster_starts = active & ~np.roll(active, 1)
    return int(np.count_nonzero(cluster_starts)) >= 2


def _outer_line_model(
    component: np.ndarray,
    xx: np.ndarray,
    yy: np.ndarray,
    click_x: float,
    click_y: float,
    radius: float,
) -> tuple[np.ndarray, np.ndarray, float] | None:
    """Fit a long stroke from component pixels outside the marker region."""
    radial = np.hypot(xx - click_x, yy - click_y)
    outer = component & (radial >= 0.60 * radius)
    outer_y, outer_x = np.nonzero(outer)
    if outer_x.size < 6:
        return None

    points = np.column_stack((xx[outer], yy[outer])).astype(np.float64)
    origin = np.mean(points, axis=0)
    centred = points - origin
    covariance = centred.T @ centred / max(float(points.shape[0]), 1.0)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    minor, major = float(eigenvalues[0]), float(eigenvalues[1])
    if major <= 0.0 or major / max(minor, 0.04) < 8.0:
        return None
    direction = eigenvectors[:, 1]
    projections = centred @ direction
    if float(np.ptp(projections)) < 1.05 * radius:
        return None
    perpendicular = np.array([-direction[1], direction[0]])
    residuals = np.abs(centred @ perpendicular)
    residual_90 = float(np.percentile(residuals, 90.0))
    if residual_90 > max(2.25, 0.18 * radius):
        return None

    # Refit the offset from the central residual band.  This remains stable
    # when a marker contributes one or two outlying pixels to the outer set.
    inliers = residuals <= max(1.0, 1.5 * residual_90)
    if int(np.count_nonzero(inliers)) >= 4:
        origin = np.mean(points[inliers], axis=0)
        centred_inliers = points[inliers] - origin
        covariance = centred_inliers.T @ centred_inliers / float(np.count_nonzero(inliers))
        _, eigenvectors = np.linalg.eigh(covariance)
        direction = eigenvectors[:, 1]
        perpendicular = np.array([-direction[1], direction[0]])
        residuals = np.abs((points - origin) @ perpendicular)

    half_width = max(0.75, float(np.percentile(residuals, 90.0)) + 0.35)
    half_width = min(half_width, max(2.5, 0.22 * radius))
    return origin, direction, half_width


def _shape_quality(
    marker_x: np.ndarray,
    marker_y: np.ndarray,
    weights: np.ndarray,
    centre_x: float,
    centre_y: float,
) -> tuple[float, int, float] | None:
    dx = marker_x - centre_x
    dy = marker_y - centre_y
    weight_sum = float(np.sum(weights))
    if weight_sum <= 0.0:
        return None
    covariance = np.array(
        [
            [np.sum(weights * dx * dx), np.sum(weights * dx * dy)],
            [np.sum(weights * dx * dy), np.sum(weights * dy * dy)],
        ],
        dtype=np.float64,
    ) / weight_sum
    eigenvalues = np.linalg.eigvalsh(covariance)
    minor, major = float(eigenvalues[0]), float(eigenvalues[1])
    if minor < 0.18 or major < 0.35:
        return None
    isotropy = float(np.sqrt(max(minor, 0.0) / max(major, 1e-12)))
    if isotropy < 0.25:
        return None

    radial = np.hypot(dx, dy)
    radial_cutoff = max(0.7, float(np.percentile(radial, 35.0)))
    angular_points = radial >= radial_cutoff
    if int(np.count_nonzero(angular_points)) < 4:
        return None
    angles = np.mod(np.arctan2(dy[angular_points], dx[angular_points]), 2.0 * np.pi)
    bins = np.floor(angles * (12.0 / (2.0 * np.pi))).astype(int)
    angular_coverage = int(np.unique(np.clip(bins, 0, 11)).size)
    if angular_coverage < 6:
        return None

    # Filled and hollow chart markers are normally centrally symmetric.  A
    # bent curve can have acceptable covariance and angular coverage, but its
    # foreground has no counterpart after a 180-degree rotation.  Match each
    # point to the nearest reflected point with one-pixel raster tolerance.
    points = np.column_stack((marker_x, marker_y))
    reflected = np.column_stack((2.0 * centre_x - marker_x, 2.0 * centre_y - marker_y))
    # A dense pairwise distance matrix grows quadratically and could consume
    # hundreds of MB at the largest UI search radius.  Nearest-neighbour lookup
    # gives the same symmetry test with bounded memory.
    nearest, _ = cKDTree(points).query(reflected, k=1)
    matched = nearest <= 1.15
    central_symmetry = float(np.sum(weights[matched]) / weight_sum)
    if central_symmetry < 0.65:
        return None
    return isotropy, angular_coverage, central_symmetry


def _has_compact_marker_evidence(
    component: np.ndarray,
    xx: np.ndarray,
    yy: np.ndarray,
    click_x: float,
    click_y: float,
    radius: float,
) -> bool:
    """Distinguish a marker body/outline from an ordinary thin curve.

    Filled markers have a genuinely two-dimensional core.  Hollow markers
    enclose at least one local background region.  Requiring one of those two
    properties prevents a bend in a polyline from looking like a compact blob
    merely because its covariance happens to be two-dimensional.
    """
    binary = component.astype(np.uint8)
    padded = np.pad(binary, 1, mode="constant", constant_values=0)
    inscribed = cv2.distanceTransform(padded, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)[
        1:-1, 1:-1
    ]
    if float(np.max(inscribed, initial=0.0)) >= 2.5:
        return True

    inverse = (~component).astype(np.uint8)
    # A one-pixel raster circle is normally 8-connected; the complementary
    # background must therefore use 4-connectivity to avoid leaking through
    # diagonal corners of the outline.
    count, labels, stats, _ = cv2.connectedComponentsWithStats(inverse, connectivity=4)
    height, width = component.shape
    for label in range(1, count):
        left = int(stats[label, cv2.CC_STAT_LEFT])
        top = int(stats[label, cv2.CC_STAT_TOP])
        region_width = int(stats[label, cv2.CC_STAT_WIDTH])
        region_height = int(stats[label, cv2.CC_STAT_HEIGHT])
        area = int(stats[label, cv2.CC_STAT_AREA])
        touches_edge = (
            left == 0
            or top == 0
            or left + region_width >= width
            or top + region_height >= height
        )
        if touches_edge or area < 2:
            continue
        hole = labels == label
        hole_x = float(np.mean(xx[hole]))
        hole_y = float(np.mean(yy[hole]))
        if np.hypot(hole_x - click_x, hole_y - click_y) <= 0.65 * radius:
            return True
    return False
