"""Command line: `poyi`, `poyi intro`, `poyi chat`, `poyi say`, `poyi doctor`, `poyi eval`."""

from __future__ import annotations

import argparse
import sys
from typing import Iterable

from poyi import __version__
from poyi.brain.agent import Event
from poyi.config import Settings, has_credentials
from poyi.core import Poyi
from poyi.identity import ACRONYM, FULL_FORM, NAME
from poyi.memory import MemoryStore
from poyi.memory.consolidate import consolidate

TOOL_LABELS = {
    "web_search": "searching",
    "web_fetch": "reading",
    "current_time": "checking the time",
    "calculate": "calculating",
    "memory": "remembering",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="poyi", description=f"{NAME}: {FULL_FORM}")
    parser.add_argument("--version", action="version", version=f"{NAME} {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("intro", help=f"print how {NAME} introduces itself (default)")
    sub.add_parser("chat", help=f"talk to {NAME} in a loop; Ctrl-D or Ctrl-C to leave")
    say = sub.add_parser("say", help=f"send one message to {NAME} and print the reply")
    say.add_argument("text", nargs="+", help="what to say")
    sub.add_parser("doctor", help="check credentials, settings, and that the model answers")
    mem = sub.add_parser("memory", help=f"see, show, or forget what {NAME} remembers")
    mem_sub = mem.add_subparsers(dest="memory_command")
    show = mem_sub.add_parser("show", help="print profile, threads, today, tomorrow, or a file path")
    show.add_argument("what", nargs="?", default="profile")
    forget = mem_sub.add_parser("forget", help="delete one memory file, or everything with --all")
    forget.add_argument("path", nargs="?", help="path relative to the memory folder")
    forget.add_argument("--all", action="store_true", help="wipe all memory")
    forget.add_argument("--yes", action="store_true", help="skip the confirmation")
    con = sub.add_parser("consolidate", help="run the nightly memory pass now")
    con.add_argument("--dry-run", action="store_true", help="show what would change without writing")
    ev = sub.add_parser("eval", help="run an eval set against the live model")
    ev.add_argument("suite", choices=["character"], help="which eval set")
    ev.add_argument("--limit", type=int, default=None, help="run only the first N cases")
    ev.add_argument("--verbose", action="store_true", help="print every reply")
    return parser


def intro(being: Poyi) -> int:
    print(NAME)
    print(f"{ACRONYM} - {FULL_FORM}")
    print(being.introduce())
    return 0


def render(events: Iterable[Event], out=None) -> None:
    """Print a streamed reply, with a quiet note when a tool runs."""
    out = out or sys.stdout
    prompt = f"{NAME.lower():<4} > "
    started = False
    for event in events:
        if event.kind == "text":
            if not started:
                out.write(prompt)
                started = True
            out.write(event.data)
            out.flush()
        elif event.kind == "tool":
            label = TOOL_LABELS.get(event.data, event.data)
            out.write(f"{'' if not started else chr(10)}     ({label}...)\n")
            started = False
            out.flush()
        elif event.kind == "refusal":
            if not started:
                out.write(prompt)
                started = True
            out.write(event.data)
            out.flush()
    out.write("\n")
    out.flush()


def chat(being: Poyi) -> int:
    print(being.introduce())
    if not being.awake:
        print(f"     (no credentials found; {NAME} will say so until you add one)")
    try:
        while True:
            line = input("you  > ").strip()
            if not line:
                continue
            render(being.stream(line))
    except (EOFError, KeyboardInterrupt):
        print()
    return 0


def say(being: Poyi, text: str) -> int:
    render(being.stream(text))
    return 0


def doctor(settings: Settings) -> int:
    ok = True
    print(f"{NAME} {__version__}")
    print(f"model         {settings.model}  (effort {settings.effort})")
    print(f"fast model    {settings.fast_model}")
    print(f"home          {settings.home}")
    print(f"web tools     {'on' if settings.web else 'off'}")
    print(f"compaction    {'on' if settings.compaction else 'off'}")
    print(f"fallbacks     {'on' if settings.fallbacks else 'off'}")
    print(f"user          {settings.user_name or '(unset; set POYI_USER)'}")
    if not has_credentials():
        print("credentials   MISSING: set ANTHROPIC_API_KEY or run `ant auth login`")
        return 1
    print("credentials   found")
    try:
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model=settings.fast_model,
            max_tokens=16,
            messages=[{"role": "user", "content": "Reply with the single word: ready"}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "").strip()
        print(f"live check    ok ({settings.fast_model} said {text!r})")
    except Exception as exc:  # noqa: BLE001 - doctor reports, it doesn't crash
        print(f"live check    FAILED: {type(exc).__name__}: {exc}")
        ok = False
    return 0 if ok else 1


def memory_command(settings: Settings, args: argparse.Namespace) -> int:
    store = MemoryStore(settings.home / "memory").ensure()
    if args.memory_command == "show":
        what = args.what
        named = {
            "profile": store.profile,
            "threads": store.threads,
            "today": store.read_log,
            "tomorrow": store.tomorrow_note,
        }
        if what in named:
            text = named[what]()
        else:
            target = (store.root / what)
            if not target.is_file():
                print(f"no such memory file: {what}")
                return 1
            text = target.read_text()
        print(text.rstrip() or "(empty)")
        return 0
    if args.memory_command == "forget":
        if args.all:
            if not args.yes:
                answer = input(f"Wipe everything {NAME} remembers? Type 'forget' to confirm: ").strip()
                if answer != "forget":
                    print("kept.")
                    return 1
            store.wipe()
            print("All memory cleared.")
            return 0
        if not args.path:
            print("give a path, or --all")
            return 1
        target = store.root / args.path
        if not target.is_file():
            print(f"no such memory file: {args.path}")
            return 1
        target.unlink()
        print(f"forgot {args.path}")
        return 0
    files = store.files()
    print(f"memory at {store.root}")
    for rel, size in files:
        print(f"  {size:>7}  {rel}")
    return 0


def consolidate_command(settings: Settings, dry_run: bool) -> int:
    if not has_credentials():
        print("credentials   MISSING: set ANTHROPIC_API_KEY or run `ant auth login`")
        return 1
    store = MemoryStore(settings.home / "memory").ensure()
    result = consolidate(store, settings, dry_run=dry_run)
    print("profile\n-------")
    print(result.profile.rstrip())
    print("\nthreads\n-------")
    print(result.threads.rstrip())
    print("\ntomorrow\n--------")
    print(result.tomorrow.rstrip() or "(nothing)")
    if result.dropped:
        print("\nlet go\n------")
        for item in result.dropped:
            print(f"- {item}")
    print("\n(dry run, nothing written)" if dry_run else "\nwritten.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    if args.command == "doctor":
        return doctor(settings)
    if args.command == "memory":
        return memory_command(settings, args)
    if args.command == "consolidate":
        return consolidate_command(settings, args.dry_run)
    if args.command == "eval":
        from poyi.evals.character import run as run_character

        return run_character(settings, limit=args.limit, verbose=args.verbose)
    being = Poyi.default(settings)
    if args.command == "chat":
        return chat(being)
    if args.command == "say":
        return say(being, " ".join(args.text))
    return intro(being)


if __name__ == "__main__":
    sys.exit(main())
