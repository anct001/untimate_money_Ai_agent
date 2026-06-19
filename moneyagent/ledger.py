"""Honest revenue ledger.

The agent NEVER invents revenue. You log real, completed, paid work here and
the ledger reports actual progress toward the monthly target. This keeps the
"$10k/month" goal grounded in reality instead of wishful automation.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path


@dataclass
class Entry:
    date: str
    source: str        # which workflow / client / channel
    description: str
    amount_usd: float
    status: str        # "invoiced" | "paid"


class Ledger:
    def __init__(self, path: Path, monthly_target_usd: float = 10000) -> None:
        self.path = Path(path)
        self.monthly_target_usd = monthly_target_usd
        self.entries: list[Entry] = self._load()

    def _load(self) -> list[Entry]:
        if not self.path.exists():
            return []
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
            return [Entry(**r) for r in rows]
        except (json.JSONDecodeError, OSError, TypeError):
            return []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([asdict(e) for e in self.entries], indent=2), encoding="utf-8"
        )

    def add(self, source: str, description: str, amount_usd: float, status: str = "invoiced") -> Entry:
        entry = Entry(
            date=date.today().isoformat(),
            source=source,
            description=description,
            amount_usd=round(float(amount_usd), 2),
            status=status,
        )
        self.entries.append(entry)
        self._save()
        return entry

    def month_summary(self, year: int | None = None, month: int | None = None) -> dict:
        now = datetime.now()
        year = year or now.year
        month = month or now.month
        prefix = f"{year:04d}-{month:02d}"

        rows = [e for e in self.entries if e.date.startswith(prefix)]
        paid = sum(e.amount_usd for e in rows if e.status == "paid")
        invoiced = sum(e.amount_usd for e in rows if e.status == "invoiced")
        total = paid + invoiced
        target = self.monthly_target_usd
        return {
            "period": prefix,
            "paid_usd": round(paid, 2),
            "invoiced_usd": round(invoiced, 2),
            "total_usd": round(total, 2),
            "target_usd": target,
            "progress_pct": round(100 * total / target, 1) if target else 0.0,
            "remaining_usd": round(max(target - total, 0), 2),
            "entries": len(rows),
        }
