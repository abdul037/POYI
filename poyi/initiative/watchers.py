"""Watchers turn the picture and the machine into events.

Each watcher is called every tick with the world and the time, and returns
zero or more events. De-duplication happens in the loop by `Event.key`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Protocol

from poyi.initiative.events import Event
from poyi.world.model import World
from poyi.world.sensors import run

TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
DAY_RE = re.compile(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b", re.I)
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class Watcher(Protocol):
    name: str

    def check(self, world: World, now: datetime) -> list[Event]: ...


def parse_next_item(text: str, now: datetime) -> datetime | None:
    """'09:00 Mon Standup' or '11:30 Dentist' -> the next such time, or None."""
    m = TIME_RE.search(text)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return None
    when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    d = DAY_RE.search(text)
    if d:
        target = DAYS.index(d.group(1).lower())
        ahead = (target - now.weekday()) % 7
        when = when + timedelta(days=ahead)
        if ahead == 0 and when < now - timedelta(minutes=30):
            when += timedelta(days=7)
    elif when < now - timedelta(minutes=30):
        when += timedelta(days=1)
    return when


@dataclass
class NextWatcher:
    """Something in `next` is coming up: fire once at lead time."""

    lead_minutes: int = 10
    name: str = "next"

    def check(self, world: World, now: datetime) -> list[Event]:
        out: list[Event] = []
        for item in world.next:
            if item.endswith("(reminder)"):
                continue  # reminders fire on their own, at the moment they are due
            when = parse_next_item(item, now)
            if when is None:
                continue
            minutes = (when - now).total_seconds() / 60
            if 0 <= minutes <= self.lead_minutes:
                out.append(Event(
                    source="next",
                    title=f"{item.strip()} in {int(round(minutes)) or 'under a'} minute{'s' if round(minutes) != 1 else ''}",
                    importance=0.7,
                    due=when.isoformat(timespec="seconds"),
                    key=f"next:{item.strip()}:{when.date().isoformat()}",
                ))
        return out


@dataclass
class ThreadsWatcher:
    """A promise or a waiting-on that has sat for a while: one nudge a day, mid-morning."""

    read_threads: Callable[[], str]
    hour: int = 10
    name: str = "threads"

    def check(self, world: World, now: datetime) -> list[Event]:
        if now.hour != self.hour:
            return []
        out: list[Event] = []
        heading = ""
        for raw in self.read_threads().splitlines():
            line = raw.strip()
            if line.startswith("## "):
                heading = line[3:].strip().lower()
            elif line.startswith("- ") and heading == "promised":
                item = line[2:].strip()
                out.append(Event(
                    source="threads",
                    title=f"Still open: {item}",
                    importance=0.45,
                    key=f"threads:{item}:{now.date().isoformat()}",
                ))
        return out


BATTERY = ["sh", "-c", "pmset -g batt | grep -Eo '[0-9]+%; (charging|discharging|charged|AC attached)' | head -1"]


@dataclass
class BatteryWatcher:
    """Low battery while discharging, once per drop below the line."""

    threshold: int = 15
    runner: Callable[[list[str]], str] | None = None
    name: str = "system"

    def check(self, world: World, now: datetime) -> list[Event]:
        text = (self.runner or run)(BATTERY)
        m = re.match(r"(\d+)%; (\w+)", text or "")
        if not m:
            return []
        percent, state = int(m.group(1)), m.group(2)
        if state == "discharging" and percent <= self.threshold:
            return [Event(source="system", title=f"Battery at {percent}%", importance=0.6,
                          key=f"system:battery:{now.date().isoformat()}:{now.hour}")]
        return []


@dataclass
class ScheduledWatcher:
    """A fixed daily moment, e.g. the morning brief, that fires once a day."""

    at: str            # "08:00"
    source: str        # "brief"
    title: str
    importance: float = 0.6
    name: str = "scheduled"

    def check(self, world: World, now: datetime) -> list[Event]:
        try:
            hour, minute = (int(x) for x in self.at.split(":"))
        except ValueError:
            return []
        start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if 0 <= (now - start).total_seconds() < 15 * 60:
            return [Event(source=self.source, title=self.title, importance=self.importance,
                          key=f"{self.source}:{self.title}:{now.date().isoformat()}")]
        return []


def default_watchers(settings: Any, read_threads: Callable[[], str]) -> list[Any]:
    return [
        NextWatcher(),
        ThreadsWatcher(read_threads=read_threads),
        BatteryWatcher(),
        ScheduledWatcher(at=settings.brief_morning, source="brief", title="Morning brief", importance=0.65),
        ScheduledWatcher(at=settings.brief_evening, source="brief", title="Evening wind-down", importance=0.5),
    ]
