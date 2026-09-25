"""Public file API for Chart Digitizer project sessions."""

from __future__ import annotations

import json
from pathlib import Path

from src.core.project.deserialization import _deserialise
from src.core.project.serialization import _serialise
from src.models.project_data import ProjectState


PROJECT_EXT = ".digitizer"


def save_project(state: ProjectState, path: Path) -> None:
    data = _serialise(state)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )


def load_project(path: Path) -> ProjectState:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _deserialise(raw)


__all__ = ["PROJECT_EXT", "load_project", "save_project"]
