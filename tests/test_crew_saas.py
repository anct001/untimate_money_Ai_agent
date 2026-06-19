"""Offline tests for the crew and SaaS request handler."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from moneyagent.crew import Crew  # noqa: E402
from moneyagent.providers.base import CompletionResult  # noqa: E402
from moneyagent.workflows.saas_automation import ServiceRequest, process_request  # noqa: E402


class ScriptedRouter:
    def __init__(self, responses):
        self._responses = list(responses)
        self.last_attempts = []

    def complete(self, messages, **kw):
        text = self._responses.pop(0) if self._responses else "done"
        return CompletionResult(text=text, provider="scripted", model="x")

    def chat(self, prompt, *, system=None, tier="light", **kw):
        return self.complete([], tier=tier).text


def test_crew_runs_roles_and_synthesizes():
    router = ScriptedRouter(["research view", "skeptic view", "SYNTHESIS"])
    crew = Crew.from_names(router, ["researcher", "skeptic"])
    result = crew.run("should we launch X?")
    assert set(result.perspectives) == {"researcher", "skeptic"}
    assert result.perspectives["researcher"] == "research view"
    assert result.synthesis == "SYNTHESIS"


def test_crew_unknown_role():
    router = ScriptedRouter([])
    try:
        Crew.from_names(router, ["nope"])
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown role")


def test_saas_process_request():
    router = ScriptedRouter(["a plan", "THE SUMMARY"])
    out = process_request(ServiceRequest("summarize", "long text here"), router)
    assert out["job"] == "summarize"
    assert out["output"] == "THE SUMMARY"


def test_saas_unknown_job():
    router = ScriptedRouter([])
    try:
        process_request(ServiceRequest("nonexistent", "x"), router)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown job")
