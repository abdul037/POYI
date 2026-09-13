"""The brain's write-back into the world model."""

from __future__ import annotations

from typing import Any, Callable

from anthropic import beta_tool

from poyi.world.model import MODES, PLACES


def make_update_world_tool(note: Callable[[dict[str, Any]], dict[str, Any]]) -> Any:
    @beta_tool
    def update_world(
        place: str = "",
        activity: str = "",
        mode: str = "",
        note_text: str = "",
        next_item: str = "",
        person: str = "",
    ) -> str:
        """Update the picture of the person when something they said changes it.

        Use it when they tell you where they are or are going, what they're doing
        or about to do, that they want quiet, or that something is coming up. Do
        not call it for small talk.

        Args:
            place: "home", "away", or "unknown".
            activity: a word: coding, meeting, browsing, messaging, listening,
                writing, reading, eating, resting, travelling, idle.
            mode: "relaxed", "focus", "meeting", "away", or "asleep". Only when
                they ask for it or clearly state it.
            note_text: a short line worth keeping in the picture, e.g. "leaving
                for the dentist at 11".
            next_item: something coming up, e.g. "11:30 Dentist".
            person: a person state, e.g. "Sam: expecting a reply about Friday".
        """
        updates: dict[str, Any] = {}
        if place:
            if place not in PLACES:
                return f"place must be one of {', '.join(PLACES)}"
            updates["place"] = place
        if activity:
            updates["activity"] = activity.strip().lower()
            updates["app"] = ""
            updates["window"] = ""
        if mode:
            if mode not in MODES:
                return f"mode must be one of {', '.join(MODES)}"
            updates["mode"] = mode
            updates["mode_source"] = "manual"
        extra: dict[str, list[str]] = {}
        if note_text:
            extra["notes"] = [note_text.strip()]
        if next_item:
            extra["next"] = [next_item.strip()]
        if person:
            extra["people"] = [person.strip()]
        changed = note({**updates, "__append__": extra} if extra else updates)
        return "Updated: " + ", ".join(sorted(changed)) if changed else "Nothing changed."

    return update_world
