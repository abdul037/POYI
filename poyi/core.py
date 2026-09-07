"""The being itself."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

from poyi.brain.agent import REFUSAL_LINE, Brain, Event
from poyi.brain.character import build_system_prompt
from poyi.brain.tools import default_tools
from poyi.config import Settings, has_credentials
from poyi.identity import INTRO, NAME
from poyi.memory import MemoryStore, PoyiMemoryTool, render_memory_context
from poyi.hands import Hands, build_hands
from poyi.hands.registry import Confirmer
from poyi.initiative import Initiative, Notifier, default_watchers, make_model_tiebreak
from poyi.initiative.brief import make_brief_fn
from poyi.initiative.tool import make_feedback_tool
from poyi.world import Refresher, WorldStore, default_sensors
from poyi.world.tool import make_update_world_tool

NO_MIND = (
    f"({NAME} has no mind wired in: no Anthropic credential was found. "
    "Set ANTHROPIC_API_KEY, or run `ant auth login`, then try again.)"
)


@dataclass
class Poyi:
    """A single conversation with Poyi.

    With a `brain`, replies come from Claude. Without one, Poyi says so
    honestly instead of pretending.
    """

    brain: Brain | None = None
    memory: MemoryStore | None = None
    world: Refresher | None = None
    initiative: Initiative | None = None
    hands: Hands | None = None
    history: list[tuple[str, str]] = field(default_factory=list)

    speaker: Any | None = None

    @classmethod
    def default(cls, settings: Settings | None = None, *, confirmer: Confirmer | None = None,
                voice: bool | None = None) -> "Poyi":
        """Poyi as installed: character, memory, the picture, initiative, hands, and a voice if on."""
        settings = settings or Settings.from_env()
        voice = settings.voice if voice is None else voice
        memory = MemoryStore(settings.home / "memory").ensure()
        hands = build_hands(settings, confirmer=confirmer, read_profile=memory.profile)
        world = Refresher(WorldStore(settings.home), [*default_sensors(settings, memory.threads), *hands.sensors], settings)
        speaker = None
        if voice:
            from poyi.voice.assemble import make_speaker

            speaker = make_speaker(settings)
        remote = None
        if settings.telegram_token and settings.telegram_chat_id:
            from poyi.fronts.telegram import TelegramBot, TelegramChannel

            remote = TelegramChannel(TelegramBot(settings.telegram_token), settings.telegram_chat_id)
        notifier = Notifier(desktop=settings.notify, speaker=speaker, remote=remote)
        awake = has_credentials()
        client = None
        brief = tiebreak = None
        if awake:
            import anthropic

            client = anthropic.Anthropic()
            brief = make_brief_fn(settings, memory, world.render, client=client, root=settings.home)
            tiebreak = make_model_tiebreak(client, settings.fast_model)
        initiative = Initiative(settings.home, world, [*default_watchers(settings, memory.threads), *hands.watchers],
                                notifier, tiebreak=tiebreak, brief=brief)
        if not awake:
            return cls(brain=None, memory=memory, world=world, initiative=initiative, hands=hands, speaker=speaker)
        world.refresh(force=True)

        def picture() -> str:
            world.refresh()
            extra = initiative.render_for_picture()
            return world.render() + ("\n" + extra if extra else "")

        brain = Brain(
            settings,
            client=client,
            tools=[*default_tools(settings), PoyiMemoryTool(memory), make_update_world_tool(world.note),
                   make_feedback_tool(initiative.feedback), *hands.tools()],
            system=build_system_prompt(settings, memory=True, world=True, initiative=True, hands=True, voice=voice),
            context=render_memory_context(memory),
            turn_context=picture,
        )
        return cls(brain=brain, memory=memory, world=world, initiative=initiative, hands=hands, speaker=speaker)

    @property
    def awake(self) -> bool:
        return self.brain is not None

    def introduce(self) -> str:
        return INTRO

    def stream(self, message: str) -> Iterator[Event]:
        self.history.append(("user", message))
        if self.brain is None:
            yield Event("text", NO_MIND)
            self.history.append((NAME.lower(), NO_MIND))
            yield Event("done")
            return
        parts: list[str] = []
        refused = False
        for event in self.brain.stream(message):
            if event.kind == "text":
                parts.append(event.data)
            elif event.kind == "refusal":
                refused = True
            yield event
        text = "".join(parts).strip()
        if not text and refused:
            text = REFUSAL_LINE
        self.history.append((NAME.lower(), text))
        if self.initiative is not None:
            self.initiative.mark_shown_mentioned()

    def reply(self, message: str) -> str:
        for _ in self.stream(message):
            pass
        return self.history[-1][1]

    def last_usage(self) -> Any | None:
        return self.brain.last_usage if self.brain else None
