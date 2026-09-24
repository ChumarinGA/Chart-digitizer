"""Editable point tables for reference and data points with bidirectional sync."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

POINT_PALETTE = [
    QColor(230, 70, 70),
    QColor(70, 180, 70),
    QColor(70, 120, 230),
    QColor(230, 180, 40),
    QColor(180, 70, 220),
    QColor(40, 200, 200),
    QColor(230, 120, 50),
    QColor(140, 200, 60),
    QColor(200, 80, 140),
    QColor(100, 160, 220),
    QColor(220, 200, 80),
    QColor(160, 100, 60),
    QColor(80, 220, 160),
    QColor(220, 100, 180),
    QColor(100, 100, 180),
    QColor(180, 180, 100),
    QColor(120, 60, 160),
    QColor(60, 160, 120),
    QColor(200, 140, 100),
    QColor(100, 200, 220),
]


def point_color(index: int) -> QColor:
    return POINT_PALETTE[index % len(POINT_PALETTE)]


class _BasePointTable(QTableWidget):
    """Common base for both ref-point and data-point tables."""

    point_wind_changed = Signal(int, float, float)
    key_move = Signal(int, float, float)

    def __init__(self, headers: list[str], parent: QWidget | None = None) -> None:
        super().__init__(0, len(headers), parent)
        self.setHorizontalHeaderLabels(headers)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.verticalHeader().setVisible(False)
        self._updating = False
        self._arrow_step = 1.0
        self._ctrl_step = 10.0
        self._shift_step = 0.1

    def set_nudge_steps(self, arrow: float, ctrl: float, shift: float) -> None:
        self._arrow_step = float(arrow)
        self._ctrl_step = float(ctrl)
        self._shift_step = float(shift)

    def _make_ro_item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _make_rw_item(self, text: str) -> QTableWidgetItem:
        return QTableWidgetItem(text)

    def _fmt(self, v: float) -> str:
        """Format for display without throwing away scientific precision.

        The tables used to round every value to four decimal places and the
        export path then parsed that rounded text again.  In particular,
        values such as ``1e-6`` silently became zero.  Twelve significant
        digits keep the table readable while preserving the useful precision
        of manually digitised data.
        """
        return f"{v:.12g}"

    def remove_selected_row(self) -> int | None:
        rows = self.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        self.removeRow(row)
        self._renumber()
        return row

    def _renumber(self) -> None:
        self._updating = True
        for r in range(self.rowCount()):
            item = self.item(r, 0)
            if item:
                item.setText(str(r + 1))
                # Keep the marker's existing colour stable when an earlier
                # row is deleted.  Recolouring only the table made it disagree
                # with the corresponding canvas marker.
        self._updating = False

    def selected_row(self) -> int | None:
        rows = self.selectionModel().selectedRows()
        if rows:
            return rows[0].row()
        return None

    def selected_rows(self) -> list[int]:
        return sorted({idx.row() for idx in self.selectionModel().selectedRows()})

    def set_row_color(self, row: int, color: QColor) -> None:
        if 0 <= row < self.rowCount():
            item = self.item(row, 0)
            if item is not None:
                item.setBackground(QBrush(color))

    def select_all_rows(self) -> None:
        self.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.selectAll()
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            row = self.selected_row()
            if row is not None:
                step = self._arrow_step
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    step = self._ctrl_step
                elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    step = self._shift_step
                dx, dy = 0.0, 0.0
                if key == Qt.Key.Key_Left:
                    dx = -step
                elif key == Qt.Key.Key_Right:
                    dx = step
                elif key == Qt.Key.Key_Up:
                    dy = -step
                elif key == Qt.Key.Key_Down:
                    dy = step
                self.key_move.emit(row, dx, dy)
                return
        super().keyPressEvent(event)


class RefPointTable(_BasePointTable):
    """Calibration anchors with independent X/Y roles.

    An X anchor contributes only its horizontal pixel coordinate, while a Y
    anchor contributes only its vertical coordinate.  ``Both`` is useful for
    a known grid intersection or plot corner.  Keeping the unused value blank
    avoids the old and very error-prone requirement to invent a second value.
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

    def add_row(self, x_wind: float, y_wind: float,
                x_ref: float | None = None, y_ref: float | None = None,
                color: QColor | None = None, axis: str = "X") -> int:
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

    def _make_value_item(self, value: float | None, axis_name: str) -> QTableWidgetItem:
        # Both value columns deliberately stay editable.  Typing the other
        # coordinate promotes a single-axis anchor to a known intersection.
        item = self._make_rw_item("" if value is None else self._fmt(value))
        other = "Y" if axis_name == "X" else "X"
        item.setToolTip(
            f"Known {axis_name} coordinate. Filling both {axis_name} and {other} "
            "automatically changes Axis to Both."
        )
        return item

    def _begin_value_edit(self, row: int, col: int) -> None:
        """A single click in a value cell should visibly open its editor."""
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
        # Do not rewrite the semantic role while the user has left an invalid
        # value in a cell.  Build will report that exact row and field.
        if not (x_valid and y_valid):
            return
        if x_present and y_present:
            axis = "Both"
        elif x_present:
            axis = "X"
        elif y_present:
            axis = "Y"
        else:
            return  # retain the intended role selected before the click
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

    def get_ref_data(self) -> list[tuple[float, float, float | None, float | None, str]]:
        result = []
        for r in range(self.rowCount()):
            try:
                axis = self.item(r, 1).text()
                xw = float(self.item(r, 2).text())
                yw = float(self.item(r, 3).text())
            except (ValueError, AttributeError) as exc:
                raise ValueError(
                    f"Calibration row {r + 1}: pixel coordinates must be numbers"
                ) from exc
            if not (math.isfinite(xw) and math.isfinite(yw)):
                raise ValueError(
                    f"Calibration row {r + 1}: pixel coordinates must be finite"
                )
            xr = self._optional_float(self.item(r, 4), row=r, field="X value")
            yr = self._optional_float(self.item(r, 5), row=r, field="Y value")
            result.append((xw, yw, xr, yr, axis))
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


