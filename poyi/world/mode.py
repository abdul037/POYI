"""Mode: the one field that gates initiative.

    asleep   inside quiet hours, or idle for a long time at night
    meeting  a call or meeting app is frontmost
    away     not at home and not at the machine
    focus    the same working activity for a while with little idling
    relaxed  everything else

A manual mode with an expiry always wins.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from poyi.world.model import MODES, World

FOCUS_ACTIVITIES = {"coding", "writing", "reading"}


def parse_quiet_hours(spec: str) -> tuple[time, time] | None:
    """'23:00-07:00' -> (time(23), time(7)). Empty or bad input -> None."""
    try:
        start, end = spec.split("-")
        h1, m1 = (int(x) for x in start.strip().split(":"))
        h2, m2 = (int(x) for x in end.strip().split(":"))
        return time(h1, m1), time(h2, m2)
    except (ValueError, AttributeError):
        return None


def in_window(now: time, window: tuple[time, time]) -> bool:
    start, end = window
    if start <= end:
        return start <= now < end
    return now >= start or now < end  # wraps midnight


@dataclass
class Override:
    mode: str
    until: datetime

    def active(self, now: datetime) -> bool:
        return self.mode in MODES and now < self.until

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "until": self.until.isoformat(timespec="seconds")}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Override | None":
        if not data:
            return None
        try:
            return cls(mode=data["mode"], until=datetime.fromisoformat(data["until"]))
        except (KeyError, ValueError):
            return None


def parse_duration(text: str) -> timedelta:
    """'90m', '2h', '45' (minutes), '1h30m'."""
    text = text.strip().lower()
    if text.isdigit():
        return timedelta(minutes=int(text))
    total = timedelta()
    number = ""
    for ch in text:
        if ch.isdigit():
            number += ch
        elif ch in "hm" and number:
            total += timedelta(hours=int(number)) if ch == "h" else timedelta(minutes=int(number))
            number = ""
        else:
            raise ValueError(f"bad duration: {text!r}")
    if number:
        raise ValueError(f"bad duration: {text!r}")
    return total


def infer_mode(
    world: World,
    *,
    now: datetime,
    quiet_hours: str = "23:00-07:00",
    focus_after_min: int = 25,
    same_activity_minutes: int = 0,
    override: Override | None = None,
) -> tuple[str, str]:
    """Return (mode, source)."""
    if override and override.active(now):
        return override.mode, "manual"
    n = world.now
    window = parse_quiet_hours(quiet_hours)
    if window and in_window(now.time(), window) and n.idle_minutes >= 10:
        return "asleep", "inferred"
    if n.activity == "meeting":
        return "meeting", "inferred"
    if n.place == "away" or (n.place == "unknown" and n.idle_minutes >= 60):
        return "away", "inferred"
    if n.activity in FOCUS_ACTIVITIES and same_activity_minutes >= focus_after_min and n.idle_minutes < 5:
        return "focus", "inferred"
    return "relaxed", "inferred"
