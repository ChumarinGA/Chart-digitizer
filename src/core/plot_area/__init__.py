"""Detection and sub-pixel refinement of a chart's rectangular plot area."""

from src.core.plot_area.detection import detect_plot_area
from src.core.plot_area.frame_refinement import refine_frame_centerlines
from src.core.plot_area.geometry import Rect, crop_to_plot_area

__all__ = [
    "Rect",
    "crop_to_plot_area",
    "detect_plot_area",
    "refine_frame_centerlines",
]
