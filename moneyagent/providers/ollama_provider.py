"""Local Ollama provider — free, private, no quota.

Run `ollama serve` and pull a small model (e.g. `ollama pull llama3.2:3b`).
"""
from __future__ import annotations

import os

import requests

from .base import CompletionResult, Message, Provider, ProviderError


class OllamaProvider(Provider):
    def __init__(
        self,
        name: str,
        models: dict[str, str],
        tiers: list[str],
        daily_request_limit: int = 0,
        host: str | None = None,
    ) -> None:
        super().__init__(name, models, tiers, daily_request_limit)
        self.host = (host or os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=2)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def complete(
        self,
        messages: list[Message],
        model: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        timeout: int = 120,
    ) -> CompletionResult:
        payload = {
            "model": model,
            "messages": [m.as_dict() for m in messages],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        try:
            resp = requests.post(f"{self.host}/api/chat", json=payload, timeout=timeout)
        except requests.RequestException as exc:
            raise ProviderError(f"{self.name}: request failed: {exc}") from exc

        if resp.status_code != 200:
            raise ProviderError(
                f"{self.name}: HTTP {resp.status_code}: {resp.text[:300]}"
            )

        data = resp.json()
        text = data.get("message", {}).get("content", "")
        return CompletionResult(
            text=text,
            provider=self.name,
            model=model,
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            raw=data,
        )
