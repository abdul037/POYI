"""Run the sensors, infer the mode, persist, and record what changed."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from poyi.config import Settings
from poyi.world.mode import infer_mode
from poyi.world.model import Now, World
from poyi.world.store import WorldStore

NOW_FIELDS = set(Now.__dataclass_fields__)
LIST_FIELDS = {"next", "people", "threads", "notes"}


def apply(world: World, updates: dict[str, Any]) -> dict[str, Any]:
    """Apply sensor updates; return the fields that actually changed."""
    changed: dict[str, Any] = {}
    for key, value in updates.items():
        if key in NOW_FIELDS:
            if getattr(world.now, key) != value:
                setattr(world.now, key, value)
                changed[key] = value
        elif key in LIST_FIELDS:
            if getattr(world, key) != list(value):
                setattr(world, key, list(value))
                changed[key] = list(value)
        elif key == "home":
            merged = {**world.home, **dict(value)}
            if merged != world.home:
                world.home = merged
                changed["home"] = merged
    return changed


class Refresher:
    """Owns the world in memory and knows how long the activity has been steady."""

    def __init__(self, store: WorldStore, sensors: list[Any], settings: Settings) -> None:
        self.store = store
        self.sensors = sensors
        self.settings = settings
        self.world = store.load()
        self._activity_since: datetime | None = None
        self._last_refresh: datetime | None = None
        self._holds: dict[str, datetime] = {}  # fields the brain set; sensors leave them alone for a while
        self.hold_for = timedelta(minutes=30)

    def refresh(self, now: datetime | None = None, *, force: bool = False) -> dict[str, Any]:
        now = now or datetime.now()
        if not force and self._last_refresh and (now - self._last_refresh).total_seconds() < self.settings.world_refresh_s:
            return {}
        self._last_refresh = now
        changed: dict[str, Any] = {}
        before_activity = self.world.now.activity
        for sensor in self.sensors:
            try:
                reads = sensor.read(self.world, now)
                reads = {k: v for k, v in reads.items() if not (k in self._holds and now < self._holds[k])}
                changed.update(apply(self.world, reads))
            except Exception as exc:  # noqa: BLE001 - a broken sensor must not stop the rest
                changed[f"{sensor.name}_error"] = f"{type(exc).__name__}: {exc}"
        if self.world.now.activity != before_activity or self._activity_since is None:
            self._activity_since = now
        steady = int((now - self._activity_since).total_seconds() // 60)
        mode, source = infer_mode(
            self.world,
            now=now,
            quiet_hours=self.settings.quiet_hours,
            focus_after_min=self.settings.focus_after_min,
            same_activity_minutes=steady,
            override=self.store.override(),
        )
        if (mode, source) != (self.world.now.mode, self.world.now.mode_source):
            self.world.now.mode, self.world.now.mode_source = mode, source
            changed["mode"] = mode
        self.world.touch(now)
        self.store.save(self.world)
        # Time ticking is not a change worth recording.
        recorded = {k: v for k, v in changed.items() if k not in {"time", "part_of_day"}}
        self.store.record(recorded, now)
        return changed

    def note(self, updates: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
        """Apply an update from the brain (not a sensor) and persist it."""
        now = now or datetime.now()
        updates = dict(updates)
        appends: dict[str, list[str]] = updates.pop("__append__", None) or {}
        changed = apply(self.world, updates)
        for key in changed:
            self._holds[key] = now + self.hold_for
        for key, items in appends.items():
            if key not in LIST_FIELDS:
                continue
            current: list[str] = getattr(self.world, key)
            for item in items:
                if item and item not in current:
                    current.append(item)
                    changed.setdefault(key, []).append(item)
            del current[:-12]
        self.world.touch(now)
        self.store.save(self.world)
        self.store.record({"from": "brain", **changed}, now)
        return changed

    def render(self) -> str:
        return self.world.render()
