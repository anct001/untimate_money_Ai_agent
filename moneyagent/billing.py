"""Billing & metering for the SaaS workflow.

Honest, incremental monetization for the SaaS path:
  * API-key auth with per-key plans.
  * Monthly request quotas per plan (persisted) + a simple per-minute rate limit.
  * Optional Stripe checkout — the service runs free (no Stripe) in dev, and you
    flip on charging by setting STRIPE_API_KEY when you're ready.

Nothing here makes network calls unless you explicitly call the Stripe helper
with a configured key, so it's safe to import and test offline.
"""
from __future__ import annotations

import json
import os
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


class KeyStore:
    """Maps API keys to {'plan': ..., 'label': ...}."""

    def __init__(self, keys: dict[str, dict] | None = None) -> None:
        self.keys = keys or {}

    @classmethod
    def from_env_or_file(cls, path: Path | None = None) -> KeyStore:
        """Load keys from MONEYAGENT_API_KEYS env ("key:plan,key2:plan") or a JSON file.

        If neither is set, mint a single dev key so the service is usable locally.
        """
        keys: dict[str, dict] = {}
        env = os.getenv("MONEYAGENT_API_KEYS", "").strip()
        if env:
            for pair in env.split(","):
                if ":" in pair:
                    key, plan = pair.split(":", 1)
                    key, plan = key.strip(), plan.strip()
                    keys[key] = {"plan": plan if plan in PLANS else "free", "label": "env"}
        elif path and Path(path).exists():
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            for key, rec in data.items():
                rec.setdefault("plan", "free")
                keys[key] = rec

        if not keys:
            dev_key = "dev-" + os.urandom(6).hex()
            keys[dev_key] = {"plan": "pro", "label": "auto-dev"}
        return cls(keys)

    def verify(self, key: str) -> dict | None:
        return self.keys.get((key or "").strip())


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


def create_checkout_session(plan: str, success_url: str, cancel_url: str) -> dict:
    """Create a Stripe Checkout session for a plan. Requires STRIPE_API_KEY.

    Returns {'url': ...} to redirect the customer to. Raises if Stripe isn't
    configured/installed — so charging is strictly opt-in.
    """
    if plan not in PLANS:
        raise ValueError(f"Unknown plan '{plan}'. Known: {sorted(PLANS)}")
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
