"""Compatibility facade for the point-table widgets.

New code may import the tables from :mod:`src.gui.tables`. This module keeps
the original import path stable for extensions and existing callers.
"""

from src.gui.tables import (
    POINT_PALETTE,
    CropCornerTable,
    DataPointTable,
    RefPointTable,
    _BasePointTable,
    point_color,
)

__all__ = [
    "CropCornerTable",
    "DataPointTable",
    "POINT_PALETTE",
    "RefPointTable",
    "_BasePointTable",
    "point_color",
]
