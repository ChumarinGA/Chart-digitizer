"""Regression tests for editing calibration-anchor values.

The axis label is derived from the values that are present.  Both value
columns must remain directly editable: an anchor initially created for one
axis can later be promoted to a known X/Y intersection without recreating it.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication

from src.gui.point_table import RefPointTable


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _x_anchor_table() -> RefPointTable:
    table = RefPointTable()
    table.add_row(10.0, 20.0, x_ref=3.0, axis="X")
    return table


def test_unused_y_value_of_x_anchor_is_blank_and_editable(qapp: QApplication) -> None:
    """The previously disabled cell must accept keyboard focus and editing."""

    table = _x_anchor_table()
    y_value = table.item(0, 5)

    assert y_value.text() == ""
    assert y_value.flags() & Qt.ItemFlag.ItemIsEnabled
    assert y_value.flags() & Qt.ItemFlag.ItemIsSelectable
    assert y_value.flags() & Qt.ItemFlag.ItemIsEditable

    table.resize(700, 180)
    table.show()
    qapp.processEvents()
    QTest.mouseClick(
        table.viewport(),
        Qt.MouseButton.LeftButton,
        pos=table.visualItemRect(y_value).center(),
    )
    assert table.state() == QAbstractItemView.State.EditingState
    table.close()


def test_entering_y_value_promotes_x_anchor_before_change_signal(
    qapp: QApplication,
) -> None:
    """Signal observers must see an already-updated ``Both`` model row."""

    table = _x_anchor_table()
    snapshots: list[tuple[float, float, float | None, float | None, str]] = []
    table.ref_value_changed.connect(lambda: snapshots.append(table.get_ref_data()[0]))
    signal_spy = QSignalSpy(table.ref_value_changed)

    table.item(0, 5).setText("4.25")

    assert signal_spy.count() == 1
    assert table.item(0, 1).text() == "Both"
    assert table.get_ref_data() == [(10.0, 20.0, 3.0, 4.25, "Both")]
    assert snapshots == [(10.0, 20.0, 3.0, 4.25, "Both")]


def test_clearing_y_value_downgrades_both_anchor_before_change_signal(
    qapp: QApplication,
) -> None:
    """Removing the second value must restore the remaining single-axis role."""

    table = _x_anchor_table()
    table.item(0, 5).setText("4.25")
    assert table.item(0, 1).text() == "Both"

    snapshots: list[tuple[float, float, float | None, float | None, str]] = []
    table.ref_value_changed.connect(lambda: snapshots.append(table.get_ref_data()[0]))
    signal_spy = QSignalSpy(table.ref_value_changed)

    table.item(0, 5).setText("")

    assert signal_spy.count() == 1
    assert table.item(0, 1).text() == "X"
    assert table.get_ref_data() == [(10.0, 20.0, 3.0, None, "X")]
    assert snapshots == [(10.0, 20.0, 3.0, None, "X")]


def test_x_value_of_y_anchor_is_editable_and_promotes_to_both(
    qapp: QApplication,
) -> None:
    table = RefPointTable()
    table.add_row(10.0, 20.0, y_ref=7.0, axis="Y")

    x_value = table.item(0, 4)
    assert x_value.text() == ""
    assert x_value.flags() & Qt.ItemFlag.ItemIsEditable

    x_value.setText("2.5")

    assert table.item(0, 1).text() == "Both"
    assert table.get_ref_data() == [(10.0, 20.0, 2.5, 7.0, "Both")]


def test_clearing_x_value_downgrades_both_anchor_to_y(qapp: QApplication) -> None:
    table = RefPointTable()
    table.add_row(10.0, 20.0, x_ref=2.5, y_ref=7.0, axis="Both")

    table.item(0, 4).setText("")

    assert table.item(0, 1).text() == "Y"
    assert table.get_ref_data() == [(10.0, 20.0, None, 7.0, "Y")]


def test_invalid_or_nonfinite_value_is_reported_and_does_not_change_role(
    qapp: QApplication,
) -> None:
    table = _x_anchor_table()
    table.item(0, 5).setText("nan")

    assert table.item(0, 1).text() == "X"
    with pytest.raises(ValueError, match=r"row 1: Y value must be finite"):
        table.get_ref_data()
