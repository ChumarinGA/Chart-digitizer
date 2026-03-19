"""Main application window — simplified for manual-first workflow."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QToolBar,
    QWidget,
)

from src.gui.image_canvas import ImageCanvas
from src.gui.mode_panel import ModePanel
from src.gui.start_screen import StartScreen
from src.models.project_data import ProjectState


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Chart Digitizer")
        self.resize(1400, 850)

        self._project = ProjectState()

        # --- Start screen ---
        self._start_screen = StartScreen()
        self._start_screen.file_selected.connect(self._on_file_selected)

        # --- Workspace ---
        self._workspace = QWidget()
        self._canvas = ImageCanvas()
        self._panel = ModePanel(self._project, self._canvas)

        ws = QHBoxLayout(self._workspace)
        ws.setContentsMargins(0, 0, 0, 0)
        ws.addWidget(self._canvas, stretch=3)
        ws.addWidget(self._panel, stretch=1)

        self._workspace.setVisible(False)
        self.setCentralWidget(self._start_screen)

        # --- Toolbar ---
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        tb.addAction("Open").triggered.connect(self._open_file)
        tb.addSeparator()

        self._act_settings = tb.addAction("Settings")
        self._act_settings.triggered.connect(self._open_settings)

        self._act_save_proj = tb.addAction("Save project")
        self._act_save_proj.triggered.connect(self._save_project)

        self._act_load_proj = tb.addAction("Load project")
        self._act_load_proj.triggered.connect(self._load_project)

        # --- Status bar ---
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._canvas.mouse_moved.connect(self._update_status)

    # ---- file handling ----

    @Slot(str)
    def _on_file_selected(self, path: str) -> None:
        self._load_image(Path(path))

    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open chart image", "",
            "Images (*.png *.jpg *.jpeg);;All files (*)",
        )
        if path:
            self._load_image(Path(path))

    def _load_image(self, path: Path) -> None:
        import cv2
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            QMessageBox.warning(self, "Error", f"Cannot read image:\n{path}")
            return

        self._project = ProjectState(image_path=path, image=img)
        self._canvas.set_image(path)
        self._panel.set_project(self._project)

        self._start_screen.setVisible(False)
        self.setCentralWidget(self._workspace)
        self._workspace.setVisible(True)
        self._status.showMessage(f"Loaded: {path.name}")

    # ---- status bar ----

    @Slot(float, float)
    def _update_status(self, px: float, py: float) -> None:
        msg = f"Pixel: ({px:.1f}, {py:.1f})"
        try:
            cal = self._project.calibration
            if cal.x_axis._slope is not None:
                dx, dy = cal.pixel_to_data(px, py)
                msg += f"  |  Data: ({dx:.4g}, {dy:.4g})"
        except Exception:
            pass
        self._status.showMessage(msg)

    # ---- settings / project ----

    def _open_settings(self) -> None:
        from src.gui.settings_dialog import SettingsDialog
        SettingsDialog(self._project.settings, self).exec()

    def _save_project(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project", "", "Digitizer project (*.digitizer);;All (*)",
        )
        if path:
            from src.core.project import save_project
            try:
                save_project(self._project, Path(path))
                self._status.showMessage(f"Project saved: {path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _load_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load project", "", "Digitizer project (*.digitizer);;All (*)",
        )
        if path:
            from src.core.project import load_project
            try:
                state = load_project(Path(path))
                if state.image_path and state.image_path.exists():
                    import cv2
                    state.image = cv2.imread(str(state.image_path), cv2.IMREAD_COLOR)
                    self._canvas.set_image(state.image_path)
                self._project = state
                self._panel.set_project(state)
                self._start_screen.setVisible(False)
                self.setCentralWidget(self._workspace)
                self._workspace.setVisible(True)
                self._status.showMessage(f"Project loaded: {path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))
