"""Append-only memory log (JSONL).

A minimal persistent memory so autonomous runs leave a trail and can recall
what was done. Not a vector store — just durable, greppable notes.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class Memory:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def add(self, kind: str, content: str, **meta) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {"ts": datetime.now().isoformat(timespec="seconds"), "kind": kind,
                  "content": content, **meta}
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def recent(self, n: int = 20) -> list[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()[-n:]
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
