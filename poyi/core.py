"""The being itself."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

from poyi.brain.agent import REFUSAL_LINE, Brain, Event
from poyi.config import Settings, has_credentials
from poyi.identity import INTRO, NAME

NO_MIND = (
    f"({NAME} has no mind wired in: no Anthropic credential was found. "
    "Set ANTHROPIC_API_KEY, or run `ant auth login`, then try again.)"
)


@dataclass
class Poyi:
    """A single conversation with Poyi.

    With a `brain`, replies come from Claude. Without one, Poyi says so
    honestly instead of pretending.
    """

    brain: Brain | None = None
    history: list[tuple[str, str]] = field(default_factory=list)

    @classmethod
    def default(cls, settings: Settings | None = None) -> "Poyi":
        settings = settings or Settings.from_env()
        if not has_credentials():
            return cls(brain=None)
        return cls(brain=Brain(settings))

    @property
    def awake(self) -> bool:
        return self.brain is not None

    def introduce(self) -> str:
        return INTRO

    def stream(self, message: str) -> Iterator[Event]:
        self.history.append(("user", message))
        if self.brain is None:
            yield Event("text", NO_MIND)
            self.history.append((NAME.lower(), NO_MIND))
            yield Event("done")
            return
        parts: list[str] = []
        refused = False
        for event in self.brain.stream(message):
            if event.kind == "text":
                parts.append(event.data)
            elif event.kind == "refusal":
                refused = True
            yield event
        text = "".join(parts).strip()
        if not text and refused:
            text = REFUSAL_LINE
        self.history.append((NAME.lower(), text))

    def reply(self, message: str) -> str:
        for _ in self.stream(message):
            pass
        return self.history[-1][1]

    def last_usage(self) -> Any | None:
        return self.brain.last_usage if self.brain else None
