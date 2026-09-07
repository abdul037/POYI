"""The initiative loop: every tick, refresh the picture, run the watchers,
decide, deliver, learn.

    speak    notify now (voice later); "ignored" if nothing comes back in 30 min
    mention  held until the next conversation turn shows it in the picture
    note     appended to the picture's notes, quietly
    log      recorded only
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from poyi.initiative.events import ROUTES, Event, EventLog
from poyi.initiative.notify import Notifier
from poyi.initiative.policy import Decision, Weights, decide
from poyi.world.model import World
from poyi.world.refresh import Refresher

log = logging.getLogger(__name__)

IGNORED_AFTER = timedelta(minutes=30)
Tiebreak = Callable[[Event, World, Decision], str | None]
BriefFn = Callable[[str], str]


class RouteChoice(BaseModel):
    route: str
    reason: str


TIEBREAK_SYSTEM = (
    "You decide whether a companion AI should interrupt its person right now. "
    "Routes: speak (notify now), mention (bring up at the next pause), note (leave it in the picture), log (record only). "
    "Respect their mode: focus and meeting want almost nothing; asleep wants nothing. Pick one route."
)


def make_model_tiebreak(client: Any, model: str) -> Tiebreak:
    def tiebreak(event: Event, world: World, decision: Decision) -> str | None:
        prompt = (
            f"Picture:\n{world.render()}\n\nEvent: {event.title}\n{event.body}\n"
            f"importance {event.importance:.2f}, due {event.due or 'none'}.\n"
            f"The rules score {decision.score:.2f} and lean {decision.route}. Choose the route."
        )
        try:
            response = client.messages.parse(
                model=model, max_tokens=200, system=TIEBREAK_SYSTEM,
                messages=[{"role": "user", "content": prompt}], output_format=RouteChoice,
            )
            route = response.parsed_output.route.strip().lower()
            return route if route in ROUTES else None
        except Exception as exc:  # noqa: BLE001 - a tiebreak failure just keeps the rules' answer
            log.warning("tiebreak failed: %s", exc)
            return None

    return tiebreak


class Initiative:
    def __init__(
        self,
        root: Path,
        refresher: Refresher,
        watchers: list[Any],
        notifier: Notifier,
        *,
        tiebreak: Tiebreak | None = None,
        brief: BriefFn | None = None,
    ) -> None:
        self.root = Path(root) / "initiative"
        self.log = EventLog(self.root)
        self.weights = Weights(self.root / "weights.json")
        self.refresher = refresher
        self.watchers = watchers
        self.notifier = notifier
        self.tiebreak = tiebreak
        self.brief = brief
        self.shown: list[str] = []  # mention ids included in the last picture

    # --- the tick ------------------------------------------------------------------

    def tick(self, now: datetime | None = None) -> list[Event]:
        now = now or datetime.now()
        self.refresher.refresh(now)
        world = self.refresher.world
        seen = self.log.seen_keys()
        handled: list[Event] = []
        for watcher in self.watchers:
            try:
                events = watcher.check(world, now)
            except Exception as exc:  # noqa: BLE001 - one broken watcher must not stop the rest
                log.warning("watcher %s failed: %s", getattr(watcher, "name", watcher), exc)
                continue
            for event in events:
                if event.key and event.key in seen:
                    continue
                seen.add(event.key)
                self.route(event, world, now)
                self.deliver(event, now)
                self.log.append(event)
                handled.append(event)
        self.expire(now)
        return handled

    def route(self, event: Event, world: World, now: datetime) -> Decision:
        decision = decide(event, world, self.weights, now)
        if decision.ambiguous and self.tiebreak:
            choice = self.tiebreak(event, world, decision)
            if choice in ROUTES and choice != decision.route:
                decision.reason += f"; tiebreak chose {choice} over {decision.route}"
                decision.route = choice
        event.route, event.score, event.reason, event.mode = decision.route, decision.score, decision.reason, world.now.mode
        return decision

    def deliver(self, event: Event, now: datetime) -> None:
        if event.source == "brief" and self.brief and event.route in ("speak", "mention"):
            kind = "morning" if "morning" in event.title.lower() else "evening"
            try:
                event.body = self.brief(kind)
            except Exception as exc:  # noqa: BLE001
                event.body = f"(brief failed: {type(exc).__name__}: {exc})"
        if event.route == "speak":
            body = event.body.splitlines()[0] if event.body else ""
            self.notifier.send(event.title, body, voice=self.refresher.world.now.mode == "relaxed")
            event.delivered_at = now.isoformat(timespec="seconds")
        elif event.route == "note":
            self.refresher.note({"__append__": {"notes": [event.title]}}, now)

    def expire(self, now: datetime) -> None:
        for event in self.log.undelivered_speaks():
            try:
                delivered = datetime.fromisoformat(event.delivered_at)
            except ValueError:
                continue
            if now - delivered >= IGNORED_AFTER:
                self.feedback(event.id, "ignored")

    # --- feedback and the picture -----------------------------------------------------

    def feedback(self, event_id: str, verdict: str) -> Event | None:
        event = self.log.get(event_id)
        if event is None:
            return None
        event.feedback = verdict
        self.weights.learn(event.source, event.mode or self.refresher.world.now.mode, verdict)
        self.log.append(event)
        return event

    def render_for_picture(self, now: datetime | None = None) -> str:
        now = now or datetime.now()
        lines: list[str] = []
        pending = self.log.pending_mentions()
        self.shown = [e.id for e in pending]
        if pending:
            lines.append("mention:")
            lines.extend(f"  - [{e.id}] {e.title}" for e in pending[:6])
        recent = [e for e in self.log.undelivered_speaks() if e.delivered_at]
        if recent:
            lines.append("recent:")
            for e in recent[-3:]:
                try:
                    ago = int((now - datetime.fromisoformat(e.delivered_at)).total_seconds() // 60)
                except ValueError:
                    ago = 0
                lines.append(f"  - [{e.id}] {e.title} (notified {ago} min ago)")
        return "\n".join(lines)

    def mark_shown_mentioned(self, now: datetime | None = None) -> int:
        now = now or datetime.now()
        count = 0
        for event_id in self.shown:
            event = self.log.get(event_id)
            if event and not event.delivered_at:
                event.delivered_at = now.isoformat(timespec="seconds")
                event.feedback = "mentioned"
                self.log.append(event)
                count += 1
        self.shown = []
        return count

    def recent(self, limit: int = 20) -> list[Event]:
        return self.log.recent(limit)
