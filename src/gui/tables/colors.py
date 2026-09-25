"""Shared colour palette for point tables and canvas markers."""

from __future__ import annotations

from PySide6.QtGui import QColor


POINT_PALETTE = [
    QColor(230, 70, 70),
    QColor(70, 180, 70),
    QColor(70, 120, 230),
    QColor(230, 180, 40),
    QColor(180, 70, 220),
    QColor(40, 200, 200),
    QColor(230, 120, 50),
    QColor(140, 200, 60),
    QColor(200, 80, 140),
    QColor(100, 160, 220),
    QColor(220, 200, 80),
    QColor(160, 100, 60),
    QColor(80, 220, 160),
    QColor(220, 100, 180),
    QColor(100, 100, 180),
    QColor(180, 180, 100),
    QColor(120, 60, 160),
    QColor(60, 160, 120),
    QColor(200, 140, 100),
    QColor(100, 200, 220),
]


def point_color(index: int) -> QColor:
    """Return the stable cyclic colour assigned to a point index."""
    return POINT_PALETTE[index % len(POINT_PALETTE)]


__all__ = ["POINT_PALETTE", "point_color"]
