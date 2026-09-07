"""Getting a word to the person. Desktop notification now; voice and phone later."""

from __future__ import annotations

from typing import Callable

from poyi.identity import NAME
from poyi.world.sensors import run


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def notify_macos(title: str, body: str, runner: Callable[[list[str]], str] = run) -> bool:
    script = f'display notification "{_escape(body)}" with title "{_escape(NAME)}" subtitle "{_escape(title)}"'
    out = run(["osascript", "-e", script]) if runner is run else runner(["osascript", "-e", script])
    return out is not None


class Notifier:
    """Sends to every channel it has. Returns True if at least one worked."""

    def __init__(self, *, desktop: bool = True, printer: Callable[[str], None] | None = None,
                 runner: Callable[[list[str]], str] | None = None) -> None:
        self.desktop = desktop
        self.printer = printer
        self.runner = runner
        self.sent: list[tuple[str, str]] = []

    def send(self, title: str, body: str = "") -> bool:
        self.sent.append((title, body))
        ok = False
        if self.printer:
            self.printer(f"{NAME}: {title}" + (f" — {body}" if body else ""))
            ok = True
        if self.desktop:
            ok = notify_macos(title, body, runner=self.runner or run) or ok
        return ok
