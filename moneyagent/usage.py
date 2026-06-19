"""Per-provider daily usage tracking, persisted to JSON.

Used by the router to honour free-tier daily request limits and to report
how much each provider has been leaned on.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path


class UsageTracker:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
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
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def _today(self) -> str:
        return date.today().isoformat()

    def _bucket(self, provider: str) -> dict:
        day = self._today()
        entry = self._data.get(provider)
        if not entry or entry.get("day") != day:
            entry = {"day": day, "requests": 0, "prompt_tokens": 0, "completion_tokens": 0}
            self._data[provider] = entry
        return entry

    def count_today(self, provider: str) -> int:
        return self._bucket(provider)["requests"]

    def at_limit(self, provider: str, daily_limit: int) -> bool:
        if daily_limit <= 0:  # 0 means unlimited
            return False
        return self.count_today(provider) >= daily_limit

    def record(self, provider: str, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        bucket = self._bucket(provider)
        bucket["requests"] += 1
        bucket["prompt_tokens"] += prompt_tokens
        bucket["completion_tokens"] += completion_tokens
        self._save()

    def snapshot(self) -> dict:
        # Refresh day rollover for all known providers before returning.
        for name in list(self._data.keys()):
            self._bucket(name)
        return dict(self._data)
