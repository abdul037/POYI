"""Tools with judgment.

Every hand goes through the registry, which knows its tier:

    free     read-only; runs immediately
    confirm  a reversible side effect; Poyi states it in one line and waits
             for a go-ahead before it runs
    locked   shell, deleting, money; refused unless explicitly enabled

Every call, allowed or not, is written to the audit log.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol

TIERS = ("free", "confirm", "locked")


class Confirmer(Protocol):
    def ask(self, description: str) -> bool: ...


class DenyAll:
    """Non-interactive default: nothing that needs a go-ahead runs."""

    def ask(self, description: str) -> bool:
        return False


class AllowAll:
    def ask(self, description: str) -> bool:
        return True


class PromptConfirmer:
    """Asks on the terminal. Later fronts (voice, phone) implement the same protocol."""

    def __init__(self, ask_fn: Callable[[str], str] = input, out: Callable[[str], None] = print) -> None:
        self.ask_fn = ask_fn
        self.out = out

    def ask(self, description: str) -> bool:
        try:
            answer = self.ask_fn(f"     poyi wants to: {description}\n     go ahead? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            self.out("")
            return False
        return answer in {"y", "yes"}


@dataclass
class Hand:
    name: str
    tier: str
    describe: Callable[..., str]  # (**kwargs) -> the one-line read-back
    run: Callable[..., Any]       # (**kwargs) -> result
    tool: Any = None              # the @beta_tool wrapper, set by the registry


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def write(self, entry: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text().splitlines()
        out = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out


@dataclass
class Registry:
    audit: AuditLog
    confirmer: Confirmer = field(default_factory=DenyAll)
    unlocked: set[str] = field(default_factory=set)  # names of locked hands that are enabled
    hands: dict[str, Hand] = field(default_factory=dict)

    def add(self, hand: Hand) -> Hand:
        if hand.tier not in TIERS:
            raise ValueError(f"unknown tier {hand.tier!r} for {hand.name}")
        self.hands[hand.name] = hand
        return hand

    def call(self, hand_name: str, /, **kwargs: Any) -> Any:
        name = hand_name
        hand = self.hands[name]
        started = time.time()
        entry: dict[str, Any] = {"at": datetime.now().isoformat(timespec="seconds"), "hand": name,
                                 "tier": hand.tier, "args": kwargs}
        try:
            description = hand.describe(**kwargs)
        except Exception as exc:  # noqa: BLE001
            description = f"{name} {kwargs}"
            entry["describe_error"] = str(exc)
        entry["description"] = description
        if hand.tier == "locked" and name not in self.unlocked:
            entry["outcome"] = "refused: locked"
            self.audit.write(entry)
            return f"Refused: {name} is locked. It can be enabled with POYI_UNLOCK={name}."
        if hand.tier == "confirm":
            if not self.confirmer.ask(description):
                entry["outcome"] = "declined"
                self.audit.write(entry)
                return f"They declined: {description}. Do not retry; ask them what they'd prefer."
            entry["confirmed"] = True
        try:
            result = hand.run(**kwargs)
            entry["outcome"] = "ok"
            entry["result"] = result if isinstance(result, str) else "(non-text)"
        except Exception as exc:  # noqa: BLE001 - the model should hear about failures, not crash
            entry["outcome"] = f"error: {type(exc).__name__}: {exc}"
            result = f"Failed: {type(exc).__name__}: {exc}"
        entry["ms"] = int((time.time() - started) * 1000)
        self.audit.write(entry)
        return result

    def tools(self) -> list[Any]:
        return [h.tool for h in self.hands.values() if h.tool is not None]

    def summary(self) -> list[tuple[str, str, bool]]:
        return [(h.name, h.tier, h.tier != "locked" or h.name in self.unlocked) for h in self.hands.values()]
