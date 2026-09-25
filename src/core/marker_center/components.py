"""Connected-component and shape checks for marker-centre detection."""

from __future__ import annotations

import cv2
import numpy as np
from scipy.spatial import cKDTree


def choose_component(
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


def has_multiple_long_directions(
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


def outer_line_model(
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


def shape_quality(
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


def has_compact_marker_evidence(
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
