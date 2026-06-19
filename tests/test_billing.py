"""Offline tests for billing/metering."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from moneyagent.billing import KeyStore, UsageMeter  # noqa: E402


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
