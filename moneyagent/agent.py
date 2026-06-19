"""A small, honest agent loop: plan -> draft -> self-critique -> finalize.

This is deliberately simple and synchronous. It uses the cheap tier for
planning/critique and the heavy tier for the main generation, so most of the
token spend lands on free local/quota-friendly models.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .providers.base import Message
from .router import LLMRouter

logger = logging.getLogger("moneyagent.agent")


@dataclass
class AgentResult:
    output: str
    plan: str = ""
    critique: str = ""
    steps: list[str] = field(default_factory=list)


class Agent:
    def __init__(self, router: LLMRouter, system_prompt: str | None = None) -> None:
        self.router = router
        self.system_prompt = system_prompt or (
            "You are a careful, honest assistant. You do real, lawful work. "
            "If a task asks for deception, spam, or anything that violates a "
            "platform's terms, you refuse and explain why."
        )

    def _ask(self, prompt: str, *, tier: str, max_tokens: int = 1500) -> str:
        return self.router.chat(
            prompt, system=self.system_prompt, tier=tier, max_tokens=max_tokens
        ).strip()

    def run(self, task: str, *, self_review: bool = True) -> AgentResult:
        steps: list[str] = []

        # 1) Plan (cheap tier).
        plan = self._ask(
            f"Break this task into a short, concrete plan (max 5 bullet points). "
            f"Do not do the task yet.\n\nTASK:\n{task}",
            tier="light",
            max_tokens=400,
        )
        steps.append("planned")

        # 2) Execute (heavy tier for quality).
        draft = self._ask(
            f"Complete the task fully and concretely. Follow this plan.\n\n"
            f"PLAN:\n{plan}\n\nTASK:\n{task}",
            tier="heavy",
            max_tokens=2000,
        )
        steps.append("drafted")

        if not self_review:
            return AgentResult(output=draft, plan=plan, steps=steps)

        # 3) Self-critique (cheap tier).
        critique = self._ask(
            "Critique the draft below for correctness, completeness and tone. "
            "List concrete fixes only. If it is already good, say 'NO CHANGES'.\n\n"
            f"TASK:\n{task}\n\nDRAFT:\n{draft}",
            tier="light",
            max_tokens=500,
        )
        steps.append("critiqued")

        if "NO CHANGES" in critique.upper():
            return AgentResult(output=draft, plan=plan, critique=critique, steps=steps)

        # 4) Revise (heavy tier).
        final = self._ask(
            f"Revise the draft applying the fixes. Output only the final result.\n\n"
            f"FIXES:\n{critique}\n\nDRAFT:\n{draft}",
            tier="heavy",
            max_tokens=2000,
        )
        steps.append("revised")
        return AgentResult(output=final, plan=plan, critique=critique, steps=steps)


# --------------------------------------------------------------------------
# Tool-using ReAct agent (provider-agnostic: works via prompting, so even a
# small local model with no native function-calling can drive tools).
# --------------------------------------------------------------------------

REACT_SYSTEM = """You are a careful, honest agent that can use tools to do real, lawful work.

Available tools:
{tools}

Work in a loop. Each turn output EXACTLY ONE of these two blocks, nothing else:

THOUGHT: <your reasoning>
ACTION: <one tool name from the list>
ACTION_INPUT: <the input string for that tool>

— or, when you have the answer —

THOUGHT: <your reasoning>
FINAL: <the complete answer for the user>

Rules: use real tool output, never invent it. Refuse spam, deception, or anything
that violates a platform's terms. Keep going until you can give FINAL."""


@dataclass
class ToolAgentResult:
    answer: str
    transcript: list[str] = field(default_factory=list)
    steps: int = 0


def parse_react(text: str) -> dict:
    """Parse one ReAct turn into {'final': str} or {'action','input'}."""
    if "FINAL:" in text:
        return {"final": text.split("FINAL:", 1)[1].strip()}

    action = input_ = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("ACTION:"):
            action = stripped.split(":", 1)[1].strip()
        elif stripped.upper().startswith("ACTION_INPUT:"):
            input_ = line.split(":", 1)[1].strip()
    if action is not None:
        return {"action": action, "input": input_ or ""}
    return {"final": text.strip()}  # model didn't follow format; treat as answer


class ToolAgent:
    def __init__(self, router: LLMRouter, registry, *, max_steps: int = 6, tier: str = "heavy"):
        self.router = router
        self.registry = registry
        self.max_steps = max_steps
        self.tier = tier
        self.system_prompt = REACT_SYSTEM.format(tools=registry.describe())

    def run(self, task: str) -> ToolAgentResult:
        messages = [Message("system", self.system_prompt), Message("user", f"TASK: {task}")]
        transcript: list[str] = []

        for step in range(1, self.max_steps + 1):
            reply = self.router.complete(
                messages, tier=self.tier, max_tokens=900, temperature=0.3
            ).text.strip()
            transcript.append(reply)
            parsed = parse_react(reply)

            if "final" in parsed:
                return ToolAgentResult(answer=parsed["final"], transcript=transcript, steps=step)

            tool = self.registry.get(parsed["action"])
            if tool is None:
                observation = (
                    f"ERROR: unknown tool '{parsed['action']}'. "
                    f"Choose from: {self.registry.names()}"
                )
            else:
                try:
                    observation = tool.run(parsed["input"])
                except Exception as exc:  # noqa: BLE001 - feed the error back to the model
                    observation = f"ERROR running {tool.name}: {exc}"

            messages.append(Message("assistant", reply))
            messages.append(Message("user", f"OBSERVATION: {observation}"))
            transcript.append(f"OBSERVATION: {observation}")

        # Out of steps: ask for a best-effort final answer.
        messages.append(Message("user", "Stop using tools. Give your FINAL answer now."))
        final = self.router.complete(messages, tier=self.tier, max_tokens=900).text.strip()
        answer = parse_react(final).get("final", final)
        transcript.append(final)
        return ToolAgentResult(answer=answer, transcript=transcript, steps=self.max_steps)
