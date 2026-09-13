"""The world model: a small, always-current picture of the person.

Rendered into every turn in under 800 tokens. Sensors update it on a timer;
the brain updates it after a turn when something it heard changes the picture.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

MODES = ("relaxed", "focus", "meeting", "away", "asleep")
PLACES = ("home", "away", "unknown")


@dataclass
class Now:
    time: str = ""            # "Sunday 7 September 2026, 21:40"
    part_of_day: str = ""     # morning / afternoon / evening / night
    place: str = "unknown"    # home / away / unknown
    activity: str = "unknown" # coding / meeting / browsing / messaging / listening / idle / unknown
    app: str = ""             # frontmost app name, when known
    window: str = ""          # front window title, coarse
    idle_minutes: int = 0     # since the last keyboard or mouse input
    mode: str = "relaxed"     # relaxed / focus / meeting / away / asleep
    mode_source: str = "inferred"  # inferred / manual


@dataclass
class World:
    now: Now = field(default_factory=Now)
    next: list[str] = field(default_factory=list)      # "09:00 Mon  Standup (video)"
    people: list[str] = field(default_factory=list)    # "Sam: messaged 2h ago, unanswered"
    threads: list[str] = field(default_factory=list)   # open loops, from memory
    home: dict[str, str] = field(default_factory=dict) # "office lights": "on"
    notes: list[str] = field(default_factory=list)     # things the brain wrote back
    updated: str = ""                                  # ISO timestamp of the last refresh

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "World":
        now = Now(**{k: v for k, v in (data.get("now") or {}).items() if k in Now.__dataclass_fields__})
        return cls(
            now=now,
            next=list(data.get("next") or []),
            people=list(data.get("people") or []),
            threads=list(data.get("threads") or []),
            home=dict(data.get("home") or {}),
            notes=list(data.get("notes") or []),
            updated=data.get("updated") or "",
        )

    def touch(self, when: datetime | None = None) -> None:
        self.updated = (when or datetime.now()).isoformat(timespec="seconds")

    def render(self, max_items: int = 6) -> str:
        """A compact YAML-like block for the prompt."""
        n = self.now
        lines = ["now:"]
        if n.time:
            lines.append(f"  time: {n.time}" + (f" ({n.part_of_day})" if n.part_of_day else ""))
        lines.append(f"  place: {n.place}")
        activity = n.activity
        if n.app:
            activity += f" ({n.app}" + (f": {n.window}" if n.window else "") + ")"
        lines.append(f"  activity: {activity}")
        if n.idle_minutes >= 5:
            lines.append(f"  idle: {n.idle_minutes} min")
        lines.append(f"  mode: {n.mode}" + (" (set by them)" if n.mode_source == "manual" else ""))

        def section(name: str, items: list[str]) -> None:
            if not items:
                return
            lines.append(f"{name}:")
            for item in items[:max_items]:
                lines.append(f"  - {item}")
            if len(items) > max_items:
                lines.append(f"  - (+{len(items) - max_items} more)")

        section("next", self.next)
        section("people", self.people)
        section("threads", self.threads)
        if self.home:
            lines.append("home:")
            for k, v in list(self.home.items())[:max_items]:
                lines.append(f"  {k}: {v}")
        section("notes", self.notes)
        return "\n".join(lines)
