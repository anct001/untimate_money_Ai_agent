"""Per-model USD cost estimation (LiteLLM-style, simplified).

Most models we target are free-tier (cost 0). The table exists so that if you
ever fall back to a paid model, spend is still tracked and the daily budget
guard can stop runaway cost. Prices are USD per 1M tokens (input, output) and
are approximate — override in config if you need accuracy.
"""
from __future__ import annotations

# model id (or prefix) -> (input_per_mtok, output_per_mtok) in USD.
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    # Free local / free-tier hosted models.
    "llama3.2:3b": (0.0, 0.0),
    "llama3.1:8b": (0.0, 0.0),
    "llama-3.1-8b-instant": (0.0, 0.0),
    "llama-3.3-70b-versatile": (0.0, 0.0),
    "gemini-2.0-flash-lite": (0.0, 0.0),
    "gemini-2.0-flash": (0.0, 0.0),
    "meta-llama/llama-3.3-70b-instruct:free": (0.0, 0.0),
    "llama3.1-8b": (0.0, 0.0),
    "llama-3.3-70b": (0.0, 0.0),
    "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free": (0.0, 0.0),
    # Examples of paid fallbacks (so budget guard has teeth if you add them).
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.0),
    "claude-3-5-haiku": (0.80, 4.0),
}


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    rate = PRICES_USD_PER_MTOK.get(model)
    if rate is None:
        # Unknown model: treat as free but don't crash. Add it to the table to track.
        return 0.0
    in_rate, out_rate = rate
    cost = (prompt_tokens / 1_000_000) * in_rate + (completion_tokens / 1_000_000) * out_rate
    return round(cost, 6)
