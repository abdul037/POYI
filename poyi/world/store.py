"""Persistence for the world: one JSON file, plus an append-only history of changes."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from poyi.world.mode import Override
from poyi.world.model import World


class WorldStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "world.json"
        self.history_path = self.root / "world-history.jsonl"
        self.override_path = self.root / "world-override.json"

    def load(self) -> World:
        if self.path.exists():
            try:
                return World.from_dict(json.loads(self.path.read_text()))
            except (ValueError, TypeError):
                pass
        return World()

    def save(self, world: World) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(world.to_dict(), indent=2) + "\n")

    def record(self, changes: dict[str, Any], when: datetime | None = None) -> None:
        """Append what changed, so later phases can learn from the past."""
        if not changes:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        entry = {"at": (when or datetime.now()).isoformat(timespec="seconds"), **changes}
        with self.history_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def override(self) -> Override | None:
        if not self.override_path.exists():
            return None
        try:
            return Override.from_dict(json.loads(self.override_path.read_text()))
        except ValueError:
            return None

    def set_override(self, override: Override | None) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if override is None:
            if self.override_path.exists():
                self.override_path.unlink()
            return
        self.override_path.write_text(json.dumps(override.to_dict()) + "\n")
