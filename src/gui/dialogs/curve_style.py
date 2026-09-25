"""Modeless editor for the visual style of extracted curves."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QPushButton,
    QWidget,
)


class CurveStyleDialog(QDialog):
    """Edit curve colour, width and line pattern with live signals."""

    color_changed = Signal(QColor)
    thickness_changed = Signal(float)
    line_style_changed = Signal(Qt.PenStyle)

    _LINE_STYLES: tuple[tuple[str, Qt.PenStyle], ...] = (
        ("Solid", Qt.PenStyle.SolidLine),
        ("Dash", Qt.PenStyle.DashLine),
        ("Dot", Qt.PenStyle.DotLine),
        ("Dash-dot", Qt.PenStyle.DashDotLine),
        ("Dash-dot-dot", Qt.PenStyle.DashDotDotLine),
    )

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        color: QColor = QColor(255, 80, 80),
        thickness: float = 2.0,
        line_style: Qt.PenStyle = Qt.PenStyle.SolidLine,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Curve Style")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self._color = QColor(color)

        form = QFormLayout(self)

        self._color_button = QPushButton()
        self._color_button.setToolTip("Choose curve colour")
        self._color_button.clicked.connect(self._choose_color)
        self._update_color_button()
        form.addRow("Colour:", self._color_button)

        self._thickness_spin = QDoubleSpinBox()
        self._thickness_spin.setRange(0.5, 50.0)
        self._thickness_spin.setSingleStep(0.5)
        self._thickness_spin.setDecimals(1)
        self._thickness_spin.setValue(max(0.5, thickness))
        self._thickness_spin.valueChanged.connect(self.thickness_changed.emit)
        form.addRow("Thickness:", self._thickness_spin)

        self._line_style_combo = QComboBox()
        for label, style in self._LINE_STYLES:
            self._line_style_combo.addItem(label, userData=style)
        selected = self._line_style_combo.findData(Qt.PenStyle(line_style))
        self._line_style_combo.setCurrentIndex(max(0, selected))
        self._line_style_combo.currentIndexChanged.connect(self._on_line_style)
        form.addRow("Line pattern:", self._line_style_combo)

        self.resize(280, 140)

    def current_color(self) -> QColor:
        return QColor(self._color)

    def current_thickness(self) -> float:
        return self._thickness_spin.value()

    def current_line_style(self) -> Qt.PenStyle:
        return Qt.PenStyle(self._line_style_combo.currentData())

    def set_color(self, color: QColor, *, emit: bool = False) -> None:
        if not color.isValid():
            return
        self._color = QColor(color)
        self._update_color_button()
        if emit:
            self.color_changed.emit(QColor(self._color))

    def set_thickness(self, thickness: float) -> None:
        self._thickness_spin.setValue(max(0.5, thickness))

    def set_line_style(self, style: Qt.PenStyle) -> None:
        index = self._line_style_combo.findData(Qt.PenStyle(style))
        if index >= 0:
            self._line_style_combo.setCurrentIndex(index)

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(self._color, self, "Curve colour")
        self.set_color(color, emit=True)

    def _update_color_button(self) -> None:
        name = self._color.name(QColor.NameFormat.HexArgb)
        self._color_button.setText(self._color.name())
        self._color_button.setStyleSheet(
            f"QPushButton {{ background-color: {name}; min-width: 90px; }}"
        )

    def _on_line_style(self, _index: int) -> None:
        self.line_style_changed.emit(self.current_line_style())


__all__ = ["CurveStyleDialog"]
