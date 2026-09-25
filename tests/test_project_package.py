"""Compatibility and round-trip checks for the project persistence package."""

from pathlib import Path

from src.core import project
from src.core.project.api import load_project as modular_load_project
from src.core.project.api import save_project as modular_save_project
from src.core.project.deserialization import _deserialise as modular_deserialise
from src.core.project.serialization import _serialise as modular_serialise
from src.models.calibration_data import AxisCalibration, CalibrationResult, RefPoint
from src.models.project_data import AppSettings, ProjectState
from src.models.series_data import ExtractedPoint, SeriesData
from src.models.types import CombinedMode, ExtractionMode, ScaleType, SeriesKind


def test_project_package_preserves_the_original_import_api() -> None:
    from src.core.project import PROJECT_EXT, load_project, save_project

    assert PROJECT_EXT == ".digitizer"
    assert load_project is modular_load_project
    assert save_project is modular_save_project
    assert project._serialise is modular_serialise
    assert project._deserialise is modular_deserialise
    assert project.ProjectState is ProjectState
    assert project.CalibrationResult is CalibrationResult
    assert project.SeriesData is SeriesData
    assert project.Path is Path


def _representative_state() -> ProjectState:
    calibration = CalibrationResult(
        x_axis=AxisCalibration(
            scale=ScaleType.LINEAR,
            ref_points=[
                RefPoint(pixel=10.5, data_value=-2.0),
                RefPoint(pixel=210.5, data_value=8.0),
            ],
        ),
        y_axis=AxisCalibration(
            scale=ScaleType.LOG,
            ref_points=[
                RefPoint(pixel=310.5, data_value=1.0),
                RefPoint(pixel=10.5, data_value=1000.0),
            ],
        ),
    )
    calibration.build()

    settings = AppSettings(
        x_scale=ScaleType.LINEAR,
        y_scale=ScaleType.LOG,
        n_calibration_points=4,
        segmentation_sensitivity=0.65,
        min_curve_length=42,
        max_line_thickness=17,
        skeletonize=False,
        curve_step_dx=0.25,
        min_marker_area=12,
        max_marker_area=3456,
        marker_center_sensitivity=0.73,
        arrow_step=0.5,
        ctrl_step=5.0,
        shift_step=0.05,
        snap_to_edge=False,
        magnifier_enabled=True,
    )
    series = SeriesData(
        index=1,
        name="Измерения",
        kind=SeriesKind.DISCRETE,
        mode=ExtractionMode.MANUAL,
        color_hint=(10, 20, 30),
        points=[
            ExtractedPoint(x=-1.25, y=2.5),
            ExtractedPoint(x=3.75, y=125.0),
        ],
    )
    return ProjectState(
        image_path=Path("данные/график.png"),
        crop_rect=(10.5, 10.5, 200.0, 300.0),
        calibration=calibration,
        series=[series],
        settings=settings,
        calibration_anchors=[
            (10.5, 310.5, -2.0, 1.0, "Both"),
            (210.5, 10.5, 8.0, 1000.0, "Both"),
        ],
        scatter_points_px=[[(35.25, 250.75), (120.5, 140.5)]],
        curve_points_px=[[(20.5, 290.5), (110.5, 150.5), (200.5, 30.5)]],
        scatter_point_styles=[[('STAR', 7.5), ('SQUARE', 6.0)]],
        curve_point_styles=[[('CIRCLE', 4.5), ('DIAMOND_45', 5.0)]],
        curve_visual_styles=[("#cc123456", 3.5, "DashDotLine")],
        scatter_default_point_style=("STAR", 7.5),
        curve_default_point_style=("DIAMOND_45", 5.0),
        scatter_active_fill_opacity=21,
        curve_active_fill_opacity=34,
        curve_default_thickness=3.5,
        combined_mode=CombinedMode.INTERPOLATION,
    )


def test_project_file_is_canonical_across_a_full_round_trip(tmp_path) -> None:
    first_path = tmp_path / "first.digitizer"
    second_path = tmp_path / "second.digitizer"

    modular_save_project(_representative_state(), first_path)
    restored = modular_load_project(first_path)
    modular_save_project(restored, second_path)

    assert second_path.read_bytes() == first_path.read_bytes()
    assert restored.image_path == Path("данные/график.png")
    assert restored.calibration.is_built
    assert restored.combined_mode is CombinedMode.INTERPOLATION
    assert restored.series[0].name == "Измерения"
    assert restored.series[0].color_hint == (10, 20, 30)
    assert restored.scatter_points_px[0][0] == (35.25, 250.75)
    assert restored.curve_visual_styles == [
        ("#cc123456", 3.5, "DashDotLine")
    ]
