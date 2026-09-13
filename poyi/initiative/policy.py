"""Decide what to do with an event: speak now, mention later, note, or log.

Rules handle the clear cases. Weights learned from feedback nudge the score.
A fast model can break ties in the ambiguous band (see `loop.py`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from poyi.initiative.events import Event
from poyi.world.model import World

SPEAK_AT = 0.70
MENTION_AT = 0.45
NOTE_AT = 0.25
AMBIGUOUS_BAND = 0.06

# How much an interruption costs in each mode, subtracted from the score.
MODE_COST = {"relaxed": 0.0, "focus": 0.25, "meeting": 0.45, "away": 0.15, "asleep": 1.0}
MODE_HARD = {"asleep": "note", "meeting": "note"}  # never speak in these unless urgent
URGENT_MINUTES = 10

FEEDBACK_DELTA = {"not_now": -0.15, "thanks": 0.05, "ignored": -0.03, "mentioned": 0.0}


@dataclass
class Decision:
    route: str
    score: float
    reason: str
    ambiguous: bool = False


class Weights:
    """Per-source and per-(source, mode) adjustments, in [-0.5, 0.5]."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.data: dict[str, float] = {}
        if self.path.exists():
            try:
                self.data = {k: float(v) for k, v in json.loads(self.path.read_text()).items()}
            except (ValueError, TypeError):
                self.data = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n")

    def get(self, source: str, mode: str) -> float:
        return self.data.get(source, 0.0) + self.data.get(f"{source}:{mode}", 0.0)

    def learn(self, source: str, mode: str, feedback: str) -> None:
        delta = FEEDBACK_DELTA.get(feedback, 0.0)
        if not delta:
            return
        for key, share in ((source, 0.5), (f"{source}:{mode}", 1.0)):
            self.data[key] = max(-0.5, min(0.5, self.data.get(key, 0.0) + delta * share))
        self.save()


def time_pressure(event: Event, now: datetime) -> float:
    """0 for nothing due; up to 1 as the due time arrives."""
    minutes = event.due_in_minutes(now)
    if minutes is None:
        return 0.0
    if minutes <= 0:
        return 1.0
    if minutes <= URGENT_MINUTES:
        return 0.9
    if minutes <= 60:
        return 0.5
    if minutes <= 24 * 60:
        return 0.2
    return 0.05


def decide(event: Event, world: World, weights: Weights, now: datetime) -> Decision:
    mode = world.now.mode
    pressure = time_pressure(event, now)
    base = 0.6 * event.importance + 0.4 * pressure
    adjusted = base + weights.get(event.source, mode) - MODE_COST.get(mode, 0.0)
    score = round(max(0.0, min(1.0, adjusted)), 4)
    urgent = event.importance >= 0.8 and pressure >= 0.9

    if mode == "asleep" or (mode in MODE_HARD and not urgent):
        return Decision(MODE_HARD[mode], score, f"{mode}: hard rule, no interruptions")
    if urgent:
        return Decision("speak", max(score, SPEAK_AT), "urgent: important and due now")

    if score >= SPEAK_AT:
        route = "speak"
    elif score >= MENTION_AT:
        route = "mention"
    elif score >= NOTE_AT:
        route = "note"
    else:
        route = "log"
    ambiguous = any(abs(score - t) < AMBIGUOUS_BAND for t in (SPEAK_AT, MENTION_AT, NOTE_AT))
    reason = f"importance {event.importance:.2f}, pressure {pressure:.2f}, mode {mode} (cost {MODE_COST.get(mode, 0):.2f}), learned {weights.get(event.source, mode):+.2f}"
    return Decision(route, score, reason, ambiguous)


def describe_routes() -> dict[str, str]:
    return {
        "speak": "notify now (and say it aloud once there is a voice)",
        "mention": "bring it up at the next natural pause in conversation",
        "note": "leave it in the picture and the next brief, quietly",
        "log": "record only",
    }
