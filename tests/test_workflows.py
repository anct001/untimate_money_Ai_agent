"""Offline tests for indicators and the ledger."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from moneyagent.ledger import Ledger  # noqa: E402
from moneyagent.workflows.trading_signals import compute_indicators  # noqa: E402


def test_compute_indicators_uptrend():
    prices = [float(i) for i in range(1, 61)]  # steadily rising
    ind = compute_indicators(prices)
    assert ind["trend"] == "uptrend"
    assert ind["last_price"] == 60.0
    assert ind["sma20"] is not None and ind["sma50"] is not None
    assert 0 <= ind["rsi14"] <= 100


def test_compute_indicators_empty():
    assert compute_indicators([]) == {}


def test_ledger_progress(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json", monthly_target_usd=1000)
    ledger.add("content", "blog post", 200, status="paid")
    ledger.add("saas", "subscription", 300, status="invoiced")
    s = ledger.month_summary()
    assert s["paid_usd"] == 200
    assert s["invoiced_usd"] == 300
    assert s["total_usd"] == 500
    assert s["progress_pct"] == 50.0
    assert s["remaining_usd"] == 500

    # Reload from disk to confirm persistence.
    again = Ledger(tmp_path / "ledger.json", monthly_target_usd=1000)
    assert again.month_summary()["total_usd"] == 500
