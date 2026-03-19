"""Data structures for extracted series."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.models.types import ExtractionMode, SeriesKind


@dataclass(order=True)
class ExtractedPoint:
    """A single data point in graph coordinates."""
    x: float
    y: float = field(compare=False)


@dataclass
class SeriesData:
    """Holds all information about one extracted dependency / series."""
    index: int
    name: str = ""
    kind: SeriesKind = SeriesKind.CONTINUOUS
    points: list[ExtractedPoint] = field(default_factory=list)
    mode: ExtractionMode = ExtractionMode.AUTO
    color_hint: Optional[tuple[int, int, int]] = None  # BGR hint for segmentation

    def sort_by_x(self) -> None:
        """Sort points by ascending X coordinate."""
        self.points.sort()

    @property
    def xs(self) -> list[float]:
        return [p.x for p in self.points]

    @property
    def ys(self) -> list[float]:
        return [p.y for p in self.points]
