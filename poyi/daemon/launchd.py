"""Start at login, restart on crash: a launchd user agent."""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path
from typing import Callable

LABEL = "com.poyi.daemon"


def plist_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def build_plist(python: str, log_dir: Path, env: dict[str, str] | None = None) -> bytes:
    log_dir = Path(log_dir)
    data = {
        "Label": LABEL,
        "ProgramArguments": [python, "-m", "poyi.cli", "daemon"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Interactive",
        "StandardOutPath": str(log_dir / "daemon.log"),
        "StandardErrorPath": str(log_dir / "daemon.err"),
        "EnvironmentVariables": {"PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin", **(env or {})},
    }
    return plistlib.dumps(data)


def install(poyi_home: Path, *, python: str | None = None, run: Callable[[list[str]], str] | None = None,
            plist: Path | None = None) -> Path:
    target = plist or plist_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    log_dir = Path(poyi_home) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    target.write_bytes(build_plist(python or sys.executable, log_dir, {"POYI_HOME": str(poyi_home)}))
    if run:
        run(["launchctl", "unload", str(target)])
        run(["launchctl", "load", str(target)])
    return target


def uninstall(*, run: Callable[[list[str]], str] | None = None, plist: Path | None = None) -> bool:
    target = plist or plist_path()
    if not target.exists():
        return False
    if run:
        run(["launchctl", "unload", str(target)])
    target.unlink()
    return True
