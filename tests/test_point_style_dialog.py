from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from src.gui.style_dialog import PointStyleDialog


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_active_fill_opacity_has_faint_default(qapp: QApplication) -> None:
    dialog = PointStyleDialog()

    assert dialog.current_active_fill_opacity() == 15


def test_active_fill_opacity_setter_is_silent_by_default(
    qapp: QApplication,
) -> None:
    dialog = PointStyleDialog()
    spy = QSignalSpy(dialog.active_fill_opacity_changed)

    dialog.set_active_fill_opacity(40)

    assert dialog.current_active_fill_opacity() == 40
    assert spy.count() == 0


def test_active_fill_opacity_setter_can_emit(qapp: QApplication) -> None:
    dialog = PointStyleDialog()
    spy = QSignalSpy(dialog.active_fill_opacity_changed)

    dialog.set_active_fill_opacity(35, emit=True)

    assert spy.count() == 1
    assert spy.at(0) == [35]


@pytest.mark.parametrize(("requested", "expected"), [(-10, 0), (110, 100)])
def test_active_fill_opacity_is_clamped(
    qapp: QApplication,
    requested: int,
    expected: int,
) -> None:
    dialog = PointStyleDialog()

    dialog.set_active_fill_opacity(requested)

    assert dialog.current_active_fill_opacity() == expected
