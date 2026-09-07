"""iMessage through AppleScript. Always asks first. Names resolve through
~/.poyi/contacts.json, which you edit by hand: {"Sam": "+447700900123"}.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from anthropic import beta_tool

from poyi.hands.registry import Hand, Registry
from poyi.world import sensors as _sensors

Runner = Callable[[list[str]], str]

SEND_SCRIPT = '''
tell application "Messages"
  set targetService to 1st account whose service type = iMessage
  set targetBuddy to participant "{handle}" of targetService
  send "{text}" to targetBuddy
end tell
return "ok"
'''


class Contacts:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
            return {str(k): str(v) for k, v in data.items()}
        except (ValueError, AttributeError):
            return {}

    def resolve(self, who: str) -> str | None:
        who = who.strip()
        if "@" in who or who.replace("+", "").replace(" ", "").isdigit():
            return who
        for name, handle in self.load().items():
            if name.lower() == who.lower():
                return handle
        return None


def _q(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def register(registry: Registry, contacts: Contacts, *, runner: Runner | None = None) -> None:
    r: Runner = runner or _sensors.run

    def send(to: str, text: str) -> str:
        handle = contacts.resolve(to)
        if handle is None:
            return f"I don't have a number or address for {to!r}. Add it to {contacts.path} as {{\"{to}\": \"+1...\"}}."
        out = r(["osascript", "-e", SEND_SCRIPT.format(handle=_q(handle), text=_q(text))])
        if out.strip() != "ok":
            raise RuntimeError("Messages didn't confirm the send")
        return f"Sent to {to}: {text!r}"

    h = registry.add(Hand("send_message", "confirm", lambda to, text: f"message {to}: {text!r}", send))

    @beta_tool
    def send_message(to: str, text: str) -> str:
        """Send an iMessage. Always asks them first, with the text read back.

        Args:
            to: a name from their contacts, or a phone number or email.
            text: the message, in their voice unless they want yours.
        """
        return registry.call("send_message", to=to, text=text)

    h.tool = send_message
