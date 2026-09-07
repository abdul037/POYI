"""The agent loop around Claude.

`Brain.stream()` sends one user turn, lets the SDK tool runner handle any tool
calls, and yields text as it arrives. History is mirrored locally so it can be
inspected, saved, and (later) fed to memory and the world model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterator

from poyi.brain.character import build_system_prompt
from poyi.brain.tools import default_tools
from poyi.config import Settings

log = logging.getLogger(__name__)

REFUSAL_LINE = "I'm not going to help with that one."


@dataclass(frozen=True)
class Event:
    """Something that happened while Poyi was replying.

    kind: "text" (a piece of the reply), "tool" (a tool started; data is its
    name), "refusal" (the model declined), or "done".
    """

    kind: str
    data: str = ""


class Brain:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: Any | None = None,
        tools: list[Any] | None = None,
        system: str | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self._client = client
        self.tools = list(tools) if tools is not None else default_tools(self.settings)
        self.system = system if system is not None else build_system_prompt(self.settings)
        self.messages: list[dict[str, Any]] = []
        self.last_usage: Any | None = None

    @property
    def client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def request_params(self) -> dict[str, Any]:
        """The exact parameters for the next request. Stable prefix first."""
        s = self.settings
        params: dict[str, Any] = {
            "model": s.model,
            "max_tokens": s.max_tokens,
            "system": [
                {"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}
            ],
            "tools": self.tools,
            "messages": list(self.messages),
            "stream": True,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": s.effort},
            "max_iterations": s.max_tool_rounds,
        }
        betas: list[str] = []
        if s.compaction:
            betas.append("compact-2026-01-12")
            params["context_management"] = {"edits": [{"type": "compact_20260112"}]}
        if s.fallbacks:
            betas.append("server-side-fallback-2026-07-01")
            params["fallbacks"] = "default"
        if betas:
            params["betas"] = betas
        return params

    def reply(self, text: str) -> str:
        return "".join(e.data for e in self.stream(text) if e.kind == "text")

    def stream(self, text: str) -> Iterator[Event]:
        self.messages.append({"role": "user", "content": text})
        runner = self.client.beta.messages.tool_runner(**self.request_params())
        refused = False
        for stream in runner:
            for event in stream:
                kind = getattr(event, "type", None)
                if kind == "content_block_delta":
                    delta = event.delta
                    if getattr(delta, "type", None) == "text_delta":
                        yield Event("text", delta.text)
                elif kind == "content_block_start":
                    block = event.content_block
                    if getattr(block, "type", None) in ("tool_use", "server_tool_use"):
                        yield Event("tool", block.name)
            final = stream.get_final_message()
            self.last_usage = getattr(final, "usage", None)
            # Mirror the full content so tool_use and compaction blocks survive.
            self.messages.append({"role": "assistant", "content": final.content})
            tool_response = runner.generate_tool_call_response()
            if tool_response is not None:
                self.messages.append(tool_response)
            if getattr(final, "stop_reason", None) == "refusal":
                refused = True
        if refused:
            yield Event("refusal", REFUSAL_LINE)
        yield Event("done")

    def forget_conversation(self) -> None:
        self.messages.clear()
