"""Provider abstraction shared by every backend."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class ProviderError(RuntimeError):
    """Raised when a provider call fails (network, auth, quota, bad response)."""


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str

    def as_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class CompletionResult:
    text: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: dict = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class Provider(ABC):
    """A single LLM backend.

    Subclasses talk to one service (or class of services). The router treats
    them uniformly: pick a model for a task tier, then call ``complete``.
    """

    def __init__(
        self,
        name: str,
        models: dict[str, str],
        tiers: list[str],
        daily_request_limit: int = 0,
    ) -> None:
        self.name = name
        self.models = models  # tier -> model id
        self.tiers = tiers
        self.daily_request_limit = daily_request_limit

    def model_for(self, tier: str) -> str | None:
        return self.models.get(tier)

    def handles(self, tier: str) -> bool:
        return tier in self.tiers and self.model_for(tier) is not None

    @abstractmethod
    def is_available(self) -> bool:
        """Cheap check: is this provider configured/reachable enough to try?"""

    @abstractmethod
    def complete(
        self,
        messages: list[Message],
        model: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        timeout: int = 120,
    ) -> CompletionResult:
        """Run a chat completion. Raise ProviderError on failure."""
