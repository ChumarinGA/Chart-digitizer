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
    n_calibration_points: int = 2

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
    crop_rect: Optional[tuple[int, int, int, int]] = None

    calibration: CalibrationResult = field(default_factory=CalibrationResult)
    series: list[SeriesData] = field(default_factory=list)
    settings: AppSettings = field(default_factory=AppSettings)

    # Combined export mode
    combined_mode: CombinedMode = CombinedMode.UNION_X
