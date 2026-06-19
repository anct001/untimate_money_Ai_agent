"""Workflow base class."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..agent import Agent
from ..router import LLMRouter


@dataclass
class WorkflowResult:
    title: str
    output: str
    meta: dict = field(default_factory=dict)
    # Set when a human must review/approve before the result is used externally.
    needs_human_review: bool = True
    disclaimer: str = ""


class Workflow(ABC):
    name: str = "workflow"

    def __init__(self, router: LLMRouter, agent: Agent | None = None) -> None:
        self.router = router
        self.agent = agent or Agent(router)

    @abstractmethod
    def run(self, **kwargs) -> WorkflowResult:
        ...
