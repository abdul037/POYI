"""The morning brief and the evening wind-down, written by the brain."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Callable

from poyi.brain.agent import Brain
from poyi.brain.character import build_system_prompt
from poyi.brain.tools import default_tools
from poyi.config import Settings
from poyi.memory.store import MemoryStore, render_memory_context

PROMPTS = {
    "morning": (
        "It's the morning brief. At most six short lines of plain text, no greeting, no headings: "
        "what's on today from the picture and the threads, anything from the last nightly note worth "
        "carrying in, and one thing about the people who matter if there is one. If there's nothing, "
        "say so in one line."
    ),
    "evening": (
        "It's the evening wind-down. At most five short lines, no greeting, no headings: what moved "
        "today from today's log, what's still open, and anything to set up for tomorrow. If today was "
        "quiet, say so in one line."
    ),
}


def make_brief_fn(
    settings: Settings,
    memory: MemoryStore,
    render_world: Callable[[], str],
    *,
    client: Any | None = None,
    root: Path | None = None,
) -> Callable[[str], str]:
    """Returns brief(kind) -> text. Saves each brief under <root>/briefs/."""

    def brief(kind: str) -> str:
        prompt = PROMPTS.get(kind, PROMPTS["morning"])
        brain = Brain(
            settings,
            client=client,
            tools=default_tools(settings, web=False),
            system=build_system_prompt(settings, memory=True, world=True),
            context=render_memory_context(memory),
            turn_context=render_world,
        )
        text = brain.reply(prompt).strip()
        if root is not None:
            folder = Path(root) / "briefs"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{date.today().isoformat()}-{kind}.md").write_text(text + "\n")
        return text

    return brief
