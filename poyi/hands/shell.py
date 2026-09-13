"""The shell: locked by default, and even when unlocked, only allowlisted prefixes."""

from __future__ import annotations

import shlex
import subprocess
from typing import Callable

from anthropic import beta_tool

from poyi.hands.registry import Hand, Registry


def register(registry: Registry, allow: list[str], *, runner: Callable[[list[str]], str] | None = None) -> None:
    def allowed(command: str) -> bool:
        parts = shlex.split(command)
        if not parts:
            return False
        for prefix in allow:
            want = shlex.split(prefix)
            if parts[: len(want)] == want:
                return True
        return False

    def run_shell(command: str) -> str:
        if not allowed(command):
            return f"Not allowed: {command!r} is outside the allowlist ({', '.join(allow) or 'empty'})."
        if runner:
            return runner(shlex.split(command))
        proc = subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=30, check=False)
        out = (proc.stdout + proc.stderr).strip()
        return out[:6000] if out else f"(exit {proc.returncode}, no output)"

    hand = registry.add(Hand("run_shell", "locked", lambda command: f"run `{command}`", run_shell))

    @beta_tool
    def run_shell(command: str) -> str:  # noqa: F811
        """Run a shell command. Locked unless they have enabled it, and then only commands
        that start with an allowlisted prefix.

        Args:
            command: the command line, e.g. "git status".
        """
        return registry.call("run_shell", command=command)

    hand.tool = run_shell
