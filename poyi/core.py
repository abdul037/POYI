"""The being itself."""

from dataclasses import dataclass, field

from .identity import INTRO, NAME


@dataclass
class Poyi:
    """A single conversation with Poyi.

    `reply` is the one method to replace when a language model is wired in.
    Everything else (history, introduction, CLI) already works around it.
    """

    history: list[tuple[str, str]] = field(default_factory=list)

    def introduce(self) -> str:
        return INTRO

    def reply(self, message: str) -> str:
        self.history.append(("user", message))
        text = f"({NAME} has no mind wired in yet. You said: {message!r})"
        self.history.append((NAME.lower(), text))
        return text
