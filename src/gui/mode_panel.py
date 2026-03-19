"""Mode panel — 3-mode (Crop / Ref / Data) interface with tables and multi-series tabs."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from scipy.interpolate import CubicSpline

from src.core.calibration import build_calibration
from src.core.export import export_to_excel
from src.core.plot_area import detect_plot_area
from src.gui.image_canvas import ImageCanvas
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


def _curve_series_color(index: int) -> QColor:
    return _CURVE_PALETTE[index % len(_CURVE_PALETTE)]


class ModePanel(QWidget):
    """Right-side panel with Crop / Ref Points / Data Points modes."""

    def __init__(self, project: ProjectState, canvas: ImageCanvas,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._canvas = canvas

        # --- Scatter state ---
        self._ref_points: list[DraggablePoint] = []
        self._series_points: list[list[DraggablePoint]] = [[]]
        self._series_tables: list[DataPointTable] = []

        # --- Curve state ---
        self._curve_points: list[list[DraggablePoint]] = [[]]
        self._curve_tables: list[DataPointTable] = []
        self._curve_paths: list[CurvePathOverlay] = []
        self._curve_colors: list[QColor] = [_curve_series_color(0)]
        self._curve_point_size: float = 4.0
        self._curve_thickness: float = 2.0
        self._curve_dx: float = 0.1

        self._crop_overlay: Optional[CropOverlay] = None
        self._grid_overlay = RefGridOverlay()
        self._canvas.add_overlay(self._grid_overlay)
        self._grid_overlay.setVisible(False)

        self._calibration: Optional[CalibrationResult] = None
        self._crop_confirmed = False

        self._style_dialog: Optional[PointStyleDialog] = None
        self._current_shape = PointShape.CIRCLE
        self._current_size = DraggablePoint.DEFAULT_SIZE

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

        # --- Export ---
        export_row = QHBoxLayout()
        self._combined_mode = QComboBox()
        self._combined_mode.addItems(["Union X", "Uniform grid", "Interpolation"])
        export_row.addWidget(QLabel("Combined:"))
        export_row.addWidget(self._combined_mode, stretch=1)
        root.addLayout(export_row)

        btn_export = QPushButton("Export to Excel")
        btn_export.setObjectName("primary")
        btn_export.clicked.connect(self._do_export)
        root.addWidget(btn_export)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #66bb6a; font-size: 12px;")
        root.addWidget(self._status)

        self._canvas.scene_clicked.connect(self._on_canvas_click)

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    def set_project(self, project: ProjectState) -> None:
        self._project = project
        self._clear_all()

    # ------------------------------------------------------------------
    # page builders
    # ------------------------------------------------------------------

    def _build_crop_page(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel("Detect or adjust the plot area rectangle."))
        btn_auto = QPushButton("Auto-detect area")
        btn_auto.clicked.connect(self._crop_auto)
        lay.addWidget(btn_auto)
        btn_ok = QPushButton("Confirm area")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self._crop_confirm)
        lay.addWidget(btn_ok)

        self._crop_corner_table = CropCornerTable()
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
        lay.addWidget(QLabel("Click inside the plot area to add reference points."))

        form = QFormLayout()
        self._x_scale_combo = QComboBox()
        self._x_scale_combo.addItems(["Linear", "Logarithmic"])
        form.addRow("X scale:", self._x_scale_combo)
        self._y_scale_combo = QComboBox()
        self._y_scale_combo.addItems(["Linear", "Logarithmic"])
        form.addRow("Y scale:", self._y_scale_combo)
        lay.addLayout(form)

        self._ref_table = RefPointTable()
        lay.addWidget(self._ref_table, stretch=1)

        btn_row = QHBoxLayout()
        btn_del = QPushButton("Delete selected")
        btn_del.clicked.connect(self._ref_delete_selected)
        btn_row.addWidget(btn_del)

        btn_clear = QPushButton("Clear all ref points")
        btn_clear.clicked.connect(self._ref_clear_all)
        btn_row.addWidget(btn_clear)

        btn_build = QPushButton("Build Calibration")
        btn_build.setObjectName("primary")
        btn_build.clicked.connect(self._rebuild_calibration)
        btn_row.addWidget(btn_build)
        lay.addLayout(btn_row)

        self._ref_status = QLabel("Need >= 2 distinct X refs and >= 2 distinct Y refs.")
        self._ref_status.setWordWrap(True)
        lay.addWidget(self._ref_status)

        self._ref_table.point_wind_changed.connect(self._ref_table_wind_changed)
        self._ref_table.ref_value_changed.connect(self._on_ref_value_changed)
        self._ref_table.key_move.connect(self._ref_key_move)
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

    def _build_scatter_subpage(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("Click inside the plot area to add data points."))

        snap_row = QHBoxLayout()
        self._snap_free = QRadioButton("Free")
        self._snap_x = QRadioButton("Snap X")
        self._snap_y = QRadioButton("Snap Y")
        self._snap_free.setChecked(True)
        for rb in (self._snap_free, self._snap_x, self._snap_y):
            snap_row.addWidget(rb)
        lay.addLayout(snap_row)

        tool_row = QHBoxLayout()
        btn_style = QPushButton("Style Points")
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
        lay.addWidget(QLabel("Click to add control points; a smooth curve connects them."))

        # Controls row
        ctrl_form = QFormLayout()

        self._curve_size_spin = QDoubleSpinBox()
        self._curve_size_spin.setRange(1.0, 50.0)
        self._curve_size_spin.setValue(self._curve_point_size)
        self._curve_size_spin.setSingleStep(0.5)
        self._curve_size_spin.setDecimals(1)
        self._curve_size_spin.valueChanged.connect(self._on_curve_point_size)
        ctrl_form.addRow("Point size:", self._curve_size_spin)

        self._curve_thick_spin = QDoubleSpinBox()
        self._curve_thick_spin.setRange(0.5, 10.0)
        self._curve_thick_spin.setValue(self._curve_thickness)
        self._curve_thick_spin.setSingleStep(0.5)
        self._curve_thick_spin.setDecimals(1)
        self._curve_thick_spin.valueChanged.connect(self._on_curve_thickness)
        ctrl_form.addRow("Curve thickness:", self._curve_thick_spin)

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

    # ------------------------------------------------------------------
    # scatter series tabs management
    # ------------------------------------------------------------------

    def _make_series_tab_widget(self, si: int) -> QWidget:
        container = QWidget()
        vlay = QVBoxLayout(container)
        vlay.setContentsMargins(0, 0, 0, 0)

        table = DataPointTable()
        table.point_wind_changed.connect(
            lambda row, x, y, s=si: self._data_table_wind_changed(s, row, x, y)
        )
        table.key_move.connect(
            lambda row, dx, dy, s=si: self._data_key_move(s, row, dx, dy)
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
                    self._safe_hide_point(pt)
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

    # ------------------------------------------------------------------
    # curve series tabs management
    # ------------------------------------------------------------------

    def _make_curve_tab_widget(self, ci: int) -> QWidget:
        container = QWidget()
        vlay = QVBoxLayout(container)
        vlay.setContentsMargins(0, 0, 0, 0)

        table = DataPointTable()
        table.point_wind_changed.connect(
            lambda row, x, y, s=ci: self._curve_table_wind_changed(s, row, x, y)
        )
        table.key_move.connect(
            lambda row, dx, dy, s=ci: self._curve_key_move(s, row, dx, dy)
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
                    self._safe_hide_point(pt)
                self._curve_points.pop(idx)
            if idx < len(self._curve_paths):
                path = self._curve_paths.pop(idx)
                try:
                    self._canvas.remove_overlay(path)
                except Exception:
                    pass
            if idx < len(self._curve_colors):
                self._curve_colors.pop(idx)

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
        if self._stack.currentIndex() == 2 and not self._is_scatter_mode():
            self._refresh_data_visibility()

    # ------------------------------------------------------------------
    # curve controls
    # ------------------------------------------------------------------

    @Slot(float)
    def _on_curve_point_size(self, val: float) -> None:
        self._curve_point_size = val
        for pts_list in self._curve_points:
            for pt in pts_list:
                pt.set_point_size(val)

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
        if ci < len(self._curve_colors):
            self._curve_colors[ci] = color
        if ci < len(self._curve_paths):
            self._curve_paths[ci].set_color(color)
        if ci < len(self._curve_points):
            for pt in self._curve_points[ci]:
                pt._color = color
                pt.update()

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
                    self._crop_overlay.set_editing_style()
                    self._crop_overlay.set_confirmed_style(self._opacity_slider.value())
            else:
                self._crop_overlay.setVisible(self._crop_confirmed)
                if self._crop_confirmed:
                    self._crop_overlay.set_confirmed_style(self._opacity_slider.value())
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
    # canvas click dispatch
    # ------------------------------------------------------------------

    @Slot(float, float)
    def _on_canvas_click(self, sx: float, sy: float) -> None:
        mode = self._stack.currentIndex()
        if mode in (1, 2):
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
        rect = detect_plot_area(self._project.image)
        if rect is None:
            h, w = self._project.image.shape[:2]
            rect = (0, 0, w, h)
        self._show_crop_overlay(*rect)
        self._crop_status.setText(f"Area: {rect[2]}x{rect[3]} at ({rect[0]},{rect[1]})")

    def _crop_confirm(self) -> None:
        if self._crop_overlay:
            self._project.crop_rect = self._crop_overlay.get_rect()
        elif self._project.image is not None:
            h, w = self._project.image.shape[:2]
            self._project.crop_rect = (0, 0, w, h)
        else:
            return
        self._crop_confirmed = True
        self._crop_overlay.set_confirmed_style(self._opacity_slider.value())
        self._update_all_point_bounds()
        r = self._project.crop_rect
        self._crop_status.setText(f"Confirmed: {r[2]}x{r[3]} at ({r[0]},{r[1]})")
        self._status.setText("Plot area set. Switch to Ref Points.")

    def _show_crop_overlay(self, x: int, y: int, w: int, h: int) -> None:
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
            self._crop_overlay.set_fill_opacity(value)

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

    # ------------------------------------------------------------------
    # REFERENCE POINTS
    # ------------------------------------------------------------------

    def _add_ref_point(self, sx: float, sy: float) -> None:
        idx = len(self._ref_points)
        color = point_color(idx)
        pt = DraggablePoint(sx, sy, color=color)
        pt.set_bounds(self._crop_bounds_rectf())
        self._canvas.add_overlay(pt)
        self._ref_points.append(pt)
        self._ref_table.add_row(sx, sy, 0.0, 0.0, color=color)

        pt.position_changed.connect(
            lambda x, y, r=idx: self._on_ref_dragged(r, x, y)
        )

    def _on_ref_dragged(self, row: int, x: float, y: float) -> None:
        self._ref_table.update_wind(row, x, y)

    @Slot(int, float, float)
    def _ref_table_wind_changed(self, row: int, x: float, y: float) -> None:
        if 0 <= row < len(self._ref_points):
            self._ref_points[row].set_pos_silent(x, y)

    @Slot()
    def _on_ref_value_changed(self) -> None:
        pass

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

    def _ref_clear_all(self) -> None:
        for pt in self._ref_points:
            self._safe_remove_point(pt)
        self._ref_points.clear()
        self._ref_table.setRowCount(0)
        self._calibration = None
        self._project.calibration = None
        self._grid_overlay.clear_grid()
        self._grid_overlay.setVisible(False)
        self._ref_status.setText("Need >= 2 distinct X refs and >= 2 distinct Y refs.")
        self._ref_status.setStyleSheet("color: #cccccc;")

    def _reconnect_ref_signals(self) -> None:
        for i, pt in enumerate(self._ref_points):
            try:
                pt.position_changed.disconnect()
            except RuntimeError:
                pass
            pt.position_changed.connect(
                lambda x, y, r=i: self._on_ref_dragged(r, x, y)
            )

    def _rebuild_calibration(self) -> None:
        data = self._ref_table.get_ref_data()
        x_pairs = [(xw, xr) for xw, _, xr, _ in data]
        y_pairs = [(yw, yr) for _, yw, _, yr in data]

        unique_x = len({xr for _, xr in x_pairs})
        unique_y = len({yr for _, yr in y_pairs})

        if len(x_pairs) >= 2 and len(y_pairs) >= 2 and unique_x >= 2 and unique_y >= 2:
            scale_x = ScaleType.LOG if self._x_scale_combo.currentIndex() == 1 else ScaleType.LINEAR
            scale_y = ScaleType.LOG if self._y_scale_combo.currentIndex() == 1 else ScaleType.LINEAR
            try:
                self._calibration = build_calibration(x_pairs, y_pairs, scale_x, scale_y)
                self._project.calibration = self._calibration
                n = len(data)
                accuracy_note = (
                    "exact fit" if n == 2
                    else f"least-squares fit ({n} pts, higher accuracy)"
                )
                self._ref_status.setText(f"Calibration OK — {accuracy_note}")
                self._ref_status.setStyleSheet("color: #66bb6a;")
                self._update_grid()
                self._grid_overlay.setVisible(True)
                for table in self._series_tables:
                    table.update_all_fig(self._calibration)
                for table in self._curve_tables:
                    table.update_all_fig(self._calibration)
                return
            except Exception as e:
                self._ref_status.setText(f"Calibration error: {e}")
                self._ref_status.setStyleSheet("color: #ff6666;")
                self._calibration = None
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

        self._grid_overlay.clear_grid()
        self._grid_overlay.setVisible(False)

    def _update_grid(self) -> None:
        if self._calibration is None or self._project.crop_rect is None:
            self._grid_overlay.clear_grid()
            return
        data = self._ref_table.get_ref_data()
        x_refs = sorted({xr for _, _, xr, _ in data})
        y_refs = sorted({yr for _, _, _, yr in data})
        self._grid_overlay.update_grid(self._calibration, self._project.crop_rect, x_refs, y_refs)

    # ------------------------------------------------------------------
    # SCATTER DATA POINTS
    # ------------------------------------------------------------------

    def _add_data_point(self, sx: float, sy: float) -> None:
        if self._calibration is None:
            QMessageBox.warning(self, "Data", "Build calibration first (Ref Points tab).")
            return

        si = self._active_series_index()
        if si >= len(self._series_tables):
            return

        constraint = DragConstraint.FREE
        x_fig_override: Optional[float] = None
        y_fig_override: Optional[float] = None

        if self._snap_x.isChecked():
            sx, x_fig_override = self._snap_to_x_grid(sx)
            constraint = DragConstraint.VERTICAL_ONLY
        elif self._snap_y.isChecked():
            sy, y_fig_override = self._snap_to_y_grid(sy)
            constraint = DragConstraint.HORIZONTAL_ONLY

        idx = len(self._series_points[si])
        color = point_color(idx)
        pt = DraggablePoint(sx, sy, color=color)
        pt.set_constraint(constraint)
        pt.set_bounds(self._crop_bounds_rectf())
        pt.set_point_shape(self._current_shape)
        pt.set_point_size(self._current_size)
        self._canvas.add_overlay(pt)
        self._series_points[si].append(pt)

        try:
            xf = x_fig_override if x_fig_override is not None else self._calibration.x_axis.pixel_to_data(sx)
            yf = y_fig_override if y_fig_override is not None else self._calibration.y_axis.pixel_to_data(sy)
        except Exception:
            xf, yf = 0.0, 0.0

        table = self._series_tables[si]
        row = table.add_row(sx, sy, xf, yf, color=color)
        pt.position_changed.connect(
            lambda x, y, s=si, r=row: self._on_data_dragged(s, r, x, y)
        )
        self._update_data_status()

    def _on_data_dragged(self, si: int, row: int, x: float, y: float) -> None:
        if si < len(self._series_tables):
            self._series_tables[si].update_wind(row, x, y)
            if self._calibration:
                try:
                    xf = self._calibration.x_axis.pixel_to_data(x)
                    yf = self._calibration.y_axis.pixel_to_data(y)
                    self._series_tables[si].update_fig(row, xf, yf)
                except Exception:
                    pass

    @Slot(int, float, float)
    def _data_table_wind_changed(self, si: int, row: int, x: float, y: float) -> None:
        if 0 <= si < len(self._series_points) and 0 <= row < len(self._series_points[si]):
            self._series_points[si][row].set_pos_silent(x, y)
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

    def _data_clear_series(self, si: int) -> None:
        if si >= len(self._series_points):
            return
        for pt in self._series_points[si]:
            self._safe_remove_point(pt)
        self._series_points[si].clear()
        if si < len(self._series_tables):
            self._series_tables[si].setRowCount(0)
        self._update_data_status()

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

    def _add_curve_point(self, sx: float, sy: float) -> None:
        if self._calibration is None:
            QMessageBox.warning(self, "Data", "Build calibration first (Ref Points tab).")
            return

        ci = self._active_curve_index()
        if ci >= len(self._curve_tables):
            return

        idx = len(self._curve_points[ci])
        color = self._curve_colors[ci] if ci < len(self._curve_colors) else QColor(255, 80, 80)
        pt = DraggablePoint(sx, sy, color=color)
        pt.set_bounds(self._crop_bounds_rectf())
        pt.set_point_size(self._curve_point_size)
        pt.set_point_shape(PointShape.CIRCLE)
        self._canvas.add_overlay(pt)
        self._curve_points[ci].append(pt)

        try:
            xf = self._calibration.x_axis.pixel_to_data(sx)
            yf = self._calibration.y_axis.pixel_to_data(sy)
        except Exception:
            xf, yf = 0.0, 0.0

        table = self._curve_tables[ci]
        row = table.add_row(sx, sy, xf, yf, color=color)
        pt.position_changed.connect(
            lambda x, y, s=ci, r=row: self._on_curve_dragged(s, r, x, y)
        )
        self._rebuild_curve_path(ci)
        self._update_curve_status()

    def _on_curve_dragged(self, ci: int, row: int, x: float, y: float) -> None:
        if ci < len(self._curve_tables):
            self._curve_tables[ci].update_wind(row, x, y)
            if self._calibration:
                try:
                    xf = self._calibration.x_axis.pixel_to_data(x)
                    yf = self._calibration.y_axis.pixel_to_data(y)
                    self._curve_tables[ci].update_fig(row, xf, yf)
                except Exception:
                    pass
        self._rebuild_curve_path(ci)

    @Slot(int, float, float)
    def _curve_table_wind_changed(self, ci: int, row: int, x: float, y: float) -> None:
        if 0 <= ci < len(self._curve_points) and 0 <= row < len(self._curve_points[ci]):
            self._curve_points[ci][row].set_pos_silent(x, y)
        if self._calibration:
            try:
                xf = self._calibration.x_axis.pixel_to_data(x)
                yf = self._calibration.y_axis.pixel_to_data(y)
                if ci < len(self._curve_tables):
                    self._curve_tables[ci].update_fig(row, xf, yf)
            except Exception:
                pass
        self._rebuild_curve_path(ci)

    @Slot(int, float, float)
    def _curve_key_move(self, ci: int, row: int, dx: float, dy: float) -> None:
        if 0 <= ci < len(self._curve_points) and 0 <= row < len(self._curve_points[ci]):
            self._curve_points[ci][row].moveBy(dx, dy)
            self._rebuild_curve_path(ci)

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

    def _curve_clear_series(self, ci: int) -> None:
        if ci >= len(self._curve_points):
            return
        for pt in self._curve_points[ci]:
            self._safe_remove_point(pt)
        self._curve_points[ci].clear()
        if ci < len(self._curve_tables):
            self._curve_tables[ci].setRowCount(0)
        self._rebuild_curve_path(ci)
        self._update_curve_status()

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
        qpoints = [pt.pos() for pt in pts]
        self._curve_paths[ci].update_from_points(qpoints)

    def _update_curve_status(self) -> None:
        total = sum(len(pts) for pts in self._curve_points)
        self._curve_status.setText(
            f"{total} control point(s) across {len(self._curve_points)} curve(s)"
        )

    # ------------------------------------------------------------------
    # grid snap helpers
    # ------------------------------------------------------------------

    def _snap_to_x_grid(self, click_x: float) -> tuple[float, float]:
        data = self._ref_table.get_ref_data()
        x_refs = sorted({xr for _, _, xr, _ in data})
        if not x_refs or self._calibration is None:
            return click_x, 0.0
        best_ref = min(x_refs, key=lambda xr: abs(self._calibration.x_axis.data_to_pixel(xr) - click_x))
        return self._calibration.x_axis.data_to_pixel(best_ref), best_ref

    def _snap_to_y_grid(self, click_y: float) -> tuple[float, float]:
        data = self._ref_table.get_ref_data()
        y_refs = sorted({yr for _, _, _, yr in data})
        if not y_refs or self._calibration is None:
            return click_y, 0.0
        best_ref = min(y_refs, key=lambda yr: abs(self._calibration.y_axis.data_to_pixel(yr) - click_y))
        return self._calibration.y_axis.data_to_pixel(best_ref), best_ref

    # ------------------------------------------------------------------
    # export
    # ------------------------------------------------------------------

    def _do_export(self) -> None:
        scatter_total = sum(len(pts) for pts in self._series_points)
        curve_total = sum(len(pts) for pts in self._curve_points)
        if scatter_total == 0 and curve_total == 0:
            QMessageBox.warning(self, "Export", "No data points to export.")
            return
        if self._calibration is None:
            QMessageBox.warning(self, "Export", "No calibration built.")
            return

        self._project.series.clear()
        series_idx = 1

        # Scatter series
        for si, table in enumerate(self._series_tables):
            sd = SeriesData(
                index=series_idx, kind=SeriesKind.DISCRETE,
                mode=ExtractionMode.MANUAL,
            )
            for row_idx in range(table.rowCount()):
                try:
                    xf = float(table.item(row_idx, 3).text())
                    yf = float(table.item(row_idx, 4).text())
                    sd.points.append(ExtractedPoint(x=xf, y=yf))
                except (ValueError, AttributeError):
                    continue
            if sd.points:
                sd.sort_by_x()
                self._project.series.append(sd)
                series_idx += 1

        # Curve series — sample spline at dx step
        dx = self._curve_dx
        for ci, table in enumerate(self._curve_tables):
            sd = SeriesData(
                index=series_idx, kind=SeriesKind.CONTINUOUS,
                mode=ExtractionMode.MANUAL,
            )
            ctrl: list[tuple[float, float]] = []
            for row_idx in range(table.rowCount()):
                try:
                    xf = float(table.item(row_idx, 3).text())
                    yf = float(table.item(row_idx, 4).text())
                    ctrl.append((xf, yf))
                except (ValueError, AttributeError):
                    continue

            if len(ctrl) >= 2:
                ctrl.sort(key=lambda p: p[0])
                xs = np.array([p[0] for p in ctrl])
                ys = np.array([p[1] for p in ctrl])
                try:
                    cs = CubicSpline(xs, ys)
                    x_export = np.arange(xs[0], xs[-1] + dx * 0.5, dx)
                    if x_export[-1] > xs[-1]:
                        x_export = x_export[:-1]
                        x_export = np.append(x_export, xs[-1])
                    y_export = cs(x_export)
                    for xi, yi in zip(x_export, y_export):
                        sd.points.append(ExtractedPoint(x=float(xi), y=float(yi)))
                except Exception:
                    for xf, yf in ctrl:
                        sd.points.append(ExtractedPoint(x=xf, y=yf))
            elif len(ctrl) == 1:
                sd.points.append(ExtractedPoint(x=ctrl[0][0], y=ctrl[0][1]))

            if sd.points:
                self._project.series.append(sd)
                series_idx += 1

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
        try:
            pt.position_changed.disconnect()
        except RuntimeError:
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
        self._series_points = [[]]
        self._series_tables.clear()
        while self._data_tabs.count():
            self._data_tabs.removeTab(0)
        self._rebuild_series_tabs(self._series_spin.value())

        # Curve points and paths
        for pts_list in self._curve_points:
            for pt in pts_list:
                self._safe_remove_point(pt)
        self._curve_points = [[]]
        self._curve_tables.clear()
        for path in self._curve_paths:
            try:
                self._canvas.remove_overlay(path)
            except Exception:
                pass
        self._curve_paths.clear()
        self._curve_colors = [_curve_series_color(0)]
        while self._curve_tabs.count():
            self._curve_tabs.removeTab(0)
        self._rebuild_curve_tabs(self._curve_series_spin.value())

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
