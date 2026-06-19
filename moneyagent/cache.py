"""Tiny on-disk prompt cache.

Identical requests are served from disk instead of burning free-tier quota.
Keyed by the messages + sampling params (not the provider), so a repeated
prompt is reused no matter who answered it last time.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path


class PromptCache:
    def __init__(self, path: Path, ttl_seconds: int = 7 * 24 * 3600, enabled: bool = True):
        self.path = Path(path)
        self.ttl = ttl_seconds
        self.enabled = enabled
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data), encoding="utf-8")

    @staticmethod
    def key(messages: list[dict], tier: str, temperature: float, max_tokens: int) -> str:
        blob = json.dumps(
            {"m": messages, "t": tier, "temp": temperature, "mt": max_tokens},
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def get(self, key: str) -> str | None:
        if not self.enabled:
            return None
        entry = self._data.get(key)
        if not entry:
            return None
        if self.ttl > 0 and time.time() - entry.get("ts", 0) > self.ttl:
            self._data.pop(key, None)
            return None
        return entry.get("text")

    def set(self, key: str, text: str) -> None:
        if not self.enabled:
            return
        self._data[key] = {"text": text, "ts": time.time()}
        self._save()
