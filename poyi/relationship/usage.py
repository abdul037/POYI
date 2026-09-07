"""Every turn, in one line: when, how long, how many tokens, roughly what it cost.

The dashboard reads this. So does the care check.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

# USD per million tokens: input, output, cache read (about a tenth of input), cache write (1.25x input)
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-fable-5-1": (10.0, 50.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> float:
    price_in, price_out = PRICES.get(model, (5.0, 25.0))
    return (input_tokens * price_in + output_tokens * price_out + cache_read * price_in * 0.1 + cache_write * price_in * 1.25) / 1_000_000


@dataclass
class Turn:
    at: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    first_token_ms: int = 0
    total_ms: int = 0
    rounds: int = 1
    front: str = ""

    @property
    def cost(self) -> float:
        return estimate_cost(self.model, self.input_tokens, self.output_tokens, self.cache_read, self.cache_write)

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "cost": round(self.cost, 6)}


class UsageLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def record(self, turn: Turn) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(turn.to_dict()) + "\n")

    def turns(self, days: int | None = None, today: date | None = None) -> Iterator[Turn]:
        if not self.path.exists():
            return iter(())
        cutoff = None
        if days is not None:
            cutoff = ((today or date.today()) - timedelta(days=days - 1)).isoformat()
        out = []
        for line in self.path.read_text().splitlines():
            try:
                data = json.loads(line)
            except ValueError:
                continue
            data.pop("cost", None)
            turn = Turn(**{k: v for k, v in data.items() if k in Turn.__dataclass_fields__})
            if cutoff is None or turn.at[:10] >= cutoff:
                out.append(turn)
        return iter(out)

    def by_day(self, days: int = 7, today: date | None = None) -> dict[str, dict[str, float]]:
        totals: dict[str, dict[str, float]] = defaultdict(lambda: {"turns": 0, "cost": 0.0, "first_ms": 0.0, "total_ms": 0.0, "late": 0})
        for t in self.turns(days, today):
            day = t.at[:10]
            d = totals[day]
            d["turns"] += 1
            d["cost"] += t.cost
            d["first_ms"] += t.first_token_ms
            d["total_ms"] += t.total_ms
            hour = int(t.at[11:13]) if len(t.at) >= 13 else 12
            if hour < 6:
                d["late"] += 1
        for d in totals.values():
            if d["turns"]:
                d["first_ms"] = round(d["first_ms"] / d["turns"])
                d["total_ms"] = round(d["total_ms"] / d["turns"])
        return dict(sorted(totals.items()))


def usage_from_message(usage: Any) -> tuple[int, int, int, int]:
    """(input, output, cache_read, cache_write) from a response usage object or dict."""
    get = (lambda k: usage.get(k, 0)) if isinstance(usage, dict) else (lambda k: getattr(usage, k, 0))
    return (int(get("input_tokens") or 0), int(get("output_tokens") or 0),
            int(get("cache_read_input_tokens") or 0), int(get("cache_creation_input_tokens") or 0))
