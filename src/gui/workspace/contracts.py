"""Contracts shared by the tools composing the workspace editor.

A tool owns one area of behaviour.  The panel owns the shared Qt widgets and
live editor state so every tool observes the same point collections and signal
order.  ``HostBoundTool`` is the small adapter between those responsibilities.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class WorkspaceHost(Protocol):
    """Minimal structural marker for the panel hosting workspace tools."""

    _project: Any
    _canvas: Any


class HostBoundTool:
    """Composition adapter forwarding shared workspace state to its host.

    Behaviour belongs to the concrete tool object. Reads and writes of widget
    and state attributes are forwarded to preserve one owner and a predictable
    Qt signal order.
    """

    __slots__ = ("_host",)

    def __init__(self, host: WorkspaceHost) -> None:
        object.__setattr__(self, "_host", host)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._host, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_host":
            object.__setattr__(self, name, value)
            return
        setattr(self._host, name, value)
