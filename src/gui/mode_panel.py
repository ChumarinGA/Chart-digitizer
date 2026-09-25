"""Backward-compatible import for the workspace panel.

The implementation lives in :mod:`src.gui.workspace.panel`.  Keeping this
module allows existing integrations to continue importing ``ModePanel`` from
its historical location.
"""

from src.gui.workspace.panel import ModePanel

__all__ = ["ModePanel"]
