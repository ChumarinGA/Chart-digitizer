"""Table for calibration reference points."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTableWidgetItem, QWidget

from src.gui.tables.base import _BasePointTable
from src.gui.tables.colors import point_color


class RefPointTable(_BasePointTable):
    """Calibration anchors with independent X/Y roles.

    An X anchor contributes only its horizontal pixel coordinate, while a Y
    anchor contributes only its vertical coordinate. ``Both`` is useful for a
    known grid intersection or plot corner. Keeping the unused value blank
    avoids the error-prone requirement to invent a second value.
    """

    ref_value_changed = Signal()
    HEADERS = ["#", "Axis", "x_px", "y_px", "X value", "Y value"]
    VALID_AXES = {"X", "Y", "Both"}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(self.HEADERS, parent)
        self.cellChanged.connect(self._on_cell_changed)
        self.cellClicked.connect(self._begin_value_edit)
        self.horizontalHeaderItem(1).setToolTip(
            "Derived automatically from the non-empty X/Y value cells."
        )
        self.horizontalHeaderItem(4).setToolTip(
            "Known X coordinate; leave blank when only Y is known."
        )
        self.horizontalHeaderItem(5).setToolTip(
            "Known Y coordinate; leave blank when only X is known."
        )

    def add_row(
        self,
        x_wind: float,
        y_wind: float,
        x_ref: float | None = None,
        y_ref: float | None = None,
        color: QColor | None = None,
        axis: str = "X",
    ) -> int:
        if axis not in self.VALID_AXES:
            raise ValueError(f"Unknown calibration anchor axis: {axis}")
        self._updating = True
        row = self.rowCount()
        self.insertRow(row)
        num_item = self._make_ro_item(str(row + 1))
        if color is None:
            color = point_color(row)
        num_item.setBackground(QBrush(color))
        self.setItem(row, 0, num_item)
        axis = self._canonical_axis(axis, x_ref, y_ref)
        axis_item = self._make_ro_item(axis)
        axis_item.setToolTip(
            "Automatic role: X when only X value is filled, Y when only Y is "
            "filled, Both when both values are filled."
        )
        self.setItem(row, 1, axis_item)
        self.setItem(row, 2, self._make_rw_item(self._fmt(x_wind)))
        self.setItem(row, 3, self._make_rw_item(self._fmt(y_wind)))
        self.setItem(row, 4, self._make_value_item(x_ref, "X"))
        self.setItem(row, 5, self._make_value_item(y_ref, "Y"))
        self._updating = False
        return row

    @staticmethod
    def _canonical_axis(
        fallback: str, x_ref: float | None, y_ref: float | None
    ) -> str:
        """Derive the role when values exist, preserving intent while blank."""
        has_x = x_ref is not None and math.isfinite(float(x_ref))
        has_y = y_ref is not None and math.isfinite(float(y_ref))
        if has_x and has_y:
            return "Both"
        if has_x:
            return "X"
        if has_y:
            return "Y"
        return fallback

    def _make_value_item(
        self, value: float | None, axis_name: str
    ) -> QTableWidgetItem:
        # Both value columns deliberately stay editable. Typing the other
        # coordinate promotes a single-axis anchor to a known intersection.
        item = self._make_rw_item("" if value is None else self._fmt(value))
        other = "Y" if axis_name == "X" else "X"
        item.setToolTip(
            f"Known {axis_name} coordinate. Filling both {axis_name} and {other} "
            "automatically changes Axis to Both."
        )
        return item

    def _begin_value_edit(self, row: int, col: int) -> None:
        """Open an editable value cell immediately on a single click."""
        if col in (4, 5):
            item = self.item(row, col)
            if item is not None and item.flags() & Qt.ItemFlag.ItemIsEditable:
                self.editItem(item)

    @staticmethod
    def _value_state(item: QTableWidgetItem | None) -> tuple[bool, bool]:
        """Return ``(present, valid_finite_number)`` for a value cell."""
        if item is None:
            return False, True
        text = item.text().strip()
        if not text or text == "—":
            return False, True
        try:
            return True, math.isfinite(float(text))
        except ValueError:
            return True, False

    def _sync_axis_role(self, row: int) -> None:
        x_present, x_valid = self._value_state(self.item(row, 4))
        y_present, y_valid = self._value_state(self.item(row, 5))
        # Do not rewrite the semantic role while an invalid value remains;
        # the calibration build reports that exact row and field.
        if not (x_valid and y_valid):
            return
        if x_present and y_present:
            axis = "Both"
        elif x_present:
            axis = "X"
        elif y_present:
            axis = "Y"
        else:
            return
        self.item(row, 1).setText(axis)

    def _mark_value_validity(self, row: int, col: int) -> None:
        item = self.item(row, col)
        if item is None:
            return
        _present, valid = self._value_state(item)
        axis_name = "X" if col == 4 else "Y"
        if valid:
            item.setForeground(QBrush())
            other = "Y" if axis_name == "X" else "X"
            item.setToolTip(
                f"Known {axis_name} coordinate. Filling both {axis_name} and {other} "
                "automatically changes Axis to Both."
            )
        else:
            item.setForeground(QBrush(QColor(255, 102, 102)))
            item.setToolTip(
                f"Invalid {axis_name} value: enter a finite number or leave the cell blank."
            )

    def update_wind(self, row: int, x: float, y: float) -> None:
        if row < 0 or row >= self.rowCount():
            return
        self._updating = True
        self.item(row, 2).setText(self._fmt(x))
        self.item(row, 3).setText(self._fmt(y))
        self._updating = False

    @staticmethod
    def _optional_float(
        item: QTableWidgetItem | None, *, row: int, field: str
    ) -> float | None:
        if item is None:
            return None
        text = item.text().strip()
        if not text or text == "—":
            return None
        try:
            value = float(text)
        except ValueError as exc:
            raise ValueError(
                f"Calibration row {row + 1}: {field} must be a number or blank"
            ) from exc
        if not math.isfinite(value):
            raise ValueError(
                f"Calibration row {row + 1}: {field} must be finite"
            )
        return value

    def get_ref_data(
        self,
    ) -> list[tuple[float, float, float | None, float | None, str]]:
        result = []
        for row in range(self.rowCount()):
            try:
                axis = self.item(row, 1).text()
                x_wind = float(self.item(row, 2).text())
                y_wind = float(self.item(row, 3).text())
            except (ValueError, AttributeError) as exc:
                raise ValueError(
                    f"Calibration row {row + 1}: pixel coordinates must be numbers"
                ) from exc
            if not (math.isfinite(x_wind) and math.isfinite(y_wind)):
                raise ValueError(
                    f"Calibration row {row + 1}: pixel coordinates must be finite"
                )
            x_ref = self._optional_float(
                self.item(row, 4), row=row, field="X value"
            )
            y_ref = self._optional_float(
                self.item(row, 5), row=row, field="Y value"
            )
            result.append((x_wind, y_wind, x_ref, y_ref, axis))
        return result

    def _on_cell_changed(self, row: int, col: int) -> None:
        if self._updating:
            return
        if col in (2, 3):
            try:
                x = float(self.item(row, 2).text())
                y = float(self.item(row, 3).text())
                self.point_wind_changed.emit(row, x, y)
            except (ValueError, AttributeError):
                pass
        if col in (4, 5):
            self._updating = True
            try:
                self._mark_value_validity(row, col)
                self._sync_axis_role(row)
            finally:
                self._updating = False
            self.ref_value_changed.emit()


__all__ = ["RefPointTable"]
