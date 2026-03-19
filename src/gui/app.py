"""Application entry point — creates QApplication and shows MainWindow."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

_STYLE_PATH = Path(__file__).resolve().parent.parent.parent / "resources" / "styles" / "dark.qss"


def run_application(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv
    app = QApplication(argv)
    app.setApplicationName("Chart Digitizer")
    app.setOrganizationName("ChartDigitizer")

    if _STYLE_PATH.exists():
        app.setStyleSheet(_STYLE_PATH.read_text(encoding="utf-8"))

    from src.gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()
