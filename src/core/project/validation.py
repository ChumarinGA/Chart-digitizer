"""Validation helpers for values restored from project files."""

from __future__ import annotations

import math


def _bounded_finite_float(
    raw: object, default: float, lower: float, upper: float
) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return max(lower, min(value, upper))


def _bounded_percent(raw: object, default: int) -> int:
    """Read a persisted percentage without accepting NaN or infinity."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return int(round(max(0.0, min(100.0, value))))


__all__ = ["_bounded_finite_float", "_bounded_percent"]
