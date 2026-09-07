"""Hands on the Mac: apps, URLs, clipboard, media, and a look at the screen.

All through `run()` with timeouts, all fake-able through `runner`.
"""

from __future__ import annotations

import base64
import re
import tempfile
from pathlib import Path
from typing import Any, Callable

from anthropic import beta_tool

from poyi.hands.registry import Hand, Registry
from poyi.world.sensors import run

Runner = Callable[[list[str]], str]
URL_RE = re.compile(r"^https?://[^\s]+$", re.I)


def _osa(script: str) -> list[str]:
    return ["osascript", "-e", script]


def _q(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def register(registry: Registry, *, runner: Runner | None = None, screenshot_dir: Path | None = None) -> None:
    r: Runner = runner or run

    # --- apps and URLs -----------------------------------------------------------------
    def open_app(name: str) -> str:
        if not re.match(r"^[\w .\-]+$", name):
            raise ValueError("odd app name")
        out = r(["open", "-a", name])
        return f"Opened {name}." if out == "" else out

    def open_url(url: str) -> str:
        if not URL_RE.match(url):
            raise ValueError("only http(s) URLs")
        r(["open", url])
        return f"Opened {url}."

    # --- clipboard ------------------------------------------------------------------------
    def clipboard_read() -> str:
        text = r(["pbpaste"])
        return text[:4000] if text else "(clipboard is empty or not text)"

    def clipboard_write(text: str) -> str:
        r(["sh", "-c", f"printf %s {_shell_quote(text)} | pbcopy"])
        return "Copied to the clipboard."

    # --- media ------------------------------------------------------------------------------
    def media(action: str) -> str:
        action = action.strip().lower()
        if action in {"play", "pause", "playpause", "play_pause", "toggle"}:
            r(_osa('tell application "Music" to playpause'))
            r(_osa('tell application "Spotify" to playpause'))
            return "Toggled play/pause."
        if action in {"next", "skip"}:
            r(_osa('tell application "Spotify" to next track'))
            r(_osa('tell application "Music" to next track'))
            return "Skipped."
        if action in {"previous", "back"}:
            r(_osa('tell application "Spotify" to previous track'))
            r(_osa('tell application "Music" to previous track'))
            return "Went back a track."
        if action == "mute":
            r(_osa("set volume with output muted"))
            return "Muted."
        if action == "unmute":
            r(_osa("set volume without output muted"))
            return "Unmuted."
        m = re.match(r"^volume\s+(\d{1,3})$", action)
        if m:
            level = max(0, min(100, int(m.group(1))))
            r(_osa(f"set volume output volume {level}"))
            return f"Volume {level}."
        raise ValueError("action must be play, pause, next, previous, mute, unmute, or 'volume N'")

    # --- the screen -------------------------------------------------------------------------
    def look_at_screen() -> Any:
        folder = screenshot_dir or Path(tempfile.gettempdir())
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "poyi-screen.png"
        r(["screencapture", "-x", "-t", "png", str(path)])
        if not path.exists() or path.stat().st_size == 0:
            return "Couldn't capture the screen (Screen Recording permission?)."
        data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
        try:
            path.unlink()
        except OSError:
            pass
        return [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
            {"type": "text", "text": "The screen right now."},
        ]

    hands = [
        Hand("open_app", "free", lambda name: f"open {name}", open_app),
        Hand("open_url", "free", lambda url: f"open {url}", open_url),
        Hand("clipboard_read", "free", lambda: "read the clipboard", clipboard_read),
        Hand("clipboard_write", "free", lambda text: f"copy {text[:40]!r} to the clipboard", clipboard_write),
        Hand("media", "free", lambda action: f"media: {action}", media),
        Hand("look_at_screen", "free", lambda: "take a look at the screen", look_at_screen),
    ]
    for h in hands:
        registry.add(h)

    @beta_tool
    def open_app(name: str) -> str:  # noqa: F811 - the tool wraps the hand of the same name
        """Open or switch to an app on the Mac.

        Args:
            name: the app's name, e.g. "Safari", "Spotify", "Visual Studio Code".
        """
        return registry.call("open_app", name=name)

    @beta_tool
    def open_url(url: str) -> str:  # noqa: F811
        """Open a web address in the default browser.

        Args:
            url: a full http or https URL.
        """
        return registry.call("open_url", url=url)

    @beta_tool
    def clipboard_read() -> str:  # noqa: F811
        """Read the text currently on the clipboard."""
        return registry.call("clipboard_read")

    @beta_tool
    def clipboard_write(text: str) -> str:  # noqa: F811
        """Put text on the clipboard.

        Args:
            text: what to copy.
        """
        return registry.call("clipboard_write", text=text)

    @beta_tool
    def media(action: str) -> str:  # noqa: F811
        """Control music: play, pause, next, previous, mute, unmute, or "volume 40".

        Args:
            action: one of those words, or "volume N" with N from 0 to 100.
        """
        return registry.call("media", action=action)

    @beta_tool
    def look_at_screen() -> Any:  # noqa: F811
        """Take a screenshot so you can see what's on their screen. Only when they ask what's on
        their screen or to look at something; never on your own initiative."""
        return registry.call("look_at_screen")

    for h, t in zip(hands, [open_app, open_url, clipboard_read, clipboard_write, media, look_at_screen]):
        h.tool = t


def _shell_quote(text: str) -> str:
    return "'" + text.replace("'", "'\"'\"'") + "'"
