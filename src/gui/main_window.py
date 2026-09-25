"""Main application window — simplified for manual-first workflow."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QWidget,
)

from src.gui.image_canvas import ImageCanvas
from src.gui.start_screen import StartScreen
from src.gui.workspace.panel import ModePanel
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
        self._workspace_active = False

        ws = QHBoxLayout(self._workspace)
        ws.setContentsMargins(0, 0, 0, 0)
        ws.addWidget(self._canvas)

        # A real QMainWindow dock gives the control panel desktop-editor
        # behaviour: its inner edge is draggable, closing it gives all space
        # back to the canvas, and the native title-bar button can float/re-dock
        # it as a separate window.  The scroll area keeps every control
        # reachable on short displays and while the dock is narrow.
        self._panel_scroll = QScrollArea()
        self._panel_scroll.setObjectName("modePanelScroll")
        self._panel_scroll.setWidgetResizable(True)
        self._panel_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._panel_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._panel_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._panel_scroll.setWidget(self._panel)

        self._panel_dock = QDockWidget("Digitization tools", self)
        self._panel_dock.setObjectName("modePanelDock")
        self._panel_dock.setToolTip(
            "Drag the inner border to resize. Use the title-bar buttons to float or hide."
        )
        self._panel_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._panel_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self._panel_dock.setWidget(self._panel_scroll)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._panel_dock)
        self._panel_dock.hide()

        # Keep both pages owned by one permanent central widget.  Replacing a
        # QMainWindow central widget can schedule the previous page for
        # deletion, which made later image/project loads unsafe.
        self._central_stack = QStackedWidget()
        self._central_stack.addWidget(self._start_screen)
        self._central_stack.addWidget(self._workspace)
        self._central_stack.setCurrentWidget(self._start_screen)
        self.setCentralWidget(self._central_stack)

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

        tb.addSeparator()
        self._act_panel = self._panel_dock.toggleViewAction()
        self._act_panel.setText("Panel")
        self._act_panel.setShortcut("Ctrl+B")
        self._act_panel.setToolTip("Show or completely hide the tools panel")
        self._act_panel.setEnabled(False)
        tb.addAction(self._act_panel)

        self._act_detach_panel = tb.addAction("Detach panel")
        self._act_detach_panel.setCheckable(True)
        self._act_detach_panel.setEnabled(False)
        self._act_detach_panel.setToolTip(
            "Move the tools into a separate window; toggle again to dock it on the right"
        )
        self._act_detach_panel.toggled.connect(self._set_panel_floating)
        self._panel_dock.topLevelChanged.connect(self._on_panel_top_level_changed)

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

        self._enter_workspace()
        self._status.showMessage(f"Loaded: {path.name}")

    def _enter_workspace(self) -> None:
        """Show the canvas and enable the dockable tools after loading data."""
        first_entry = not self._workspace_active
        self._central_stack.setCurrentWidget(self._workspace)
        self._workspace_active = True
        self._act_panel.setEnabled(True)
        self._act_detach_panel.setEnabled(True)
        if first_entry:
            self._panel_dock.show()
            # A useful first width without imposing a permanent min/max.  From
            # here on the user controls it by dragging the dock boundary.
            preferred = max(420, min(620, self.width() // 2))
            self.resizeDocks(
                [self._panel_dock], [preferred], Qt.Orientation.Horizontal
            )

    @Slot(bool)
    def _set_panel_floating(self, floating: bool) -> None:
        """Toolbar counterpart to the dock's native float/re-dock button."""
        if not self._workspace_active:
            return
        if floating:
            self._panel_dock.show()
            self._panel_dock.setFloating(True)
        else:
            self._panel_dock.setFloating(False)
            if (
                self.dockWidgetArea(self._panel_dock)
                == Qt.DockWidgetArea.NoDockWidgetArea
            ):
                self.addDockWidget(
                    Qt.DockWidgetArea.RightDockWidgetArea, self._panel_dock
                )
            self._panel_dock.show()

    @Slot(bool)
    def _on_panel_top_level_changed(self, floating: bool) -> None:
        previous = self._act_detach_panel.blockSignals(True)
        self._act_detach_panel.setChecked(floating)
        self._act_detach_panel.setText("Dock panel" if floating else "Detach panel")
        self._act_detach_panel.blockSignals(previous)

    # ---- status bar ----

    @Slot(float, float)
    def _update_status(self, px: float, py: float) -> None:
        msg = f"Pixel: ({px:.1f}, {py:.1f})"
        try:
            cal = self._project.calibration
            if cal.is_built:
                dx, dy = cal.pixel_to_data(px, py)
                msg += f"  |  Data: ({dx:.4g}, {dy:.4g})"
        except Exception:
            pass
        self._status.showMessage(msg)

    # ---- settings / project ----

    def _open_settings(self) -> None:
        from src.gui.dialogs.settings import SettingsDialog
        SettingsDialog(self._project.settings, self).exec()
        self._panel.apply_settings()

    def _save_project(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project", "", "Digitizer project (*.digitizer);;All (*)",
        )
        if path:
            from src.core.project import save_project
            try:
                self._panel.sync_project_state()
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
                self._enter_workspace()
                self._status.showMessage(f"Project loaded: {path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))
