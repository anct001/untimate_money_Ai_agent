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
