"""Google Gemini provider (generativelanguage REST API, free tier)."""
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

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(Provider):
    def __init__(
        self,
        name: str,
        models: dict[str, str],
        tiers: list[str],
        api_key_env: str,
        daily_request_limit: int = 0,
    ) -> None:
        super().__init__(name, models, tiers, daily_request_limit)
        self.api_key = os.getenv(api_key_env, "").strip()

    def is_available(self) -> bool:
        return bool(self.api_key)

    @staticmethod
    def _to_gemini(messages: list[Message]) -> tuple[str | None, list[dict]]:
        """Gemini keeps the system prompt separate and uses 'model' for assistant."""
        system_parts: list[str] = []
        contents: list[dict] = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.content)
                continue
            role = "model" if m.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m.content}]})
        system = "\n\n".join(system_parts) if system_parts else None
        return system, contents

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

        system, contents = self._to_gemini(messages)
        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        url = f"{API_ROOT}/{model}:generateContent?key={self.api_key}"
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
        except requests.RequestException as exc:
            raise TransientError(f"{self.name}: request failed: {exc}") from exc

        if resp.status_code != 200:
            raise error_for_status(self.name, resp.status_code, resp.text)

        data = resp.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"{self.name}: unexpected response: {data}") from exc

        usage = data.get("usageMetadata", {})
        return CompletionResult(
            text=text,
            provider=self.name,
            model=model,
            prompt_tokens=usage.get("promptTokenCount", 0),
            completion_tokens=usage.get("candidatesTokenCount", 0),
            raw=data,
        )
