"""Modeless dialog for configuring point shape and size in real time."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
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
    """Non-modal dialog emitting shape/size changes in real time."""

    shape_changed = Signal(PointShape)
    size_changed = Signal(float)

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

        self.resize(260, 100)

    def current_shape(self) -> PointShape:
        return self._shape_combo.currentData()

    def current_size(self) -> float:
        return self._size_spin.value()

    def _on_size(self, val: float) -> None:
        self.size_changed.emit(val)

    def _on_shape(self, _idx: int) -> None:
        shape = self._shape_combo.currentData()
        if shape is not None:
            self.shape_changed.emit(shape)
