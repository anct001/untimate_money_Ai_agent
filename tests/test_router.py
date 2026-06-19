"""Offline tests for routing, fallback and quota — no network required."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from moneyagent.config import Config  # noqa: E402
from moneyagent.providers.base import CompletionResult, Message, Provider, ProviderError  # noqa: E402
from moneyagent.router import LLMRouter, NoProviderAvailable  # noqa: E402
from moneyagent.usage import UsageTracker  # noqa: E402


class FakeProvider(Provider):
    """In-memory provider for tests."""

    def __init__(self, name, *, available=True, fail=False, **kw):
        super().__init__(name, models={"light": "m-l", "heavy": "m-h"}, tiers=["light", "heavy"], **kw)
        self._available = available
        self._fail = fail
        self.calls = 0

    def is_available(self):
        return self._available

    def complete(self, messages, model, **kw):
        self.calls += 1
        if self._fail:
            raise ProviderError(f"{self.name}: forced failure")
        return CompletionResult(text=f"{self.name}:{model}", provider=self.name, model=model,
                                prompt_tokens=1, completion_tokens=1)


def make_router(tmp_path, providers):
    cfg = Config(providers=[], paths={"data_dir": str(tmp_path)}, root=tmp_path)
    router = LLMRouter.__new__(LLMRouter)
    router.config = cfg
    router.usage = UsageTracker(Path(tmp_path) / "usage.json")
    router.providers = providers
    router.last_attempts = []
    return router


def test_routes_to_first_available(tmp_path):
    a, b = FakeProvider("a"), FakeProvider("b")
    router = make_router(tmp_path, [a, b])
    out = router.complete([Message("user", "hi")], tier="light")
    assert out.provider == "a"
    assert a.calls == 1 and b.calls == 0


def test_falls_back_on_failure(tmp_path):
    a, b = FakeProvider("a", fail=True), FakeProvider("b")
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
    out = router.complete([Message("user", "3")], tier="light")  # a now at limit
    assert out.provider == "b"
    assert a.calls == 2


def test_raises_when_all_fail(tmp_path):
    a, b = FakeProvider("a", fail=True), FakeProvider("b", fail=True)
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