class DataPointTable(_BasePointTable):
    """Table: # | x_wind | y_wind | x_fig | y_fig"""

    HEADERS = ["#", "x_wind", "y_wind", "x_fig", "y_fig"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(self.HEADERS, parent)
        self.cellChanged.connect(self._on_cell_changed)

    def add_row(self, x_wind: float, y_wind: float,
                x_fig: float = 0.0, y_fig: float = 0.0,
                color: QColor | None = None) -> int:
        self._updating = True
        row = self.rowCount()
        self.insertRow(row)
        num_item = self._make_ro_item(str(row + 1))
        if color is None:
            color = point_color(row)
        num_item.setBackground(QBrush(color))
        self.setItem(row, 0, num_item)
        self.setItem(row, 1, self._make_rw_item(self._fmt(x_wind)))
        self.setItem(row, 2, self._make_rw_item(self._fmt(y_wind)))
        self.setItem(row, 3, self._make_ro_item(self._fmt(x_fig)))
        self.setItem(row, 4, self._make_ro_item(self._fmt(y_fig)))
        self._updating = False
        return row

    def update_wind(self, row: int, x: float, y: float) -> None:
        if row < 0 or row >= self.rowCount():
            return
        self._updating = True
        self.item(row, 1).setText(self._fmt(x))
        self.item(row, 2).setText(self._fmt(y))
        self._updating = False

    def update_fig(self, row: int, x_fig: float, y_fig: float) -> None:
        if row < 0 or row >= self.rowCount():
            return
        self._updating = True
        self.item(row, 3).setText(self._fmt(x_fig))
        self.item(row, 4).setText(self._fmt(y_fig))
        self._updating = False

    def update_all_fig(self, calibration) -> None:
        self._updating = True
        for r in range(self.rowCount()):
            try:
                xw = float(self.item(r, 1).text())
                yw = float(self.item(r, 2).text())
                xf, yf = calibration.pixel_to_data(xw, yw)
                self.item(r, 3).setText(self._fmt(xf))
                self.item(r, 4).setText(self._fmt(yf))
            except Exception:
                self.item(r, 3).setText("?")
                self.item(r, 4).setText("?")
        self._updating = False

    def clear_fig_values(self) -> None:
        """Mark derived data coordinates stale while calibration is invalid."""
        self._updating = True
        for row in range(self.rowCount()):
            self.item(row, 3).setText("—")
            self.item(row, 4).setText("—")
        self._updating = False

    def _on_cell_changed(self, row: int, col: int) -> None:
        if self._updating:
            return
        if col in (1, 2):
            try:
                x = float(self.item(row, 1).text())
                y = float(self.item(row, 2).text())
                self.point_wind_changed.emit(row, x, y)
            except (ValueError, AttributeError):
                pass


class CropCornerTable(_BasePointTable):
    """Fixed 4-row table for crop rectangle corners.

    Row 0 = leftdown  (bottom-left)
    Row 1 = rightdown (bottom-right)
    Row 2 = leftup    (top-left)
    Row 3 = rightup   (top-right)
    """

    HEADERS = ["Corner", "x_wind", "y_wind"]
    CORNER_NAMES = ["leftdown", "rightdown", "leftup", "rightup"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(self.HEADERS, parent)
        self._updating = True
        for i, name in enumerate(self.CORNER_NAMES):
            self.insertRow(i)
            name_item = self._make_ro_item(name)
            name_item.setBackground(QBrush(point_color(i)))
            self.setItem(i, 0, name_item)
            self.setItem(i, 1, self._make_rw_item("0.0000"))
            self.setItem(i, 2, self._make_rw_item("0.0000"))
        self._updating = False
        self.cellChanged.connect(self._on_cell_changed)

    def update_corner(self, row: int, x: float, y: float) -> None:
        if row < 0 or row >= 4:
            return
        self._updating = True
        self.item(row, 1).setText(self._fmt(x))
        self.item(row, 2).setText(self._fmt(y))
        self._updating = False

    def update_corner_x(self, row: int, x: float) -> None:
        if row < 0 or row >= 4:
            return
        self._updating = True
        self.item(row, 1).setText(self._fmt(x))
        self._updating = False

    def update_corner_y(self, row: int, y: float) -> None:
        if row < 0 or row >= 4:
            return
        self._updating = True
        self.item(row, 2).setText(self._fmt(y))
        self._updating = False

    def _on_cell_changed(self, row: int, col: int) -> None:
        if self._updating:
            return
        if col in (1, 2):
            try:
                x = float(self.item(row, 1).text())
                y = float(self.item(row, 2).text())
                self.point_wind_changed.emit(row, x, y)
            except (ValueError, AttributeError):
                pass
