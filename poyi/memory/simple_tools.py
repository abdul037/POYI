"""Write-only memory tools for conversation.

Everything Poyi could read is already in its context under "What you
remember", so the brain only needs to write. The Anthropic memory tool
insists on viewing the directory before anything else, which cost a round
trip every turn; these three tools don't.
"""

from __future__ import annotations

from typing import Any

from anthropic import beta_tool

from poyi.memory.store import MemoryStore

PROFILE_HEADINGS = ("who they are", "people who matter", "preferences", "how they like things done")
THREAD_HEADINGS = ("promised", "waiting on", "working on", "goals")


def make_memory_tools(store: MemoryStore) -> list[Any]:
    @beta_tool
    def remember(line: str, where: str = "profile", heading: str = "", replaces: str = "") -> str:
        """Save a standing fact about them or the people in their life, or an open loop.

        Args:
            line: one plain line, e.g. "Amina, sister, lives in Leeds". No date tag; it's added.
                People lines may carry (birthday: MM-DD) and (last spoke: YYYY-MM-DD); goals may
                carry (check-in: YYYY-MM-DD).
            where: "profile" for standing facts, "threads" for open loops.
            heading: profile: "who they are", "people who matter", "preferences", "how they like
                things done". threads: "promised", "waiting on", "working on", "goals".
            replaces: text of an older line to remove first, e.g. when updating (last spoke: ...).
        """
        where = (where or "profile").strip().lower()
        if where not in ("profile", "threads"):
            return 'where must be "profile" or "threads"'
        heading = heading.strip().lower()
        if not heading:
            heading = "people who matter" if where == "profile" else "working on"
        if replaces.strip():
            store.remove_lines(replaces.strip())
        store.add_line(where, heading, line.strip(), tag_seen=where == "profile")
        return f"Remembered under {heading}: {line.strip()}"

    @beta_tool
    def log_today(line: str) -> str:
        """Add one line to today's log: something that happened that a good friend would
        remember. Not for small talk.

        Args:
            line: what happened, in a few words, e.g. "told me his sister Amina lives in Leeds".
        """
        store.append_log(line.strip())
        return "Logged."

    @beta_tool
    def forget(text: str) -> str:
        """Remove every memory line containing this text: profile, threads, and logs. Use it when
        they ask you to forget something, then tell them it's gone.

        Args:
            text: a distinctive piece of the line(s) to remove.
        """
        removed = store.remove_lines(text.strip())
        return f"Forgot {removed} line(s)." if removed else "Nothing matched."

    return [remember, log_today, forget]
