"""Value objects returned by marker-centre detection."""

from __future__ import annotations

from dataclasses import dataclass


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


def failure_result(x: float, y: float, reason: str) -> MarkerCenterResult:
    """Return the unchanged position as a rejected marker candidate."""
    return MarkerCenterResult(float(x), float(y), 0.0, False, reason)
