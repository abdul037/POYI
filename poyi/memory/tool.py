"""The Anthropic memory tool, backed by the plain files in MemoryStore.

Claude addresses everything under `/memories`. Every path is resolved inside
the store root; anything that escapes it is refused.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from anthropic.lib.tools import BetaAbstractMemoryTool

from poyi.memory.store import MemoryStore

ROOT = "/memories"


class PoyiMemoryTool(BetaAbstractMemoryTool):
    def __init__(self, store: MemoryStore) -> None:
        super().__init__()
        self.store = store.ensure()

    # --- paths -------------------------------------------------------------

    def _resolve(self, path: str) -> Path:
        if not path.startswith(ROOT):
            raise ValueError(f"paths must start with {ROOT}")
        relative = path[len(ROOT):].lstrip("/")
        target = (self.store.root / relative).resolve()
        root = self.store.root.resolve()
        if target != root and root not in target.parents:
            raise ValueError("path escapes the memory directory")
        return target

    def _display(self, target: Path) -> str:
        rel = target.resolve().relative_to(self.store.root.resolve())
        return ROOT if str(rel) == "." else f"{ROOT}/{rel.as_posix()}"

    def _guard(self, fn, *args: Any) -> str:
        try:
            return fn(*args)
        except (ValueError, FileNotFoundError, IsADirectoryError, NotADirectoryError, OSError) as exc:
            return f"Error: {exc}"

    # --- commands ------------------------------------------------------------

    def view(self, command: Any) -> str:
        return self._guard(self._view, command.path, getattr(command, "view_range", None))

    def _view(self, path: str, view_range: list[int] | None) -> str:
        target = self._resolve(path)
        if target.is_dir():
            lines = [f"Directory: {self._display(target)}"]
            for p in sorted(target.rglob("*")):
                if p.is_file():
                    lines.append(f"- {self._display(p)}")
            return "\n".join(lines) if len(lines) > 1 else lines[0] + "\n(empty)"
        if not target.is_file():
            raise FileNotFoundError(f"{path} does not exist")
        lines = target.read_text().splitlines()
        start, end = 1, len(lines)
        if view_range:
            start = max(1, view_range[0])
            end = min(len(lines), view_range[1]) if len(view_range) > 1 and view_range[1] > 0 else len(lines)
        numbered = [f"{i}: {lines[i - 1]}" for i in range(start, end + 1)]
        return "\n".join(numbered) if numbered else "(empty file)"

    def create(self, command: Any) -> str:
        def go(path: str, text: str) -> str:
            target = self._resolve(path)
            if target == self.store.root.resolve():
                raise ValueError("cannot create the root")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
            return f"Created {self._display(target)}"

        return self._guard(go, command.path, command.file_text)

    def str_replace(self, command: Any) -> str:
        def go(path: str, old: str, new: str) -> str:
            target = self._resolve(path)
            if not target.is_file():
                raise FileNotFoundError(f"{path} does not exist")
            text = target.read_text()
            count = text.count(old)
            if count == 0:
                raise ValueError("old_str was not found")
            if count > 1:
                raise ValueError(f"old_str occurs {count} times; make it unique")
            target.write_text(text.replace(old, new, 1))
            return f"Edited {self._display(target)}"

        return self._guard(go, command.path, command.old_str, command.new_str)

    def insert(self, command: Any) -> str:
        def go(path: str, line: int, text: str) -> str:
            target = self._resolve(path)
            if not target.is_file():
                # A missing file is created rather than refused: the common case is
                # the first line of today's log.
                target.parent.mkdir(parents=True, exist_ok=True)
                header = f"# {target.stem}\n\n" if target.parent.name == "log" else ""
                target.write_text(header)
            lines = target.read_text().splitlines()
            line = max(0, min(line, len(lines)))  # clamp rather than refuse; the model often guesses the length
            new_lines = text.splitlines()
            lines[line:line] = new_lines
            target.write_text("\n".join(lines) + "\n")
            return f"Inserted {len(new_lines)} line(s) into {self._display(target)} after line {line}"

        return self._guard(go, command.path, command.insert_line, command.insert_text)

    def delete(self, command: Any) -> str:
        def go(path: str) -> str:
            target = self._resolve(path)
            if target == self.store.root.resolve():
                raise ValueError("refusing to delete the whole memory; use clear_all_memory")
            if target.is_dir():
                shutil.rmtree(target)
            elif target.is_file():
                target.unlink()
            else:
                raise FileNotFoundError(f"{path} does not exist")
            return f"Deleted {path}"

        return self._guard(go, command.path)

    def rename(self, command: Any) -> str:
        def go(old: str, new: str) -> str:
            src, dst = self._resolve(old), self._resolve(new)
            if not src.exists():
                raise FileNotFoundError(f"{old} does not exist")
            if dst.exists():
                raise ValueError(f"{new} already exists")
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            return f"Renamed {old} to {new}"

        return self._guard(go, command.old_path, command.new_path)

    def clear_all_memory(self) -> str:
        self.store.wipe()
        return "All memory cleared."
