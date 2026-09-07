"""Watchers for the long game: goals, people, the weekly reflection, and care."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

from poyi.initiative.events import Event
from poyi.world.model import World

CHECK_IN = re.compile(r"\(check-in:\s*(\d{4}-\d{2}-\d{2})\)")
BIRTHDAY = re.compile(r"\(birthday:\s*(\d{2})-(\d{2})\)")
LAST_SPOKE = re.compile(r"\(last spoke:\s*(\d{4}-\d{2}-\d{2})\)")


def _items(text: str, heading_prefix: str) -> list[str]:
    out, active = [], False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            active = line[3:].strip().lower().startswith(heading_prefix)
        elif active and line.startswith("- "):
            out.append(line[2:].strip())
    return out


def _name(item: str) -> str:
    return item.split("(")[0].split(":")[0].split(",")[0].strip() or item[:30]


@dataclass
class GoalsWatcher:
    """A goal with a (check-in: YYYY-MM-DD) that has arrived: once, mid-morning."""

    read_threads: Callable[[], str]
    hour: int = 10
    name: str = "goals"

    def check(self, world: World, now: datetime) -> list[Event]:
        if now.hour != self.hour:
            return []
        out = []
        for item in _items(self.read_threads(), "goals"):
            m = CHECK_IN.search(item)
            if not m:
                continue
            due = date.fromisoformat(m.group(1))
            if due <= now.date():
                out.append(Event(source="goals", title=f"Check-in on a goal: {_name(item)}", body=item, importance=0.55,
                                 key=f"goals:{_name(item)}:{m.group(1)}"))
        return out


@dataclass
class PeopleWatcher:
    """Birthdays two days out, and people not spoken to in a month. Never a nag: one line, once."""

    read_profile: Callable[[], str]
    quiet_days: int = 30
    hour: int = 10
    name: str = "people"

    def check(self, world: World, now: datetime) -> list[Event]:
        if now.hour != self.hour:
            return []
        out = []
        today = now.date()
        for item in _items(self.read_profile(), "people"):
            name = _name(item)
            b = BIRTHDAY.search(item)
            if b:
                month, day = int(b.group(1)), int(b.group(2))
                for year in (today.year, today.year + 1):
                    try:
                        when = date(year, month, day)
                    except ValueError:
                        continue
                    if 0 <= (when - today).days <= 2:
                        out.append(Event(source="people", title=f"{name}'s birthday is {'today' if when == today else 'on ' + when.strftime('%A')}",
                                         importance=0.7, person=name, key=f"people:birthday:{name}:{when.isoformat()}"))
                        break
            s = LAST_SPOKE.search(item)
            if s:
                last = date.fromisoformat(s.group(1))
                gap = (today - last).days
                if gap >= self.quiet_days:
                    out.append(Event(source="people", title=f"It's been {gap} days since you spoke to {name}", importance=0.45,
                                     person=name, key=f"people:quiet:{name}:{today.strftime('%Y-%m')}"))
        return out


@dataclass
class WeeklyWatcher:
    """One moment a week, e.g. Sunday evening, for the reflection."""

    weekday: int = 6        # Monday is 0
    at: str = "18:00"
    source: str = "reflection"
    title: str = "Weekly reflection"
    importance: float = 0.6
    name: str = "weekly"

    def check(self, world: World, now: datetime) -> list[Event]:
        if now.weekday() != self.weekday:
            return []
        try:
            hour, minute = (int(x) for x in self.at.split(":"))
        except ValueError:
            return []
        start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if 0 <= (now - start).total_seconds() < 30 * 60:
            iso = now.date().isocalendar()
            return [Event(source=self.source, title=self.title, importance=self.importance,
                          key=f"{self.source}:{iso.year}-W{iso.week:02d}")]
        return []


@dataclass
class CareWatcher:
    """If the pattern of use looks like it is replacing people rather than supporting them,
    say so once, kindly, and not again for a month. Deliberately conservative."""

    by_day: Callable[[int], dict[str, dict[str, float]]]   # usage.by_day(days)
    read_logs: Callable[[int], list[tuple[date, str]]]    # memory.recent_logs(days)
    heavy_turns: int = 150
    heavy_days: int = 5
    late_share: float = 0.4
    hour: int = 20
    name: str = "care"

    def signals(self) -> dict[str, Any]:
        days = self.by_day(14)
        heavy = [d for d, v in days.items() if v["turns"] >= self.heavy_turns]
        total = sum(v["turns"] for v in days.values()) or 1
        late = sum(v["late"] for v in days.values())
        logs = " ".join(text.lower() for _, text in self.read_logs(14))
        people_words = sum(logs.count(w) for w in (" with ", " called ", " met ", " spoke ", " friend", " mum", " dad", " sister", " brother", " partner"))
        return {"heavy_days": len(heavy), "late_share": late / total, "people_words": people_words, "turns": total}

    def check(self, world: World, now: datetime) -> list[Event]:
        if now.hour != self.hour:
            return []
        s = self.signals()
        worrying = (s["heavy_days"] >= self.heavy_days or s["late_share"] >= self.late_share) and s["people_words"] < 3
        if not worrying:
            return []
        return [Event(source="care", importance=0.5, key=f"care:{now.strftime('%Y-%m')}",
                      title="A gentle word about how much we've been talking",
                      body=(f"Over two weeks: {s['turns']} turns, {s['heavy_days']} heavy days, "
                            f"{int(s['late_share'] * 100)}% after midnight, and almost no one else in the log. "
                            "Say it once, kindly, and let it be."))]
