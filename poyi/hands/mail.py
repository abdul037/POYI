"""Apple Mail through AppleScript. Reading unread is free; sending asks first."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from anthropic import beta_tool

from poyi.hands.registry import Hand, Registry
from poyi.initiative.events import Event
from poyi.world.model import World
from poyi.world import sensors as _sensors

Runner = Callable[[list[str]], str]

UNREAD_SCRIPT = '''
set out to ""
tell application "Mail"
  set msgs to (messages of inbox whose read status is false)
  set n to 0
  repeat with m in msgs
    set out to out & (sender of m) & tab & (subject of m) & tab & (date received of m as string) & linefeed
    set n to n + 1
    if n is greater than or equal to {limit} then exit repeat
  end repeat
end tell
return out
'''

SEND_SCRIPT = '''
tell application "Mail"
  set m to make new outgoing message with properties {{subject:"{subject}", content:"{body}", visible:false}}
  tell m to make new to recipient at end of to recipients with properties {{address:"{to}"}}
  send m
end tell
return "ok"
'''


@dataclass
class MailMessage:
    sender: str
    subject: str
    received: str


def parse_unread(text: str) -> list[MailMessage]:
    out = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            out.append(MailMessage(parts[0].strip(), parts[1].strip(), parts[2].strip() if len(parts) > 2 else ""))
    return out


def _q(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def register(registry: Registry, *, runner: Runner | None = None) -> None:
    r: Runner = runner or _sensors.run

    def unread(limit: int = 10) -> str:
        msgs = parse_unread(r(["osascript", "-e", UNREAD_SCRIPT.replace("{limit}", str(max(1, min(int(limit), 50))))]))
        if not msgs:
            return "No unread mail (or Mail isn't reachable)."
        return "\n".join(f"{m.sender}  |  {m.subject}" + (f"  ({m.received})" if m.received else "") for m in msgs)

    def send(to: str, subject: str, body: str) -> str:
        if "@" not in to:
            raise ValueError("give an email address")
        out = r(["osascript", "-e", SEND_SCRIPT.format(subject=_q(subject), body=_q(body), to=_q(to))])
        if out.strip() != "ok":
            raise RuntimeError("Mail didn't confirm the send")
        return f"Sent {subject!r} to {to}."

    u = registry.add(Hand("mail_unread", "free", lambda limit=10: f"read up to {limit} unread emails", unread))
    s = registry.add(Hand("mail_send", "confirm",
                          lambda to, subject, body: f"email {to}: {subject!r}: {body[:80]!r}{'...' if len(body) > 80 else ''}",
                          send))

    @beta_tool
    def mail_unread(limit: int = 10) -> str:
        """Unread email in the inbox: sender and subject.

        Args:
            limit: at most this many, up to 50.
        """
        return registry.call("mail_unread", limit=limit)

    @beta_tool
    def mail_send(to: str, subject: str, body: str) -> str:
        """Send an email. Asks them first, with the text read back.

        Args:
            to: the recipient's email address.
            subject: the subject line.
            body: the message, plain text.
        """
        return registry.call("mail_send", to=to, subject=subject, body=body)

    u.tool, s.tool = mail_unread, mail_send


@dataclass
class MailWatcher:
    """Unread mail from people who matter becomes an event, once per message."""

    people: Callable[[], list[str]]   # names or addresses from the profile
    runner: Runner | None = None
    check_every_minutes: int = 5
    name: str = "mail"
    _last: datetime | None = None

    def check(self, world: World, now: datetime) -> list[Event]:
        if self._last and (now - self._last).total_seconds() < self.check_every_minutes * 60:
            return []
        self._last = now
        who = [p.lower() for p in self.people() if p.strip()]
        if not who:
            return []
        out = []
        for m in parse_unread((self.runner or _sensors.run)(["osascript", "-e", UNREAD_SCRIPT.replace("{limit}", "25")])):
            sender = m.sender.lower()
            if any(p in sender for p in who):
                out.append(Event(source="mail", title=f"Mail from {m.sender}: {m.subject}", importance=0.7,
                                 person=m.sender, key=f"mail:{m.sender}:{m.subject}:{m.received}"))
        return out


def people_from_profile(profile_text: str) -> list[str]:
    """Names under '## People who matter', first word of each line, e.g. 'Sam' from '- Sam, ...'."""
    out: list[str] = []
    active = False
    for raw in profile_text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            active = line[3:].strip().lower().startswith("people")
        elif active and line.startswith("- "):
            name = line[2:].split("(")[0].split(":")[0].split(",")[0].strip()
            if name:
                out.append(name.split()[0])
    return out
