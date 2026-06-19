"""SaaS automation scaffold — turn the agent into a billable HTTP service.

The monetization model here is honest: build a tool that solves a specific,
repetitive job for a customer (e.g. "turn raw notes into a polished summary",
"draft replies to support tickets"), expose it as an API/app, and charge a
subscription. This module gives you the request->agent->response core; you add
auth, billing (Stripe), rate limiting and a UI on top.

FastAPI is optional. `process_request` works with zero web deps so you can also
wire it into a queue, a cron job, or a CLI.

NOTE: this module intentionally does NOT use `from __future__ import annotations`.
FastAPI must resolve the Pydantic request models at runtime, and stringized
(deferred) annotations on models defined in a local scope break that resolution.
"""
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
    """Build a FastAPI app exposing the jobs, with API-key auth, per-plan quotas,
    rate limiting and an optional Stripe checkout endpoint.

    `pip install fastapi uvicorn` (and `stripe` if you enable billing).
    """
    try:
        from fastapi import Depends, FastAPI, Header, HTTPException, Request
        from fastapi.responses import HTMLResponse
        from pydantic import BaseModel
    except ImportError as exc:
        raise RuntimeError("pip install fastapi uvicorn to serve the SaaS app") from exc

    import os

    from ..billing import (
        PLANS,
        KeyStore,
        UsageMeter,
        construct_webhook_event,
        create_checkout_session,
        handle_checkout_completed,
    )
    from .landing import render_landing

    cfg = load_config()
    cfg.ensure_dirs()
    router = LLMRouter(cfg)
    keystore = KeyStore.from_env_or_file(cfg.data_dir / "api_keys.json")
    meter = UsageMeter(cfg.data_dir / "saas_usage.json")

    app = FastAPI(title="moneyagent automation", version="0.2.0")

    if any(rec.get("label") == "auto-dev" for rec in keystore.keys.values()):
        dev_key = next(iter(keystore.keys))
        print(f"[moneyagent] No API keys configured. Dev key (pro plan): {dev_key}")

    class JobIn(BaseModel):
        job: str
        input_text: str
        instructions: str = ""

    class SignupIn(BaseModel):
        email: str = ""

    class CheckoutIn(BaseModel):
        plan: str
        success_url: str
        cancel_url: str

    def authenticate(x_api_key: str = Header(default="")):
        rec = keystore.verify(x_api_key)
        if rec is None:
            raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")
        plan = PLANS.get(rec["plan"], PLANS["free"])
        if meter.rate_limited(x_api_key, plan["rate_per_minute"]):
            raise HTTPException(status_code=429, detail="rate limit exceeded")
        if meter.over_monthly_limit(x_api_key, plan["monthly_requests"]):
            raise HTTPException(status_code=402, detail="monthly plan limit reached; upgrade plan")
        return x_api_key, rec

    @app.get("/", response_class=HTMLResponse)
    def landing():
        return render_landing(PLANS, sorted(JOB_PROMPTS))

    @app.get("/health")
    def health():
        return {"status": "ok", "jobs": sorted(JOB_PROMPTS), "plans": sorted(PLANS)}

    @app.post("/v1/signup")
    def signup(body: SignupIn):
        # Self-serve free tier: instantly issue a key. No payment required.
        key = keystore.add("free", label="signup", email=body.email or None)
        return {"api_key": key, "plan": "free", "limits": PLANS["free"]}

    @app.post("/v1/run")
    def run(body: JobIn, auth=Depends(authenticate)):
        key, _rec = auth
        try:
            result = process_request(
                ServiceRequest(body.job, body.input_text, body.instructions), router
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        meter.record(key)
        return result

    @app.get("/v1/usage")
    def usage(auth=Depends(authenticate)):
        key, rec = auth
        plan = PLANS.get(rec["plan"], PLANS["free"])
        return {
            "plan": rec["plan"],
            "used_this_month": meter.count_month(key),
            "monthly_limit": plan["monthly_requests"],
        }

    @app.post("/v1/checkout")
    def checkout(body: CheckoutIn, auth=Depends(authenticate)):
        key, _rec = auth  # the buyer's existing (free) key; webhook upgrades it
        try:
            return create_checkout_session(
                body.plan, body.success_url, body.cancel_url, client_reference_id=key
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/webhook")
    async def stripe_webhook(request: Request, stripe_signature: str = Header(default="")):
        secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
        payload = await request.body()
        try:
            event = construct_webhook_event(payload, stripe_signature, secret)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        upgraded = handle_checkout_completed(event, keystore)
        return {"received": True, "upgraded": bool(upgraded)}

    return app
