"""Reminders and timers. Local, plain JSON, and the first hands Poyi gets."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from anthropic import beta_tool

from poyi.hands.registry import Hand, Registry
from poyi.initiative.events import Event
from poyi.world.model import World

RELATIVE = re.compile(r"^in\s+(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours)$", re.I)
CLOCK = re.compile(r"^(?:(today|tomorrow|tmrw)\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", re.I)


def parse_when(text: str, now: datetime) -> datetime:
    """'in 20m', 'in 2 hours', '18:00', '6pm', 'tomorrow 9:00', or ISO 8601."""
    text = text.strip()
    m = RELATIVE.match(text)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        return now + (timedelta(hours=n) if unit.startswith("h") else timedelta(minutes=n))
    m = CLOCK.match(text)
    if m:
        day, hour, minute, ampm = m.group(1), int(m.group(2)), int(m.group(3) or 0), m.group(4)
        if ampm:
            ampm = ampm.lower()
            if ampm == "pm" and hour < 12:
                hour += 12
            if ampm == "am" and hour == 12:
                hour = 0
        if hour > 23 or minute > 59:
            raise ValueError(f"not a time: {text!r}")
        when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if day and day.lower() != "today":
            when += timedelta(days=1)
        elif not day and when <= now:
            when += timedelta(days=1)
        return when
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"couldn't read a time from {text!r}; try 'in 20m', '18:00', or 'tomorrow 9:00'") from exc


@dataclass
class Reminder:
    text: str
    when: str  # ISO
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:6])
    done: bool = False

    def at(self) -> datetime:
        return datetime.fromisoformat(self.when)


class ReminderStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> list[Reminder]:
        if not self.path.exists():
            return []
        try:
            return [Reminder(**r) for r in json.loads(self.path.read_text())]
        except (ValueError, TypeError):
            return []

    def save(self, items: list[Reminder]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([asdict(r) for r in items], indent=2) + "\n")

    def add(self, text: str, when: datetime) -> Reminder:
        items = self.load()
        r = Reminder(text=text.strip(), when=when.isoformat(timespec="seconds"))
        items.append(r)
        self.save(items)
        return r

    def pending(self) -> list[Reminder]:
        return sorted((r for r in self.load() if not r.done), key=lambda r: r.when)

    def cancel(self, ref: str) -> Reminder | None:
        items = self.load()
        ref = ref.strip().lower()
        for r in items:
            if not r.done and (r.id.startswith(ref) or ref in r.text.lower()):
                r.done = True
                self.save(items)
                return r
        return None

    def mark_done(self, reminder_id: str) -> None:
        items = self.load()
        for r in items:
            if r.id == reminder_id:
                r.done = True
        self.save(items)


def register(registry: Registry, store: ReminderStore, now_fn=datetime.now) -> None:
    def describe_set(text: str, when: str) -> str:
        return f"set a reminder: {text!r} at {when}"

    def run_set(text: str, when: str) -> str:
        at = parse_when(when, now_fn())
        r = store.add(text, at)
        return f"Reminder [{r.id}] set for {at:%A %H:%M}: {r.text}"

    def run_list() -> str:
        items = store.pending()
        if not items:
            return "No reminders pending."
        return "\n".join(f"[{r.id}] {r.at():%a %d %b %H:%M}  {r.text}" for r in items)

    def run_cancel(ref: str) -> str:
        r = store.cancel(ref)
        return f"Cancelled [{r.id}] {r.text}" if r else f"No pending reminder matches {ref!r}."

    set_hand = registry.add(Hand("set_reminder", "free", describe_set, run_set))
    list_hand = registry.add(Hand("list_reminders", "free", lambda: "list reminders", run_list))
    cancel_hand = registry.add(Hand("cancel_reminder", "free", lambda ref: f"cancel reminder {ref!r}", run_cancel))

    @beta_tool
    def set_reminder(text: str, when: str) -> str:
        """Set a reminder or timer. Poyi will bring it up when it's due.

        Args:
            text: what to remind them of, in their words.
            when: "in 20m", "in 2 hours", "18:00", "6pm", "tomorrow 9:00", or an ISO time.
        """
        return registry.call("set_reminder", text=text, when=when)

    @beta_tool
    def list_reminders() -> str:
        """List pending reminders and timers."""
        return registry.call("list_reminders")

    @beta_tool
    def cancel_reminder(ref: str) -> str:
        """Cancel a pending reminder by its id or a word from its text.

        Args:
            ref: the id in brackets, or a distinctive word from the reminder.
        """
        return registry.call("cancel_reminder", ref=ref)

    set_hand.tool, list_hand.tool, cancel_hand.tool = set_reminder, list_reminders, cancel_reminder


@dataclass
class ReminderWatcher:
    """Due reminders become high-importance events, then are marked done."""

    store: ReminderStore
    name: str = "reminder"

    def check(self, world: World, now: datetime) -> list[Event]:
        out = []
        for r in self.store.pending():
            if r.at() <= now:
                out.append(Event(source="reminder", title=r.text, importance=0.9, due=r.when,
                                 key=f"reminder:{r.id}"))
                self.store.mark_done(r.id)
        return out

    def upcoming(self, now: datetime, hours: int = 24) -> list[str]:
        """For the picture's `next` list."""
        horizon = now + timedelta(hours=hours)
        return [f"{r.at():%H:%M}{'' if r.at().date() == now.date() else r.at().strftime(' %a')} {r.text}"
                for r in self.store.pending() if now <= r.at() <= horizon]
