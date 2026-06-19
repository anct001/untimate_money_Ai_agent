"""Content workflow — drafts articles/blog posts/translations for client work.

Honest framing: this produces a *draft* to speed up real freelance delivery.
You review, fact-check and edit before sending to a client. It deliberately
does not auto-publish or mass-generate SEO spam.
"""
from __future__ import annotations

from .base import Workflow, WorkflowResult

REVIEW_DISCLAIMER = (
    "AI-generated draft. Fact-check claims, verify any statistics/quotes, and "
    "edit for voice before delivering to a client or publishing."
)


class ContentWorkflow(Workflow):
    name = "content"

    def run(  # type: ignore[override]
        self,
        *,
        topic: str,
        kind: str = "blog post",
        audience: str = "general readers",
        words: int = 600,
        tone: str = "clear and professional",
        language: str = "English",
    ) -> WorkflowResult:
        task = (
            f"Write a {kind} of about {words} words in {language}.\n"
            f"Topic: {topic}\n"
            f"Audience: {audience}\n"
            f"Tone: {tone}\n\n"
            "Requirements:\n"
            "- Use a clear structure with a strong opening and a short conclusion.\n"
            "- Be accurate; do NOT invent specific statistics, studies or quotes.\n"
            "- Where a factual claim would normally need a source, mark it "
            "[verify] so the human editor can check it.\n"
            "- Output clean Markdown."
        )
        result = self.agent.run(task, self_review=True)
        return WorkflowResult(
            title=f"{kind.title()}: {topic}",
            output=result.output,
            meta={"plan": result.plan, "words_target": words, "language": language},
            needs_human_review=True,
            disclaimer=REVIEW_DISCLAIMER,
        )
