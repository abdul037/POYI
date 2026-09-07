"""Build the registry for this installation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from poyi.config import Settings
from poyi.hands import macos, reminders, shell
from poyi.hands.registry import AuditLog, Confirmer, DenyAll, Registry
from poyi.world.model import World


@dataclass
class Hands:
    registry: Registry
    reminders: reminders.ReminderStore
    watchers: list[Any]
    sensors: list[Any]

    def tools(self) -> list[Any]:
        return self.registry.tools()


@dataclass
class RemindersSensor:
    """Upcoming reminders ride the picture's `next` list, tagged so they merge cleanly."""

    watcher: reminders.ReminderWatcher
    name: str = "reminders"

    def read(self, world: World, now: datetime) -> dict[str, Any]:
        kept = [item for item in world.next if not item.endswith("(reminder)")]
        upcoming = [f"{line} (reminder)" for line in self.watcher.upcoming(now)]
        return {"next": kept + upcoming}


def build_hands(settings: Settings, *, confirmer: Confirmer | None = None, root: Path | None = None,
                runner: Any | None = None) -> Hands:
    root = root or settings.home
    registry = Registry(AuditLog(root / "hands" / "audit.jsonl"), confirmer or DenyAll(), set(settings.unlock))
    store = reminders.ReminderStore(root / "reminders.json")
    reminders.register(registry, store)
    macos.register(registry, runner=runner, screenshot_dir=root / "hands")
    shell.register(registry, settings.shell_allow, runner=runner)
    watcher = reminders.ReminderWatcher(store)
    return Hands(registry=registry, reminders=store, watchers=[watcher], sensors=[RemindersSensor(watcher)])
