"""The nightly pass: fold the day's log into the profile and threads.

Run with `poyi consolidate`. Later the daemon schedules it. The model decides
what changed about the person and what has expired; code then applies the
decay rule so nothing lingers on the model's say-so alone.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel

from poyi.config import Settings
from poyi.identity import NAME
from poyi.memory.store import DEFAULT_DECAY_DAYS, MemoryStore, decay_profile


class Consolidation(BaseModel):
    profile: str
    threads: str
    tomorrow: str
    dropped: list[str]


SYSTEM = f"""You are {NAME}'s nightly memory pass. {NAME} is a companion to one person. You are given today's log, the current profile, and the open threads. Produce the updated profile, the updated threads, and a short note for tomorrow.

Rules for the profile:
- Standing facts only: who they are, the people who matter to them, preferences, how they like things done. One line per fact under the existing headings.
- Every fact line ends with (seen: {{today}}) if today's log reinforced it, otherwise keep its existing (seen: ...) date unchanged. New facts get (seen: {{today}}).
- Keep any line marked (keep) exactly as it is.
- Keep (birthday: MM-DD) and (last spoke: YYYY-MM-DD) tags on people; if today's log shows they spoke to someone, set that person's (last spoke: {{today}}).
- Rewrite, merge, or tighten lines; do not pad. Under 2,000 words in total.
- Never include secrets: passwords, card numbers, keys, or anything they asked to forget.

Rules for threads:
- Under Promised, Waiting on, Working on, Goals. Add what the log opened, close what it resolved, and give goals a (check-in: YYYY-MM-DD) tag if they lack one, one to four weeks out.

The tomorrow note is at most five lines: what to bring up, what to watch for, what was left unresolved. Plain language. No headings.

List in `dropped` anything you deliberately removed and why, in one short line each.
"""


def build_messages(store: MemoryStore, today: date) -> list[dict[str, Any]]:
    log = store.read_log(today).strip() or "(no log for today)"
    recent = [(d, t) for d, t in store.recent_logs(2) if d != today]
    earlier = f"\n\n# Yesterday's log\n\n{recent[0][1].strip()}" if recent else ""
    text = (
        f"Today is {today.isoformat()}.\n\n"
        f"# Today's log\n\n{log}{earlier}\n\n"
        f"# Current profile\n\n{store.profile().strip()}\n\n"
        f"# Current threads\n\n{store.threads().strip()}\n\n"
        f"# Previous tomorrow note\n\n{store.tomorrow_note().strip() or '(none)'}"
    )
    return [{"role": "user", "content": text}]


def consolidate(
    store: MemoryStore,
    settings: Settings,
    *,
    client: Any | None = None,
    today: date | None = None,
    decay_days: int = DEFAULT_DECAY_DAYS,
    dry_run: bool = False,
) -> Consolidation:
    if client is None:
        import anthropic

        client = anthropic.Anthropic()
    store.ensure()
    today = today or store.today()
    response = client.messages.parse(
        model=settings.model,
        max_tokens=16000,
        system=SYSTEM.replace("{today}", today.isoformat()),
        messages=build_messages(store, today),
        output_format=Consolidation,
    )
    result: Consolidation = response.parsed_output
    profile, decayed = decay_profile(result.profile, today, decay_days)
    result = result.model_copy(update={"profile": profile, "dropped": [*result.dropped, *(f"decayed: {d}" for d in decayed)]})
    if not dry_run:
        store.write_profile(result.profile)
        store.write_threads(result.threads)
        store.write_tomorrow_note(result.tomorrow)
        store.append_log(f"nightly pass ran; {len(result.dropped)} item(s) let go")
    return result
