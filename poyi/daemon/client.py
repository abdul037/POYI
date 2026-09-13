"""What the fronts use to talk to the daemon."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any, Callable, Iterator

from poyi.brain.agent import Event
from poyi.daemon.protocol import alive, lines, send, socket_path


class DaemonClient:
    def __init__(self, path: Path, timeout: float = 600.0) -> None:
        self.path = Path(path)
        self.timeout = timeout

    @classmethod
    def for_home(cls, home: Path) -> "DaemonClient":
        return cls(socket_path(home))

    def alive(self) -> bool:
        return alive(self.path)

    def _connect(self) -> socket.socket:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(str(self.path))
        return s

    def request(self, message: dict[str, Any]) -> dict[str, Any]:
        s = self._connect()
        try:
            send(s, message)
            return next(lines(s), {"type": "error", "text": "no reply"})
        finally:
            s.close()

    def say(self, text: str, confirm: Callable[[str], bool] | None = None) -> Iterator[Event]:
        """Stream a reply. `confirm` answers the daemon's go-ahead questions."""
        s = self._connect()
        try:
            send(s, {"type": "say", "text": text})
            for message in lines(s):
                kind = message.get("type")
                if kind == "confirm":
                    yes = confirm(str(message.get("description", ""))) if confirm else False
                    send(s, {"type": "answer", "yes": yes})
                elif kind == "done":
                    yield Event("done")
                    return
                elif kind == "error":
                    yield Event("text", f"(daemon error: {message.get('text')})")
                    yield Event("done")
                    return
                else:
                    yield Event(str(kind), str(message.get("data", "")))
        finally:
            s.close()

    def picture(self) -> str:
        return str(self.request({"type": "picture"}).get("text", ""))

    def status(self) -> dict[str, Any]:
        return self.request({"type": "status"})

    def mode(self, mode: str, minutes: int = 120) -> str:
        return str(self.request({"type": "mode", "mode": mode, "minutes": minutes}).get("text", ""))

    def tick(self) -> list[dict[str, Any]]:
        return list(self.request({"type": "tick"}).get("events", []))

    def stop(self) -> None:
        self.request({"type": "stop"})
