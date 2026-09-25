"""Modeless dialog for configuring point shape and size in real time."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QSpinBox,
    QWidget,
)

from src.gui.overlays.point_overlay import PointShape, build_shape_path


def _shape_icon(shape: PointShape, size: int = 24) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(size / 2, size / 2)
    from PySide6.QtGui import QBrush, QPen
    p.setPen(QPen(Qt.GlobalColor.black, 1))
    p.setBrush(QBrush(QColor(100, 180, 255)))
    path = build_shape_path(shape, size * 0.35)
    p.drawPath(path)
    p.end()
    return pm


class PointStyleDialog(QDialog):
    """Non-modal dialog emitting point-style changes in real time."""

    shape_changed = Signal(PointShape)
    size_changed = Signal(float)
    active_fill_opacity_changed = Signal(int)

    DEFAULT_ACTIVE_FILL_OPACITY = 15

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Point Style")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        form = QFormLayout(self)

        self._size_spin = QDoubleSpinBox()
        self._size_spin.setRange(1.0, 50.0)
        self._size_spin.setValue(5.0)
        self._size_spin.setSingleStep(0.5)
        self._size_spin.setDecimals(1)
        self._size_spin.valueChanged.connect(self._on_size)
        form.addRow("Size:", self._size_spin)

        self._shape_combo = QComboBox()
        from PySide6.QtGui import QIcon
        for shape in PointShape:
            icon = QIcon(_shape_icon(shape))
            self._shape_combo.addItem(icon, shape.value, userData=shape)
        self._shape_combo.currentIndexChanged.connect(self._on_shape)
        form.addRow("Shape:", self._shape_combo)

        self._active_fill_opacity_spin = QSpinBox()
        self._active_fill_opacity_spin.setRange(0, 100)
        self._active_fill_opacity_spin.setValue(self.DEFAULT_ACTIVE_FILL_OPACITY)
        self._active_fill_opacity_spin.setSingleStep(5)
        self._active_fill_opacity_spin.setSuffix(" %")
        self._active_fill_opacity_spin.setToolTip(
            "Fill opacity used only while a point is active. "
            "The point outline remains fully opaque."
        )
        self._active_fill_opacity_spin.valueChanged.connect(
            self._on_active_fill_opacity
        )
        form.addRow("Active fill opacity:", self._active_fill_opacity_spin)

        self.resize(290, 130)

    def current_shape(self) -> PointShape:
        return self._shape_combo.currentData()

    def current_size(self) -> float:
        return self._size_spin.value()

    def current_active_fill_opacity(self) -> int:
        """Return active-point fill opacity as a percentage in ``[0, 100]``."""
        return self._active_fill_opacity_spin.value()

    def set_shape(self, shape: PointShape, *, emit: bool = False) -> None:
        index = self._shape_combo.findData(shape)
        if index < 0:
            return
        previous = self._shape_combo.blockSignals(not emit)
        self._shape_combo.setCurrentIndex(index)
        self._shape_combo.blockSignals(previous)

    def set_size(self, size: float, *, emit: bool = False) -> None:
        previous = self._size_spin.blockSignals(not emit)
        self._size_spin.setValue(max(1.0, float(size)))
        self._size_spin.blockSignals(previous)

    def set_active_fill_opacity(self, percent: int, *, emit: bool = False) -> None:
        """Set active-point fill opacity, clamped to a valid percentage."""
        previous = self._active_fill_opacity_spin.blockSignals(not emit)
        self._active_fill_opacity_spin.setValue(max(0, min(100, int(percent))))
        self._active_fill_opacity_spin.blockSignals(previous)

    def _on_size(self, val: float) -> None:
        self.size_changed.emit(val)

    def _on_shape(self, _idx: int) -> None:
        shape = self._shape_combo.currentData()
        if shape is not None:
            self.shape_changed.emit(shape)

    def _on_active_fill_opacity(self, percent: int) -> None:
        self.active_fill_opacity_changed.emit(percent)


__all__ = ["PointStyleDialog", "_shape_icon"]
