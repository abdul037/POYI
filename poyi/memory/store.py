"""Plain files under ~/.poyi/memory that you can open, edit, and delete.

    profile.md          standing facts, one per line, each tagged (seen: YYYY-MM-DD)
    threads.md          open loops: promised, waiting on, working on, goals
    log/YYYY-MM-DD.md   what happened that day, in Poyi's words
    notes/tomorrow.md   a short note the nightly pass leaves for the next day
    history/            backups of the profile before each rewrite
"""

from __future__ import annotations

import re
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Callable

SEEN_TAG = re.compile(r"\(seen:\s*(\d{4}-\d{2}-\d{2})\)")
KEEP_TAG = "(keep)"
DEFAULT_DECAY_DAYS = 60

PROFILE_TEMPLATE = """# Profile

One line per standing fact, ending with (seen: YYYY-MM-DD). Add (keep) to a
line that must never decay. Poyi maintains this; you can edit it any time.

## Who they are

## People who matter

## Preferences

## How they like things done
"""

THREADS_TEMPLATE = """# Threads

## Promised

## Waiting on

## Working on

## Goals
"""


class MemoryStore:
    def __init__(self, root: Path, today: Callable[[], date] | None = None) -> None:
        self.root = Path(root)
        self._today = today or date.today
        self.profile_path = self.root / "profile.md"
        self.threads_path = self.root / "threads.md"
        self.log_dir = self.root / "log"
        self.notes_dir = self.root / "notes"
        self.history_dir = self.root / "history"
        self.tomorrow_path = self.notes_dir / "tomorrow.md"

    # --- lifecycle -----------------------------------------------------

    def today(self) -> date:
        return self._today()

    def ensure(self) -> "MemoryStore":
        for d in (self.root, self.log_dir, self.notes_dir, self.history_dir):
            d.mkdir(parents=True, exist_ok=True)
        if not self.profile_path.exists():
            self.profile_path.write_text(PROFILE_TEMPLATE)
        if not self.threads_path.exists():
            self.threads_path.write_text(THREADS_TEMPLATE)
        return self

    def wipe(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)
        self.ensure()

    def files(self) -> list[tuple[str, int]]:
        if not self.root.exists():
            return []
        out = []
        for p in sorted(self.root.rglob("*")):
            if p.is_file():
                out.append((str(p.relative_to(self.root)), p.stat().st_size))
        return out

    # --- profile and threads --------------------------------------------

    def profile(self) -> str:
        return self.profile_path.read_text() if self.profile_path.exists() else ""

    def write_profile(self, text: str, *, backup: bool = True) -> None:
        self.ensure()
        if backup and self.profile_path.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(self.profile_path, self.history_dir / f"profile-{stamp}.md")
        self.profile_path.write_text(text.rstrip() + "\n")

    def threads(self) -> str:
        return self.threads_path.read_text() if self.threads_path.exists() else ""

    def write_threads(self, text: str) -> None:
        self.ensure()
        self.threads_path.write_text(text.rstrip() + "\n")

    # --- daily log -------------------------------------------------------

    def log_path(self, day: date | None = None) -> Path:
        return self.log_dir / f"{(day or self.today()).isoformat()}.md"

    def read_log(self, day: date | None = None) -> str:
        p = self.log_path(day)
        return p.read_text() if p.exists() else ""

    def append_log(self, text: str, when: datetime | None = None) -> None:
        self.ensure()
        when = when or datetime.now()
        p = self.log_path(when.date())
        line = f"- {when.strftime('%H:%M')} {text.strip()}\n"
        if not p.exists():
            p.write_text(f"# {when.date().isoformat()}\n\n{line}")
        else:
            with p.open("a") as f:
                f.write(line)

    def recent_logs(self, days: int = 3) -> list[tuple[date, str]]:
        if not self.log_dir.exists():
            return []
        out = []
        for p in sorted(self.log_dir.glob("*.md"), reverse=True)[:days]:
            try:
                day = date.fromisoformat(p.stem)
            except ValueError:
                continue
            out.append((day, p.read_text()))
        return out

    # --- notes -----------------------------------------------------------

    def tomorrow_note(self) -> str:
        return self.tomorrow_path.read_text() if self.tomorrow_path.exists() else ""

    def write_tomorrow_note(self, text: str) -> None:
        self.ensure()
        self.tomorrow_path.write_text(text.rstrip() + "\n")

    # --- prompt rendering ------------------------------------------------

    def render_for_prompt(self, max_chars: int = 12000) -> str:
        sections = [f"## Profile\n\n{self.profile().strip()}", f"## Threads\n\n{self.threads().strip()}"]
        note = self.tomorrow_note().strip()
        if note:
            sections.append(f"## Note from the last nightly pass\n\n{note}")
        today_log = self.read_log().strip()
        if today_log:
            sections.append(f"## Today so far\n\n{today_log}")
        else:
            recent = [(d, t) for d, t in self.recent_logs(1) if d != self.today()]
            if recent:
                sections.append(f"## Most recent day ({recent[0][0].isoformat()})\n\n{recent[0][1].strip()}")
        text = "\n\n".join(sections)
        if len(text) > max_chars:
            text = text[: max_chars - 40].rstrip() + "\n\n[memory truncated for length]"
        return text


def decay_profile(text: str, today: date, days: int = DEFAULT_DECAY_DAYS) -> tuple[str, list[str]]:
    """Drop tagged lines not seen within `days`, unless marked (keep)."""
    kept, dropped = [], []
    for line in text.splitlines():
        m = SEEN_TAG.search(line)
        if m and KEEP_TAG not in line:
            seen = date.fromisoformat(m.group(1))
            if (today - seen).days > days:
                dropped.append(line.strip())
                continue
        kept.append(line)
    return "\n".join(kept).rstrip() + "\n", dropped


def render_memory_context(store: MemoryStore) -> str:
    return "# What you remember\n\n" + store.render_for_prompt()
