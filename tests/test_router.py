"""Offline tests for routing, fallback, quota, retry, cost — no network."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from moneyagent.cache import PromptCache  # noqa: E402
from moneyagent.config import Config  # noqa: E402
from moneyagent.providers.base import (  # noqa: E402
    AuthError,
    CompletionResult,
    Message,
    Provider,
    ProviderError,
    RateLimitError,
    TransientError,
)
from moneyagent.router import LLMRouter, NoProviderAvailable  # noqa: E402
from moneyagent.usage import UsageTracker  # noqa: E402


class FakeProvider(Provider):
    """In-memory provider for tests."""

    def __init__(self, name, *, available=True, raises=None, fail_times=0,
                 models=None, **kw):
        super().__init__(
            name,
            models=models or {"light": "m-l", "heavy": "m-h"},
            tiers=["light", "heavy"],
            **kw,
        )
        self._available = available
        self._raises = raises          # exception class to raise (or None)
        self._fail_times = fail_times  # raise for the first N calls, then succeed
        self.calls = 0

    def is_available(self):
        return self._available

    def complete(self, messages, model, **kw):
        self.calls += 1
        if self._fail_times and self.calls <= self._fail_times:
            raise (self._raises or TransientError)(f"{self.name}: transient")
        if self._raises is not None and not self._fail_times:
            raise self._raises(f"{self.name}: forced {self._raises.__name__}")
        return CompletionResult(
            text=f"{self.name}:{model}", provider=self.name, model=model,
            prompt_tokens=10, completion_tokens=20,
        )


def make_router(tmp_path, providers, **kw):
    cfg = Config(providers=[], paths={"data_dir": str(tmp_path)}, root=Path(tmp_path))
    kw.setdefault("backoff_base", 0.0)  # don't actually sleep in tests
    kw.setdefault("cache", PromptCache(Path(tmp_path) / "cache.json", enabled=False))
    router = LLMRouter(cfg, usage=UsageTracker(Path(tmp_path) / "usage.json"), **kw)
    router.providers = providers
    return router


def test_routes_to_first_available(tmp_path):
    a, b = FakeProvider("a"), FakeProvider("b")
    router = make_router(tmp_path, [a, b])
    out = router.complete([Message("user", "hi")], tier="light")
    assert out.provider == "a"
    assert a.calls == 1 and b.calls == 0


def test_falls_back_on_failure(tmp_path):
    a = FakeProvider("a", raises=ProviderError)
    b = FakeProvider("b")
    router = make_router(tmp_path, [a, b])
    out = router.complete([Message("user", "hi")], tier="heavy")
    assert out.provider == "b"
    assert a.calls == 1 and b.calls == 1


def test_skips_unavailable(tmp_path):
    a, b = FakeProvider("a", available=False), FakeProvider("b")
    router = make_router(tmp_path, [a, b])
    out = router.complete([Message("user", "hi")], tier="light")
    assert out.provider == "b"
    assert a.calls == 0


def test_respects_daily_limit(tmp_path):
    a = FakeProvider("a", daily_request_limit=2)
    b = FakeProvider("b")
    router = make_router(tmp_path, [a, b])
    router.complete([Message("user", "1")], tier="light")
    router.complete([Message("user", "2")], tier="light")
    out = router.complete([Message("user", "3")], tier="light")
    assert out.provider == "b"
    assert a.calls == 2


def test_retries_transient_then_succeeds(tmp_path):
    a = FakeProvider("a", raises=TransientError, fail_times=2)
    router = make_router(tmp_path, [a], max_retries=2)
    out = router.complete([Message("user", "hi")], tier="light")
    assert out.provider == "a"
    assert a.calls == 3  # 2 transient + 1 success


def test_rate_limit_marks_provider_for_the_day(tmp_path):
    a = FakeProvider("a", raises=RateLimitError)
    b = FakeProvider("b")
    router = make_router(tmp_path, [a, b])
    out1 = router.complete([Message("user", "1")], tier="light")
    assert out1.provider == "b"
    a.calls = 0
    out2 = router.complete([Message("user", "2")], tier="light")
    assert out2.provider == "b"
    assert a.calls == 0  # skipped, not retried


def test_auth_error_disables_provider(tmp_path):
    a = FakeProvider("a", raises=AuthError)
    b = FakeProvider("b")
    router = make_router(tmp_path, [a, b])
    router.complete([Message("user", "1")], tier="light")
    a.calls = 0
    router.complete([Message("user", "2")], tier="light")
    assert a.calls == 0  # disabled for the session


def test_cost_is_recorded(tmp_path):
    a = FakeProvider("a", models={"light": "gpt-4o-mini", "heavy": "gpt-4o"})
    router = make_router(tmp_path, [a])
    router.complete([Message("user", "hi")], tier="light")
    assert router.usage.cost_today("a") > 0
    assert router.usage.cost_today() > 0


def test_daily_budget_blocks(tmp_path):
    a = FakeProvider("a", models={"light": "gpt-4o", "heavy": "gpt-4o"})
    router = make_router(tmp_path, [a], daily_budget_usd=0.0001)
    router.complete([Message("user", "1")], tier="light")
    try:
        router.complete([Message("user", "2")], tier="light")
    except NoProviderAvailable as exc:
        assert "budget" in str(exc).lower()
    else:
        raise AssertionError("expected budget block")


def test_cache_hit_skips_provider(tmp_path):
    a = FakeProvider("a")
    router = make_router(
        tmp_path, [a], cache=PromptCache(Path(tmp_path) / "c.json", enabled=True)
    )
    first = router.complete([Message("user", "same")], tier="light")
    second = router.complete([Message("user", "same")], tier="light")
    assert first.provider == "a"
    assert second.provider == "cache"
    assert a.calls == 1  # second served from cache


def test_raises_when_all_fail(tmp_path):
    a = FakeProvider("a", raises=ProviderError)
    b = FakeProvider("b", raises=ProviderError)
    router = make_router(tmp_path, [a, b])
    try:
        router.complete([Message("user", "hi")], tier="light")
    except NoProviderAvailable:
        pass
    else:
        raise AssertionError("expected NoProviderAvailable")


def test_invalid_tier(tmp_path):
    router = make_router(tmp_path, [FakeProvider("a")])
    try:
        router.complete([Message("user", "hi")], tier="bogus")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
