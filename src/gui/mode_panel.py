"""Mode panel — 3-mode (Crop / Ref / Data) interface with tables and multi-series tabs."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Slot
from PySide6.QtGui import QColor, QDoubleValidator
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSlider,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.calibration import build_calibration
from src.core.curve_interpolation import CurveInterpolationError, CurveInterpolator
from src.core.export import export_to_excel
from src.core.marker_center import estimate_marker_center
from src.core.plot_area import detect_plot_area
from src.core.precision import snap_to_stroke_center
from src.gui.image_canvas import ImageCanvas
from src.gui.curve_style_dialog import CurveStyleDialog
from src.gui.overlays.crop_overlay import CropOverlay
from src.gui.overlays.curve_path_overlay import CurvePathOverlay
from src.gui.overlays.point_overlay import (
    DragConstraint,
    DraggablePoint,
    PointShape,
)
from src.gui.overlays.ref_grid_overlay import RefGridOverlay
from src.gui.point_table import (
    CropCornerTable,
    DataPointTable,
    RefPointTable,
    point_color,
)
from src.gui.style_dialog import PointStyleDialog
from src.models.calibration_data import CalibrationResult
from src.models.project_data import ProjectState
from src.models.series_data import ExtractedPoint, SeriesData
from src.models.types import CombinedMode, ExtractionMode, ScaleType, SeriesKind

# Corner index mapping for shared-edge propagation.
# Row 0 = leftdown (BL), 1 = rightdown (BR), 2 = leftup (TL), 3 = rightup (TR)
_X_PAIR = {0: 2, 2: 0, 1: 3, 3: 1}  # corners sharing the same X (vertical edge)
_Y_PAIR = {0: 1, 1: 0, 2: 3, 3: 2}  # corners sharing the same Y (horizontal edge)

_CURVE_PALETTE = [
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
]

_MAX_TOTAL_EXPORT_POINTS = 1_000_000


def _curve_series_color(index: int) -> QColor:
    return _CURVE_PALETTE[index % len(_CURVE_PALETTE)]


class ModePanel(QWidget):
    """Right-side panel with Crop / Ref Points / Data Points modes."""

    def __init__(self, project: ProjectState, canvas: ImageCanvas,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # The panel is hosted by a resizable dock.  Its horizontal size hint
        # must not stop the dock boundary from being dragged: the precision
        # inspector switches to a one-column layout when space is tight.
        self.setMinimumWidth(0)
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding
        )
        self._project = project
        self._canvas = canvas

        # --- Scatter state ---
        self._ref_points: list[DraggablePoint] = []
        self._series_points: list[list[DraggablePoint]] = []
        self._series_tables: list[DataPointTable] = []

        # --- Curve state ---
        self._curve_points: list[list[DraggablePoint]] = []
        self._curve_tables: list[DataPointTable] = []
        self._curve_paths: list[CurvePathOverlay] = []
        self._curve_colors: list[QColor] = [_curve_series_color(0)]
        self._curve_errors: dict[int, str] = {}
        self._curve_point_shape = PointShape.CIRCLE
        self._curve_point_size: float = 4.0
        self._curve_thickness: float = 2.0
        self._curve_dx: float = project.settings.curve_step_dx

        self._crop_overlay: Optional[CropOverlay] = None
        self._grid_overlay = RefGridOverlay()
        self._canvas.add_overlay(self._grid_overlay)
        self._grid_overlay.setVisible(False)

        self._calibration: Optional[CalibrationResult] = None
        self._crop_confirmed = False
        self._restoring = False

        self._style_dialog: Optional[PointStyleDialog] = None
        self._curve_point_style_dialog: Optional[PointStyleDialog] = None
        self._curve_style_dialog: Optional[CurveStyleDialog] = None
        self._current_shape = PointShape.CIRCLE
        self._current_size = DraggablePoint.DEFAULT_SIZE
        self._scatter_active_fill_opacity = self._normalise_active_fill_opacity(
            getattr(project, "scatter_active_fill_opacity", 15)
        )
        self._curve_active_fill_opacity = self._normalise_active_fill_opacity(
            getattr(project, "curve_active_fill_opacity", 15)
        )

        # The loupe follows the stored centre of exactly one active point.  It
        # deliberately never follows the mouse cursor: that made it impossible
        # to verify where the selected marker was actually saved.
        self._active_point: Optional[DraggablePoint] = None
        self._active_point_label = ""
        self._suspend_pixel_magnet = False

        # Crop corner DraggablePoints (bl, br, tl, tr)
        self._crop_corners: list[DraggablePoint] = []
        self._propagating_corner = False

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        # --- Mode buttons ---
        mode_row = QHBoxLayout()
        self._btn_crop = QPushButton("Crop")
        self._btn_ref = QPushButton("Ref Points")
        self._btn_data = QPushButton("Data Points")
        for btn in (self._btn_crop, self._btn_ref, self._btn_data):
            btn.setCheckable(True)
            mode_row.addWidget(btn)
        self._btn_crop.setChecked(True)

        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self._btn_crop, 0)
        self._mode_group.addButton(self._btn_ref, 1)
        self._mode_group.addButton(self._btn_data, 2)
        self._mode_group.idClicked.connect(self._switch_mode)
        root.addLayout(mode_row)

        # --- Stacked pages ---
        self._stack = QStackedWidget()
        root.addWidget(self._stack, stretch=1)
        self._build_crop_page()
        self._build_ref_page()
        self._build_data_page()
        self._build_precision_panel(root)

        # --- Export ---
        export_row = QHBoxLayout()
        self._combined_mode = QComboBox()
        self._combined_mode.addItems(["Union X", "Uniform grid", "Interpolation"])
        export_row.addWidget(QLabel("Combined:"))
        export_row.addWidget(self._combined_mode, stretch=1)
        root.addLayout(export_row)

        self._btn_export = QPushButton("Export to Excel")
        self._btn_export.setObjectName("primary")
        self._btn_export.clicked.connect(self._do_export)
        root.addWidget(self._btn_export)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #66bb6a; font-size: 12px;")
        root.addWidget(self._status)

        self._canvas.scene_clicked.connect(self._on_canvas_click)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Reflow the precision inspector as the dock boundary is dragged."""
        super().resizeEvent(event)
        if hasattr(self, "_precision_layout"):
            # Horizontal saves substantial vertical room at the normal
            # 600-ish dock width; stack only once the tools would be cramped.
            self._set_precision_compact(event.size().width() < 560)

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    def set_project(self, project: ProjectState) -> None:
        self._project = project
        self._restoring = True
        try:
            self._load_style_defaults(project)
            for checkbox in (self._pixel_center_check, self._marker_auto_check):
                previous = checkbox.blockSignals(True)
                checkbox.setChecked(False)
                checkbox.blockSignals(previous)
            self._marker_radius_spin.setValue(12)
            self._clear_all()
            self._curve_dx = project.settings.curve_step_dx
            self._curve_dx_spin.setValue(self._curve_dx)
            self._combined_mode.setCurrentIndex({
                CombinedMode.UNION_X: 0,
                CombinedMode.UNIFORM_GRID: 1,
                CombinedMode.INTERPOLATION: 2,
            }.get(project.combined_mode, 0))

            calibration = project.calibration
            has_calibration = (
                calibration is not None
                and calibration.x_axis._slope is not None
                and calibration.y_axis._slope is not None
            )
            x_scale = calibration.x_axis.scale if has_calibration else project.settings.x_scale
            y_scale = calibration.y_axis.scale if has_calibration else project.settings.y_scale
            self._x_scale_combo.setCurrentIndex(1 if x_scale == ScaleType.LOG else 0)
            self._y_scale_combo.setCurrentIndex(1 if y_scale == ScaleType.LOG else 0)

            if project.crop_rect is not None:
                self._show_crop_overlay(*project.crop_rect)
                self._crop_confirmed = True
                if self._crop_overlay is not None:
                    self._crop_overlay.set_confirmed_style(self._opacity_slider.value())

            x0, y0, width, height = project.crop_rect or (0.0, 0.0, 1.0, 1.0)
            if project.calibration_anchors:
                for anchor_x, anchor_y, x_value, y_value, axis in project.calibration_anchors:
                    self._create_ref_point(
                        anchor_x, anchor_y, axis=axis, x_ref=x_value, y_ref=y_value
                    )
            elif has_calibration:
                for ref in calibration.x_axis.ref_points:
                    self._create_ref_point(
                        ref.pixel, y0 + height, axis="X", x_ref=ref.data_value
                    )
                for ref in calibration.y_axis.ref_points:
                    self._create_ref_point(
                        x0, ref.pixel, axis="Y", y_ref=ref.data_value
                    )

            if has_calibration:
                project.settings.x_scale = calibration.x_axis.scale
                project.settings.y_scale = calibration.y_axis.scale
                self._calibration = calibration
                self._update_grid()
                self._grid_overlay.setVisible(self._stack.currentIndex() in (1, 2))
                self._set_calibration_diagnostics_status()

            scatter_pixels = project.scatter_points_px
            curve_pixels = project.curve_points_px
            if not scatter_pixels and has_calibration:
                scatter_pixels = [
                    [calibration.data_to_pixel(point.x, point.y) for point in series.points]
                    for series in project.series if series.kind == SeriesKind.DISCRETE
                ]
            if not curve_pixels and has_calibration:
                curve_pixels = [
                    [calibration.data_to_pixel(point.x, point.y) for point in series.points]
                    for series in project.series if series.kind == SeriesKind.CONTINUOUS
                ]

            self._series_spin.setValue(max(1, len(scatter_pixels)))
            self._curve_series_spin.setValue(max(1, len(curve_pixels)))
            self._snap_free.setChecked(True)
            for si, points in enumerate(scatter_pixels):
                self._data_tabs.setCurrentIndex(si)
                for px, py in points:
                    self._restore_data_point(px, py)
            for ci, points in enumerate(curve_pixels):
                self._curve_tabs.setCurrentIndex(ci)
                for px, py in points:
                    self._restore_curve_point(px, py)
            self._restore_saved_styles(project)
            if scatter_pixels or curve_pixels:
                self._data_tabs.setCurrentIndex(0)
                self._curve_tabs.setCurrentIndex(0)
            if not has_calibration and project.series and not (scatter_pixels or curve_pixels):
                self._status.setText(
                    "Project contains data series but no valid calibration; points could not be restored."
                )
            elif not has_calibration and (scatter_pixels or curve_pixels):
                for table in [*self._series_tables, *self._curve_tables]:
                    table.clear_fig_values()
                self._ref_status.setText("Calibration draft restored — press Build before digitising/exporting.")
                self._ref_status.setStyleSheet("color: #ffcc66;")
                self._status.setText(
                    "Draft pixel points restored. Rebuild calibration to recover data coordinates."
                )
            if not has_calibration and project.calibration_anchors:
                self._ref_status.setText("Calibration draft restored — press Build to validate it.")
                self._ref_status.setStyleSheet("color: #ffcc66;")
            self.apply_settings()
        finally:
            self._restoring = False
            self._switch_mode(self._stack.currentIndex())

    def _configure_point(self, point: DraggablePoint) -> None:
        settings = self._project.settings
        point.set_nudge_steps(settings.arrow_step, settings.ctrl_step, settings.shift_step)

    @staticmethod
    def _point_shape_from_name(name: object, fallback: PointShape) -> PointShape:
        try:
            return PointShape[str(name)]
        except (KeyError, TypeError):
            return fallback

    @staticmethod
    def _normalise_active_fill_opacity(value: object) -> int:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 15
        if not math.isfinite(numeric):
            return 15
        return int(round(max(0.0, min(100.0, numeric))))

    def _load_style_defaults(self, project: ProjectState) -> None:
        scatter = getattr(project, "scatter_default_point_style", ("CIRCLE", 5.0))
        curve = getattr(project, "curve_default_point_style", ("CIRCLE", 4.0))
        if not isinstance(scatter, (tuple, list)):
            scatter = ("CIRCLE", 5.0)
        if not isinstance(curve, (tuple, list)):
            curve = ("CIRCLE", 4.0)
        self._current_shape = self._point_shape_from_name(
            scatter[0] if len(scatter) >= 1 else "CIRCLE", PointShape.CIRCLE
        )
        try:
            self._current_size = max(1.0, min(50.0, float(scatter[1])))
            if not math.isfinite(self._current_size):
                raise ValueError("non-finite point size")
        except (IndexError, TypeError, ValueError):
            self._current_size = DraggablePoint.DEFAULT_SIZE
        self._curve_point_shape = self._point_shape_from_name(
            curve[0] if len(curve) >= 1 else "CIRCLE", PointShape.CIRCLE
        )
        try:
            self._curve_point_size = max(1.0, min(50.0, float(curve[1])))
            if not math.isfinite(self._curve_point_size):
                raise ValueError("non-finite point size")
        except (IndexError, TypeError, ValueError):
            self._curve_point_size = 4.0
        self._scatter_active_fill_opacity = self._normalise_active_fill_opacity(
            getattr(project, "scatter_active_fill_opacity", 15)
        )
        self._curve_active_fill_opacity = self._normalise_active_fill_opacity(
            getattr(project, "curve_active_fill_opacity", 15)
        )
        try:
            self._curve_thickness = max(
                0.5, min(50.0, float(getattr(project, "curve_default_thickness", 2.0)))
            )
            if not math.isfinite(self._curve_thickness):
                raise ValueError("non-finite curve thickness")
        except (TypeError, ValueError):
            self._curve_thickness = 2.0

        previous = self._curve_size_spin.blockSignals(True)
        self._curve_size_spin.setValue(self._curve_point_size)
        self._curve_size_spin.blockSignals(previous)
        previous = self._curve_thick_spin.blockSignals(True)
        self._curve_thick_spin.setValue(self._curve_thickness)
        self._curve_thick_spin.blockSignals(previous)

    def _restore_saved_styles(self, project: ProjectState) -> None:
        for series, styles in zip(
            self._series_points, getattr(project, "scatter_point_styles", [])
        ):
            for point, style in zip(series, styles):
                if len(style) < 2:
                    continue
                point.set_point_shape(
                    self._point_shape_from_name(style[0], self._current_shape)
                )
                try:
                    size = float(style[1])
                    if math.isfinite(size):
                        point.set_point_size(min(50.0, size))
                except (TypeError, ValueError):
                    pass

        for curve, styles in zip(
            self._curve_points, getattr(project, "curve_point_styles", [])
        ):
            for point, style in zip(curve, styles):
                if len(style) < 2:
                    continue
                point.set_point_shape(
                    self._point_shape_from_name(style[0], self._curve_point_shape)
                )
                try:
                    size = float(style[1])
                    if math.isfinite(size):
                        point.set_point_size(min(50.0, size))
                except (TypeError, ValueError):
                    pass

        valid_pen_styles = Qt.PenStyle.__members__
        for ci, style in enumerate(
            getattr(project, "curve_visual_styles", [])
        ):
            if ci >= len(self._curve_paths) or len(style) < 3:
                break
            color = QColor(str(style[0]))
            if color.isValid():
                self._set_curve_color(ci, color)
            try:
                thickness = float(style[1])
                if math.isfinite(thickness):
                    self._curve_paths[ci].set_thickness(min(50.0, thickness))
            except (TypeError, ValueError):
                pass
            try:
                pen_name = str(style[2])
                if pen_name in valid_pen_styles:
                    self._curve_paths[ci].set_line_style(valid_pen_styles[pen_name])
            except (TypeError, ValueError, KeyError):
                pass

    def _configure_table(self, table) -> None:
        settings = self._project.settings
        table.set_nudge_steps(settings.arrow_step, settings.ctrl_step, settings.shift_step)

    def apply_settings(self) -> None:
        """Apply settings that affect live manual tools."""
        for table in [self._crop_corner_table, self._ref_table,
                      *self._series_tables, *self._curve_tables]:
            self._configure_table(table)
        for point in [*self._crop_corners, *self._ref_points,
                      *(p for group in self._series_points for p in group),
                      *(p for group in self._curve_points for p in group)]:
            self._configure_point(point)
        self._centerline_snap_check.setChecked(self._project.settings.snap_to_edge)
        magnifier = self._project.settings.magnifier_enabled
        self._loupe.setVisible(magnifier)
        self._loupe_coords.setVisible(magnifier)
        mode = self._stack.currentIndex()
        self._precision_group.setVisible(mode == 2 or (mode == 1 and magnifier))
        self._curve_dx_spin.setValue(self._project.settings.curve_step_dx)
        self._x_scale_combo.setCurrentIndex(
            1 if self._project.settings.x_scale == ScaleType.LOG else 0
        )
        self._y_scale_combo.setCurrentIndex(
            1 if self._project.settings.y_scale == ScaleType.LOG else 0
        )

    # ------------------------------------------------------------------
    # page builders
    # ------------------------------------------------------------------

    def _build_crop_page(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        crop_guide = QLabel(
            "Set the four plot boundaries on the geometric centre-lines of the frame strokes. "
            "Auto-detection is a candidate only; open or rotated axes require manual verification."
        )
        crop_guide.setWordWrap(True)
        lay.addWidget(crop_guide)
        btn_auto = QPushButton("Auto-detect area")
        btn_auto.clicked.connect(self._crop_auto)
        lay.addWidget(btn_auto)
        btn_ok = QPushButton("Confirm area")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self._crop_confirm)
        lay.addWidget(btn_ok)

        self._crop_corner_table = CropCornerTable()
        self._configure_table(self._crop_corner_table)
        lay.addWidget(self._crop_corner_table, stretch=1)
        self._crop_corner_table.point_wind_changed.connect(self._crop_table_changed)
        self._crop_corner_table.key_move.connect(self._crop_key_move)

        lay.addWidget(QLabel("Crop overlay opacity:"))
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(0, 120)
        self._opacity_slider.setValue(30)
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        lay.addWidget(self._opacity_slider)

        self._crop_status = QLabel("")
        lay.addWidget(self._crop_status)
        lay.addStretch()
        self._stack.addWidget(page)

    def _build_ref_page(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)

        guide = QLabel(
            "Calibration needs at least 2 X anchors and 2 Y anchors. "
            "Choose anchors far apart. For a thick line, place the crosshair "
            "at the geometric centre of the stroke (between the two middle "
            "pixels for a 4 px line). Both value cells are editable: filling "
            "the second coordinate automatically changes Axis to Both; clear "
            "one coordinate to use the point only for X or Y."
        )
        guide.setWordWrap(True)
        lay.addWidget(guide)

        form = QFormLayout()
        self._x_scale_combo = QComboBox()
        self._x_scale_combo.addItems(["Linear", "Logarithmic"])
        self._x_scale_combo.setCurrentIndex(
            1 if self._project.settings.x_scale == ScaleType.LOG else 0
        )
        form.addRow("X scale:", self._x_scale_combo)
        self._y_scale_combo = QComboBox()
        self._y_scale_combo.addItems(["Linear", "Logarithmic"])
        self._y_scale_combo.setCurrentIndex(
            1 if self._project.settings.y_scale == ScaleType.LOG else 0
        )
        form.addRow("Y scale:", self._y_scale_combo)
        self._ref_axis_combo = QComboBox()
        self._ref_axis_combo.addItems(["X anchor", "Y anchor", "Both (known intersection)"])
        self._ref_axis_combo.setToolTip(
            "Sets the initial role. You can later fill or clear either value "
            "cell in the table; Axis will update automatically."
        )
        form.addRow("Next click adds:", self._ref_axis_combo)
        lay.addLayout(form)

        self._centerline_snap_check = QCheckBox("Snap anchors to stroke centre (±10 px)")
        self._centerline_snap_check.setChecked(self._project.settings.snap_to_edge)
        self._centerline_snap_check.setToolTip(
            "Finds the two sides of a nearby dark tick/frame stroke and uses their sub-pixel centre."
        )
        lay.addWidget(self._centerline_snap_check)

        frame_group = QGroupBox("Fast calibration from frame centre-lines")
        frame_grid = QGridLayout(frame_group)
        self._frame_value_edits: dict[str, QLineEdit] = {}
        for row, (key, text) in enumerate((
            ("x_left", "X at left"), ("x_right", "X at right"),
            ("y_bottom", "Y at bottom"), ("y_top", "Y at top"),
        )):
            edit = QLineEdit()
            edit.setValidator(QDoubleValidator(edit))
            edit.setPlaceholderText("e.g. 1e-3")
            edit.setMaximumWidth(95)
            self._frame_value_edits[key] = edit
            frame_grid.addWidget(QLabel(text), row // 2, (row % 2) * 2)
            frame_grid.addWidget(edit, row // 2, (row % 2) * 2 + 1)
        btn_frame = QPushButton("Create anchors and build")
        btn_frame.setToolTip(
            "Uses opposite intersections of the confirmed crop rectangle; its edges must follow stroke centres."
        )
        btn_frame.clicked.connect(self._calibrate_from_frame)
        frame_grid.addWidget(btn_frame, 2, 0, 1, 4)
        lay.addWidget(frame_group)

        self._ref_table = RefPointTable()
        self._configure_table(self._ref_table)
        lay.addWidget(self._ref_table, stretch=1)

        btn_row = QHBoxLayout()
        btn_del = QPushButton("Delete")
        btn_del.clicked.connect(self._ref_delete_selected)
        btn_row.addWidget(btn_del)

        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self._ref_clear_all)
        btn_row.addWidget(btn_clear)

        btn_build = QPushButton("Build")
        btn_build.setObjectName("primary")
        btn_build.clicked.connect(self._rebuild_calibration)
        btn_row.addWidget(btn_build)
        lay.addLayout(btn_row)

        self._ref_status = QLabel("Need 2 X anchors and 2 Y anchors (3+ per axis enables an error estimate).")
        self._ref_status.setWordWrap(True)
        lay.addWidget(self._ref_status)

        self._ref_table.point_wind_changed.connect(self._ref_table_wind_changed)
        self._ref_table.ref_value_changed.connect(self._on_ref_value_changed)
        self._ref_table.key_move.connect(self._ref_key_move)
        self._ref_table.currentCellChanged.connect(
            lambda row, _column, _old_row, _old_column: self._on_ref_row_selected(row)
        )
        self._x_scale_combo.currentIndexChanged.connect(self._on_calibration_input_changed)
        self._y_scale_combo.currentIndexChanged.connect(self._on_calibration_input_changed)

        self._stack.addWidget(page)

    # ------------------------------------------------------------------
    # Data Points page (Scatter / Curve sub-modes)
    # ------------------------------------------------------------------

    def _build_data_page(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)

        # Sub-mode toggle
        submode_row = QHBoxLayout()
        self._rb_scatter = QRadioButton("Scatter")
        self._rb_curve = QRadioButton("Curve")
        self._rb_scatter.setChecked(True)
        submode_row.addWidget(self._rb_scatter)
        submode_row.addWidget(self._rb_curve)
        lay.addLayout(submode_row)

        self._data_submode_stack = QStackedWidget()
        lay.addWidget(self._data_submode_stack, stretch=1)

        self._build_scatter_subpage()
        self._build_curve_subpage()

        self._rb_scatter.toggled.connect(self._on_data_submode_toggled)

        self._stack.addWidget(page)

    def _build_precision_panel(self, root: QVBoxLayout) -> None:
        """Build the common Ref/Scatter/Curve active-point inspector."""
        self._precision_group = QGroupBox("Active point precision")
        self._precision_group.setCheckable(True)
        self._precision_group.setChecked(True)
        self._precision_group.setToolTip(
            "Clear the title checkbox to collapse this section and give the point table more room."
        )
        group_layout = QVBoxLayout(self._precision_group)
        group_layout.setContentsMargins(6, 6, 6, 6)

        # Keep the group's public identity stable for the existing workflow,
        # while putting all collapsible children into a single content widget.
        self._precision_content = QWidget()
        self._precision_layout = QGridLayout(self._precision_content)
        self._precision_layout.setContentsMargins(0, 0, 0, 0)
        self._precision_layout.setHorizontalSpacing(10)
        self._precision_layout.setVerticalSpacing(6)
        group_layout.addWidget(self._precision_content)

        self._loupe = QLabel("Select or create a point")
        self._loupe.setFixedSize(180, 180)
        self._loupe.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loupe.setStyleSheet("border: 1px solid #666; background: #222;")
        self._loupe.setToolTip(
            "Nearest-neighbour source pixels. The red cross is the exact stored centre "
            "of the active point, not the mouse cursor."
        )

        self._precision_tools_widget = QWidget()
        tools = QVBoxLayout(self._precision_tools_widget)
        tools.setContentsMargins(0, 0, 0, 0)
        self._loupe_coords = QLabel(
            "Create a point or select one in a table.\n"
            "The red cross will show its exact stored centre."
        )
        self._loupe_coords.setWordWrap(True)
        tools.addWidget(self._loupe_coords)

        self._data_precision_tools = QWidget()
        data_tools = QVBoxLayout(self._data_precision_tools)
        data_tools.setContentsMargins(0, 0, 0, 0)

        self._pixel_center_check = QCheckBox("Pixel-centre magnet")
        self._pixel_center_check.setToolTip(
            "While enabled, snaps the active/new data point after placement, dragging, "
            "arrow movement, or a coordinate-table edit to a source-pixel centre. "
            "Keep this OFF for an even-width stroke: its true centre may lie between pixels."
        )
        self._pixel_center_check.toggled.connect(self._on_pixel_magnet_toggled)
        data_tools.addWidget(self._pixel_center_check)

        snap_now = QPushButton("Snap active now")
        snap_now.clicked.connect(self._snap_active_to_pixel_center)
        data_tools.addWidget(snap_now)

        self._marker_auto_check = QCheckBox("Auto centre suggestion")
        self._marker_auto_check.setToolTip(
            "Analyses a local image patch, temporarily displays the candidate, and asks "
            "for confirmation. Nothing is accepted silently. A confirmed marker centre "
            "may be sub-pixel even while the separate pixel magnet remains armed."
        )
        data_tools.addWidget(self._marker_auto_check)

        marker_row = QGridLayout()
        self._marker_center_button = QPushButton("Find marker centre…")
        self._marker_center_button.clicked.connect(self._propose_active_marker_center)
        marker_row.addWidget(self._marker_center_button, 0, 0, 1, 2)
        marker_row.addWidget(QLabel("Search radius:"), 1, 0)
        self._marker_radius_spin = QSpinBox()
        self._marker_radius_spin.setRange(4, 40)
        self._marker_radius_spin.setValue(12)
        self._marker_radius_spin.setSuffix(" px")
        self._marker_radius_spin.setToolTip(
            "Local search radius. It should contain the marker but as little neighbouring "
            "curve/grid content as possible."
        )
        marker_row.addWidget(self._marker_radius_spin, 1, 1)
        marker_row.setColumnStretch(0, 1)
        data_tools.addLayout(marker_row)

        tools.addWidget(self._data_precision_tools)
        tools.addStretch()
        self._precision_compact: bool | None = None
        self._set_precision_compact(False)
        self._precision_group.toggled.connect(self._set_precision_expanded)
        self._precision_group.setVisible(False)
        magnifier = self._project.settings.magnifier_enabled
        self._loupe.setVisible(magnifier)
        self._loupe_coords.setVisible(magnifier)
        root.addWidget(self._precision_group)

    @Slot(bool)
    def _set_precision_expanded(self, expanded: bool) -> None:
        """Show or hide the inspector body without replacing its widgets."""
        self._precision_content.setVisible(expanded)

    def _set_precision_compact(self, compact: bool) -> None:
        """Stack the loupe above its tools when the dock becomes narrow."""
        if self._precision_compact == compact:
            return
        self._precision_compact = compact
        self._precision_layout.removeWidget(self._loupe)
        self._precision_layout.removeWidget(self._precision_tools_widget)
        if compact:
            self._precision_layout.addWidget(
                self._loupe,
                0,
                0,
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter,
            )
            self._precision_layout.addWidget(self._precision_tools_widget, 1, 0)
            self._precision_layout.setColumnStretch(0, 1)
            self._precision_layout.setColumnStretch(1, 0)
        else:
            self._precision_layout.addWidget(
                self._loupe, 0, 0, Qt.AlignmentFlag.AlignTop
            )
            self._precision_layout.addWidget(self._precision_tools_widget, 0, 1)
            self._precision_layout.setColumnStretch(0, 0)
            self._precision_layout.setColumnStretch(1, 1)
        self._precision_layout.invalidate()

    def _build_scatter_subpage(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        scatter_guide = QLabel(
            "Scatter stores independent marker centres. Zoom until individual pixels are visible; "
            "put the point crosshair at the marker's geometric centre."
        )
        scatter_guide.setWordWrap(True)
        lay.addWidget(scatter_guide)

        snap_row = QGridLayout()
        self._snap_free = QRadioButton("Free")
        self._snap_x = QRadioButton("Lock X")
        self._snap_y = QRadioButton("Lock Y")
        self._snap_xy = QRadioButton("Lock X+Y")
        self._snap_free.setChecked(True)
        for rb in (self._snap_x, self._snap_y, self._snap_xy):
            rb.setToolTip("Snap to a nearby calibration anchor within the distance below.")
        for index, rb in enumerate(
            (self._snap_free, self._snap_x, self._snap_y, self._snap_xy)
        ):
            snap_row.addWidget(rb, index // 2, index % 2)
        lay.addLayout(snap_row)

        snap_options = QHBoxLayout()
        snap_options.addWidget(QLabel("Max anchor distance (px):"))
        self._snap_threshold_spin = QDoubleSpinBox()
        self._snap_threshold_spin.setRange(0.5, 1000.0)
        self._snap_threshold_spin.setValue(12.0)
        self._snap_threshold_spin.setDecimals(1)
        self._snap_threshold_spin.setToolTip(
            "No snap is applied when the nearest calibration anchor is farther away."
        )
        snap_options.addWidget(self._snap_threshold_spin)
        lay.addLayout(snap_options)

        tool_row = QHBoxLayout()
        btn_style = QPushButton("Style Points")
        btn_style.setToolTip(
            "Set shape/size for Scatter points and the translucent fill of the active point."
        )
        btn_style.clicked.connect(self._open_style_dialog)
        tool_row.addWidget(btn_style)
        tool_row.addStretch()
        lay.addLayout(tool_row)

        series_row = QHBoxLayout()
        series_row.addWidget(QLabel("Series count:"))
        self._series_spin = QSpinBox()
        self._series_spin.setRange(1, 20)
        self._series_spin.setValue(1)
        self._series_spin.valueChanged.connect(self._rebuild_series_tabs)
        series_row.addWidget(self._series_spin)
        lay.addLayout(series_row)

        self._data_tabs = QTabWidget()
        self._data_tabs.currentChanged.connect(self._on_series_tab_changed)
        lay.addWidget(self._data_tabs, stretch=1)

        btn_del = QPushButton("Delete selected data point")
        btn_del.clicked.connect(self._data_delete_selected)
        lay.addWidget(btn_del)

        self._data_status = QLabel("")
        lay.addWidget(self._data_status)

        self._rebuild_series_tabs(1)
        self._data_submode_stack.addWidget(page)

    def _build_curve_subpage(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        curve_guide = QLabel(
            "Curve represents a single-valued y(x). Control X values must be distinct. "
            "Preview and export use the same shape-preserving PCHIP interpolation; "
            "log axes are interpolated in log space."
        )
        curve_guide.setWordWrap(True)
        lay.addWidget(curve_guide)

        style_row = QHBoxLayout()
        btn_point_style = QPushButton("Style Points")
        btn_point_style.setToolTip(
            "Set shape/size for Curve points and the translucent fill of the active point."
        )
        btn_point_style.clicked.connect(self._open_curve_point_style_dialog)
        style_row.addWidget(btn_point_style)
        btn_curve_style = QPushButton("Curve Style")
        btn_curve_style.setToolTip(
            "Set colour, thickness and line pattern for the active curve."
        )
        btn_curve_style.clicked.connect(self._open_curve_style_dialog)
        style_row.addWidget(btn_curve_style)
        style_row.addStretch()
        lay.addLayout(style_row)

        # Controls row
        ctrl_form = QFormLayout()

        self._curve_size_spin = QDoubleSpinBox()
        self._curve_size_spin.setRange(1.0, 50.0)
        self._curve_size_spin.setValue(self._curve_point_size)
        self._curve_size_spin.setSingleStep(0.5)
        self._curve_size_spin.setDecimals(1)
        self._curve_size_spin.valueChanged.connect(self._on_curve_point_size)
        ctrl_form.addRow("Default point size:", self._curve_size_spin)

        self._curve_thick_spin = QDoubleSpinBox()
        self._curve_thick_spin.setRange(0.5, 50.0)
        self._curve_thick_spin.setValue(self._curve_thickness)
        self._curve_thick_spin.setSingleStep(0.5)
        self._curve_thick_spin.setDecimals(1)
        self._curve_thick_spin.valueChanged.connect(self._on_curve_thickness)
        ctrl_form.addRow("Set all curve thicknesses:", self._curve_thick_spin)

        self._curve_dx_spin = QDoubleSpinBox()
        self._curve_dx_spin.setRange(0.001, 10000.0)
        self._curve_dx_spin.setValue(self._curve_dx)
        self._curve_dx_spin.setSingleStep(0.01)
        self._curve_dx_spin.setDecimals(4)
        self._curve_dx_spin.valueChanged.connect(self._on_curve_dx)
        ctrl_form.addRow("Export dx:", self._curve_dx_spin)

        lay.addLayout(ctrl_form)

        # Series count
        cseries_row = QHBoxLayout()
        cseries_row.addWidget(QLabel("Curves count:"))
        self._curve_series_spin = QSpinBox()
        self._curve_series_spin.setRange(1, 20)
        self._curve_series_spin.setValue(1)
        self._curve_series_spin.valueChanged.connect(self._rebuild_curve_tabs)
        cseries_row.addWidget(self._curve_series_spin)
        lay.addLayout(cseries_row)

        self._curve_tabs = QTabWidget()
        self._curve_tabs.currentChanged.connect(self._on_curve_tab_changed)
        lay.addWidget(self._curve_tabs, stretch=1)

        btn_del = QPushButton("Delete selected control point")
        btn_del.clicked.connect(self._curve_delete_selected)
        lay.addWidget(btn_del)

        self._curve_status = QLabel("")
        lay.addWidget(self._curve_status)

        self._rebuild_curve_tabs(1)
        self._data_submode_stack.addWidget(page)

    @Slot(bool)
    def _on_data_submode_toggled(self, scatter_checked: bool) -> None:
        self._data_submode_stack.setCurrentIndex(0 if scatter_checked else 1)
        if self._stack.currentIndex() == 2:
            self._refresh_data_visibility()
            self._sync_active_point_for_mode()

    def _is_scatter_mode(self) -> bool:
        return self._data_submode_stack.currentIndex() == 0

    # ------------------------------------------------------------------
    # style dialog (scatter only)
    # ------------------------------------------------------------------

    def _open_style_dialog(self) -> None:
        if self._style_dialog is None:
            self._style_dialog = PointStyleDialog(self)
            self._style_dialog.shape_changed.connect(self._on_style_shape)
            self._style_dialog.size_changed.connect(self._on_style_size)
            self._style_dialog.active_fill_opacity_changed.connect(
                self._on_scatter_active_fill_opacity
            )
        self._style_dialog.set_shape(self._current_shape)
        self._style_dialog.set_size(self._current_size)
        self._style_dialog.set_active_fill_opacity(
            self._scatter_active_fill_opacity
        )
        self._style_dialog.show()
        self._style_dialog.raise_()
        self._style_dialog.activateWindow()

    @Slot(PointShape)
    def _on_style_shape(self, shape: PointShape) -> None:
        self._current_shape = shape
        self._apply_style_to_selected()

    @Slot(float)
    def _on_style_size(self, size: float) -> None:
        self._current_size = size
        self._apply_style_to_selected()

    @Slot(int)
    def _on_scatter_active_fill_opacity(self, percent: int) -> None:
        self._scatter_active_fill_opacity = self._normalise_active_fill_opacity(
            percent
        )
        for points in self._series_points:
            for point in points:
                point.set_active_fill_opacity(self._scatter_active_fill_opacity)

    def _apply_style_to_selected(self) -> None:
        si = self._active_series_index()
        if si >= len(self._series_tables):
            return
        table = self._series_tables[si]
        rows = table.selected_rows()
        if not rows:
            return
        pts = self._series_points[si] if si < len(self._series_points) else []
        for r in rows:
            if 0 <= r < len(pts):
                pts[r].set_point_shape(self._current_shape)
                pts[r].set_point_size(self._current_size)

    def _open_curve_point_style_dialog(self) -> None:
        if self._curve_point_style_dialog is None:
            self._curve_point_style_dialog = PointStyleDialog(self)
            self._curve_point_style_dialog.setWindowTitle("Curve Point Style")
            self._curve_point_style_dialog.shape_changed.connect(
                self._on_curve_point_style_shape
            )
            self._curve_point_style_dialog.size_changed.connect(
                self._on_curve_point_style_size
            )
            self._curve_point_style_dialog.active_fill_opacity_changed.connect(
                self._on_curve_active_fill_opacity
            )
        self._curve_point_style_dialog.set_shape(self._curve_point_shape)
        self._curve_point_style_dialog.set_size(self._curve_point_size)
        self._curve_point_style_dialog.set_active_fill_opacity(
            self._curve_active_fill_opacity
        )
        self._curve_point_style_dialog.show()
        self._curve_point_style_dialog.raise_()
        self._curve_point_style_dialog.activateWindow()

    @Slot(PointShape)
    def _on_curve_point_style_shape(self, shape: PointShape) -> None:
        self._curve_point_shape = shape
        self._apply_curve_point_style_to_selected(shape=shape)

    @Slot(float)
    def _on_curve_point_style_size(self, size: float) -> None:
        self._curve_point_size = size
        previous = self._curve_size_spin.blockSignals(True)
        self._curve_size_spin.setValue(size)
        self._curve_size_spin.blockSignals(previous)
        self._apply_curve_point_style_to_selected(size=size)

    @Slot(int)
    def _on_curve_active_fill_opacity(self, percent: int) -> None:
        self._curve_active_fill_opacity = self._normalise_active_fill_opacity(
            percent
        )
        for points in self._curve_points:
            for point in points:
                point.set_active_fill_opacity(self._curve_active_fill_opacity)

    def _apply_curve_point_style_to_selected(
        self,
        *,
        shape: PointShape | None = None,
        size: float | None = None,
    ) -> None:
        ci = self._active_curve_index()
        if ci >= len(self._curve_tables) or ci >= len(self._curve_points):
            return
        rows = self._curve_tables[ci].selected_rows()
        for row in rows:
            if 0 <= row < len(self._curve_points[ci]):
                point = self._curve_points[ci][row]
                if shape is not None:
                    point.set_point_shape(shape)
                if size is not None:
                    point.set_point_size(size)

    def _open_curve_style_dialog(self) -> None:
        ci = self._active_curve_index()
        if ci >= len(self._curve_paths):
            return
        if self._curve_style_dialog is None:
            self._curve_style_dialog = CurveStyleDialog(self)
            self._curve_style_dialog.color_changed.connect(self._on_curve_style_color)
            self._curve_style_dialog.thickness_changed.connect(
                self._on_curve_style_thickness
            )
            self._curve_style_dialog.line_style_changed.connect(
                self._on_curve_style_line_pattern
            )
        self._sync_curve_style_dialog()
        self._curve_style_dialog.show()
        self._curve_style_dialog.raise_()
        self._curve_style_dialog.activateWindow()

    def _sync_curve_style_dialog(self) -> None:
        if self._curve_style_dialog is None:
            return
        ci = self._active_curve_index()
        if ci >= len(self._curve_paths):
            return
        path = self._curve_paths[ci]
        previous = self._curve_style_dialog.blockSignals(True)
        self._curve_style_dialog.set_color(path.color())
        self._curve_style_dialog.set_thickness(path.thickness())
        self._curve_style_dialog.set_line_style(path.line_style())
        self._curve_style_dialog.blockSignals(previous)
        self._curve_style_dialog.setWindowTitle(f"Curve {ci + 1} Style")

    @Slot(QColor)
    def _on_curve_style_color(self, color: QColor) -> None:
        self._set_curve_color(self._active_curve_index(), color)

    @Slot(float)
    def _on_curve_style_thickness(self, thickness: float) -> None:
        ci = self._active_curve_index()
        if ci < len(self._curve_paths):
            self._curve_paths[ci].set_thickness(thickness)

    @Slot(Qt.PenStyle)
    def _on_curve_style_line_pattern(self, style: Qt.PenStyle) -> None:
        ci = self._active_curve_index()
        if ci < len(self._curve_paths):
            self._curve_paths[ci].set_line_style(style)

    # ------------------------------------------------------------------
    # scatter series tabs management
    # ------------------------------------------------------------------

    def _make_series_tab_widget(self, si: int) -> QWidget:
        container = QWidget()
        vlay = QVBoxLayout(container)
        vlay.setContentsMargins(0, 0, 0, 0)

        table = DataPointTable()
        self._configure_table(table)
        table.point_wind_changed.connect(
            lambda row, x, y, s=si: self._data_table_wind_changed(s, row, x, y)
        )
        table.key_move.connect(
            lambda row, dx, dy, s=si: self._data_key_move(s, row, dx, dy)
        )
        table.currentCellChanged.connect(
            lambda row, _column, _old_row, _old_column, s=si:
                self._on_data_row_selected(s, row)
        )
        vlay.addWidget(table, stretch=1)

        btn_row = QHBoxLayout()
        btn_sel = QPushButton("Select all")
        btn_sel.clicked.connect(lambda checked=False, t=table: t.select_all_rows())
        btn_row.addWidget(btn_sel)

        btn_clear = QPushButton("Clear all points")
        btn_clear.clicked.connect(lambda checked=False, s=si: self._data_clear_series(s))
        btn_row.addWidget(btn_clear)
        vlay.addLayout(btn_row)

        container._table = table  # type: ignore[attr-defined]
        return container

    def _rebuild_series_tabs(self, n: int) -> None:
        while self._data_tabs.count() > n:
            idx = self._data_tabs.count() - 1
            self._data_tabs.removeTab(idx)
            if idx < len(self._series_tables):
                self._series_tables.pop(idx)
            if idx < len(self._series_points):
                for pt in self._series_points[idx]:
                    self._safe_remove_point(pt)
                self._series_points.pop(idx)

        while self._data_tabs.count() < n:
            idx = self._data_tabs.count()
            container = self._make_series_tab_widget(idx)
            self._series_tables.append(container._table)  # type: ignore[attr-defined]
            self._series_points.append([])
            self._data_tabs.addTab(container, f"Series {idx + 1}")

    def _active_series_index(self) -> int:
        return max(0, self._data_tabs.currentIndex())

    @Slot(int)
    def _on_series_tab_changed(self, idx: int) -> None:
        if self._stack.currentIndex() == 2 and self._is_scatter_mode():
            self._refresh_data_visibility()
            self._sync_active_point_for_mode()

    # ------------------------------------------------------------------
    # curve series tabs management
    # ------------------------------------------------------------------

    def _make_curve_tab_widget(self, ci: int) -> QWidget:
        container = QWidget()
        vlay = QVBoxLayout(container)
        vlay.setContentsMargins(0, 0, 0, 0)

        table = DataPointTable()
        self._configure_table(table)
        table.point_wind_changed.connect(
            lambda row, x, y, s=ci: self._curve_table_wind_changed(s, row, x, y)
        )
        table.key_move.connect(
            lambda row, dx, dy, s=ci: self._curve_key_move(s, row, dx, dy)
        )
        table.currentCellChanged.connect(
            lambda row, _column, _old_row, _old_column, s=ci:
                self._on_curve_row_selected(s, row)
        )
        vlay.addWidget(table, stretch=1)

        btn_row = QHBoxLayout()

        btn_sel = QPushButton("Select all")
        btn_sel.clicked.connect(lambda checked=False, t=table: t.select_all_rows())
        btn_row.addWidget(btn_sel)

        btn_color = QPushButton("Color")
        btn_color.clicked.connect(lambda checked=False, s=ci: self._curve_pick_color(s))
        btn_row.addWidget(btn_color)

        btn_clear = QPushButton("Clear curve")
        btn_clear.clicked.connect(lambda checked=False, s=ci: self._curve_clear_series(s))
        btn_row.addWidget(btn_clear)

        vlay.addLayout(btn_row)

        container._table = table  # type: ignore[attr-defined]
        return container

    def _rebuild_curve_tabs(self, n: int) -> None:
        while self._curve_tabs.count() > n:
            idx = self._curve_tabs.count() - 1
            self._curve_tabs.removeTab(idx)
            if idx < len(self._curve_tables):
                self._curve_tables.pop(idx)
            if idx < len(self._curve_points):
                for pt in self._curve_points[idx]:
                    self._safe_remove_point(pt)
                self._curve_points.pop(idx)
            if idx < len(self._curve_paths):
                path = self._curve_paths.pop(idx)
                try:
                    self._canvas.remove_overlay(path)
                except Exception:
                    pass
            if idx < len(self._curve_colors):
                self._curve_colors.pop(idx)
            self._curve_errors.pop(idx, None)

        while self._curve_tabs.count() < n:
            idx = self._curve_tabs.count()
            container = self._make_curve_tab_widget(idx)
            self._curve_tables.append(container._table)  # type: ignore[attr-defined]
            self._curve_points.append([])

            color = _curve_series_color(idx)
            if idx < len(self._curve_colors):
                self._curve_colors[idx] = color
            else:
                self._curve_colors.append(color)

            path = CurvePathOverlay(color=color, thickness=self._curve_thickness)
            self._canvas.add_overlay(path)
            vis = (self._stack.currentIndex() == 2
                   and not self._is_scatter_mode()
                   and idx == self._active_curve_index())
            path.setVisible(vis)
            self._curve_paths.append(path)

            self._curve_tabs.addTab(container, f"Curve {idx + 1}")

    def _active_curve_index(self) -> int:
        return max(0, self._curve_tabs.currentIndex())

    @Slot(int)
    def _on_curve_tab_changed(self, idx: int) -> None:
        self._sync_curve_style_dialog()
        if self._stack.currentIndex() == 2 and not self._is_scatter_mode():
            self._refresh_data_visibility()
            self._sync_active_point_for_mode()

    # ------------------------------------------------------------------
    # curve controls
    # ------------------------------------------------------------------

    @Slot(float)
    def _on_curve_point_size(self, val: float) -> None:
        self._curve_point_size = val

    @Slot(float)
    def _on_curve_thickness(self, val: float) -> None:
        self._curve_thickness = val
        for path in self._curve_paths:
            path.set_thickness(val)

    @Slot(float)
    def _on_curve_dx(self, val: float) -> None:
        self._curve_dx = val

    def _curve_pick_color(self, ci: int) -> None:
        old = self._curve_colors[ci] if ci < len(self._curve_colors) else QColor(255, 80, 80)
        color = QColorDialog.getColor(old, self, "Curve Color")
        if not color.isValid():
            return
        self._set_curve_color(ci, color)

    def _set_curve_color(self, ci: int, color: QColor) -> None:
        if ci < 0 or not color.isValid():
            return
        if ci < len(self._curve_colors):
            self._curve_colors[ci] = QColor(color)
        if ci < len(self._curve_paths):
            self._curve_paths[ci].set_color(color)
        if ci < len(self._curve_points):
            for pt in self._curve_points[ci]:
                pt.set_color(color)
        if ci < len(self._curve_tables):
            for row in range(self._curve_tables[ci].rowCount()):
                self._curve_tables[ci].set_row_color(row, color)

    # ------------------------------------------------------------------
    # mode switching
    # ------------------------------------------------------------------

    @Slot(int)
    def _switch_mode(self, idx: int) -> None:
        self._stack.setCurrentIndex(idx)

        # Crop overlay + corner points
        if self._crop_overlay:
            self._crop_overlay.set_interactive(False)
            if idx == 0:
                self._crop_overlay.setVisible(True)
                if self._crop_confirmed:
                    self._crop_overlay.set_confirmed_style(self._opacity_slider.value())
                else:
                    self._crop_overlay.set_editing_style()
            else:
                # Keep the confirmed yellow work-area boundary visible through
                # calibration and digitisation, but remove its fill so it does
                # not tint source pixels used for precision picking.
                self._crop_overlay.setVisible(self._crop_confirmed)
                if self._crop_confirmed:
                    self._crop_overlay.set_confirmed_style(0)
        for pt in self._crop_corners:
            pt.setVisible(idx == 0 and self._crop_overlay is not None)

        self._grid_overlay.setVisible(idx in (1, 2) and self._calibration is not None)

        for pt in self._ref_points:
            pt.setVisible(idx == 1)

        # Hide everything first, then _refresh_data_visibility selectively shows
        for pts_list in self._series_points:
            for pt in pts_list:
                pt.setVisible(False)
        for pts_list in self._curve_points:
            for pt in pts_list:
                pt.setVisible(False)
        for path in self._curve_paths:
            path.setVisible(False)

        if idx == 2:
            self._refresh_data_visibility()

        self._precision_group.setVisible(
            idx == 2 or (idx == 1 and self._project.settings.magnifier_enabled)
        )
        self._data_precision_tools.setVisible(idx == 2)
        self._sync_active_point_for_mode()

    def _refresh_data_visibility(self) -> None:
        is_scatter = self._is_scatter_mode()

        # Scatter points: visible only in scatter sub-mode, active tab only
        si = self._active_series_index()
        for i, pts_list in enumerate(self._series_points):
            vis = is_scatter and (i == si)
            for pt in pts_list:
                pt.setVisible(vis)

        # Curve points and paths: visible only in curve sub-mode, active tab only
        ci = self._active_curve_index()
        for i, pts_list in enumerate(self._curve_points):
            vis = (not is_scatter) and (i == ci)
            for pt in pts_list:
                pt.setVisible(vis)
        for i, path in enumerate(self._curve_paths):
            path.setVisible((not is_scatter) and (i == ci))

    # ------------------------------------------------------------------
    # active-point precision tools
    # ------------------------------------------------------------------

    def _register_point(self, point: DraggablePoint) -> None:
        """Connect selection/drag lifecycle without disturbing position slots."""
        point.activated.connect(lambda p=point: self._activate_point(p))
        point.drag_finished.connect(lambda p=point: self._on_point_drag_finished(p))

    def _point_context(self, point: DraggablePoint) -> tuple[str, object, int] | None:
        if point in self._crop_corners:
            row = self._crop_corners.index(point)
            return (f"Crop corner {row + 1}", self._crop_corner_table, row)
        if point in self._ref_points:
            row = self._ref_points.index(point)
            return (f"Calibration anchor {row + 1}", self._ref_table, row)
        for si, points in enumerate(self._series_points):
            if point in points:
                row = points.index(point)
                table = self._series_tables[si] if si < len(self._series_tables) else None
                return (f"Scatter {si + 1}, point {row + 1}", table, row)
        for ci, points in enumerate(self._curve_points):
            if point in points:
                row = points.index(point)
                table = self._curve_tables[ci] if ci < len(self._curve_tables) else None
                return (f"Curve {ci + 1}, control point {row + 1}", table, row)
        return None

    def _is_data_point(self, point: DraggablePoint | None) -> bool:
        if point is None:
            return False
        return any(point in points for points in self._series_points) or any(
            point in points for points in self._curve_points
        )

    def _activate_point(self, point: DraggablePoint) -> None:
        context = self._point_context(point)
        if context is None:
            return
        if self._active_point is not point:
            if self._active_point is not None:
                try:
                    self._active_point.set_active_visual(False)
                except RuntimeError:
                    pass
            self._active_point = point
            point.set_active_visual(True)
        self._active_point_label = context[0]
        table, row = context[1], context[2]
        if table is not None and table.currentRow() != row:
            table.selectRow(row)
        self._refresh_active_loupe()

    def _clear_active_point(self) -> None:
        if self._active_point is not None:
            try:
                self._active_point.set_active_visual(False)
            except (RuntimeError, TypeError):
                pass
        self._active_point = None
        self._active_point_label = ""
        if hasattr(self, "_loupe"):
            self._loupe.clear()
            self._loupe.setText("Select or create a point")
            self._loupe_coords.setText(
                "Create a point or select one in a table.\n"
                "The red cross will show its exact stored centre."
            )

    def _refresh_active_loupe(self) -> None:
        point = self._active_point
        if point is None:
            return
        try:
            pos = point.pos()
        except RuntimeError:
            self._clear_active_point()
            return
        self._update_loupe(pos.x(), pos.y())

    def _refresh_loupe_if_active(self, point: DraggablePoint | None) -> None:
        if point is not None and point is self._active_point:
            self._refresh_active_loupe()

    def _sync_active_point_for_mode(self) -> None:
        mode = self._stack.currentIndex()
        candidates: list[DraggablePoint]
        table = None
        if mode == 1:
            candidates = self._ref_points
            table = self._ref_table
        elif mode == 2 and self._is_scatter_mode():
            si = self._active_series_index()
            candidates = self._series_points[si] if si < len(self._series_points) else []
            table = self._series_tables[si] if si < len(self._series_tables) else None
        elif mode == 2:
            ci = self._active_curve_index()
            candidates = self._curve_points[ci] if ci < len(self._curve_points) else []
            table = self._curve_tables[ci] if ci < len(self._curve_tables) else None
        else:
            return

        if self._active_point in candidates:
            self._activate_point(self._active_point)
            return
        row = table.selected_row() if table is not None else None
        if row is not None and 0 <= row < len(candidates):
            self._activate_point(candidates[row])
        elif candidates:
            self._activate_point(candidates[-1])
        else:
            self._clear_active_point()

    def _on_ref_row_selected(self, row: int) -> None:
        if 0 <= row < len(self._ref_points):
            self._activate_point(self._ref_points[row])

    def _on_data_row_selected(self, series: int, row: int) -> None:
        if (0 <= series < len(self._series_points)
                and 0 <= row < len(self._series_points[series])):
            self._activate_point(self._series_points[series][row])

    def _on_curve_row_selected(self, curve: int, row: int) -> None:
        if (0 <= curve < len(self._curve_points)
                and 0 <= row < len(self._curve_points[curve])):
            self._activate_point(self._curve_points[curve][row])

    def _pixel_center_coordinates(self, x: float, y: float) -> tuple[float, float]:
        """Return centres of the source pixels containing the scene position."""
        column = math.floor(x)
        row = math.floor(y)
        if self._project.image is not None:
            height, width = self._project.image.shape[:2]
            column = max(0, min(column, width - 1))
            row = max(0, min(row, height - 1))
        return column + 0.5, row + 0.5

    def _pixel_magnet_applies_to(self, point: DraggablePoint) -> bool:
        return (
            self._pixel_center_check.isChecked()
            and not self._restoring
            and not self._suspend_pixel_magnet
            and point is self._active_point
            and self._is_data_point(point)
        )

    def _redirect_position_to_pixel_center(
        self, point: DraggablePoint, x: float, y: float
    ) -> bool:
        """Enforce an armed magnet for any committed movement path.

        Returns true when ``setPos`` emitted a nested position update; the
        caller must then stop processing the obsolete unsnapped coordinates.
        """
        if not self._pixel_magnet_applies_to(point):
            return False
        target_x, target_y = self._pixel_center_coordinates(x, y)
        if math.isclose(x, target_x, abs_tol=1e-12) and math.isclose(
            y, target_y, abs_tol=1e-12
        ):
            return False
        before = QPointF(point.pos())
        point.setPos(target_x, target_y)
        after = point.pos()
        return not (
            math.isclose(before.x(), after.x(), abs_tol=1e-12)
            and math.isclose(before.y(), after.y(), abs_tol=1e-12)
        )

    def _set_point_pos_without_pixel_magnet(
        self, point: DraggablePoint, position: QPointF
    ) -> None:
        previous = self._suspend_pixel_magnet
        self._suspend_pixel_magnet = True
        try:
            point.setPos(position)
        finally:
            self._suspend_pixel_magnet = previous

    def _snap_point_to_pixel_center(
        self, point: DraggablePoint, *, report: bool = True
    ) -> bool:
        if not self._is_data_point(point):
            if report:
                self._status.setText("Pixel-centre magnet applies only to Scatter/Curve points.")
            return False
        old = QPointF(point.pos())
        target_x, target_y = self._pixel_center_coordinates(old.x(), old.y())
        point.setPos(target_x, target_y)
        new = point.pos()
        moved = not (
            math.isclose(old.x(), new.x(), abs_tol=1e-12)
            and math.isclose(old.y(), new.y(), abs_tol=1e-12)
        )
        self._refresh_loupe_if_active(point)
        if report:
            if moved:
                self._status.setText(
                    f"Active point snapped to pixel centre ({new.x():.3f}, {new.y():.3f})."
                )
            else:
                self._status.setText(
                    "Active point was already at a pixel centre, or its axis lock prevented movement."
                )
        return moved

    @Slot(bool)
    def _on_pixel_magnet_toggled(self, enabled: bool) -> None:
        if enabled and self._is_data_point(self._active_point):
            self._snap_point_to_pixel_center(self._active_point)

    def _snap_active_to_pixel_center(self) -> None:
        if self._active_point is None:
            self._status.setText("Select a Scatter/Curve point first.")
            return
        self._snap_point_to_pixel_center(self._active_point)

    def _on_point_drag_finished(self, point: DraggablePoint) -> None:
        self._activate_point(point)
        if self._pixel_center_check.isChecked() and self._is_data_point(point):
            self._snap_point_to_pixel_center(point, report=False)

    def _propose_active_marker_center(self) -> None:
        point = self._active_point
        if point is None or not self._is_data_point(point):
            self._status.setText("Select a Scatter/Curve point first.")
            return
        self._propose_marker_center(point, notify_failure=True)

    def _propose_marker_center(
        self,
        point: DraggablePoint,
        *,
        notify_failure: bool = False,
    ) -> bool:
        """Preview a detected centre and apply it only after confirmation."""
        if self._project.image is None:
            message = "Marker-centre search needs the source image loaded in this project."
            self._status.setText(message)
            if notify_failure:
                QMessageBox.information(self, "Marker centre", message)
            return False

        self._activate_point(point)
        original = QPointF(point.pos())
        try:
            result = estimate_marker_center(
                self._project.image,
                original.x(),
                original.y(),
                radius=float(self._marker_radius_spin.value()),
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            message = f"Marker-centre search failed: {exc}"
            self._status.setText(message)
            if notify_failure:
                QMessageBox.information(self, "Marker centre", message)
            return False

        try:
            configured_quality = float(
                self._project.settings.marker_center_sensitivity
            )
        except (TypeError, ValueError):
            configured_quality = 0.5
        if not math.isfinite(configured_quality):
            configured_quality = 0.5
        minimum_quality = max(0.48, min(1.0, configured_quality))
        if not result.applied or result.confidence < minimum_quality:
            reason = result.reason
            if result.applied:
                reason = (
                    f"quality {result.confidence:.2f} is below the configured "
                    f"minimum {minimum_quality:.2f}"
                )
            message = f"No reliable marker centre proposed: {reason}."
            self._status.setText(message)
            if notify_failure:
                QMessageBox.information(
                    self,
                    "Marker centre",
                    message + "\n\nThe active point was not changed.",
                )
            return False

        # Temporarily show the candidate in both the canvas and point-centred
        # loupe.  Rejecting the dialog restores the exact original coordinate.
        raw_candidate = QPointF(result.candidate_x, result.candidate_y)
        self._set_point_pos_without_pixel_magnet(point, raw_candidate)
        displayed = QPointF(point.pos())
        constraint_delta = math.hypot(
            displayed.x() - raw_candidate.x(), displayed.y() - raw_candidate.y()
        )
        if constraint_delta > 0.05:
            self._set_point_pos_without_pixel_magnet(point, original)
            message = (
                "Axis lock or crop bounds prevent applying the complete marker-centre "
                "candidate. Unlock/reposition the point and retry."
            )
            self._status.setText(message)
            if notify_failure:
                QMessageBox.information(self, "Marker centre", message)
            return False
        self._refresh_active_loupe()
        QApplication.processEvents()
        shift = math.hypot(displayed.x() - original.x(), displayed.y() - original.y())
        if shift <= 1e-12:
            self._status.setText("The detected marker centre already matches the point.")
            return False

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Confirm marker centre")
        box.setText(
            "A marker-centre candidate is now shown by the active crosshair"
            + (" and loupe." if self._project.settings.magnifier_enabled else ".")
        )
        box.setInformativeText(
            f"Original: ({original.x():.4f}, {original.y():.4f})\n"
            f"Candidate: ({displayed.x():.4f}, {displayed.y():.4f})\n"
            f"Shift: {shift:.3f} px; quality score: {100.0 * result.confidence:.0f}%\n\n"
            "Use it only if the crosshair visually matches the marker's geometric centre."
        )
        use_button = box.addButton("Use candidate", QMessageBox.ButtonRole.AcceptRole)
        keep_button = box.addButton("Keep original", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep_button)
        box.exec()

        if box.clickedButton() is use_button:
            self._status.setText(
                f"Confirmed marker centre at ({displayed.x():.4f}, {displayed.y():.4f})."
            )
            return True

        self._set_point_pos_without_pixel_magnet(point, original)
        self._refresh_active_loupe()
        self._status.setText("Marker-centre candidate rejected; original point restored.")
        return False

    # ------------------------------------------------------------------
    # canvas click dispatch
    # ------------------------------------------------------------------

    def _update_loupe(self, sx: float, sy: float) -> None:
        """Render the loupe at a stored point centre (never at the cursor)."""
        pixmap = self._canvas.loupe_pixmap(sx, sy, radius=8, size=180)
        if not pixmap.isNull():
            self._loupe.setPixmap(pixmap)
        else:
            self._loupe.clear()
            self._loupe.setText("Image preview unavailable")
        def raster_location(value: float, axis: str) -> str:
            boundary = round(value)
            if math.isclose(value, boundary, abs_tol=1e-9):
                return f"{axis}: boundary between pixels {boundary - 1} and {boundary}"
            return f"{axis}: pixel {math.floor(value)} (centre {math.floor(value) + 0.5:g})"

        self._loupe_coords.setText(
            f"{self._active_point_label or 'Active point'}\n"
            f"stored centre: x = {sx:.4f}, y = {sy:.4f}\n"
            f"{raster_location(sx, 'x')}\n{raster_location(sy, 'y')}\n\n"
            "Red cross = exact stored centre. Pixel centres are at n + 0.5; "
            "an even-width stroke centre can lie between them."
        )

    @Slot(float, float)
    def _on_canvas_click(self, sx: float, sy: float) -> None:
        mode = self._stack.currentIndex()
        if mode in (1, 2):
            if not self._crop_confirmed:
                self._status.setText("Confirm the plot boundaries on the Crop tab first.")
                return
            if not self._is_within_crop(sx, sy):
                return
        if mode == 1:
            self._add_ref_point(sx, sy)
        elif mode == 2:
            if self._is_scatter_mode():
                self._add_data_point(sx, sy)
            else:
                self._add_curve_point(sx, sy)

    def _is_within_crop(self, sx: float, sy: float) -> bool:
        r = self._project.crop_rect
        if r is None:
            return True
        x0, y0, w, h = r
        return x0 <= sx <= x0 + w and y0 <= sy <= y0 + h

    def _crop_bounds_rectf(self) -> Optional[QRectF]:
        r = self._project.crop_rect
        if r is None:
            return None
        x0, y0, w, h = r
        return QRectF(x0, y0, w, h)

    # ------------------------------------------------------------------
    # CROP — auto / confirm / overlay
    # ------------------------------------------------------------------

    def _crop_auto(self) -> None:
        if self._project.image is None:
            QMessageBox.warning(self, "Crop", "No image loaded.")
            return
        detected = detect_plot_area(self._project.image)
        if detected is None:
            h, w = self._project.image.shape[:2]
            rect = (0, 0, w, h)
        else:
            # OpenCV reports array-index centres (integer pixel 0 is its
            # centre); QPixmap scene coordinates place that centre at 0.5.
            rect = (detected[0] + 0.5, detected[1] + 0.5, detected[2], detected[3])
        self._show_crop_overlay(*rect)
        if self._calibration is not None:
            self._invalidate_calibration("Plot bounds changed — confirm them and rebuild calibration.")
        self._crop_status.setText(
            f"Candidate bounds: {rect[2]:.2f}×{rect[3]:.2f} "
            f"at ({rect[0]:.2f}, {rect[1]:.2f}). Verify all four sides at high zoom."
        )

    def _crop_confirm(self) -> None:
        previous_rect = self._project.crop_rect
        if self._crop_overlay:
            self._project.crop_rect = self._crop_overlay.get_rect()
        elif self._project.image is not None:
            h, w = self._project.image.shape[:2]
            self._show_crop_overlay(0.0, 0.0, float(w), float(h))
            self._project.crop_rect = self._crop_overlay.get_rect()
        else:
            return
        self._crop_confirmed = True
        if self._crop_overlay is None:
            return
        self._crop_overlay.set_confirmed_style(self._opacity_slider.value())
        self._update_all_point_bounds()
        r = self._project.crop_rect
        self._crop_status.setText(
            f"Confirmed centre-lines: {r[2]:.3f}×{r[3]:.3f} "
            f"at ({r[0]:.3f}, {r[1]:.3f})"
        )
        self._status.setText("Plot area set. Switch to Ref Points.")
        changed = (
            previous_rect is None
            or any(not math.isclose(a, b, abs_tol=1e-12)
                   for a, b in zip(previous_rect, self._project.crop_rect))
        )
        if changed and self._calibration is not None:
            self._invalidate_calibration("Plot frame changed — rebuild calibration.")

    def _show_crop_overlay(self, x: float, y: float, w: float, h: float) -> None:
        if self._crop_overlay:
            self._crop_overlay.set_rect(x, y, w, h)
            self._crop_overlay.set_editing_style()
            self._crop_overlay.set_interactive(False)
            self._crop_overlay.setVisible(True)
        else:
            self._crop_overlay = CropOverlay(x, y, w, h)
            self._crop_overlay.set_interactive(False)
            self._canvas.add_overlay(self._crop_overlay)
        self._crop_confirmed = False
        self._sync_crop_corners_from_rect(x, y, w, h)

    @Slot(int)
    def _on_opacity_changed(self, value: int) -> None:
        if self._crop_overlay and self._crop_confirmed:
            # Later stages retain the yellow boundary only; filling the crop
            # would alter the apparent source colours under the loupe.
            self._crop_overlay.set_fill_opacity(
                value if self._stack.currentIndex() == 0 else 0
            )

    # ------------------------------------------------------------------
    # CROP — corner point system
    # ------------------------------------------------------------------

    def _sync_crop_corners_from_rect(self, x: float, y: float, w: float, h: float) -> None:
        """Create or reposition the 4 corner DraggablePoints from rect (x,y,w,h)."""
        positions = [
            (x, y + h),      # 0: leftdown / BL
            (x + w, y + h),  # 1: rightdown / BR
            (x, y),          # 2: leftup / TL
            (x + w, y),      # 3: rightup / TR
        ]

        if not self._crop_corners:
            for i, (cx, cy) in enumerate(positions):
                color = point_color(i)
                pt = DraggablePoint(cx, cy, color=color)
                self._configure_point(pt)
                self._register_point(pt)
                pt.set_precision_style(True)
                pt.position_changed.connect(
                    lambda px, py, idx=i: self._on_crop_corner_dragged(idx, px, py)
                )
                self._canvas.add_overlay(pt)
                self._crop_corners.append(pt)
        else:
            self._propagating_corner = True
            for i, (cx, cy) in enumerate(positions):
                self._crop_corners[i].set_pos_silent(cx, cy)
            self._propagating_corner = False

        self._propagating_corner = True
        for i, (cx, cy) in enumerate(positions):
            self._crop_corner_table.update_corner(i, cx, cy)
        self._propagating_corner = False

    def _on_crop_corner_dragged(self, idx: int, nx: float, ny: float) -> None:
        """A corner was dragged on the canvas; propagate edge constraints."""
        if self._propagating_corner:
            return
        self._propagating_corner = True

        self._crop_corner_table.update_corner(idx, nx, ny)

        xp = _X_PAIR[idx]
        self._crop_corners[xp].set_pos_silent(nx, self._crop_corners[xp].pos().y())
        self._crop_corner_table.update_corner_x(xp, nx)

        yp = _Y_PAIR[idx]
        self._crop_corners[yp].set_pos_silent(self._crop_corners[yp].pos().x(), ny)
        self._crop_corner_table.update_corner_y(yp, ny)

        self._rebuild_rect_from_corners()
        self._propagating_corner = False
        if 0 <= idx < len(self._crop_corners):
            self._refresh_loupe_if_active(self._crop_corners[idx])

    @Slot(int, float, float)
    def _crop_table_changed(self, row: int, x: float, y: float) -> None:
        """A corner coordinate was edited in the table."""
        if self._propagating_corner or row < 0 or row >= 4:
            return
        if not self._crop_corners:
            return
        self._propagating_corner = True

        self._crop_corners[row].set_pos_silent(x, y)

        xp = _X_PAIR[row]
        self._crop_corners[xp].set_pos_silent(x, self._crop_corners[xp].pos().y())
        self._crop_corner_table.update_corner_x(xp, x)

        yp = _Y_PAIR[row]
        self._crop_corners[yp].set_pos_silent(self._crop_corners[yp].pos().x(), y)
        self._crop_corner_table.update_corner_y(yp, y)

        self._rebuild_rect_from_corners()
        self._propagating_corner = False
        self._refresh_loupe_if_active(self._crop_corners[row])

    @Slot(int, float, float)
    def _crop_key_move(self, row: int, dx: float, dy: float) -> None:
        """Arrow key pressed while a corner row is selected."""
        if row < 0 or row >= 4 or not self._crop_corners:
            return
        pt = self._crop_corners[row]
        old = pt.pos()
        new_x, new_y = old.x() + dx, old.y() + dy
        self._on_crop_corner_dragged(row, new_x, new_y)
        pt.set_pos_silent(new_x, new_y)

    def _rebuild_rect_from_corners(self) -> None:
        """Recompute the CropOverlay rect from the 4 corner positions."""
        if len(self._crop_corners) < 4 or self._crop_overlay is None:
            return
        positions = [pt.pos() for pt in self._crop_corners]
        left = positions[0].x()
        right = positions[1].x()
        top = positions[2].y()
        bottom = positions[0].y()
        x = min(left, right)
        y = min(top, bottom)
        w = abs(right - left)
        h = abs(bottom - top)
        if w < 1:
            w = 1
        if h < 1:
            h = 1
        self._crop_overlay.set_rect(x, y, w, h)
        self._crop_confirmed = False
        self._crop_status.setText("Bounds modified — press Confirm area before calibration.")
        if self._calibration is not None:
            self._invalidate_calibration("Plot bounds changed — confirm them and rebuild calibration.")

    # ------------------------------------------------------------------
    # REFERENCE POINTS
    # ------------------------------------------------------------------

    def _add_ref_point(self, sx: float, sy: float) -> None:
        axis = ("X", "Y", "Both")[self._ref_axis_combo.currentIndex()]
        snap_messages: list[str] = []
        if self._centerline_snap_check.isChecked() and self._project.image is not None:
            if axis in ("X", "Both"):
                snapped = snap_to_stroke_center(
                    self._project.image, sx, sy, "vertical", search_radius=10
                )
                if snapped.applied:
                    snap_messages.append(f"X {sx:.3f}→{snapped.coordinate:.3f}")
                    sx = snapped.coordinate
            if axis in ("Y", "Both"):
                snapped = snap_to_stroke_center(
                    self._project.image, sx, sy, "horizontal", search_radius=10
                )
                if snapped.applied:
                    snap_messages.append(f"Y {sy:.3f}→{snapped.coordinate:.3f}")
                    sy = snapped.coordinate

        self._create_ref_point(sx, sy, axis=axis)
        self._invalidate_calibration("Anchor added — enter its known value, then rebuild.")
        if snap_messages:
            self._status.setText("Centre-line snap: " + ", ".join(snap_messages))

    def _create_ref_point(
        self,
        sx: float,
        sy: float,
        *,
        axis: str,
        x_ref: float | None = None,
        y_ref: float | None = None,
    ) -> None:
        idx = len(self._ref_points)
        color = point_color(idx)
        pt = DraggablePoint(sx, sy, color=color)
        self._configure_point(pt)
        self._register_point(pt)
        pt.set_precision_style(True)
        pt.set_bounds(self._crop_bounds_rectf())
        self._canvas.add_overlay(pt)
        self._ref_points.append(pt)
        self._ref_table.add_row(
            sx, sy, x_ref, y_ref, color=color, axis=axis
        )

        pt.position_changed.connect(
            lambda x, y, r=idx: self._on_ref_dragged(r, x, y)
        )
        self._ref_table.selectRow(idx)
        self._activate_point(pt)

    def _on_ref_dragged(self, row: int, x: float, y: float) -> None:
        self._ref_table.update_wind(row, x, y)
        if 0 <= row < len(self._ref_points):
            self._refresh_loupe_if_active(self._ref_points[row])
        self._invalidate_calibration("Anchor moved — rebuild calibration.")

    @Slot(int, float, float)
    def _ref_table_wind_changed(self, row: int, x: float, y: float) -> None:
        if 0 <= row < len(self._ref_points):
            point = self._ref_points[row]
            point.set_pos_silent(x, y)
            actual = point.pos()
            self._ref_table.update_wind(row, actual.x(), actual.y())
            self._refresh_loupe_if_active(point)
            self._invalidate_calibration("Anchor coordinates changed — rebuild calibration.")

    @Slot()
    def _on_ref_value_changed(self) -> None:
        self._invalidate_calibration("Anchor value changed — rebuild calibration.")

    def _on_calibration_input_changed(self, *_args) -> None:
        if self._restoring:
            return
        self._invalidate_calibration("Axis scale changed — rebuild calibration.")

    @Slot(int, float, float)
    def _ref_key_move(self, row: int, dx: float, dy: float) -> None:
        if 0 <= row < len(self._ref_points):
            self._ref_points[row].moveBy(dx, dy)

    def _ref_delete_selected(self) -> None:
        row = self._ref_table.remove_selected_row()
        if row is not None and 0 <= row < len(self._ref_points):
            pt = self._ref_points.pop(row)
            self._safe_remove_point(pt)
            self._reconnect_ref_signals()
            self._invalidate_calibration("Anchor deleted — rebuild calibration.")
            self._sync_active_point_for_mode()

    def _ref_clear_all(self) -> None:
        self._clear_reference_items()
        self._sync_active_point_for_mode()
        self._invalidate_calibration(
            "Need 2 X anchors and 2 Y anchors (3+ per axis enables an error estimate)."
        )

    def _clear_reference_items(self) -> None:
        for pt in self._ref_points:
            self._safe_remove_point(pt)
        self._ref_points.clear()
        self._ref_table.setRowCount(0)

    def _invalidate_calibration(self, reason: str) -> None:
        """Prevent stale calibration from being used after any input change."""
        self._calibration = None
        self._project.calibration = CalibrationResult()
        self._grid_overlay.clear_grid()
        self._grid_overlay.setVisible(False)
        for table in [*self._series_tables, *self._curve_tables]:
            table.clear_fig_values()
        for ci, path in enumerate(self._curve_paths):
            path.update_from_polyline([])
            if ci < len(self._curve_points) and len(self._curve_points[ci]) >= 2:
                self._curve_errors[ci] = "calibration is stale"
        self._update_curve_status()
        self._ref_status.setText(reason)
        self._ref_status.setStyleSheet("color: #ffcc66;")

    def _calibrate_from_frame(self) -> None:
        rect = self._project.crop_rect
        if rect is None:
            QMessageBox.warning(
                self, "Calibration", "Confirm the plot frame centre-lines on the Crop tab first."
            )
            return
        try:
            values = {key: float(edit.text()) for key, edit in self._frame_value_edits.items()}
            if not all(math.isfinite(value) for value in values.values()):
                raise ValueError("all limits must be finite")
        except ValueError as exc:
            QMessageBox.warning(
                self, "Calibration", f"Enter four valid axis limits ({exc})."
            )
            return

        x0, y0, width, height = rect
        self._clear_reference_items()
        self._create_ref_point(
            x0, y0 + height, axis="Both",
            x_ref=values["x_left"], y_ref=values["y_bottom"],
        )
        self._create_ref_point(
            x0 + width, y0, axis="Both",
            x_ref=values["x_right"], y_ref=values["y_top"],
        )
        self._rebuild_calibration()

    def _reconnect_ref_signals(self) -> None:
        for i, pt in enumerate(self._ref_points):
            try:
                pt.position_changed.disconnect()
            except RuntimeError:
                pass
            pt.position_changed.connect(
                lambda x, y, r=i: self._on_ref_dragged(r, x, y)
            )

    def _set_calibration_diagnostics_status(self) -> None:
        if self._calibration is None:
            return
        x_axis = self._calibration.x_axis
        y_axis = self._calibration.y_axis
        def resolution(axis, label: str) -> str:
            if axis.scale == ScaleType.LOG:
                exponent = abs(axis._slope)
                factor = 10.0 ** exponent if exponent <= 308.0 else math.inf
                return f"{label} ×{factor:.6g}/px"
            return f"{label} {abs(axis._slope):.6g} units/px"
        resolution_note = f"{resolution(x_axis, 'X')}; {resolution(y_axis, 'Y')}"
        if x_axis.n_points == 2 and y_axis.n_points == 2:
            target = max(3, self._project.settings.n_calibration_points)
            note = (
                "2 anchors/axis: exact fit; error cannot be estimated. "
                f"Use {target}+ per axis to measure placement consistency. "
                f"Resolution: {resolution_note}."
            )
        else:
            rows = self._ref_table.get_ref_data()
            x_rows = [index + 1 for index, row in enumerate(rows) if row[2] is not None]
            y_rows = [index + 1 for index, row in enumerate(rows) if row[3] is not None]
            worst_x = x_rows[max(
                range(len(x_axis.residuals_pixels)),
                key=lambda i: abs(x_axis.residuals_pixels[i]),
            )]
            worst_y = y_rows[max(
                range(len(y_axis.residuals_pixels)),
                key=lambda i: abs(y_axis.residuals_pixels[i]),
            )]
            note = (
                f"X: {x_axis.n_points} anchors, RMS {x_axis.rmse_pixels:.3f} px, "
                f"max {x_axis.max_error_pixels:.3f} px (row {worst_x}); "
                f"Y: {y_axis.n_points} anchors, RMS {y_axis.rmse_pixels:.3f} px, "
                f"max {y_axis.max_error_pixels:.3f} px (row {worst_y}). "
                f"Resolution: {resolution_note}."
            )
        worst = max(x_axis.max_error_pixels or 0.0, y_axis.max_error_pixels or 0.0)
        color = "#66bb6a" if worst <= 0.75 else "#ffcc66"
        verdict = "Calibration OK" if worst <= 0.75 else "Calibration warning"
        self._ref_status.setText(f"{verdict} — {note}")
        self._ref_status.setStyleSheet(f"color: {color};")

    def _rebuild_calibration(self) -> None:
        try:
            data = self._ref_table.get_ref_data()
        except ValueError as exc:
            self._invalidate_calibration(f"Calibration input error — {exc}.")
            self._ref_status.setStyleSheet("color: #ff6666;")
            return
        x_pairs = [(xw, xr) for xw, _, xr, _, _ in data if xr is not None]
        y_pairs = [(yw, yr) for _, yw, _, yr, _ in data if yr is not None]

        unique_x = len({xr for _, xr in x_pairs})
        unique_y = len({yr for _, yr in y_pairs})

        if len(x_pairs) >= 2 and len(y_pairs) >= 2 and unique_x >= 2 and unique_y >= 2:
            scale_x = ScaleType.LOG if self._x_scale_combo.currentIndex() == 1 else ScaleType.LINEAR
            scale_y = ScaleType.LOG if self._y_scale_combo.currentIndex() == 1 else ScaleType.LINEAR
            try:
                self._calibration = build_calibration(x_pairs, y_pairs, scale_x, scale_y)
                self._project.calibration = self._calibration
                self._project.settings.x_scale = scale_x
                self._project.settings.y_scale = scale_y
                self._set_calibration_diagnostics_status()
                self._update_grid()
                self._grid_overlay.setVisible(True)
                for table in self._series_tables:
                    table.update_all_fig(self._calibration)
                for table in self._curve_tables:
                    table.update_all_fig(self._calibration)
                for ci in range(len(self._curve_paths)):
                    self._rebuild_curve_path(ci)
                self._update_curve_status()
                return
            except Exception as e:
                self._ref_status.setText(f"Calibration error: {e}")
                self._ref_status.setStyleSheet("color: #ff6666;")
                self._calibration = None
                self._project.calibration = CalibrationResult()
        else:
            need_x = max(0, 2 - unique_x)
            need_y = max(0, 2 - unique_y)
            parts = []
            if need_x:
                parts.append(f"{need_x} more distinct X ref(s)")
            if need_y:
                parts.append(f"{need_y} more distinct Y ref(s)")
            self._ref_status.setText(
                "Need " + " and ".join(parts)
                if parts else "Enter ref values and click Build."
            )
            self._ref_status.setStyleSheet("color: #cccccc;")
            self._calibration = None
            self._project.calibration = CalibrationResult()

        self._grid_overlay.clear_grid()
        self._grid_overlay.setVisible(False)

    def _update_grid(self) -> None:
        if self._calibration is None or self._project.crop_rect is None:
            self._grid_overlay.clear_grid()
            return
        data = self._ref_table.get_ref_data()
        x_refs = sorted({xr for _, _, xr, _, _ in data if xr is not None})
        y_refs = sorted({yr for _, _, _, yr, _ in data if yr is not None})
        self._grid_overlay.update_grid(self._calibration, self._project.crop_rect, x_refs, y_refs)

    # ------------------------------------------------------------------
    # SCATTER DATA POINTS
    # ------------------------------------------------------------------

    def _restore_data_point(self, sx: float, sy: float) -> None:
        if self._calibration is not None:
            self._add_data_point(sx, sy)
            return
        si = self._active_series_index()
        if si >= len(self._series_tables):
            return
        color = point_color(len(self._series_points[si]))
        point = DraggablePoint(sx, sy, color=color)
        self._configure_point(point)
        self._register_point(point)
        point.set_bounds(self._crop_bounds_rectf())
        point.set_point_shape(self._current_shape)
        point.set_point_size(self._current_size)
        point.set_active_fill_opacity(self._scatter_active_fill_opacity)
        self._canvas.add_overlay(point)
        self._series_points[si].append(point)
        table = self._series_tables[si]
        row = table.add_row(sx, sy, 0.0, 0.0, color=color)
        table.clear_fig_values()
        point.position_changed.connect(
            lambda x, y, s=si, r=row: self._on_data_dragged(s, r, x, y)
        )
        table.selectRow(row)
        self._activate_point(point)
        self._update_data_status()

    def _add_data_point(self, sx: float, sy: float) -> None:
        if self._calibration is None:
            QMessageBox.warning(self, "Data", "Build calibration first (Ref Points tab).")
            return

        si = self._active_series_index()
        if si >= len(self._series_tables):
            return

        if self._pixel_center_check.isChecked() and not self._restoring:
            sx, sy = self._pixel_center_coordinates(sx, sy)

        constraint = DragConstraint.FREE
        x_fig_override: Optional[float] = None
        y_fig_override: Optional[float] = None

        if self._snap_xy.isChecked():
            sx, x_fig_override = self._snap_to_x_grid(sx)
            sy, y_fig_override = self._snap_to_y_grid(sy)
            if x_fig_override is not None and y_fig_override is not None:
                constraint = DragConstraint.FIXED
            elif x_fig_override is not None:
                constraint = DragConstraint.VERTICAL_ONLY
            elif y_fig_override is not None:
                constraint = DragConstraint.HORIZONTAL_ONLY
        elif self._snap_x.isChecked():
            sx, x_fig_override = self._snap_to_x_grid(sx)
            if x_fig_override is not None:
                constraint = DragConstraint.VERTICAL_ONLY
        elif self._snap_y.isChecked():
            sy, y_fig_override = self._snap_to_y_grid(sy)
            if y_fig_override is not None:
                constraint = DragConstraint.HORIZONTAL_ONLY

        try:
            xf = (x_fig_override if x_fig_override is not None
                  else self._calibration.x_axis.pixel_to_data(sx))
            yf = (y_fig_override if y_fig_override is not None
                  else self._calibration.y_axis.pixel_to_data(sy))
        except Exception as exc:
            QMessageBox.warning(self, "Data", f"Cannot convert this point: {exc}")
            return

        idx = len(self._series_points[si])
        color = point_color(idx)
        pt = DraggablePoint(sx, sy, color=color)
        self._configure_point(pt)
        self._register_point(pt)
        pt.set_constraint(constraint)
        pt.set_bounds(self._crop_bounds_rectf())
        pt.set_point_shape(self._current_shape)
        pt.set_point_size(self._current_size)
        pt.set_active_fill_opacity(self._scatter_active_fill_opacity)
        self._canvas.add_overlay(pt)
        self._series_points[si].append(pt)

        table = self._series_tables[si]
        row = table.add_row(sx, sy, xf, yf, color=color)
        pt.position_changed.connect(
            lambda x, y, s=si, r=row: self._on_data_dragged(s, r, x, y)
        )
        table.selectRow(row)
        self._activate_point(pt)
        self._update_data_status()
        if self._marker_auto_check.isChecked() and not self._restoring:
            self._propose_marker_center(pt)

    def _on_data_dragged(self, si: int, row: int, x: float, y: float) -> None:
        point = None
        if 0 <= si < len(self._series_points) and 0 <= row < len(self._series_points[si]):
            point = self._series_points[si][row]
            if self._redirect_position_to_pixel_center(point, x, y):
                return
        if si < len(self._series_tables):
            self._series_tables[si].update_wind(row, x, y)
            if self._calibration:
                try:
                    xf = self._calibration.x_axis.pixel_to_data(x)
                    yf = self._calibration.y_axis.pixel_to_data(y)
                    self._series_tables[si].update_fig(row, xf, yf)
                except Exception:
                    pass
        self._refresh_loupe_if_active(point)

    @Slot(int, float, float)
    def _data_table_wind_changed(self, si: int, row: int, x: float, y: float) -> None:
        if 0 <= si < len(self._series_points) and 0 <= row < len(self._series_points[si]):
            point = self._series_points[si][row]
            point.set_pos_silent(x, y)
            if self._pixel_magnet_applies_to(point):
                self._snap_point_to_pixel_center(point, report=False)
            actual = point.pos()
            x, y = actual.x(), actual.y()
            if si < len(self._series_tables):
                self._series_tables[si].update_wind(row, x, y)
            self._refresh_loupe_if_active(point)
        if self._calibration:
            try:
                xf = self._calibration.x_axis.pixel_to_data(x)
                yf = self._calibration.y_axis.pixel_to_data(y)
                if si < len(self._series_tables):
                    self._series_tables[si].update_fig(row, xf, yf)
            except Exception:
                pass

    @Slot(int, float, float)
    def _data_key_move(self, si: int, row: int, dx: float, dy: float) -> None:
        if 0 <= si < len(self._series_points) and 0 <= row < len(self._series_points[si]):
            self._series_points[si][row].moveBy(dx, dy)

    def _data_delete_selected(self) -> None:
        si = self._active_series_index()
        if si >= len(self._series_tables):
            return
        table = self._series_tables[si]
        row = table.remove_selected_row()
        if row is not None and 0 <= row < len(self._series_points[si]):
            pt = self._series_points[si].pop(row)
            self._safe_remove_point(pt)
            self._reconnect_data_signals(si)
            self._update_data_status()
            self._sync_active_point_for_mode()

    def _data_clear_series(self, si: int) -> None:
        if si >= len(self._series_points):
            return
        for pt in self._series_points[si]:
            self._safe_remove_point(pt)
        self._series_points[si].clear()
        if si < len(self._series_tables):
            self._series_tables[si].setRowCount(0)
        self._update_data_status()
        self._sync_active_point_for_mode()

    def _reconnect_data_signals(self, si: int) -> None:
        if si >= len(self._series_points):
            return
        for i, pt in enumerate(self._series_points[si]):
            try:
                pt.position_changed.disconnect()
            except RuntimeError:
                pass
            pt.position_changed.connect(
                lambda x, y, s=si, r=i: self._on_data_dragged(s, r, x, y)
            )

    def _update_data_status(self) -> None:
        total = sum(len(pts) for pts in self._series_points)
        self._data_status.setText(f"{total} point(s) total across {len(self._series_points)} series")

    # ------------------------------------------------------------------
    # CURVE DATA POINTS
    # ------------------------------------------------------------------

    def _restore_curve_point(self, sx: float, sy: float) -> None:
        if self._calibration is not None:
            self._add_curve_point(sx, sy)
            return
        ci = self._active_curve_index()
        if ci >= len(self._curve_tables):
            return
        color = self._curve_colors[ci]
        point = DraggablePoint(sx, sy, color=color)
        self._configure_point(point)
        self._register_point(point)
        point.set_bounds(self._crop_bounds_rectf())
        point.set_point_size(self._curve_point_size)
        point.set_point_shape(self._curve_point_shape)
        point.set_active_fill_opacity(self._curve_active_fill_opacity)
        self._canvas.add_overlay(point)
        self._curve_points[ci].append(point)
        table = self._curve_tables[ci]
        row = table.add_row(sx, sy, 0.0, 0.0, color=color)
        table.clear_fig_values()
        point.position_changed.connect(
            lambda x, y, s=ci, r=row: self._on_curve_dragged(s, r, x, y)
        )
        table.selectRow(row)
        self._activate_point(point)
        self._rebuild_curve_path(ci)
        self._update_curve_status()

    def _add_curve_point(self, sx: float, sy: float) -> None:
        if self._calibration is None:
            QMessageBox.warning(self, "Data", "Build calibration first (Ref Points tab).")
            return

        ci = self._active_curve_index()
        if ci >= len(self._curve_tables):
            return

        if self._pixel_center_check.isChecked() and not self._restoring:
            sx, sy = self._pixel_center_coordinates(sx, sy)

        try:
            xf, yf = self._calibration.pixel_to_data(sx, sy)
        except Exception as exc:
            QMessageBox.warning(self, "Curve", f"Cannot convert this control point: {exc}")
            return

        idx = len(self._curve_points[ci])
        color = self._curve_colors[ci] if ci < len(self._curve_colors) else QColor(255, 80, 80)
        pt = DraggablePoint(sx, sy, color=color)
        self._configure_point(pt)
        self._register_point(pt)
        pt.set_bounds(self._crop_bounds_rectf())
        pt.set_point_size(self._curve_point_size)
        pt.set_point_shape(self._curve_point_shape)
        pt.set_active_fill_opacity(self._curve_active_fill_opacity)
        self._canvas.add_overlay(pt)
        self._curve_points[ci].append(pt)

        table = self._curve_tables[ci]
        row = table.add_row(sx, sy, xf, yf, color=color)
        pt.position_changed.connect(
            lambda x, y, s=ci, r=row: self._on_curve_dragged(s, r, x, y)
        )
        table.selectRow(row)
        self._activate_point(pt)
        self._rebuild_curve_path(ci)
        self._update_curve_status()
        if self._marker_auto_check.isChecked() and not self._restoring:
            self._propose_marker_center(pt)

    def _on_curve_dragged(self, ci: int, row: int, x: float, y: float) -> None:
        point = None
        if 0 <= ci < len(self._curve_points) and 0 <= row < len(self._curve_points[ci]):
            point = self._curve_points[ci][row]
            if self._redirect_position_to_pixel_center(point, x, y):
                return
        if ci < len(self._curve_tables):
            self._curve_tables[ci].update_wind(row, x, y)
            if self._calibration:
                try:
                    xf = self._calibration.x_axis.pixel_to_data(x)
                    yf = self._calibration.y_axis.pixel_to_data(y)
                    self._curve_tables[ci].update_fig(row, xf, yf)
                except Exception:
                    pass
        self._refresh_loupe_if_active(point)
        self._rebuild_curve_path(ci)
        self._update_curve_status()

    @Slot(int, float, float)
    def _curve_table_wind_changed(self, ci: int, row: int, x: float, y: float) -> None:
        if 0 <= ci < len(self._curve_points) and 0 <= row < len(self._curve_points[ci]):
            point = self._curve_points[ci][row]
            point.set_pos_silent(x, y)
            if self._pixel_magnet_applies_to(point):
                self._snap_point_to_pixel_center(point, report=False)
            actual = point.pos()
            x, y = actual.x(), actual.y()
            if ci < len(self._curve_tables):
                self._curve_tables[ci].update_wind(row, x, y)
            self._refresh_loupe_if_active(point)
        if self._calibration:
            try:
                xf = self._calibration.x_axis.pixel_to_data(x)
                yf = self._calibration.y_axis.pixel_to_data(y)
                if ci < len(self._curve_tables):
                    self._curve_tables[ci].update_fig(row, xf, yf)
            except Exception:
                pass
        self._rebuild_curve_path(ci)
        self._update_curve_status()

    @Slot(int, float, float)
    def _curve_key_move(self, ci: int, row: int, dx: float, dy: float) -> None:
        if 0 <= ci < len(self._curve_points) and 0 <= row < len(self._curve_points[ci]):
            self._curve_points[ci][row].moveBy(dx, dy)
            self._rebuild_curve_path(ci)
            self._update_curve_status()

    def _curve_delete_selected(self) -> None:
        ci = self._active_curve_index()
        if ci >= len(self._curve_tables):
            return
        table = self._curve_tables[ci]
        row = table.remove_selected_row()
        if row is not None and 0 <= row < len(self._curve_points[ci]):
            pt = self._curve_points[ci].pop(row)
            self._safe_remove_point(pt)
            self._reconnect_curve_signals(ci)
            self._rebuild_curve_path(ci)
            self._update_curve_status()
            self._sync_active_point_for_mode()

    def _curve_clear_series(self, ci: int) -> None:
        if ci >= len(self._curve_points):
            return
        for pt in self._curve_points[ci]:
            self._safe_remove_point(pt)
        self._curve_points[ci].clear()
        self._curve_errors.pop(ci, None)
        if ci < len(self._curve_tables):
            self._curve_tables[ci].setRowCount(0)
        self._rebuild_curve_path(ci)
        self._update_curve_status()
        self._sync_active_point_for_mode()

    def _reconnect_curve_signals(self, ci: int) -> None:
        if ci >= len(self._curve_points):
            return
        for i, pt in enumerate(self._curve_points[ci]):
            try:
                pt.position_changed.disconnect()
            except RuntimeError:
                pass
            pt.position_changed.connect(
                lambda x, y, s=ci, r=i: self._on_curve_dragged(s, r, x, y)
            )

    def _rebuild_curve_path(self, ci: int) -> None:
        if ci >= len(self._curve_paths):
            return
        pts = self._curve_points[ci] if ci < len(self._curve_points) else []
        if len(pts) < 2:
            self._curve_errors.pop(ci, None)
            self._curve_paths[ci].update_from_polyline([pt.pos() for pt in pts])
            return
        if self._calibration is None:
            self._curve_errors[ci] = "calibration is stale"
            self._curve_paths[ci].update_from_polyline([])
            return

        try:
            controls = [self._calibration.pixel_to_data(pt.pos().x(), pt.pos().y()) for pt in pts]
            xs = [point[0] for point in controls]
            ys = [point[1] for point in controls]
            engine = CurveInterpolator(
                xs, ys,
                self._calibration.x_axis.scale,
                self._calibration.y_axis.scale,
            )
            preview_x, preview_y = engine.sample_for_preview(512)
            qpoints = [
                QPointF(*self._calibration.data_to_pixel(float(x), float(y)))
                for x, y in zip(preview_x, preview_y)
            ]
            self._curve_paths[ci].update_from_polyline(qpoints)
            self._curve_errors.pop(ci, None)
        except (CurveInterpolationError, ValueError, RuntimeError) as exc:
            self._curve_errors[ci] = str(exc)
            self._curve_paths[ci].update_from_polyline([])

    def _update_curve_status(self) -> None:
        total = sum(len(pts) for pts in self._curve_points)
        text = f"{total} control point(s) across {len(self._curve_points)} curve(s)"
        ci = self._active_curve_index()
        if ci in self._curve_errors:
            text += f"\nCurve {ci + 1} is not exportable: {self._curve_errors[ci]}"
            self._curve_status.setStyleSheet("color: #ff6666;")
        else:
            self._curve_status.setStyleSheet("")
        self._curve_status.setText(text)

    # ------------------------------------------------------------------
    # grid snap helpers
    # ------------------------------------------------------------------

    def _snap_to_x_grid(self, click_x: float) -> tuple[float, float | None]:
        if self._calibration is None:
            return click_x, None
        data = self._ref_table.get_ref_data()
        x_refs = sorted({xr for _, _, xr, _, _ in data if xr is not None})
        if not x_refs:
            return click_x, None
        best_ref = min(x_refs, key=lambda xr: abs(self._calibration.x_axis.data_to_pixel(xr) - click_x))
        pixel = self._calibration.x_axis.data_to_pixel(best_ref)
        if abs(pixel - click_x) > self._snap_threshold_spin.value():
            return click_x, None
        return pixel, best_ref

    def _snap_to_y_grid(self, click_y: float) -> tuple[float, float | None]:
        if self._calibration is None:
            return click_y, None
        data = self._ref_table.get_ref_data()
        y_refs = sorted({yr for _, _, _, yr, _ in data if yr is not None})
        if not y_refs:
            return click_y, None
        best_ref = min(y_refs, key=lambda yr: abs(self._calibration.y_axis.data_to_pixel(yr) - click_y))
        pixel = self._calibration.y_axis.data_to_pixel(best_ref)
        if abs(pixel - click_y) > self._snap_threshold_spin.value():
            return click_y, None
        return pixel, best_ref

    # ------------------------------------------------------------------
    # export
    # ------------------------------------------------------------------

    def _collect_series(self, *, sample_curves: bool) -> list[SeriesData]:
        if self._calibration is None:
            raise ValueError("Calibration is missing or stale")

        result: list[SeriesData] = []
        series_idx = 1
        total_points = 0

        # Read authoritative floating-point positions from the graphics model,
        # never from rounded table text.
        for points in self._series_points:
            sd = SeriesData(
                index=series_idx, kind=SeriesKind.DISCRETE,
                mode=ExtractionMode.MANUAL,
            )
            for point in points:
                x, y = self._calibration.pixel_to_data(point.pos().x(), point.pos().y())
                sd.points.append(ExtractedPoint(x=x, y=y))
            if sd.points:
                total_points += len(sd.points)
                if sample_curves and total_points > _MAX_TOTAL_EXPORT_POINTS:
                    raise CurveInterpolationError(
                        f"export exceeds the total limit of {_MAX_TOTAL_EXPORT_POINTS} points"
                    )
                sd.sort_by_x()
                result.append(sd)
                series_idx += 1

        for ci, points in enumerate(self._curve_points):
            if not points:
                continue
            controls = [
                self._calibration.pixel_to_data(point.pos().x(), point.pos().y())
                for point in points
            ]
            sd = SeriesData(
                index=series_idx, kind=SeriesKind.CONTINUOUS,
                mode=ExtractionMode.MANUAL,
            )
            if sample_curves and len(controls) >= 2:
                engine = CurveInterpolator(
                    [p[0] for p in controls], [p[1] for p in controls],
                    self._calibration.x_axis.scale,
                    self._calibration.y_axis.scale,
                )
                remaining = _MAX_TOTAL_EXPORT_POINTS - total_points
                if remaining < 2:
                    raise CurveInterpolationError(
                        f"export exceeds the total limit of {_MAX_TOTAL_EXPORT_POINTS} points"
                    )
                xs, ys = engine.sample_for_export(self._curve_dx, max_samples=remaining)
                sd.points.extend(
                    ExtractedPoint(x=float(x), y=float(y)) for x, y in zip(xs, ys)
                )
            else:
                sd.points.extend(ExtractedPoint(x=x, y=y) for x, y in controls)
            total_points += len(sd.points)
            result.append(sd)
            series_idx += 1
        return result

    def sync_project_state(self) -> None:
        """Copy the live GUI state to the serialisable project model."""
        if self._crop_overlay is not None and not self._crop_confirmed:
            raise ValueError("Confirm the modified plot boundaries before saving the project")
        self._project.calibration_anchors = list(self._ref_table.get_ref_data())
        self._project.scatter_points_px = [
            [(point.pos().x(), point.pos().y()) for point in points]
            for points in self._series_points
        ]
        self._project.curve_points_px = [
            [(point.pos().x(), point.pos().y()) for point in points]
            for points in self._curve_points
        ]
        self._project.scatter_point_styles = [
            [(point.point_shape().name, point.point_size()) for point in points]
            for points in self._series_points
        ]
        self._project.curve_point_styles = [
            [(point.point_shape().name, point.point_size()) for point in points]
            for points in self._curve_points
        ]
        self._project.curve_visual_styles = [
            (
                path.color().name(QColor.NameFormat.HexArgb),
                path.thickness(),
                path.line_style().name,
            )
            for path in self._curve_paths
        ]
        self._project.scatter_default_point_style = (
            self._current_shape.name,
            self._current_size,
        )
        self._project.curve_default_point_style = (
            self._curve_point_shape.name,
            self._curve_point_size,
        )
        self._project.scatter_active_fill_opacity = (
            self._scatter_active_fill_opacity
        )
        self._project.curve_active_fill_opacity = self._curve_active_fill_opacity
        self._project.curve_default_thickness = self._curve_thickness
        has_points = any(self._series_points) or any(self._curve_points)
        if has_points and self._calibration is not None:
            self._project.series = self._collect_series(sample_curves=False)
        else:
            self._project.series.clear()
        self._project.settings.curve_step_dx = self._curve_dx
        self._project.combined_mode = {
            0: CombinedMode.UNION_X,
            1: CombinedMode.UNIFORM_GRID,
            2: CombinedMode.INTERPOLATION,
        }.get(self._combined_mode.currentIndex(), CombinedMode.UNION_X)

    def _do_export(self) -> None:
        scatter_total = sum(len(pts) for pts in self._series_points)
        curve_total = sum(len(pts) for pts in self._curve_points)
        if scatter_total == 0 and curve_total == 0:
            QMessageBox.warning(self, "Export", "No data points to export.")
            return
        if self._calibration is None:
            QMessageBox.warning(self, "Export", "No calibration built.")
            return

        try:
            self._project.series = self._collect_series(sample_curves=True)
        except (CurveInterpolationError, ValueError, RuntimeError) as exc:
            QMessageBox.critical(
                self, "Export", f"Cannot export curve data:\n{exc}\n\n"
                "Curve control X values must be distinct and the sampling step must be safe."
            )
            return

        if not self._project.series:
            QMessageBox.warning(self, "Export", "No valid points found.")
            return

        mode_map = {0: CombinedMode.UNION_X, 1: CombinedMode.UNIFORM_GRID, 2: CombinedMode.INTERPOLATION}
        self._project.combined_mode = mode_map.get(self._combined_mode.currentIndex(), CombinedMode.UNION_X)

        default = ""
        if self._project.image_path:
            default = self._project.image_path.stem + "_digitized.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "Save Excel", default, "Excel (*.xlsx)")
        if not path:
            return
        try:
            export_to_excel(self._project, Path(path))
            self._status.setText(f"Saved: {path}")
            QMessageBox.information(self, "Export", f"Saved:\n{path}")
        except PermissionError:
            QMessageBox.critical(self, "Error", "File may be open in Excel.")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    # ------------------------------------------------------------------
    # bounds management
    # ------------------------------------------------------------------

    def _update_all_point_bounds(self) -> None:
        bounds = self._crop_bounds_rectf()
        for pt in self._ref_points:
            pt.set_bounds(bounds)
        for pts_list in self._series_points:
            for pt in pts_list:
                pt.set_bounds(bounds)
        for pts_list in self._curve_points:
            for pt in pts_list:
                pt.set_bounds(bounds)

    # ------------------------------------------------------------------
    # safe helpers
    # ------------------------------------------------------------------

    def _safe_remove_point(self, pt: DraggablePoint) -> None:
        if pt is self._active_point:
            self._clear_active_point()
        try:
            pt.position_changed.disconnect()
        except RuntimeError:
            pass
        for signal in (pt.activated, pt.drag_finished):
            try:
                signal.disconnect()
            except (RuntimeError, TypeError):
                pass
        try:
            self._canvas.remove_overlay(pt)
        except RuntimeError:
            pass

    def _safe_hide_point(self, pt: DraggablePoint) -> None:
        try:
            pt.setVisible(False)
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # housekeeping
    # ------------------------------------------------------------------

    def _clear_all(self) -> None:
        # Ref points
        for pt in self._ref_points:
            self._safe_remove_point(pt)
        self._ref_points.clear()

        # Scatter points
        for pts_list in self._series_points:
            for pt in pts_list:
                self._safe_remove_point(pt)
        self._series_points = []
        self._series_tables.clear()
        while self._data_tabs.count():
            self._data_tabs.removeTab(0)
        self._series_spin.blockSignals(True)
        self._series_spin.setValue(1)
        self._series_spin.blockSignals(False)
        self._rebuild_series_tabs(1)

        # Curve points and paths
        for pts_list in self._curve_points:
            for pt in pts_list:
                self._safe_remove_point(pt)
        self._curve_points = []
        self._curve_tables.clear()
        for path in self._curve_paths:
            try:
                self._canvas.remove_overlay(path)
            except Exception:
                pass
        self._curve_paths.clear()
        self._curve_colors = [_curve_series_color(0)]
        self._curve_errors.clear()
        while self._curve_tabs.count():
            self._curve_tabs.removeTab(0)
        self._curve_series_spin.blockSignals(True)
        self._curve_series_spin.setValue(1)
        self._curve_series_spin.blockSignals(False)
        self._rebuild_curve_tabs(1)

        self._ref_table.setRowCount(0)
        self._calibration = None

        try:
            self._grid_overlay.setVisible(False)
        except RuntimeError:
            pass
        try:
            self._canvas.remove_overlay(self._grid_overlay)
        except Exception:
            pass
        self._grid_overlay = RefGridOverlay()
        self._canvas.add_overlay(self._grid_overlay)
        self._grid_overlay.setVisible(False)

        for pt in self._crop_corners:
            self._safe_remove_point(pt)
        self._crop_corners.clear()

        if self._crop_overlay:
            try:
                self._canvas.remove_overlay(self._crop_overlay)
            except Exception:
                pass
            self._crop_overlay = None
        self._crop_confirmed = False
