"""Build Provider instances from config dicts."""
from __future__ import annotations

from .base import Provider
from .gemini_provider import GeminiProvider
from .ollama_provider import OllamaProvider
from .openai_compat import OpenAICompatProvider


def build_provider(cfg: dict) -> Provider:
    ptype = cfg.get("type")
    name = cfg["name"]
    models = cfg.get("models", {})
    tiers = cfg.get("tiers", ["light", "heavy"])
    limit = int(cfg.get("daily_request_limit", 0))

    if ptype == "ollama":
        return OllamaProvider(name, models, tiers, limit, host=cfg.get("host"))

    if ptype == "openai_compat":
        return OpenAICompatProvider(
            name,
            models,
            tiers,
            base_url=cfg["base_url"],
            api_key_env=cfg["api_key_env"],
            daily_request_limit=limit,
            extra_headers=cfg.get("extra_headers"),
        )

    if ptype == "gemini":
        return GeminiProvider(
            name, models, tiers, api_key_env=cfg["api_key_env"], daily_request_limit=limit
        )

    raise ValueError(f"Unknown provider type: {ptype!r} (provider {name!r})")
