"""Enumerations and type aliases shared across the application."""

from enum import Enum, auto


class ScaleType(Enum):
    LINEAR = auto()
    LOG = auto()


class SeriesKind(Enum):
    CONTINUOUS = auto()
    DISCRETE = auto()
    MIXED = auto()


class ExtractionMode(Enum):
    AUTO = auto()
    SEMI_AUTO = auto()
    MANUAL = auto()


class CombinedMode(Enum):
    """How to build the Combined sheet in the exported Excel file."""
    UNION_X = auto()
    UNIFORM_GRID = auto()
    INTERPOLATION = auto()


class StepMode(Enum):
    """Discretisation mode for continuous curve extraction."""
    EVERY_PIXEL_COLUMN = auto()
    FIXED_DX = auto()
    RAW_SKELETON = auto()
