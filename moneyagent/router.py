"""LLMRouter — pick a provider for a task tier, with quota + fallback handling.

Strategy:
  * Tasks are tagged "light" (cheap, local-friendly) or "heavy" (needs a
    stronger model).
  * Providers are tried in config order. The router skips any that are
    disabled, unavailable (no key / offline), or over their daily quota.
  * On a provider error it falls back to the next candidate. Usage is recorded
    so free-tier limits are respected across runs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import Config
from .providers import Provider, build_provider
from .providers.base import CompletionResult, Message, ProviderError
from .usage import UsageTracker

logger = logging.getLogger("moneyagent.router")

VALID_TIERS = ("light", "heavy")


@dataclass
class RouteAttempt:
    provider: str
    model: str
    ok: bool
    error: str | None = None


class NoProviderAvailable(RuntimeError):
    pass


class LLMRouter:
    def __init__(self, config: Config, usage: UsageTracker | None = None) -> None:
        self.config = config
        self.usage = usage or UsageTracker(config.data_dir / "usage.json")
        self.providers: list[Provider] = []
        for pcfg in config.providers:
            if not pcfg.get("enabled", True):
                continue
            try:
                self.providers.append(build_provider(pcfg))
            except (ValueError, KeyError) as exc:
                logger.warning("Skipping bad provider config %s: %s", pcfg.get("name"), exc)
        self.last_attempts: list[RouteAttempt] = []

    # -- introspection ---------------------------------------------------
    def status(self) -> list[dict]:
        """Report each provider's availability and quota usage."""
        out = []
        for p in self.providers:
            used = self.usage.count_today(p.name)
            out.append(
                {
                    "name": p.name,
                    "tiers": p.tiers,
                    "available": p.is_available(),
                    "requests_today": used,
                    "daily_limit": p.daily_request_limit or "unlimited",
                    "at_limit": self.usage.at_limit(p.name, p.daily_request_limit),
                }
            )
        return out

    def _candidates(self, tier: str) -> list[Provider]:
        return [p for p in self.providers if p.handles(tier)]

    # -- core call -------------------------------------------------------
    def complete(
        self,
        messages: list[Message],
        *,
        tier: str = "light",
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> CompletionResult:
        if tier not in VALID_TIERS:
            raise ValueError(f"tier must be one of {VALID_TIERS}, got {tier!r}")

        self.last_attempts = []
        candidates = self._candidates(tier)
        if not candidates:
            raise NoProviderAvailable(f"No provider configured for tier '{tier}'")

        for provider in candidates:
            model = provider.model_for(tier)
            if self.usage.at_limit(provider.name, provider.daily_request_limit):
                self.last_attempts.append(
                    RouteAttempt(provider.name, model or "?", False, "daily limit reached")
                )
                continue
            if not provider.is_available():
                self.last_attempts.append(
                    RouteAttempt(provider.name, model or "?", False, "unavailable")
                )
                continue

            try:
                result = provider.complete(
                    messages, model, temperature=temperature, max_tokens=max_tokens
                )
                self.usage.record(provider.name, result.prompt_tokens, result.completion_tokens)
                self.last_attempts.append(RouteAttempt(provider.name, model, True))
                logger.info("Routed tier=%s -> %s/%s", tier, provider.name, model)
                return result
            except ProviderError as exc:
                logger.warning("Provider %s failed, falling back: %s", provider.name, exc)
                self.last_attempts.append(RouteAttempt(provider.name, model, False, str(exc)))
                continue

        tried = ", ".join(f"{a.provider}({a.error})" for a in self.last_attempts)
        raise NoProviderAvailable(f"All providers failed for tier '{tier}': {tried}")

    def chat(self, prompt: str, *, system: str | None = None, tier: str = "light", **kw) -> str:
        """Convenience wrapper returning just the text."""
        messages: list[Message] = []
        if system:
            messages.append(Message("system", system))
        messages.append(Message("user", prompt))
        return self.complete(messages, tier=tier, **kw).text
