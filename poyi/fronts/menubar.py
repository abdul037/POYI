"""The menubar: status, mode, mute, and the last few things Poyi brought up.

Needs `rumps` (pip install 'poyi[menubar]'). Talks to the daemon over its
socket; nothing here touches the brain directly.
"""

from __future__ import annotations

from typing import Any

from poyi.daemon.client import DaemonClient
from poyi.identity import NAME
from poyi.world.model import MODES

ICONS = {"relaxed": "◦", "focus": "●", "meeting": "■", "away": "○", "asleep": "z"}


def title_for(status: dict[str, Any]) -> str:
    if not status or status.get("type") == "error":
        return f"{NAME} ·"
    icon = ICONS.get(str(status.get("mode", "")), "·")
    pending = int(status.get("pending", 0) or 0)
    return f"{NAME} {icon}" + (f" {pending}" if pending else "")


def status_lines(status: dict[str, Any]) -> list[str]:
    if not status or status.get("type") == "error":
        return ["daemon not running", "start it with: poyi daemon"]
    lines = [f"mode: {status.get('mode', '?')}", f"doing: {status.get('activity', '?')}", f"place: {status.get('place', '?')}"]
    if status.get("pending"):
        lines.append(f"waiting to mention: {status['pending']}")
    lines.append("awake" if status.get("awake") else "no credential")
    return lines


def run(client: DaemonClient) -> int:
    try:
        import rumps
    except ImportError:
        print("rumps is not installed: pip install 'poyi[menubar]'")
        return 1

    class App(rumps.App):
        def __init__(self) -> None:
            super().__init__(NAME, quit_button="Quit")
            self.status_items = [rumps.MenuItem(line) for line in status_lines({})]
            mode_menu = rumps.MenuItem("Mode")
            for mode in MODES:
                mode_menu.add(rumps.MenuItem(mode, callback=self.set_mode))
            mode_menu.add(rumps.MenuItem("infer", callback=self.set_mode))
            self.menu = [*self.status_items, None, mode_menu, rumps.MenuItem("Tick now", callback=self.tick), None]
            self.timer = rumps.Timer(self.refresh, 20)
            self.timer.start()
            self.refresh(None)

        def refresh(self, _sender: Any) -> None:
            try:
                status = client.status() if client.alive() else {}
            except OSError:
                status = {}
            self.title = title_for(status)
            for item, line in zip(self.status_items, status_lines(status)):
                item.title = line

        def set_mode(self, sender: Any) -> None:
            mode = "off" if sender.title == "infer" else sender.title
            try:
                rumps.notification(NAME, "", client.mode(mode))
            except OSError:
                rumps.notification(NAME, "", "daemon not running")
            self.refresh(None)

        def tick(self, _sender: Any) -> None:
            try:
                events = client.tick()
                rumps.notification(NAME, "", f"{len(events)} event(s)")
            except OSError:
                rumps.notification(NAME, "", "daemon not running")

    App().run()
    return 0
