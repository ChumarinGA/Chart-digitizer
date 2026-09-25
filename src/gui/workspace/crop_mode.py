"""Crop-mode UI and interaction logic."""

from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from src.core.plot_area import detect_plot_area
from src.gui.overlays.crop_overlay import CropOverlay
from src.gui.overlays.point_overlay import DraggablePoint
from src.gui.tables.colors import point_color
from src.gui.tables.crop import CropCornerTable
from src.gui.workspace.contracts import HostBoundTool

_X_PAIR = {0: 2, 2: 0, 1: 3, 3: 1}
_Y_PAIR = {0: 1, 1: 0, 2: 3, 3: 2}


class CropMode(HostBoundTool):
    """Own the crop page, frame overlay and constrained corner editing."""

    def _build_crop_page(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        crop_guide = QLabel(
            "Set the four plot boundaries on the geometric centre-lines of the frame strokes. "
            "Auto-detection is a candidate only; open or rotated axes require manual verification."
        )
        crop_guide.setWordWrap(True)
        lay.addWidget(crop_guide)
        btn_auto = QPushButton("Auto-detect area")
        btn_auto.clicked.connect(self._crop_auto)
        lay.addWidget(btn_auto)
        btn_ok = QPushButton("Confirm area")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self._crop_confirm)
        lay.addWidget(btn_ok)

        self._crop_corner_table = CropCornerTable()
        self._configure_table(self._crop_corner_table)
        lay.addWidget(self._crop_corner_table, stretch=1)
        self._crop_corner_table.point_wind_changed.connect(self._crop_table_changed)
        self._crop_corner_table.key_move.connect(self._crop_key_move)

        lay.addWidget(QLabel("Crop overlay opacity:"))
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(0, 120)
        self._opacity_slider.setValue(30)
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        lay.addWidget(self._opacity_slider)

        self._crop_status = QLabel("")
        lay.addWidget(self._crop_status)
        lay.addStretch()
        self._stack.addWidget(page)

    def _is_within_crop(self, sx: float, sy: float) -> bool:
        r = self._project.crop_rect
        if r is None:
            return True
        x0, y0, w, h = r
        return x0 <= sx <= x0 + w and y0 <= sy <= y0 + h

    def _crop_bounds_rectf(self) -> Optional[QRectF]:
        r = self._project.crop_rect
        if r is None:
            return None
        x0, y0, w, h = r
        return QRectF(x0, y0, w, h)

    # ------------------------------------------------------------------
    # CROP — auto / confirm / overlay
    # ------------------------------------------------------------------

    def _crop_auto(self) -> None:
        if self._project.image is None:
            QMessageBox.warning(self._host, "Crop", "No image loaded.")
            return
        detected = detect_plot_area(self._project.image)
        if detected is None:
            h, w = self._project.image.shape[:2]
            rect = (0, 0, w, h)
        else:
            # OpenCV reports array-index centres (integer pixel 0 is its
            # centre); QPixmap scene coordinates place that centre at 0.5.
            rect = (detected[0] + 0.5, detected[1] + 0.5, detected[2], detected[3])
        self._show_crop_overlay(*rect)
        if self._calibration is not None:
            self._invalidate_calibration("Plot bounds changed — confirm them and rebuild calibration.")
        self._crop_status.setText(
            f"Candidate bounds: {rect[2]:.2f}×{rect[3]:.2f} "
            f"at ({rect[0]:.2f}, {rect[1]:.2f}). Verify all four sides at high zoom."
        )

    def _crop_confirm(self) -> None:
        previous_rect = self._project.crop_rect
        if self._crop_overlay:
            self._project.crop_rect = self._crop_overlay.get_rect()
        elif self._project.image is not None:
            h, w = self._project.image.shape[:2]
            self._show_crop_overlay(0.0, 0.0, float(w), float(h))
            self._project.crop_rect = self._crop_overlay.get_rect()
        else:
            return
        self._crop_confirmed = True
        if self._crop_overlay is None:
            return
        self._crop_overlay.set_confirmed_style(self._opacity_slider.value())
        self._update_all_point_bounds()
        r = self._project.crop_rect
        self._crop_status.setText(
            f"Confirmed centre-lines: {r[2]:.3f}×{r[3]:.3f} "
            f"at ({r[0]:.3f}, {r[1]:.3f})"
        )
        self._status.setText("Plot area set. Switch to Ref Points.")
        changed = (
            previous_rect is None
            or any(not math.isclose(a, b, abs_tol=1e-12)
                   for a, b in zip(previous_rect, self._project.crop_rect))
        )
        if changed and self._calibration is not None:
            self._invalidate_calibration("Plot frame changed — rebuild calibration.")

    def _show_crop_overlay(self, x: float, y: float, w: float, h: float) -> None:
        if self._crop_overlay:
            self._crop_overlay.set_rect(x, y, w, h)
            self._crop_overlay.set_editing_style()
            self._crop_overlay.set_interactive(False)
            self._crop_overlay.setVisible(True)
        else:
            self._crop_overlay = CropOverlay(x, y, w, h)
            self._crop_overlay.set_interactive(False)
            self._canvas.add_overlay(self._crop_overlay)
        self._crop_confirmed = False
        self._sync_crop_corners_from_rect(x, y, w, h)

    def _on_opacity_changed(self, value: int) -> None:
        if self._crop_overlay and self._crop_confirmed:
            # Later stages retain the yellow boundary only; filling the crop
            # would alter the apparent source colours under the loupe.
            self._crop_overlay.set_fill_opacity(
                value if self._stack.currentIndex() == 0 else 0
            )

    # ------------------------------------------------------------------
    # CROP — corner point system
    # ------------------------------------------------------------------

    def _sync_crop_corners_from_rect(self, x: float, y: float, w: float, h: float) -> None:
        """Create or reposition the 4 corner DraggablePoints from rect (x,y,w,h)."""
        positions = [
            (x, y + h),      # 0: leftdown / BL
            (x + w, y + h),  # 1: rightdown / BR
            (x, y),          # 2: leftup / TL
            (x + w, y),      # 3: rightup / TR
        ]

        if not self._crop_corners:
            for i, (cx, cy) in enumerate(positions):
                color = point_color(i)
                pt = DraggablePoint(cx, cy, color=color)
                self._configure_point(pt)
                self._register_point(pt)
                pt.set_precision_style(True)
                pt.position_changed.connect(
                    lambda px, py, idx=i: self._on_crop_corner_dragged(idx, px, py)
                )
                self._canvas.add_overlay(pt)
                self._crop_corners.append(pt)
        else:
            self._propagating_corner = True
            for i, (cx, cy) in enumerate(positions):
                self._crop_corners[i].set_pos_silent(cx, cy)
            self._propagating_corner = False

        self._propagating_corner = True
        for i, (cx, cy) in enumerate(positions):
            self._crop_corner_table.update_corner(i, cx, cy)
        self._propagating_corner = False

    def _on_crop_corner_dragged(self, idx: int, nx: float, ny: float) -> None:
        """A corner was dragged on the canvas; propagate edge constraints."""
        if self._propagating_corner:
            return
        self._propagating_corner = True

        self._crop_corner_table.update_corner(idx, nx, ny)

        xp = _X_PAIR[idx]
        self._crop_corners[xp].set_pos_silent(nx, self._crop_corners[xp].pos().y())
        self._crop_corner_table.update_corner_x(xp, nx)

        yp = _Y_PAIR[idx]
        self._crop_corners[yp].set_pos_silent(self._crop_corners[yp].pos().x(), ny)
        self._crop_corner_table.update_corner_y(yp, ny)

        self._rebuild_rect_from_corners()
        self._propagating_corner = False
        if 0 <= idx < len(self._crop_corners):
            self._refresh_loupe_if_active(self._crop_corners[idx])

    def _crop_table_changed(self, row: int, x: float, y: float) -> None:
        """A corner coordinate was edited in the table."""
        if self._propagating_corner or row < 0 or row >= 4:
            return
        if not self._crop_corners:
            return
        self._propagating_corner = True

        self._crop_corners[row].set_pos_silent(x, y)

        xp = _X_PAIR[row]
        self._crop_corners[xp].set_pos_silent(x, self._crop_corners[xp].pos().y())
        self._crop_corner_table.update_corner_x(xp, x)

        yp = _Y_PAIR[row]
        self._crop_corners[yp].set_pos_silent(self._crop_corners[yp].pos().x(), y)
        self._crop_corner_table.update_corner_y(yp, y)

        self._rebuild_rect_from_corners()
        self._propagating_corner = False
        self._refresh_loupe_if_active(self._crop_corners[row])

    def _crop_key_move(self, row: int, dx: float, dy: float) -> None:
        """Arrow key pressed while a corner row is selected."""
        if row < 0 or row >= 4 or not self._crop_corners:
            return
        pt = self._crop_corners[row]
        old = pt.pos()
        new_x, new_y = old.x() + dx, old.y() + dy
        self._on_crop_corner_dragged(row, new_x, new_y)
        pt.set_pos_silent(new_x, new_y)

    def _rebuild_rect_from_corners(self) -> None:
        """Recompute the CropOverlay rect from the 4 corner positions."""
        if len(self._crop_corners) < 4 or self._crop_overlay is None:
            return
        positions = [pt.pos() for pt in self._crop_corners]
        left = positions[0].x()
        right = positions[1].x()
        top = positions[2].y()
        bottom = positions[0].y()
        x = min(left, right)
        y = min(top, bottom)
        w = abs(right - left)
        h = abs(bottom - top)
        if w < 1:
            w = 1
        if h < 1:
            h = 1
        self._crop_overlay.set_rect(x, y, w, h)
        self._crop_confirmed = False
        self._crop_status.setText("Bounds modified — press Confirm area before calibration.")
        if self._calibration is not None:
            self._invalidate_calibration("Plot bounds changed — confirm them and rebuild calibration.")

    # ------------------------------------------------------------------
    # REFERENCE POINTS
    # ------------------------------------------------------------------
