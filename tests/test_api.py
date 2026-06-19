"""API tests for the SaaS app. Skipped if FastAPI isn't installed."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("MONEYAGENT_API_KEYS", "testkey:free")
    monkeypatch.chdir(tmp_path)  # data/ writes land in the temp dir
    from moneyagent.workflows.saas_automation import create_app

    return TestClient(create_app())


def test_health(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert "summarize" in resp.json()["jobs"]


def test_run_requires_api_key(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    resp = client.post("/v1/run", json={"job": "summarize", "input_text": "hi"})
    assert resp.status_code == 401


def test_usage_with_valid_key(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    resp = client.get("/v1/usage", headers={"X-API-Key": "testkey"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan"] == "free"
    assert body["used_this_month"] == 0


def test_checkout_disabled_without_stripe(monkeypatch, tmp_path):
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    client = _client(monkeypatch, tmp_path)
    resp = client.post(
        "/v1/checkout",
        json={"plan": "pro", "success_url": "https://x/s", "cancel_url": "https://x/c"},
    )
    assert resp.status_code == 400  # billing not configured
