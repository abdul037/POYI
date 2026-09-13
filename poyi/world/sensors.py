"""Sensors update the world on a timer. Each one is cheap, has a hard timeout,
and degrades to "unknown" rather than blocking or raising.

Everything that shells out goes through `run()`, so a sensor can never hang
the daemon on a permission dialog.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Protocol

from poyi.config import Settings
from poyi.world.model import World

Runner = Callable[[list[str]], str]


def run(argv: list[str], timeout: float = 3.0) -> str:
    """Run a command and return stdout, or "" on any failure or timeout."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


class Sensor(Protocol):
    name: str

    def read(self, world: World, now: datetime) -> dict[str, Any]:
        """Return the fields of `world.now` (or top-level lists) to update."""


def part_of_day(now: datetime) -> str:
    h = now.hour
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 22:
        return "evening"
    return "night"


@dataclass
class ClockSensor:
    name: str = "clock"

    def read(self, world: World, now: datetime) -> dict[str, Any]:
        return {"time": now.strftime("%A %-d %B %Y, %H:%M"), "part_of_day": part_of_day(now)}


ACTIVITY_BY_APP = {
    "code": "coding", "cursor": "coding", "xcode": "coding", "terminal": "coding", "iterm2": "coding",
    "warp": "coding", "claude": "coding", "pycharm": "coding", "intellij idea": "coding",
    "zoom.us": "meeting", "zoom": "meeting", "microsoft teams": "meeting", "facetime": "meeting",
    "google meet": "meeting", "webex": "meeting",
    "safari": "browsing", "google chrome": "browsing", "arc": "browsing", "firefox": "browsing",
    "brave browser": "browsing",
    "slack": "messaging", "messages": "messaging", "whatsapp": "messaging", "telegram": "messaging",
    "discord": "messaging", "mail": "messaging",
    "spotify": "listening", "music": "listening",
    "notes": "writing", "pages": "writing", "obsidian": "writing", "notion": "writing",
    "microsoft word": "writing", "textedit": "writing",
    "preview": "reading", "books": "reading", "kindle": "reading",
    "finder": "unknown",
}

FRONT_APP = ['osascript', '-e', 'tell application "System Events" to get name of first application process whose frontmost is true']
FRONT_WINDOW = ['osascript', '-e', 'tell application "System Events" to tell (first application process whose frontmost is true) to get name of front window']
IDLE_SECONDS = ["sh", "-c", "ioreg -c IOHIDSystem | awk '/HIDIdleTime/ {print $NF/1000000000; exit}'"]


@dataclass
class ActiveAppSensor:
    """Frontmost app, a coarse window title, and idle time. macOS only."""

    runner: Runner | None = None  # resolved at call time so tests can patch `run`
    name: str = "active_app"
    max_title: int = 60

    def read(self, world: World, now: datetime) -> dict[str, Any]:
        runner = self.runner or run
        app = runner(FRONT_APP)
        out: dict[str, Any] = {}
        if app:
            out["app"] = app
            out["activity"] = ACTIVITY_BY_APP.get(app.lower(), "unknown")
            title = runner(FRONT_WINDOW)
            out["window"] = title[: self.max_title] if title else ""
        idle = runner(IDLE_SECONDS)
        try:
            minutes = int(float(idle) // 60) if idle else 0
        except ValueError:
            minutes = 0
        out["idle_minutes"] = minutes
        if minutes >= 15 and out.get("activity", world.now.activity) != "meeting":
            out["activity"] = "idle"
        return out


SSID_IPCONFIG = ["sh", "-c", "ipconfig getsummary en0 | awk -F' SSID : ' '/ SSID : /{print $2}'"]
SSID_NETWORKSETUP = ["sh", "-c", "networksetup -getairportnetwork en0 | sed -n 's/^Current Wi-Fi Network: //p'"]


@dataclass
class PlaceSensor:
    """Home or away from the Wi-Fi network name. Needs POYI_HOME_SSID."""

    home_ssid: str = ""
    runner: Runner | None = None
    name: str = "place"

    def read(self, world: World, now: datetime) -> dict[str, Any]:
        if not self.home_ssid:
            return {}
        runner = self.runner or run
        ssid = runner(SSID_IPCONFIG) or runner(SSID_NETWORKSETUP)
        if not ssid:
            return {"place": "unknown"}
        return {"place": "home" if ssid.strip() == self.home_ssid else "away"}


@dataclass
class ThreadsSensor:
    """Open loops from memory's threads.md, as short lines."""

    read_threads: Callable[[], str]
    name: str = "threads"
    limit: int = 8

    def read(self, world: World, now: datetime) -> dict[str, Any]:
        items: list[str] = []
        heading = ""
        for raw in self.read_threads().splitlines():
            line = raw.strip()
            if line.startswith("## "):
                heading = line[3:].strip().lower()
            elif line.startswith("- ") and heading:
                items.append(f"{heading}: {line[2:].strip()}")
        return {"threads": items[: self.limit]}


def default_sensors(settings: Settings, read_threads: Callable[[], str] | None = None) -> list[Any]:
    sensors: list[Any] = [ClockSensor(), ActiveAppSensor(), PlaceSensor(home_ssid=settings.home_ssid)]
    if read_threads is not None:
        sensors.append(ThreadsSensor(read_threads=read_threads))
    return sensors
