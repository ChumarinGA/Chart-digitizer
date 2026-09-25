"""Compatibility checks for the dialog module split."""

from src.gui.curve_style_dialog import CurveStyleDialog as LegacyCurveStyleDialog
from src.gui.dialogs import CurveStyleDialog, PointStyleDialog, SettingsDialog
from src.gui.dialogs.curve_style import CurveStyleDialog as ModularCurveStyleDialog
from src.gui.dialogs.point_style import PointStyleDialog as ModularPointStyleDialog
from src.gui.dialogs.settings import SettingsDialog as ModularSettingsDialog
from src.gui.settings_dialog import SettingsDialog as LegacySettingsDialog
from src.gui.style_dialog import PointStyleDialog as LegacyPointStyleDialog


def test_legacy_dialog_imports_are_exact_aliases() -> None:
    assert LegacyPointStyleDialog is PointStyleDialog is ModularPointStyleDialog
    assert LegacyCurveStyleDialog is CurveStyleDialog is ModularCurveStyleDialog
    assert LegacySettingsDialog is SettingsDialog is ModularSettingsDialog
