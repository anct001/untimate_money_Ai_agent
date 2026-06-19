"""Offline tests for the ReAct agent, tools and autopilot — no network."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from moneyagent.agent import ToolAgent, parse_react  # noqa: E402
from moneyagent.config import Config  # noqa: E402
from moneyagent.jobs import Autopilot, JobSpec  # noqa: E402
from moneyagent.providers.base import CompletionResult  # noqa: E402
from moneyagent.tools import default_registry  # noqa: E402
from moneyagent.tools.builtin import calculator  # noqa: E402


class ScriptedRouter:
    """A fake router that replays canned completions."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.daily_budget_usd = 0.0
        self.last_attempts = []

    def complete(self, messages, **kw):
        text = self._responses.pop(0) if self._responses else "FINAL: done"
        return CompletionResult(text=text, provider="scripted", model="x")

    def chat(self, prompt, *, system=None, tier="light", **kw):
        return self.complete([], tier=tier).text


# -- parser ----------------------------------------------------------------

def test_parse_react_action():
    out = parse_react("THOUGHT: think\nACTION: calculator\nACTION_INPUT: 2+2")
    assert out == {"action": "calculator", "input": "2+2"}


def test_parse_react_final():
    out = parse_react("THOUGHT: done\nFINAL: the answer is 4")
    assert out == {"final": "the answer is 4"}


def test_parse_react_fallback_to_final():
    out = parse_react("just some text with no markers")
    assert "final" in out


# -- tools -----------------------------------------------------------------

def test_calculator_ok():
    assert calculator("2 * (3 + 4)") == "14"


def test_calculator_rejects_code():
    assert calculator("__import__('os').system('ls')").startswith("ERROR")


def test_read_file_sandbox(tmp_path):
    (tmp_path / "ok.txt").write_text("hello", encoding="utf-8")
    reg = default_registry(workspace=tmp_path, allow_network=False)
    read_file = reg.get("read_file").run
    assert read_file("ok.txt") == "hello"
    assert read_file("../../etc/passwd").startswith("ERROR")


# -- ReAct loop ------------------------------------------------------------

def test_tool_agent_uses_tool():
    router = ScriptedRouter([
        "THOUGHT: I should compute\nACTION: calculator\nACTION_INPUT: 2+2",
        "THOUGHT: got it\nFINAL: The answer is 4.",
    ])
    reg = default_registry(workspace=None, allow_network=False)  # calculator only
    agent = ToolAgent(router, reg, max_steps=4)
    result = agent.run("what is 2+2?")
    assert result.answer == "The answer is 4."
    assert result.steps == 2
    assert any("OBSERVATION: 4" in line for line in result.transcript)


# -- autopilot -------------------------------------------------------------

def test_autopilot_run_once(tmp_path):
    cfg = Config(
        providers=[],
        paths={"data_dir": str(tmp_path / "data"), "output_dir": str(tmp_path / "out")},
        root=tmp_path,
    )
    router = ScriptedRouter(["a plan", "the drafted checklist"])
    pilot = Autopilot(cfg, router=router)
    spec = JobSpec(name="morning", workflow="chat", params={"task": "make a checklist"})
    path = pilot.run_once(spec)

    assert Path(path).exists()
    assert "checklist" in Path(path).read_text(encoding="utf-8")
    assert pilot.memory.recent(1)[0]["job"] == "morning"
