"""Billing & metering for the SaaS workflow.

Honest, incremental monetization for the SaaS path:
  * API-key auth with per-key plans (self-serve signup issues a free key).
  * Monthly request quotas per plan (persisted) + a simple per-minute rate limit.
  * Optional Stripe Checkout + webhook that auto-upgrades a key's plan on payment.

Nothing here makes network calls unless you explicitly call a Stripe helper with
a configured key, so it's safe to import and test offline. Stripe is opt-in:
set STRIPE_API_KEY (+ STRIPE_WEBHOOK_SECRET) only when you're ready to charge.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from collections import deque
from datetime import datetime
from pathlib import Path

# plan name -> limits / price. Tune to your offering.
PLANS: dict[str, dict] = {
    "free": {"monthly_requests": 100, "rate_per_minute": 5, "price_usd": 0},
    "starter": {"monthly_requests": 2_000, "rate_per_minute": 30, "price_usd": 19},
    "pro": {"monthly_requests": 20_000, "rate_per_minute": 120, "price_usd": 99},
}


def generate_key() -> str:
    return "ma-" + secrets.token_urlsafe(24)


class KeyStore:
    """Maps API keys to {'plan': ..., 'label': ..., 'email'?: ...}.

    File-backed (provisioned/upgraded keys persist). Keys supplied via the
    MONEYAGENT_API_KEYS env var are overlaid at load time but not written back.
    """

    def __init__(self, keys: dict[str, dict] | None = None, path: Path | None = None) -> None:
        self.keys = keys or {}
        self.path = Path(path) if path else None

    @classmethod
    def from_env_or_file(cls, path: Path | None = None) -> KeyStore:
        keys: dict[str, dict] = {}
        if path and Path(path).exists():
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8"))
                for key, rec in data.items():
                    rec.setdefault("plan", "free")
                    keys[key] = rec
            except (json.JSONDecodeError, OSError):
                pass

        env = os.getenv("MONEYAGENT_API_KEYS", "").strip()
        if env:
            for pair in env.split(","):
                if ":" in pair:
                    key, plan = (x.strip() for x in pair.split(":", 1))
                    keys[key] = {"plan": plan if plan in PLANS else "free", "label": "env"}

        if not keys:
            dev = generate_key()
            keys[dev] = {"plan": "pro", "label": "auto-dev"}
        return cls(keys, path)

    def verify(self, key: str) -> dict | None:
        return self.keys.get((key or "").strip())

    def save(self) -> None:
        """Persist provisioned keys (skip ephemeral env/auto-dev entries)."""
        if not self.path:
            return
        persist = {k: v for k, v in self.keys.items() if v.get("label") not in ("env", "auto-dev")}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(persist, indent=2), encoding="utf-8")

    def add(self, plan: str = "free", *, label: str = "signup", email: str | None = None) -> str:
        key = generate_key()
        rec = {"plan": plan if plan in PLANS else "free", "label": label}
        if email:
            rec["email"] = email
        self.keys[key] = rec
        self.save()
        return key

    def set_plan(self, key: str, plan: str) -> bool:
        if key in self.keys and plan in PLANS:
            self.keys[key]["plan"] = plan
            self.save()
            return True
        return False


class UsageMeter:
    """Per-key monthly request counts (persisted) + in-memory per-minute window."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._counts = self._load()
        self._recent: dict[str, deque] = {}

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._counts, indent=2), encoding="utf-8")

    @staticmethod
    def _month() -> str:
        return datetime.now().strftime("%Y-%m")

    def count_month(self, key: str) -> int:
        return self._counts.get(key, {}).get(self._month(), 0)

    def record(self, key: str) -> None:
        month = self._month()
        self._counts.setdefault(key, {})
        self._counts[key][month] = self._counts[key].get(month, 0) + 1
        self._save()

    def over_monthly_limit(self, key: str, limit: int) -> bool:
        return limit > 0 and self.count_month(key) >= limit

    def rate_limited(self, key: str, per_minute: int) -> bool:
        if per_minute <= 0:
            return False
        now = time.time()
        window = self._recent.setdefault(key, deque())
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= per_minute:
            return True
        window.append(now)
        return False


# --- Stripe helpers (opt-in; importing stripe lazily) ---------------------

def create_checkout_session(
    plan: str,
    success_url: str,
    cancel_url: str,
    client_reference_id: str | None = None,
) -> dict:
    """Create a Stripe Checkout session for a plan. Requires STRIPE_API_KEY.

    `client_reference_id` (the buyer's existing API key) is echoed back by the
    webhook so we know which key to upgrade. Raises if Stripe isn't configured.
    """
    if plan not in PLANS:
        raise ValueError(f"Unknown plan '{plan}'. Known: {sorted(PLANS)}")
    if PLANS[plan]["price_usd"] <= 0:
        raise ValueError("free plan does not require checkout; use /v1/signup")
    api_key = os.getenv("STRIPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("STRIPE_API_KEY not set; billing is disabled.")
    try:
        import stripe
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pip install stripe to enable checkout") from exc

    stripe.api_key = api_key
    session = stripe.checkout.Session.create(
        mode="subscription",
        client_reference_id=client_reference_id,
        metadata={"plan": plan},
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"moneyagent {plan}"},
                "unit_amount": PLANS[plan]["price_usd"] * 100,
                "recurring": {"interval": "month"},
            },
            "quantity": 1,
        }],
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return {"url": session.url, "id": session.id}


def construct_webhook_event(payload: bytes, sig_header: str, secret: str) -> dict:
    """Verify and parse a Stripe webhook. Requires the signing secret."""
    if not secret:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET not set")
    try:
        import stripe
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pip install stripe to verify webhooks") from exc
    return stripe.Webhook.construct_event(payload, sig_header, secret)


def handle_checkout_completed(event: dict, keystore: KeyStore) -> str | None:
    """On 'checkout.session.completed', upgrade the buyer's key to the paid plan.

    Pure function over the event dict, so it's unit-testable without Stripe.
    Returns the upgraded key, or None if the event isn't actionable.
    """
    if event.get("type") != "checkout.session.completed":
        return None
    obj = event.get("data", {}).get("object", {})
    key = obj.get("client_reference_id")
    plan = (obj.get("metadata") or {}).get("plan", "starter")
    if key and keystore.verify(key) and keystore.set_plan(key, plan):
        return key
    return None
