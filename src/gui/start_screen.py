"""Start / welcome screen with drag-and-drop and file-open button."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class StartScreen(QWidget):
    file_selected = Signal(str)

    _SUPPORTED = {".png", ".jpg", ".jpeg"}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Chart Digitizer")
        title.setStyleSheet("font-size: 28px; font-weight: bold; margin-bottom: 16px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        hint = QLabel("Drag and drop a chart image here\nor click the button below")
        hint.setStyleSheet("font-size: 15px; color: #aaaaaa; margin-bottom: 24px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        btn = QPushButton("Open image file")
        btn.setObjectName("primary")
        btn.setFixedWidth(220)
        btn.clicked.connect(self._open_dialog)
        layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self._drop_label = QLabel("")
        self._drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_label.setStyleSheet("color: #ff6666; margin-top: 12px;")
        layout.addWidget(self._drop_label)

    # ---- drag & drop ----

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in self._SUPPORTED:
                self.file_selected.emit(str(path))
                return
        self._drop_label.setText("Unsupported file format. Use PNG or JPEG.")

    def _open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open chart image", "",
            "Images (*.png *.jpg *.jpeg);;All files (*)",
        )
        if path:
            self.file_selected.emit(path)
