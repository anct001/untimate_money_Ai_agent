"""Tool registry shared by the ReAct agent."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class Tool:
    name: str
    description: str  # one line: what it does + input format
    run: Callable[[str], str]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def describe(self) -> str:
        if not self._tools:
            return "(no tools available)"
        return "\n".join(f"- {t.name}: {t.description}" for t in self._tools.values())
