"""The brain's way of learning from how they reacted to an interruption."""

from __future__ import annotations

from typing import Any, Callable

from anthropic import beta_tool

VERDICTS = ("not_now", "thanks")


def make_feedback_tool(feedback: Callable[[str, str], Any]) -> Any:
    @beta_tool
    def interruption_feedback(event_id: str, verdict: str) -> str:
        """Record how they reacted to something you raised on your own initiative.

        Call it when they respond to an item from the picture's "mention" or
        "recent" lists: a notification, or something you brought up unprompted.

        Args:
            event_id: the id in square brackets from the picture.
            verdict: "not_now" if they didn't want it then, "thanks" if it was welcome.
        """
        verdict = verdict.strip().lower()
        if verdict not in VERDICTS:
            return f"verdict must be one of {', '.join(VERDICTS)}"
        event = feedback(event_id.strip("[] "), verdict)
        if event is None:
            return f"no event with id {event_id}"
        return f"Noted {verdict} for {event.source}: {event.title}"

    return interruption_feedback
