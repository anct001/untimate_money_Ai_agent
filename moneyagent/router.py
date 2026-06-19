"""LLMRouter — pick a provider for a task tier, with quota + fallback handling.

Resilience model (inspired by LiteLLM's router):
  * Tasks are tagged "light" (cheap, local-friendly) or "heavy" (stronger model).
  * Providers are tried in config order. The router skips any that are disabled,
    unavailable (no key / offline), over their daily request quota, in a
    cooldown window, rate-limited for the day, or auth-failed this session.
  * Transient errors (5xx / network) are retried with exponential backoff before
    falling back to the next provider.
  * Rate-limit (429) marks the provider spent for the day; auth errors disable it
    for the session; other failures put it in a short cooldown.
  * USD cost is estimated per call and a daily budget can hard-stop paid spend.
  * Identical requests can be served from an on-disk cache to conserve quota.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date

from .cache import PromptCache
from .config import Config
from .pricing import estimate_cost_usd
from .providers import Provider, build_provider
from .providers.base import (
    AuthError,
    CompletionResult,
    Message,
    ProviderError,
    RateLimitError,
    TransientError,
)
from .usage import UsageTracker

logger = logging.getLogger("moneyagent.router")

VALID_TIERS = ("light", "heavy")


@dataclass
class RouteAttempt:
    provider: str
    model: str
    ok: bool
    error: str | None = None


@dataclass
class _ProviderState:
    cooldown_until: float = 0.0
    rate_limited_day: str = ""   # ISO date the provider hit its rate limit
    disabled: bool = False       # auth failure this session


class NoProviderAvailable(RuntimeError):
    pass


class LLMRouter:
    def __init__(
        self,
        config: Config,
        usage: UsageTracker | None = None,
        *,
        max_retries: int = 2,
        backoff_base: float = 1.0,
        cooldown_seconds: float = 30.0,
        daily_budget_usd: float = 0.0,
        cache: PromptCache | None = None,
    ) -> None:
        self.config = config
        self.usage = usage or UsageTracker(config.data_dir / "usage.json")
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.cooldown_seconds = cooldown_seconds
        self.daily_budget_usd = daily_budget_usd
        self.cache = cache if cache is not None else PromptCache(config.data_dir / "cache.json")
        self.providers: list[Provider] = []
        for pcfg in config.providers:
            if not pcfg.get("enabled", True):
                continue
            try:
                self.providers.append(build_provider(pcfg))
            except (ValueError, KeyError) as exc:
                logger.warning("Skipping bad provider config %s: %s", pcfg.get("name"), exc)
        self.last_attempts: list[RouteAttempt] = []
        self._state: dict[str, _ProviderState] = {}

    # -- runtime state ---------------------------------------------------
    def _st(self, name: str) -> _ProviderState:
        if not hasattr(self, "_state"):  # tolerate __new__-built instances (tests)
            self._state = {}
        return self._state.setdefault(name, _ProviderState())

    @staticmethod
    def _today() -> str:
        return date.today().isoformat()

    def _skippable(self, provider: Provider) -> str | None:
        """Return a reason to skip this provider, or None if it's worth trying."""
        st = self._st(provider.name)
        if st.disabled:
            return "auth-disabled"
        if st.rate_limited_day == self._today():
            return "rate-limited today"
        if time.time() < st.cooldown_until:
            return "cooling down"
        if self.usage.at_limit(provider.name, provider.daily_request_limit):
            return "daily limit reached"
        if not provider.is_available():
            return "unavailable"
        return None

    # -- introspection ---------------------------------------------------
    def status(self) -> list[dict]:
        out = []
        for p in self.providers:
            out.append(
                {
                    "name": p.name,
                    "tiers": p.tiers,
                    "available": p.is_available(),
                    "requests_today": self.usage.count_today(p.name),
                    "daily_limit": p.daily_request_limit or "unlimited",
                    "cost_today_usd": self.usage.cost_today(p.name),
                    "skip_reason": self._skippable(p),
                }
            )
        return out

    def _candidates(self, tier: str) -> list[Provider]:
        return [p for p in self.providers if p.handles(tier)]

    # -- single provider call with retry --------------------------------
    def _call_with_retry(
        self, provider: Provider, model: str, messages, temperature, max_tokens
    ) -> CompletionResult:
        attempt = 0
        while True:
            try:
                return provider.complete(
                    messages, model, temperature=temperature, max_tokens=max_tokens
                )
            except TransientError as exc:
                if attempt >= self.max_retries:
                    raise
                delay = self.backoff_base * (2 ** attempt)
                logger.warning(
                    "%s transient error (retry %d/%d in %.1fs): %s",
                    provider.name, attempt + 1, self.max_retries, delay, exc,
                )
                time.sleep(delay)
                attempt += 1

    # -- core call -------------------------------------------------------
    def complete(
        self,
        messages: list[Message],
        *,
        tier: str = "light",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        use_cache: bool = True,
    ) -> CompletionResult:
        if tier not in VALID_TIERS:
            raise ValueError(f"tier must be one of {VALID_TIERS}, got {tier!r}")

        self.last_attempts = []
        msg_dicts = [m.as_dict() for m in messages]

        cache_key = None
        if use_cache and getattr(self, "cache", None) is not None and self.cache.enabled:
            cache_key = self.cache.key(msg_dicts, tier, temperature, max_tokens)
            cached = self.cache.get(cache_key)
            if cached is not None:
                logger.info("cache hit (tier=%s)", tier)
                return CompletionResult(text=cached, provider="cache", model="cache")

        if self.daily_budget_usd and self.usage.over_budget(self.daily_budget_usd):
            raise NoProviderAvailable(
                f"Daily budget ${self.daily_budget_usd} reached "
                f"(spent ${self.usage.cost_today()})."
            )

        candidates = self._candidates(tier)
        if not candidates:
            raise NoProviderAvailable(f"No provider configured for tier '{tier}'")

        for provider in candidates:
            model = provider.model_for(tier)
            skip = self._skippable(provider)
            if skip:
                self.last_attempts.append(RouteAttempt(provider.name, model or "?", False, skip))
                continue

            try:
                result = self._call_with_retry(
                    provider, model, messages, temperature, max_tokens
                )
            except RateLimitError as exc:
                self._st(provider.name).rate_limited_day = self._today()
                logger.warning("%s rate-limited; skipping for the day", provider.name)
                self.last_attempts.append(RouteAttempt(provider.name, model, False, f"429: {exc}"))
                continue
            except AuthError as exc:
                self._st(provider.name).disabled = True
                logger.warning("%s auth error; disabling for session", provider.name)
                self.last_attempts.append(RouteAttempt(provider.name, model, False, f"auth: {exc}"))
                continue
            except ProviderError as exc:
                self._st(provider.name).cooldown_until = time.time() + self.cooldown_seconds
                logger.warning(
                    "%s failed; cooldown %.0fs: %s", provider.name, self.cooldown_seconds, exc
                )
                self.last_attempts.append(RouteAttempt(provider.name, model, False, str(exc)))
                continue

            cost = estimate_cost_usd(model, result.prompt_tokens, result.completion_tokens)
            self.usage.record(provider.name, result.prompt_tokens, result.completion_tokens, cost)
            self._st(provider.name).cooldown_until = 0.0  # reset on success
            self.last_attempts.append(RouteAttempt(provider.name, model, True))
            logger.info("Routed tier=%s -> %s/%s (est $%.6f)", tier, provider.name, model, cost)
            if cache_key is not None:
                self.cache.set(cache_key, result.text)
            return result

        tried = ", ".join(f"{a.provider}({a.error})" for a in self.last_attempts)
        raise NoProviderAvailable(f"All providers failed for tier '{tier}': {tried}")

    def chat(self, prompt: str, *, system: str | None = None, tier: str = "light", **kw) -> str:
        messages: list[Message] = []
        if system:
            messages.append(Message("system", system))
        messages.append(Message("user", prompt))
        return self.complete(messages, tier=tier, **kw).text
