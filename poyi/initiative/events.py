"""Events: things that happened that Poyi might want to tell you about."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

ROUTES = ("speak", "mention", "note", "log")


@dataclass
class Event:
    source: str                 # "next", "threads", "system", "brief", "mail", "home", ...
    title: str                  # one line, what happened
    body: str = ""              # a little more, optional
    importance: float = 0.5     # 0..1, the watcher's own view
    due: str | None = None      # ISO time when this stops mattering, if any
    person: str = ""            # who it is about, if anyone
    key: str = ""               # de-duplication key; same key won't fire twice
    at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    route: str = ""             # decided by the policy
    mode: str = ""              # their mode when it was decided
    score: float = 0.0
    reason: str = ""
    feedback: str = ""          # not_now / thanks / ignored / mentioned
    delivered_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def due_in_minutes(self, now: datetime) -> float | None:
        if not self.due:
            return None
        try:
            return (datetime.fromisoformat(self.due) - now).total_seconds() / 60
        except ValueError:
            return None


class EventLog:
    """Append-only JSONL of every event and what was done with it."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "events.jsonl"

    def append(self, event: Event) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(event.to_dict()) + "\n")

    def iter(self) -> Iterator[Event]:
        if not self.path.exists():
            return iter(())
        events: dict[str, Event] = {}
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                e = Event.from_dict(json.loads(line))
            except (ValueError, TypeError):
                continue
            events[e.id] = e  # later lines for the same id win
        return iter(events.values())

    def recent(self, limit: int = 20) -> list[Event]:
        return sorted(self.iter(), key=lambda e: e.at, reverse=True)[:limit]

    def seen_keys(self) -> set[str]:
        return {e.key for e in self.iter() if e.key}

    def get(self, event_id: str) -> Event | None:
        for e in self.iter():
            if e.id == event_id or e.id.startswith(event_id):
                return e
        return None

    def pending_mentions(self) -> list[Event]:
        return [e for e in self.iter() if e.route == "mention" and not e.delivered_at]

    def undelivered_speaks(self) -> list[Event]:
        return [e for e in self.iter() if e.route == "speak" and e.delivered_at and not e.feedback]
