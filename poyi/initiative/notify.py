"""Getting a word to the person. Desktop notification now; voice and phone later."""

from __future__ import annotations

from typing import Any, Callable

from poyi.identity import NAME
from poyi.world import sensors as _sensors


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def notify_macos(title: str, body: str, runner: Callable[[list[str]], str] | None = None) -> bool:
    runner = runner or _sensors.run
    script = f'display notification "{_escape(body)}" with title "{_escape(NAME)}" subtitle "{_escape(title)}"'
    out = runner(["osascript", "-e", script])
    return out is not None


class Notifier:
    """Sends to every channel it has. Returns True if at least one worked."""

    def __init__(self, *, desktop: bool = True, printer: Callable[[str], None] | None = None,
                 runner: Callable[[list[str]], str] | None = None, speaker: Any | None = None) -> None:
        self.desktop = desktop
        self.printer = printer
        self.runner = runner
        self.speaker = speaker  # a voice.Speaker, when voice is on
        self.sent: list[tuple[str, str]] = []
        self.spoken: list[str] = []

    def send(self, title: str, body: str = "", *, voice: bool = True) -> bool:
        self.sent.append((title, body))
        ok = False
        if self.printer:
            self.printer(f"{NAME}: {title}" + (f" — {body}" if body else ""))
            ok = True
        if self.desktop:
            ok = notify_macos(title, body, runner=self.runner) or ok
        if self.speaker is not None and voice:
            line = title if not body else f"{title}. {body}"
            self.spoken.append(line)
            self.speaker.enqueue(line)
            self.speaker.finish()
            ok = True
        return ok
