"""Data-page coordination shared by Scatter and Curve modes."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QRadioButton, QStackedWidget, QVBoxLayout, QWidget

from src.gui.workspace.contracts import HostBoundTool


class DataMode(HostBoundTool):
    """Route canvas clicks and visibility to the active data sub-mode."""

    def _build_data_page(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)

        # Sub-mode toggle
        submode_row = QHBoxLayout()
        self._rb_scatter = QRadioButton("Scatter")
        self._rb_curve = QRadioButton("Curve")
        self._rb_scatter.setChecked(True)
        submode_row.addWidget(self._rb_scatter)
        submode_row.addWidget(self._rb_curve)
        lay.addLayout(submode_row)

        self._data_submode_stack = QStackedWidget()
        lay.addWidget(self._data_submode_stack, stretch=1)

        self._build_scatter_subpage()
        self._build_curve_subpage()

        self._rb_scatter.toggled.connect(self._on_data_submode_toggled)

        self._stack.addWidget(page)

    def _on_data_submode_toggled(self, scatter_checked: bool) -> None:
        self._data_submode_stack.setCurrentIndex(0 if scatter_checked else 1)
        if self._stack.currentIndex() == 2:
            self._refresh_data_visibility()
            self._sync_active_point_for_mode()

    def _is_scatter_mode(self) -> bool:
        return self._data_submode_stack.currentIndex() == 0

    # ------------------------------------------------------------------
    # style dialog (scatter only)
    # ------------------------------------------------------------------

    def _refresh_data_visibility(self) -> None:
        is_scatter = self._is_scatter_mode()

        # Scatter points: visible only in scatter sub-mode, active tab only
        si = self._active_series_index()
        for i, pts_list in enumerate(self._series_points):
            vis = is_scatter and (i == si)
            for pt in pts_list:
                pt.setVisible(vis)

        # Curve points and paths: visible only in curve sub-mode, active tab only
        ci = self._active_curve_index()
        for i, pts_list in enumerate(self._curve_points):
            vis = (not is_scatter) and (i == ci)
            for pt in pts_list:
                pt.setVisible(vis)
        for i, path in enumerate(self._curve_paths):
            path.setVisible((not is_scatter) and (i == ci))

    # ------------------------------------------------------------------
    # active-point precision tools
    # ------------------------------------------------------------------

    def _on_canvas_click(self, sx: float, sy: float) -> None:
        mode = self._stack.currentIndex()
        if mode in (1, 2):
            if not self._crop_confirmed:
                self._status.setText("Confirm the plot boundaries on the Crop tab first.")
                return
            if not self._is_within_crop(sx, sy):
                return
        if mode == 1:
            self._add_ref_point(sx, sy)
        elif mode == 2:
            if self._is_scatter_mode():
                self._add_data_point(sx, sy)
            else:
                self._add_curve_point(sx, sy)
