"""Shared colours used by Curve series in the workspace."""

from __future__ import annotations

from PySide6.QtGui import QColor


_CURVE_PALETTE = (
    QColor(255, 80, 80),
    QColor(80, 160, 255),
    QColor(80, 200, 80),
    QColor(255, 180, 40),
    QColor(200, 80, 220),
    QColor(40, 210, 210),
    QColor(255, 130, 60),
    QColor(160, 220, 80),
    QColor(220, 100, 160),
    QColor(120, 180, 240),
)


def curve_series_color(index: int) -> QColor:
    """Return the repeatable default colour for a zero-based Curve index."""
    return QColor(_CURVE_PALETTE[index % len(_CURVE_PALETTE)])


__all__ = ["curve_series_color"]
