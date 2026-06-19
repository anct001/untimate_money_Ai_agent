"""SaaS automation scaffold — turn the agent into a billable HTTP service.

The monetization model here is honest: build a tool that solves a specific,
repetitive job for a customer (e.g. "turn raw notes into a polished summary",
"draft replies to support tickets"), expose it as an API/app, and charge a
subscription. This module gives you the request->agent->response core; you add
auth, billing (Stripe), rate limiting and a UI on top.

FastAPI is optional. `process_request` works with zero web deps so you can also
wire it into a queue, a cron job, or a CLI.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..agent import Agent
from ..config import load_config
from ..router import LLMRouter


@dataclass
class ServiceRequest:
    job: str           # which automation to run, e.g. "summarize", "reply_draft"
    input_text: str
    instructions: str = ""


# Define the concrete jobs your SaaS sells. Keep them narrow and reliable.
JOB_PROMPTS: dict[str, str] = {
    "summarize": "Summarize the input into clear bullet points and a one-line TL;DR.",
    "reply_draft": (
        "Draft a polite, professional reply to the input message. Keep it concise. "
        "Do not make promises or commitments on the user's behalf; leave [placeholders] "
        "where the human must decide."
    ),
    "rewrite": "Rewrite the input to be clearer and more concise, preserving meaning.",
}


def process_request(req: ServiceRequest, router: LLMRouter | None = None) -> dict:
    if req.job not in JOB_PROMPTS:
        raise ValueError(f"Unknown job '{req.job}'. Known: {sorted(JOB_PROMPTS)}")

    router = router or LLMRouter(load_config())
    agent = Agent(router)
    task = (
        f"{JOB_PROMPTS[req.job]}\n\n"
        f"Extra instructions: {req.instructions or '(none)'}\n\n"
        f"INPUT:\n{req.input_text}"
    )
    result = agent.run(task, self_review=False)
    return {
        "job": req.job,
        "output": result.output,
        "route": [a.provider for a in router.last_attempts if a.ok],
    }


def create_app():  # pragma: no cover - exercised only when FastAPI is installed
    """Build a FastAPI app exposing the jobs. `pip install fastapi uvicorn`."""
    try:
        from fastapi import FastAPI, HTTPException
        from pydantic import BaseModel
    except ImportError as exc:
        raise RuntimeError("pip install fastapi uvicorn to serve the SaaS app") from exc

    app = FastAPI(title="moneyagent automation", version="0.1.0")
    router = LLMRouter(load_config())

    class JobIn(BaseModel):
        job: str
        input_text: str
        instructions: str = ""

    @app.get("/health")
    def health():
        return {"status": "ok", "jobs": sorted(JOB_PROMPTS)}

    @app.post("/v1/run")
    def run(body: JobIn):
        try:
            return process_request(
                ServiceRequest(body.job, body.input_text, body.instructions), router
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return app
