"""Offline tests for billing/metering."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from moneyagent.billing import (  # noqa: E402
    KeyStore,
    UsageMeter,
    generate_key,
    handle_checkout_completed,
)


def test_keystore_from_env(monkeypatch):
    monkeypatch.setenv("MONEYAGENT_API_KEYS", "k1:pro, k2:free, k3:bogus")
    store = KeyStore.from_env_or_file()
    assert store.verify("k1")["plan"] == "pro"
    assert store.verify("k2")["plan"] == "free"
    assert store.verify("k3")["plan"] == "free"  # unknown plan -> free
    assert store.verify("missing") is None


def test_keystore_mints_dev_key(monkeypatch):
    monkeypatch.delenv("MONEYAGENT_API_KEYS", raising=False)
    store = KeyStore.from_env_or_file(path=None)
    assert len(store.keys) == 1
    rec = next(iter(store.keys.values()))
    assert rec["plan"] == "pro" and rec["label"] == "auto-dev"


def test_usage_meter_monthly(tmp_path):
    meter = UsageMeter(tmp_path / "u.json")
    assert meter.count_month("k") == 0
    meter.record("k")
    meter.record("k")
    assert meter.count_month("k") == 2
    assert meter.over_monthly_limit("k", 2) is True
    assert meter.over_monthly_limit("k", 5) is False
    # Persisted across reloads.
    assert UsageMeter(tmp_path / "u.json").count_month("k") == 2


def test_usage_meter_rate_limit(tmp_path):
    meter = UsageMeter(tmp_path / "u.json")
    assert meter.rate_limited("k", per_minute=2) is False
    assert meter.rate_limited("k", per_minute=2) is False
    assert meter.rate_limited("k", per_minute=2) is True  # third in the window
    assert meter.rate_limited("k", per_minute=0) is False  # unlimited


def test_generate_key_unique():
    keys = {generate_key() for _ in range(100)}
    assert len(keys) == 100
    assert all(k.startswith("ma-") for k in keys)


def test_keystore_provision_and_persist(tmp_path, monkeypatch):
    monkeypatch.delenv("MONEYAGENT_API_KEYS", raising=False)
    path = tmp_path / "keys.json"
    store = KeyStore.from_env_or_file(path)  # mints a dev key
    key = store.add("free", label="signup", email="a@b.com")
    assert store.verify(key)["plan"] == "free"
    assert store.set_plan(key, "pro") is True
    assert store.verify(key)["plan"] == "pro"

    # Reload: provisioned key persists, ephemeral dev key does not.
    reloaded = KeyStore.from_env_or_file(path)
    assert reloaded.verify(key)["plan"] == "pro"
    assert all(rec.get("label") != "auto-dev" for rec in reloaded.keys.values())


def test_handle_checkout_completed_upgrades(tmp_path, monkeypatch):
    monkeypatch.delenv("MONEYAGENT_API_KEYS", raising=False)
    store = KeyStore.from_env_or_file(tmp_path / "keys.json")
    key = store.add("free")
    event = {
        "type": "checkout.session.completed",
        "data": {"object": {"client_reference_id": key, "metadata": {"plan": "pro"}}},
    }
    assert handle_checkout_completed(event, store) == key
    assert store.verify(key)["plan"] == "pro"

    # Non-actionable events return None.
    assert handle_checkout_completed({"type": "other"}, store) is None
    assert handle_checkout_completed(
        {"type": "checkout.session.completed",
         "data": {"object": {"client_reference_id": "unknown", "metadata": {}}}},
        store,
    ) is None
