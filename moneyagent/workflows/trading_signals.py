"""Trading-signals workflow — ANALYSIS ONLY. It never places real orders.

It computes simple, transparent technical indicators from price data and asks
the model to summarize them into an educational, risk-flagged briefing. Real
trading decisions and order placement stay 100% with the human.

Data source is pluggable: pass `prices` (a list of closing prices, oldest
first) directly, or install `yfinance` to fetch them by ticker.
"""
from __future__ import annotations

from .base import Workflow, WorkflowResult

RISK_DISCLAIMER = (
    "NOT financial advice. Educational analysis only. Markets are risky; past "
    "indicators do not predict future returns. This tool does not and will not "
    "place real-money orders. Verify everything and consult a licensed advisor."
)


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window or window <= 0:
        return None
    return sum(values[-window:]) / window


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    gains, losses = [], []
    for prev, cur in zip(values[-period - 1 : -1], values[-period:], strict=False):
        change = cur - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _fetch_prices(ticker: str, period: str = "3mo") -> list[float]:
    try:
        import yfinance as yf  # optional dependency
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Provide `prices=` directly, or `pip install yfinance` to fetch by ticker."
        ) from exc
    hist = yf.Ticker(ticker).history(period=period)
    return [float(x) for x in hist["Close"].dropna().tolist()]


def compute_indicators(prices: list[float]) -> dict:
    if not prices:
        return {}
    last = prices[-1]
    sma20, sma50 = _sma(prices, 20), _sma(prices, 50)
    rsi = _rsi(prices, 14)
    trend = "n/a"
    if sma20 and sma50:
        trend = "uptrend" if sma20 > sma50 else "downtrend"
    return {
        "last_price": round(last, 4),
        "sma20": round(sma20, 4) if sma20 else None,
        "sma50": round(sma50, 4) if sma50 else None,
        "rsi14": rsi,
        "trend": trend,
        "samples": len(prices),
    }


class TradingSignalsWorkflow(Workflow):
    name = "signals"

    def run(  # type: ignore[override]
        self,
        *,
        ticker: str = "",
        prices: list[float] | None = None,
        period: str = "3mo",
    ) -> WorkflowResult:
        if prices is None:
            if not ticker:
                raise ValueError("Provide either `ticker` or `prices`.")
            prices = _fetch_prices(ticker, period)

        ind = compute_indicators(prices)
        if not ind:
            raise ValueError("No price data to analyze.")

        task = (
            "You are a markets educator. Given these transparent indicators, write "
            "a short, neutral briefing: what the indicators currently suggest, the "
            "key risks, and what a human should verify before acting. Do NOT give a "
            "buy/sell instruction.\n\n"
            f"Instrument: {ticker or 'provided series'}\n"
            f"Indicators: {ind}"
        )
        result = self.agent.run(task, self_review=False)
        return WorkflowResult(
            title=f"Signal briefing: {ticker or 'series'}",
            output=result.output,
            meta=ind,
            needs_human_review=True,
            disclaimer=RISK_DISCLAIMER,
        )
