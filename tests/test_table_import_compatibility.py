"""Compatibility checks for the point-table module split."""

from src.gui import point_table as legacy
from src.gui.tables import (
    BasePointTable,
    CropCornerTable,
    DataPointTable,
    POINT_PALETTE,
    RefPointTable,
    point_color,
)
from src.gui.tables.base import _BasePointTable
from src.gui.tables.colors import POINT_PALETTE as MODULAR_POINT_PALETTE
from src.gui.tables.crop import CropCornerTable as ModularCropCornerTable
from src.gui.tables.data import DataPointTable as ModularDataPointTable
from src.gui.tables.reference import RefPointTable as ModularRefPointTable


def test_legacy_point_table_imports_are_exact_aliases() -> None:
    assert legacy.RefPointTable is RefPointTable is ModularRefPointTable
    assert legacy.DataPointTable is DataPointTable is ModularDataPointTable
    assert legacy.CropCornerTable is CropCornerTable is ModularCropCornerTable
    assert legacy._BasePointTable is _BasePointTable is BasePointTable
    assert legacy.point_color is point_color
    assert legacy.POINT_PALETTE is POINT_PALETTE is MODULAR_POINT_PALETTE


def test_modular_tables_keep_the_common_base_class() -> None:
    assert issubclass(RefPointTable, BasePointTable)
    assert issubclass(DataPointTable, BasePointTable)
    assert issubclass(CropCornerTable, BasePointTable)
