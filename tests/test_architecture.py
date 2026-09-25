"""Small dependency checks that keep the documented module boundaries intact."""

from __future__ import annotations

import ast
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
        elif isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
    return result


def _python_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.py"))


def test_models_do_not_depend_on_core_or_gui() -> None:
    forbidden: list[tuple[Path, str]] = []
    for path in _python_files(SRC / "models"):
        for module in _imports(path):
            if module.startswith(("src.core", "src.gui")):
                forbidden.append((path, module))
    assert forbidden == []


def test_core_does_not_depend_on_gui() -> None:
    forbidden: list[tuple[Path, str]] = []
    for path in _python_files(SRC / "core"):
        for module in _imports(path):
            if module.startswith("src.gui"):
                forbidden.append((path, module))
    assert forbidden == []


def test_new_gui_code_does_not_import_compatibility_facades() -> None:
    facades = {
        "src.gui.curve_style_dialog",
        "src.gui.mode_panel",
        "src.gui.point_table",
        "src.gui.settings_dialog",
        "src.gui.style_dialog",
    }
    offenders: list[tuple[Path, str]] = []
    facade_files = {
        "curve_style_dialog.py",
        "mode_panel.py",
        "point_table.py",
        "settings_dialog.py",
        "style_dialog.py",
    }
    for path in _python_files(SRC / "gui"):
        if path.name in facade_files:
            continue
        for module in _imports(path):
            if module in facades:
                offenders.append((path, module))
    assert offenders == []
