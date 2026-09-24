"""Top-level project state that aggregates every aspect of a digitisation session."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from src.models.calibration_data import CalibrationResult
from src.models.series_data import SeriesData
from src.models.types import CombinedMode, ScaleType


@dataclass
class AppSettings:
    """User-adjustable processing parameters (Section 16 of the spec)."""
    # Calibration
    x_scale: ScaleType = ScaleType.LINEAR
    y_scale: ScaleType = ScaleType.LINEAR
    n_calibration_points: int = 3

    # Curves
    segmentation_sensitivity: float = 0.5
    min_curve_length: int = 30
    max_line_thickness: int = 20
    skeletonize: bool = True
    curve_step_dx: float = 1.0

    # Markers
    min_marker_area: int = 10
    max_marker_area: int = 2000
    marker_center_sensitivity: float = 0.5

    # Manual mode
    arrow_step: float = 1.0
    ctrl_step: float = 10.0
    shift_step: float = 0.1
    snap_to_edge: bool = True
    magnifier_enabled: bool = True


@dataclass
class ProjectState:
    """Full state of a digitisation session."""
    image_path: Optional[Path] = None
    image: Optional[np.ndarray] = None  # loaded BGR image

    # Plot area crop rectangle (x, y, w, h) in pixel coordinates
    # Continuous scene coordinates; half-pixels are meaningful for the centre
    # of even-width frame strokes.
    crop_rect: Optional[tuple[float, float, float, float]] = None

    calibration: CalibrationResult = field(default_factory=CalibrationResult)
    series: list[SeriesData] = field(default_factory=list)
    settings: AppSettings = field(default_factory=AppSettings)

    # Lossless live-editor state.  Data-space ``series`` remains the portable
    # representation, while these fields preserve unfinished calibration and
    # exact pixel placements across Save/Load.
    calibration_anchors: list[tuple[float, float, Optional[float], Optional[float], str]] = field(
        default_factory=list
    )
    scatter_points_px: list[list[tuple[float, float]]] = field(default_factory=list)
    curve_points_px: list[list[tuple[float, float]]] = field(default_factory=list)

    # Visual editor state.  Shape and Qt pen-style names are stored as plain
    # strings so the data model does not depend on the GUI package.
    scatter_point_styles: list[list[tuple[str, float]]] = field(default_factory=list)
    curve_point_styles: list[list[tuple[str, float]]] = field(default_factory=list)
    curve_visual_styles: list[tuple[str, float, str]] = field(default_factory=list)
    scatter_default_point_style: tuple[str, float] = ("CIRCLE", 5.0)
    curve_default_point_style: tuple[str, float] = ("CIRCLE", 4.0)
    # Percentage used only for the currently active Scatter/Curve target.
    scatter_active_fill_opacity: int = 15
    curve_active_fill_opacity: int = 15
    curve_default_thickness: float = 2.0

    # Combined export mode
    combined_mode: CombinedMode = CombinedMode.UNION_X
