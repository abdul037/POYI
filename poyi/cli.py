"""Command line entry point: `poyi`, `poyi intro`, `poyi chat`."""

import argparse
import sys

from poyi import __version__
from poyi.core import Poyi
from poyi.identity import ACRONYM, FULL_FORM, NAME


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="poyi", description=f"{NAME}: {FULL_FORM}")
    parser.add_argument("--version", action="version", version=f"{NAME} {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("intro", help=f"print how {NAME} introduces itself (default)")
    sub.add_parser("chat", help=f"talk to {NAME} in a loop; Ctrl-D or Ctrl-C to leave")
    return parser


def intro(being: Poyi) -> int:
    print(NAME)
    print(f"{ACRONYM} - {FULL_FORM}")
    print(being.introduce())
    return 0


def chat(being: Poyi) -> int:
    print(being.introduce())
    prompt_you = "you  > "
    prompt_poyi = f"{NAME.lower():<4} > "
    try:
        while True:
            line = input(prompt_you).strip()
            if not line:
                continue
            print(prompt_poyi + being.reply(line))
    except (EOFError, KeyboardInterrupt):
        print()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    being = Poyi()
    if args.command == "chat":
        return chat(being)
    return intro(being)


if __name__ == "__main__":
    sys.exit(main())
