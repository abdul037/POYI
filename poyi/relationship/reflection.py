"""The Sunday reflection: what it noticed, what it got wrong, what it's still holding."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Callable

from poyi.brain.agent import Brain
from poyi.brain.character import build_system_prompt
from poyi.brain.tools import default_tools
from poyi.config import Settings
from poyi.initiative.events import Event
from poyi.memory.store import MemoryStore, render_memory_context

PROMPT = """It's the weekly reflection. Two minutes of reading at most, plain text, no headings, no lists.

Cover three things, a short paragraph each: what you noticed about them this week from the logs; what you got wrong, using the initiative record below (things they said "not now" to or ignored count as wrong, things they thanked you for count as right); and what you're still holding for them from the threads. End with one line inviting "less of that" or "more of that" on anything.

This week's logs:
{logs}

Initiative record (route, feedback, title):
{decisions}
"""


def make_reflection_fn(settings: Settings, memory: MemoryStore, render_world: Callable[[], str],
                       recent_events: Callable[[], list[Event]], *, client: Any | None = None,
                       root: Path | None = None) -> Callable[[], str]:
    def reflect() -> str:
        logs = "\n\n".join(f"{d.isoformat()}\n{text.strip()}" for d, text in reversed(memory.recent_logs(7))) or "(no logs)"
        decisions = "\n".join(f"{e.route:<7} {e.feedback or '-':<9} {e.title}" for e in recent_events() if e.route in ("speak", "mention")) or "(nothing raised)"
        brain = Brain(settings.deep(), client=client, tools=default_tools(settings, web=False),
                      system=build_system_prompt(settings, memory=True, world=True),
                      context=render_memory_context(memory), turn_context=render_world)
        text = brain.reply(PROMPT.format(logs=logs, decisions=decisions)).strip()
        if root is not None:
            folder = Path(root) / "reflections"
            folder.mkdir(parents=True, exist_ok=True)
            iso = date.today().isocalendar()
            (folder / f"{iso.year}-W{iso.week:02d}.md").write_text(text + "\n")
        return text

    return reflect
