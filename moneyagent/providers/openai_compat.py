"""Generic provider for any OpenAI-compatible /chat/completions endpoint.

Works with Groq, OpenRouter, Cerebras, Together, and local servers like
LM Studio or vLLM — they all speak the same wire format.
"""
from __future__ import annotations

import os

import requests

from .base import (
    CompletionResult,
    Message,
    Provider,
    ProviderError,
    TransientError,
    error_for_status,
)


class OpenAICompatProvider(Provider):
    def __init__(
        self,
        name: str,
        models: dict[str, str],
        tiers: list[str],
        base_url: str,
        api_key_env: str,
        daily_request_limit: int = 0,
        extra_headers: dict | None = None,
    ) -> None:
        super().__init__(name, models, tiers, daily_request_limit)
        self.base_url = base_url.rstrip("/")
        self.api_key = os.getenv(api_key_env, "").strip()
        self.extra_headers = extra_headers or {}

    def is_available(self) -> bool:
        return bool(self.api_key)

    def complete(
        self,
        messages: list[Message],
        model: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        timeout: int = 120,
    ) -> CompletionResult:
        if not self.api_key:
            raise ProviderError(f"{self.name}: missing API key")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        payload = {
            "model": model,
            "messages": [m.as_dict() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise TransientError(f"{self.name}: request failed: {exc}") from exc

        if resp.status_code != 200:
            raise error_for_status(self.name, resp.status_code, resp.text)

        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"{self.name}: unexpected response: {data}") from exc

        usage = data.get("usage", {})
        return CompletionResult(
            text=text or "",
            provider=self.name,
            model=model,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )
