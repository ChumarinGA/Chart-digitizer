"""Settings dialog with tabs for all user-adjustable parameters."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.models.project_data import AppSettings
from src.models.types import ScaleType


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(420, 480)
        self._settings = settings

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # --- Calibration tab ---
        cal_tab = QWidget()
        cal_form = QFormLayout(cal_tab)

        self._x_scale_combo = QComboBox()
        self._x_scale_combo.addItems(["Linear", "Logarithmic"])
        self._x_scale_combo.setCurrentIndex(0 if settings.x_scale == ScaleType.LINEAR else 1)
        cal_form.addRow("X scale:", self._x_scale_combo)

        self._y_scale_combo = QComboBox()
        self._y_scale_combo.addItems(["Linear", "Logarithmic"])
        self._y_scale_combo.setCurrentIndex(0 if settings.y_scale == ScaleType.LINEAR else 1)
        cal_form.addRow("Y scale:", self._y_scale_combo)

        self._n_cal = QSpinBox()
        self._n_cal.setRange(2, 10)
        self._n_cal.setValue(settings.n_calibration_points)
        cal_form.addRow("Calibration points:", self._n_cal)
        tabs.addTab(cal_tab, "Calibration")

        # --- Curves tab ---
        curves_tab = QWidget()
        curves_form = QFormLayout(curves_tab)

        self._seg_sens = QDoubleSpinBox()
        self._seg_sens.setRange(0.0, 1.0)
        self._seg_sens.setSingleStep(0.05)
        self._seg_sens.setValue(settings.segmentation_sensitivity)
        curves_form.addRow("Segmentation sensitivity:", self._seg_sens)

        self._min_curve = QSpinBox()
        self._min_curve.setRange(5, 1000)
        self._min_curve.setValue(settings.min_curve_length)
        curves_form.addRow("Min curve length (px):", self._min_curve)

        self._max_thickness = QSpinBox()
        self._max_thickness.setRange(1, 100)
        self._max_thickness.setValue(settings.max_line_thickness)
        curves_form.addRow("Max line thickness (px):", self._max_thickness)

        self._skel_check = QCheckBox()
        self._skel_check.setChecked(settings.skeletonize)
        curves_form.addRow("Skeletonize:", self._skel_check)

        self._step_dx = QDoubleSpinBox()
        self._step_dx.setRange(0.01, 100.0)
        self._step_dx.setValue(settings.curve_step_dx)
        curves_form.addRow("Curve step dX:", self._step_dx)
        tabs.addTab(curves_tab, "Curves")

        # --- Markers tab ---
        markers_tab = QWidget()
        markers_form = QFormLayout(markers_tab)

        self._min_marker = QSpinBox()
        self._min_marker.setRange(1, 10000)
        self._min_marker.setValue(settings.min_marker_area)
        markers_form.addRow("Min marker area (px²):", self._min_marker)

        self._max_marker = QSpinBox()
        self._max_marker.setRange(10, 50000)
        self._max_marker.setValue(settings.max_marker_area)
        markers_form.addRow("Max marker area (px²):", self._max_marker)

        self._marker_sens = QDoubleSpinBox()
        self._marker_sens.setRange(0.0, 1.0)
        self._marker_sens.setSingleStep(0.05)
        self._marker_sens.setValue(settings.marker_center_sensitivity)
        markers_form.addRow("Centre sensitivity:", self._marker_sens)
        tabs.addTab(markers_tab, "Markers")

        # --- Manual mode tab ---
        manual_tab = QWidget()
        manual_form = QFormLayout(manual_tab)

        self._arrow_step = QDoubleSpinBox()
        self._arrow_step.setRange(0.01, 50.0)
        self._arrow_step.setValue(settings.arrow_step)
        manual_form.addRow("Arrow step (px):", self._arrow_step)

        self._ctrl_step = QDoubleSpinBox()
        self._ctrl_step.setRange(0.1, 200.0)
        self._ctrl_step.setValue(settings.ctrl_step)
        manual_form.addRow("Ctrl step (px):", self._ctrl_step)

        self._shift_step = QDoubleSpinBox()
        self._shift_step.setRange(0.001, 10.0)
        self._shift_step.setDecimals(3)
        self._shift_step.setValue(settings.shift_step)
        manual_form.addRow("Shift step (px):", self._shift_step)

        self._snap_check = QCheckBox()
        self._snap_check.setChecked(settings.snap_to_edge)
        manual_form.addRow("Snap to edge:", self._snap_check)

        self._mag_check = QCheckBox()
        self._mag_check.setChecked(settings.magnifier_enabled)
        manual_form.addRow("Magnifier:", self._mag_check)
        tabs.addTab(manual_tab, "Manual mode")

        # --- Buttons ---
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._apply_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply_and_accept(self) -> None:
        s = self._settings
        s.x_scale = ScaleType.LOG if self._x_scale_combo.currentIndex() == 1 else ScaleType.LINEAR
        s.y_scale = ScaleType.LOG if self._y_scale_combo.currentIndex() == 1 else ScaleType.LINEAR
        s.n_calibration_points = self._n_cal.value()
        s.segmentation_sensitivity = self._seg_sens.value()
        s.min_curve_length = self._min_curve.value()
        s.max_line_thickness = self._max_thickness.value()
        s.skeletonize = self._skel_check.isChecked()
        s.curve_step_dx = self._step_dx.value()
        s.min_marker_area = self._min_marker.value()
        s.max_marker_area = self._max_marker.value()
        s.marker_center_sensitivity = self._marker_sens.value()
        s.arrow_step = self._arrow_step.value()
        s.ctrl_step = self._ctrl_step.value()
        s.shift_step = self._shift_step.value()
        s.snap_to_edge = self._snap_check.isChecked()
        s.magnifier_enabled = self._mag_check.isChecked()
        self.accept()
