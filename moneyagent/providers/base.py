"""Provider abstraction shared by every backend."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class ProviderError(RuntimeError):
    """Raised when a provider call fails (network, auth, quota, bad response)."""


class RateLimitError(ProviderError):
    """HTTP 429 / quota exhausted. Router marks the provider spent for the day."""


class AuthError(ProviderError):
    """HTTP 401/403 / bad key. Router disables the provider for the session."""


class TransientError(ProviderError):
    """Network/timeout/5xx. Router retries with backoff before falling back."""


def error_for_status(name: str, status: int, body: str) -> ProviderError:
    """Map an HTTP status code to the right ProviderError subclass."""
    msg = f"{name}: HTTP {status}: {body[:300]}"
    if status == 429:
        return RateLimitError(msg)
    if status in (401, 403):
        return AuthError(msg)
    if status >= 500:
        return TransientError(msg)
    return ProviderError(msg)


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
