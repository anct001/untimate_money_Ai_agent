"""Multi-agent 'crew': several role-prompted agents tackle a task, then a
synthesizer merges their perspectives into one answer.

Inspired by CrewAI / ai-hedge-fund's analyst personas. Analytical and honest by
design — roles critique and cross-check each other, which tends to catch errors
a single pass misses. Light tier is used for individual roles to conserve quota;
the synthesis runs on the heavy tier.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .providers.base import Message
from .router import LLMRouter


@dataclass
class Role:
    name: str
    instructions: str
    tier: str = "light"


# A few reusable personas. Mix and match per task.
ROLE_LIBRARY: dict[str, Role] = {
    "researcher": Role(
        "researcher",
        "Gather the key facts and considerations relevant to the task. Be concrete "
        "and flag anything uncertain with [verify].",
    ),
    "skeptic": Role(
        "skeptic",
        "Challenge assumptions. List the strongest objections, risks and failure "
        "modes. Be specific, not generic.",
    ),
    "strategist": Role(
        "strategist",
        "Propose a concrete, actionable plan with prioritized steps and trade-offs.",
    ),
    "risk": Role(
        "risk",
        "Focus only on risks, downside scenarios and what could go wrong. Quantify "
        "where possible. Never give a buy/sell instruction for financial tasks.",
        tier="light",
    ),
}


@dataclass
class CrewResult:
    synthesis: str
    perspectives: dict[str, str] = field(default_factory=dict)


class Crew:
    def __init__(self, router: LLMRouter, roles: list[Role], *, synth_tier: str = "heavy"):
        if not roles:
            raise ValueError("Crew needs at least one role")
        self.router = router
        self.roles = roles
        self.synth_tier = synth_tier

    @classmethod
    def from_names(cls, router: LLMRouter, names: list[str], **kw) -> Crew:
        roles = []
        for n in names:
            role = ROLE_LIBRARY.get(n.strip())
            if role is None:
                raise ValueError(f"Unknown role '{n}'. Known: {sorted(ROLE_LIBRARY)}")
            roles.append(role)
        return cls(router, roles, **kw)

    def run(self, task: str) -> CrewResult:
        perspectives: dict[str, str] = {}
        for role in self.roles:
            system = (
                f"You are the {role.name}. {role.instructions} "
                "Do real, lawful analysis. Keep it concise."
            )
            perspectives[role.name] = self.router.chat(
                f"TASK:\n{task}", system=system, tier=role.tier, max_tokens=700
            ).strip()

        combined = "\n\n".join(f"### {name}\n{view}" for name, view in perspectives.items())
        messages = [
            Message(
                "system",
                "You are the lead synthesizer. Merge the team's perspectives into one "
                "clear, balanced answer. Resolve disagreements explicitly and keep any "
                "[verify] flags. Do not fabricate facts.",
            ),
            Message("user", f"TASK:\n{task}\n\nTEAM PERSPECTIVES:\n{combined}"),
        ]
        synthesis = self.router.complete(messages, tier=self.synth_tier, max_tokens=1200).text.strip()
        return CrewResult(synthesis=synthesis, perspectives=perspectives)
