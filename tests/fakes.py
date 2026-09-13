"""A fake Anthropic client that mimics just enough of the tool runner."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def text_delta(text: str) -> Any:
    return SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=text))


def thinking_delta(text: str) -> Any:
    return SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="thinking_delta", thinking=text))


def tool_start(name: str, *, server: bool = False) -> Any:
    kind = "server_tool_use" if server else "tool_use"
    return SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type=kind, name=name))


def final_message(text: str = "", *, stop_reason: str = "end_turn", extra_blocks: list[Any] | None = None) -> Any:
    blocks: list[Any] = []
    if text:
        blocks.append(SimpleNamespace(type="text", text=text))
    blocks.extend(extra_blocks or [])
    return SimpleNamespace(
        content=blocks,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0),
    )


class FakeStream:
    def __init__(self, events: list[Any], final: Any) -> None:
        self.events = events
        self.final = final

    def __iter__(self):
        return iter(self.events)

    def get_final_message(self) -> Any:
        return self.final


def simple_turn(text: str, *, stop_reason: str = "end_turn") -> tuple[FakeStream, None]:
    """One assistant turn that streams `text` word by word and ends."""
    words = text.split(" ")
    events = [text_delta(w if i == len(words) - 1 else w + " ") for i, w in enumerate(words)]
    return FakeStream(events, final_message(text, stop_reason=stop_reason)), None


class FakeRunner:
    def __init__(self, turns: list[tuple[FakeStream, Any]]) -> None:
        self.turns = turns
        self.index = -1

    def __iter__(self):
        for self.index, (stream, _) in enumerate(self.turns):
            yield stream

    def generate_tool_call_response(self) -> Any:
        return self.turns[self.index][1]


class FakeClient:
    """`client.beta.messages.tool_runner(**params)` returns the scripted turns."""

    def __init__(self, turns: list[tuple[FakeStream, Any]] | None = None) -> None:
        self.turns = turns or []
        self.calls: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(tool_runner=self._tool_runner))

    def _tool_runner(self, **params: Any) -> FakeRunner:
        self.calls.append(params)
        return FakeRunner(self.turns)
