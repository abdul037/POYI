"""Telegram: the phone front. Text and voice notes in, text out, and
notifications when you're away. No library, just the Bot API over HTTPS.
"""

from __future__ import annotations

import json
import logging
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from poyi.identity import NAME

log = logging.getLogger(__name__)
Fetch = Callable[[str, dict[str, Any] | None], Any]  # (url, json body or None) -> parsed JSON


class TelegramBot:
    def __init__(self, token: str, fetch: Fetch | None = None, timeout: float = 35.0) -> None:
        self.token = token
        self.timeout = timeout
        self.fetch = fetch or self._fetch
        self.base = f"https://api.telegram.org/bot{token}"

    def _fetch(self, url: str, body: dict[str, Any] | None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 - fixed API host
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Telegram said {exc.code}") from exc

    def call(self, method: str, **params: Any) -> Any:
        result = self.fetch(f"{self.base}/{method}", params or None)
        if isinstance(result, dict) and not result.get("ok", True):
            raise RuntimeError(f"Telegram: {result.get('description', 'error')}")
        return result.get("result") if isinstance(result, dict) else result

    def send(self, chat_id: str, text: str) -> None:
        for chunk in [text[i:i + 4000] for i in range(0, max(len(text), 1), 4000)]:
            self.call("sendMessage", chat_id=chat_id, text=chunk)

    def updates(self, offset: int | None, timeout: int = 25) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        return list(self.call("getUpdates", **params) or [])

    def file_path(self, file_id: str) -> str:
        return str(self.call("getFile", file_id=file_id).get("file_path", ""))

    def download(self, file_path: str, target: Path) -> Path:
        url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        with urllib.request.urlopen(url, timeout=self.timeout) as resp:  # noqa: S310
            target.write_bytes(resp.read())
        return target


def parse_message(update: dict[str, Any]) -> tuple[str, str, str | None] | None:
    """(chat_id, text, voice_file_id) from an update, or None if there's nothing to answer."""
    message = update.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id", ""))
    if not chat_id:
        return None
    voice = (message.get("voice") or message.get("audio") or {}).get("file_id")
    text = message.get("text") or message.get("caption") or ""
    if not text and not voice:
        return None
    return chat_id, text, voice


class TelegramFront:
    """Polls for messages from one allowed chat and answers through the being."""

    def __init__(self, bot: TelegramBot, chat_id: str, being: Any, *, lock: threading.Lock | None = None,
                 stt: Any | None = None, sleep: Callable[[float], None] = time.sleep) -> None:
        self.bot = bot
        self.chat_id = str(chat_id)
        self.being = being
        self.lock = lock or threading.Lock()
        self.stt = stt
        self.sleep = sleep
        self.offset: int | None = None
        self.stop_event = threading.Event()

    def answer(self, text: str) -> str:
        with self.lock:
            reply = self.being.reply(text)
        return reply or "(nothing to say)"

    def transcribe(self, file_id: str) -> str:
        if self.stt is None:
            return ""
        path = Path(tempfile.gettempdir()) / f"poyi-tg-{file_id[:12]}.oga"
        try:
            self.bot.download(self.bot.file_path(file_id), path)
            return self.stt.transcribe(path)
        finally:
            try:
                path.unlink()
            except OSError:
                pass

    def handle(self, update: dict[str, Any]) -> str | None:
        parsed = parse_message(update)
        if parsed is None:
            return None
        chat_id, text, voice = parsed
        if chat_id != self.chat_id:
            log.info("ignoring message from chat %s", chat_id)
            return None
        if voice and not text:
            text = self.transcribe(voice)
            if not text:
                self.bot.send(chat_id, "I couldn't make that out.")
                return None
            self.bot.send(chat_id, f"you: {text}")
        reply = self.answer(text)
        self.bot.send(chat_id, reply)
        return reply

    def poll_once(self) -> int:
        updates = self.bot.updates(self.offset)
        for update in updates:
            self.offset = int(update.get("update_id", 0)) + 1
            try:
                self.handle(update)
            except Exception as exc:  # noqa: BLE001
                log.warning("telegram handle failed: %s", exc)
        return len(updates)

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # noqa: BLE001
                log.warning("telegram poll failed: %s", exc)
                self.sleep(5)


class TelegramChannel:
    """A notifier channel: sends notifications to the phone."""

    def __init__(self, bot: TelegramBot, chat_id: str) -> None:
        self.bot = bot
        self.chat_id = str(chat_id)

    def send(self, title: str, body: str = "") -> bool:
        try:
            self.bot.send(self.chat_id, f"{NAME}: {title}" + (f"\n{body}" if body else ""))
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("telegram notify failed: %s", exc)
            return False
