"""Apple Calendar through AppleScript. Reads are free; creating an event asks first.

Reading every calendar with a `whose` filter can take seconds on a big
calendar, so the sensor caches for ten minutes and everything has a timeout.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from anthropic import beta_tool

from poyi.hands.registry import Hand, Registry
from poyi.hands.reminders import parse_when
from poyi.world.model import World
from poyi.world import sensors as _sensors

Runner = Callable[[list[str]], str]

READ_SCRIPT = '''
set startDate to (current date)
set hours of startDate to 0
set minutes of startDate to 0
set seconds of startDate to 0
set endDate to startDate + ({days} * days)
set out to ""
tell application "Calendar"
  repeat with c in calendars
    try
      set evs to (every event of c whose start date is greater than or equal to startDate and start date is less than endDate)
      repeat with e in evs
        set d to start date of e
        set out to out & (year of d) & "-" & text -2 thru -1 of ("0" & ((month of d) as integer)) & "-" & text -2 thru -1 of ("0" & (day of d)) & " " & text -2 thru -1 of ("0" & (hours of d)) & ":" & text -2 thru -1 of ("0" & (minutes of d)) & tab & (summary of e) & tab & (name of c) & linefeed
      end repeat
    end try
  end repeat
end tell
return out
'''

CREATE_SCRIPT = '''
set d to (current date)
set year of d to {year}
set month of d to {month}
set day of d to {day}
set hours of d to {hour}
set minutes of d to {minute}
set seconds of d to 0
tell application "Calendar"
  set c to {calendar}
  tell c to make new event with properties {{summary:"{title}", start date:d, end date:d + ({minutes} * minutes)}}
end tell
return "ok"
'''

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass
class CalendarEvent:
    start: datetime
    title: str
    calendar: str

    def line(self, now: datetime) -> str:
        day = "" if self.start.date() == now.date() else f" {DAYS[self.start.weekday()]}"
        return f"{self.start:%H:%M}{day} {self.title}"


def parse_events(text: str) -> list[CalendarEvent]:
    out = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        try:
            start = datetime.strptime(parts[0].strip(), "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        out.append(CalendarEvent(start, parts[1].strip(), parts[2].strip() if len(parts) > 2 else ""))
    return sorted(out, key=lambda e: e.start)


def read_events(runner: Runner, days: int = 2) -> list[CalendarEvent]:
    return parse_events(runner(["osascript", "-e", READ_SCRIPT.replace("{days}", str(days))]))


def _q(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def register(registry: Registry, *, calendar_name: str = "", runner: Runner | None = None, now_fn=datetime.now) -> None:
    r: Runner = runner or _sensors.run

    def agenda(days: int = 2) -> str:
        now = now_fn()
        events = read_events(r, max(1, min(int(days), 14)))
        if not events:
            return "Nothing on the calendar in that window (or Calendar isn't reachable)."
        return "\n".join(f"{e.start:%a %d %b %H:%M}  {e.title}" + (f"  [{e.calendar}]" if e.calendar else "") for e in events)

    def create_event(title: str, when: str, minutes: int = 60) -> str:
        start = parse_when(when, now_fn())
        calendar = f'calendar "{_q(calendar_name)}"' if calendar_name else "first calendar"
        script = CREATE_SCRIPT.format(year=start.year, month=start.month, day=start.day, hour=start.hour,
                                      minute=start.minute, calendar=calendar, title=_q(title),
                                      minutes=max(5, min(int(minutes), 24 * 60)))
        out = r(["osascript", "-e", script])
        if out.strip() != "ok":
            raise RuntimeError("Calendar didn't confirm the event (is Calendar allowed for Automation?)")
        return f"Added {title!r} on {start:%A %d %B at %H:%M} for {minutes} minutes."

    a = registry.add(Hand("calendar_agenda", "free", lambda days=2: f"read the calendar for {days} day(s)", agenda))
    c = registry.add(Hand("calendar_create", "confirm",
                          lambda title, when, minutes=60: f"add {title!r} to the calendar at {when} for {minutes} min",
                          create_event))

    @beta_tool
    def calendar_agenda(days: int = 2) -> str:
        """What's on the calendar, from today, for the next few days.

        Args:
            days: how many days ahead to look, 1 to 14.
        """
        return registry.call("calendar_agenda", days=days)

    @beta_tool
    def calendar_create(title: str, when: str, minutes: int = 60) -> str:
        """Add an event to the calendar. Asks them first.

        Args:
            title: the event's name.
            when: "tomorrow 9:00", "18:00", "in 2 hours", or an ISO time.
            minutes: how long it lasts.
        """
        return registry.call("calendar_create", title=title, when=when, minutes=minutes)

    a.tool, c.tool = calendar_agenda, calendar_create


@dataclass
class CalendarSensor:
    """Today's and tomorrow's events ride the picture's next list, tagged (calendar)."""

    runner: Runner | None = None
    cache_minutes: int = 10
    name: str = "calendar"
    _cached_at: datetime | None = field(default=None, repr=False)
    _cached: list[CalendarEvent] = field(default_factory=list, repr=False)

    def events(self, now: datetime) -> list[CalendarEvent]:
        if self._cached_at is None or now - self._cached_at >= timedelta(minutes=self.cache_minutes):
            self._cached = read_events(self.runner or _sensors.run)
            self._cached_at = now
        return self._cached

    def read(self, world: World, now: datetime) -> dict[str, Any]:
        kept = [item for item in world.next if not item.endswith("(calendar)")]
        upcoming = [f"{e.line(now)} (calendar)" for e in self.events(now) if e.start >= now - timedelta(minutes=5)]
        return {"next": kept + upcoming[:8]}
