"""Command line: `poyi`, `poyi intro`, `poyi chat`, `poyi say`, `poyi doctor`, `poyi eval`."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Iterable

from poyi import __version__
from poyi.brain.agent import Event
from poyi.config import Settings, has_credentials
from poyi.core import NO_MIND, Poyi
from poyi.hands.registry import AllowAll, DenyAll, PromptConfirmer
from poyi.identity import ACRONYM, FULL_FORM, NAME
from poyi.memory import MemoryStore
from poyi.memory.consolidate import consolidate
from poyi.initiative.events import ROUTES
from poyi.initiative.policy import describe_routes
from poyi.world import MODES, PLACES, Refresher, WorldStore, default_sensors
from poyi.world.mode import Override, parse_duration

TOOL_LABELS = {
    "web_search": "searching",
    "web_fetch": "reading",
    "code_execution": "working it out",
    "current_time": "checking the time",
    "calculate": "calculating",
    "memory": "remembering",
    "update_world": "noting that",
    "interruption_feedback": "noting that",
    "set_reminder": "setting a reminder",
    "list_reminders": "checking reminders",
    "cancel_reminder": "cancelling",
    "open_app": "opening",
    "open_url": "opening",
    "clipboard_read": "reading the clipboard",
    "clipboard_write": "copying",
    "media": "music",
    "look_at_screen": "looking at the screen",
    "run_shell": "running a command",
    "calendar_agenda": "checking the calendar",
    "calendar_create": "adding to the calendar",
    "mail_unread": "checking mail",
    "mail_send": "sending mail",
    "send_message": "sending a message",
    "home_state": "checking the home",
    "home_list": "checking the home",
    "home_call": "changing the home",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="poyi", description=f"{NAME}: {FULL_FORM}")
    parser.add_argument("--version", action="version", version=f"{NAME} {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("intro", help=f"print how {NAME} introduces itself (default)")
    chat_p = sub.add_parser("chat", help=f"talk to {NAME} in a loop; Ctrl-D or Ctrl-C to leave")
    chat_p.add_argument("--local", action="store_true", help="don't go through the daemon even if it's running")
    say = sub.add_parser("say", help=f"send one message to {NAME} and print the reply")
    say.add_argument("text", nargs="+", help="what to say")
    say.add_argument("--yes", action="store_true", help="approve confirm-tier actions without asking")
    say.add_argument("--local", action="store_true", help="don't go through the daemon even if it's running")
    sub.add_parser("daemon", help=f"run {NAME} always-on: ticks, the nightly pass, the socket, the phone")
    sub.add_parser("status", help="is the daemon up, and what is it doing")
    sub.add_parser("stop", help="stop the running daemon")
    sub.add_parser("install", help="start the daemon at login (a launchd user agent)")
    sub.add_parser("uninstall", help="remove the launchd user agent")
    sub.add_parser("menubar", help="the menubar app (needs rumps)")
    sub.add_parser("telegram", help="run the Telegram front on its own, without the daemon")
    sub.add_parser("doctor", help="check credentials, settings, and that the model answers")
    mem = sub.add_parser("memory", help=f"see, show, or forget what {NAME} remembers")
    mem_sub = mem.add_subparsers(dest="memory_command")
    show = mem_sub.add_parser("show", help="print profile, threads, today, tomorrow, or a file path")
    show.add_argument("what", nargs="?", default="profile")
    forget = mem_sub.add_parser("forget", help="delete one memory file, or everything with --all")
    forget.add_argument("path", nargs="?", help="path relative to the memory folder")
    forget.add_argument("--all", action="store_true", help="wipe all memory")
    forget.add_argument("--yes", action="store_true", help="skip the confirmation")
    wld = sub.add_parser("world", help=f"the picture {NAME} has of you right now")
    wld_sub = wld.add_subparsers(dest="world_command")
    wld_sub.add_parser("refresh", help="run the sensors now and print the picture")
    mode = wld_sub.add_parser("mode", help="set your mode by hand, e.g. `mode focus --for 90m`, or `mode off`")
    mode.add_argument("mode", choices=[*MODES, "off"])
    mode.add_argument("--for", dest="duration", default="2h", help="how long, e.g. 45m, 2h, 1h30m (default 2h)")
    setter = wld_sub.add_parser("set", help="set a field by hand, e.g. `set place home`")
    setter.add_argument("field", choices=["place", "activity"])
    setter.add_argument("value")
    sub.add_parser("tick", help="one pass of the initiative loop: sensors, watchers, decisions")
    watch = sub.add_parser("watch", help="run the initiative loop in the foreground; Ctrl-C to stop")
    watch.add_argument("--interval", type=int, default=None, help="seconds between ticks")
    ini = sub.add_parser("initiative", help=f"what {NAME} decided to bring up, and why")
    ini_sub = ini.add_subparsers(dest="initiative_command")
    ini_sub.add_parser("pending", help="things waiting for the next pause")
    ini_sub.add_parser("weights", help="what it has learned about interrupting you")
    fb = ini_sub.add_parser("feedback", help="tell it how an interruption landed")
    fb.add_argument("event_id")
    fb.add_argument("verdict", choices=["not_now", "thanks"])
    hands = sub.add_parser("hands", help=f"what {NAME} can do, by tier")
    hands_sub = hands.add_subparsers(dest="hands_command")
    audit = hands_sub.add_parser("audit", help="recent actions and what happened to them")
    audit.add_argument("--limit", type=int, default=20)
    sub.add_parser("reminders", help="pending reminders and timers")
    vc = sub.add_parser("voice", help=f"talk to {NAME} out loud")
    vc.add_argument("--hands-free", action="store_true", help="no button: it listens for you to start and stop")
    vc.add_argument("--typed", action="store_true", help="type instead of speaking; replies are still spoken")
    vc.add_argument("--say", metavar="TEXT", help="just speak TEXT in the configured voice and exit")
    br = sub.add_parser("brief", help="write the morning brief or evening wind-down now")
    br.add_argument("kind", choices=["morning", "evening"])
    con = sub.add_parser("consolidate", help="run the nightly memory pass now")
    con.add_argument("--dry-run", action="store_true", help="show what would change without writing")
    ev = sub.add_parser("eval", help="run an eval set against the live model, or add a case")
    ev.add_argument("suite", choices=["character", "add"], help="which eval set, or `add` a case from a correction")
    ev.add_argument("--limit", type=int, default=None, help="run only the first N cases")
    ev.add_argument("--verbose", action="store_true", help="print every reply")
    ev.add_argument("--prompt", help="for add: what was said")
    ev.add_argument("--must", help="for add: what the reply must do")
    ev.add_argument("--must-not", default="", help="for add: what it must not do")
    us = sub.add_parser("usage", help="turns, latency, and cost by day")
    us.add_argument("--days", type=int, default=7)
    sub.add_parser("reflect", help="write the weekly reflection now")
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


def chat_via_daemon(client, confirm) -> int:
    from poyi.identity import INTRO

    print(INTRO)
    print("     (through the daemon)")
    try:
        while True:
            line = input("you  > ").strip()
            if not line:
                continue
            render(client.say(line, confirm=confirm))
    except (EOFError, KeyboardInterrupt):
        print()
    return 0


def daemon_client(settings: Settings):
    from poyi.daemon import DaemonClient

    client = DaemonClient.for_home(settings.home)
    return client if client.alive() else None


def daemon_command(settings: Settings) -> int:
    import logging

    from poyi.daemon import Daemon

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    being = Poyi.default(settings, confirmer=DenyAll())
    daemon = Daemon(being, settings)
    extra = []
    if settings.telegram_token and settings.telegram_chat_id:
        from poyi.fronts.telegram import TelegramBot, TelegramFront
        from poyi.voice.assemble import make_stt_from_settings

        stt = make_stt_from_settings(settings) if settings.stt != "typed" else None
        front = TelegramFront(TelegramBot(settings.telegram_token), settings.telegram_chat_id, being, lock=daemon.lock, stt=stt)
        extra.append(front.run)
    print(f"{NAME} daemon up; socket {daemon.path}; Ctrl-C to stop")
    return daemon.run_forever(extra)


def status_command(settings: Settings) -> int:
    client = daemon_client(settings)
    if client is None:
        print("daemon: not running (start with `poyi daemon`, or `poyi install` for login)")
        return 1
    status = client.status()
    print(f"daemon: up since {status.get('since', '?')} (pid {status.get('pid', '?')})")
    print(f"awake: {'yes' if status.get('awake') else 'no credential'}")
    print(f"mode: {status.get('mode', '?')}   doing: {status.get('activity', '?')}   place: {status.get('place', '?')}")
    print(f"turns this session: {status.get('turns', 0)}   waiting to mention: {status.get('pending', 0)}")
    return 0


def stop_command(settings: Settings) -> int:
    client = daemon_client(settings)
    if client is None:
        print("daemon: not running")
        return 1
    client.stop()
    print("daemon: stopping")
    return 0


def install_command(settings: Settings, remove: bool) -> int:
    from poyi.daemon import launchd
    from poyi.world.sensors import run

    if remove:
        print("removed" if launchd.uninstall(run=run) else "nothing installed")
        return 0
    path = launchd.install(settings.home, run=run)
    print(f"installed {path}; the daemon starts at login and restarts if it stops. Logs in {settings.home / 'logs'}.")
    return 0


def telegram_command(settings: Settings) -> int:
    if not (settings.telegram_token and settings.telegram_chat_id):
        print("set TELEGRAM_BOT_TOKEN and POYI_TELEGRAM_CHAT_ID first")
        return 1
    from poyi.fronts.telegram import TelegramBot, TelegramFront
    from poyi.voice.assemble import make_stt_from_settings

    being = Poyi.default(settings, confirmer=DenyAll())
    stt = make_stt_from_settings(settings) if settings.stt != "typed" else None
    print(f"{NAME} on Telegram; Ctrl-C to stop")
    try:
        TelegramFront(TelegramBot(settings.telegram_token), settings.telegram_chat_id, being, stt=stt).run()
    except KeyboardInterrupt:
        print()
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


def world_command(settings: Settings, args: argparse.Namespace) -> int:
    store = WorldStore(settings.home)
    memory = MemoryStore(settings.home / "memory").ensure()
    refresher = Refresher(store, default_sensors(settings, memory.threads), settings)
    if args.world_command == "mode":
        if args.mode == "off":
            store.set_override(None)
            print("manual mode cleared; inferring again.")
        else:
            try:
                until = datetime.now() + parse_duration(args.duration)
            except ValueError as exc:
                print(exc)
                return 1
            store.set_override(Override(mode=args.mode, until=until))
            print(f"mode {args.mode} until {until.strftime('%H:%M')}.")
        refresher.refresh(force=True)
        print(refresher.render())
        return 0
    if args.world_command == "set":
        if args.field == "place" and args.value not in PLACES:
            print(f"place must be one of {', '.join(PLACES)}")
            return 1
        refresher.note({args.field: args.value})
        print(refresher.render())
        return 0
    if args.world_command == "refresh" or not refresher.world.updated:
        changed = refresher.refresh(force=True)
        errors = {k: v for k, v in changed.items() if k.endswith("_error")}
        for k, v in errors.items():
            print(f"({k}: {v})")
    print(refresher.render())
    if refresher.world.now.activity == "unknown" and not refresher.world.now.app:
        print("\n(activity unknown: allow Automation for your terminal in System Settings > Privacy & Security, and set POYI_HOME_SSID for place)")
    return 0


def print_events(events) -> None:
    if not events:
        print("(nothing)")
        return
    for e in events:
        stamp = e.at[11:16] if len(e.at) >= 16 else e.at
        fb = f"  [{e.feedback}]" if e.feedback else ""
        print(f"{stamp}  {e.route:<7} {e.score:.2f}  [{e.id}] {e.title}{fb}")
        if e.reason:
            print(f"                       {e.reason}")


def tick_command(being: Poyi) -> int:
    if being.initiative is None:
        print("initiative not available")
        return 1
    handled = being.initiative.tick()
    print(f"{len(handled)} event(s)")
    print_events(handled)
    return 0


def watch_command(being: Poyi, interval: int) -> int:
    import time

    if being.initiative is None:
        print("initiative not available")
        return 1
    print(f"watching every {interval}s; Ctrl-C to stop")
    try:
        while True:
            for e in being.initiative.tick():
                print(f"{datetime.now():%H:%M}  {e.route:<7} [{e.id}] {e.title}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print()
    return 0


def initiative_command(being: Poyi, args: argparse.Namespace) -> int:
    ini = being.initiative
    if ini is None:
        print("initiative not available")
        return 1
    if args.initiative_command == "pending":
        print_events(ini.log.pending_mentions())
        return 0
    if args.initiative_command == "weights":
        if not ini.weights.data:
            print("(nothing learned yet)")
        for key, value in sorted(ini.weights.data.items()):
            print(f"{value:+.2f}  {key}")
        return 0
    if args.initiative_command == "feedback":
        event = ini.feedback(args.event_id, args.verdict)
        if event is None:
            print(f"no event with id {args.event_id}")
            return 1
        print(f"noted {args.verdict} for [{event.id}] {event.title}")
        return 0
    print("routes: " + "; ".join(f"{k} = {v}" for k, v in describe_routes().items()))
    print()
    print_events(ini.recent(20))
    return 0


def hands_command(being: Poyi, args: argparse.Namespace) -> int:
    if being.hands is None:
        print("hands not available")
        return 1
    if args.hands_command == "audit":
        entries = being.hands.registry.audit.recent(args.limit)
        if not entries:
            print("(no actions yet)")
        for e in entries:
            stamp = str(e.get("at", ""))[11:16]
            print(f"{stamp}  {e.get('tier', ''):<7} {e.get('outcome', ''):<18} {e.get('description', '')}")
        return 0
    for name, tier, enabled in being.hands.registry.summary():
        state = "" if enabled else "  (locked; enable with POYI_UNLOCK)"
        print(f"{tier:<8} {name}{state}")
    return 0


def reminders_command(being: Poyi) -> int:
    if being.hands is None:
        print("hands not available")
        return 1
    items = being.hands.reminders.pending()
    if not items:
        print("(no reminders pending)")
    for r in items:
        print(f"[{r.id}] {r.at():%a %d %b %H:%M}  {r.text}")
    return 0


def voice_command(settings: Settings, args: argparse.Namespace) -> int:
    from poyi.voice.assemble import make_speaker, make_stt_from_settings
    from poyi.voice.audio import EnergyVAD, Recorder
    from poyi.voice.loop import VoiceLoop
    from poyi.voice.stt import TypedSTT

    speaker = make_speaker(settings)
    if args.say:
        speaker.enqueue(args.say)
        speaker.finish()
        return 0
    being = Poyi.default(settings, confirmer=PromptConfirmer(), voice=True)
    if not being.awake:
        print(NO_MIND)
        return 1
    if args.typed:
        stt = TypedSTT()
    else:
        stt = make_stt_from_settings(settings)
        if stt is None:
            print("no speech-to-text configured: set POYI_STT=faster-whisper (pip install 'poyi[voice]'), or use --typed")
            return 1
    loop = VoiceLoop(being, stt, speaker, frames=Recorder().frames, vad=EnergyVAD(threshold=settings.vad_threshold))
    if args.hands_free:
        return loop.run_hands_free()
    return loop.run_push_to_talk()


def usage_command(settings: Settings, days: int) -> int:
    from poyi.relationship import UsageLog

    rows = UsageLog(settings.home / "usage.jsonl").by_day(days)
    if not rows:
        print("(no turns recorded yet)")
        return 0
    print(f"{'day':<12}{'turns':>6}{'first token':>13}{'total':>9}{'cost':>9}")
    total_cost = total_turns = 0
    for day, v in rows.items():
        print(f"{day:<12}{int(v['turns']):>6}{int(v['first_ms']):>11} ms{int(v['total_ms']):>7} ms{v['cost']:>9.3f}")
        total_cost += v["cost"]
        total_turns += int(v["turns"])
    print(f"{'total':<12}{total_turns:>6}{'':>13}{'':>9}{total_cost:>9.3f}  (USD, estimated)")
    return 0


def reflect_command(being: Poyi) -> int:
    if being.initiative is None or being.initiative.reflection is None:
        print("credentials   MISSING: set ANTHROPIC_API_KEY or run `ant auth login`")
        return 1
    print(being.initiative.reflection())
    return 0


def brief_command(being: Poyi, kind: str) -> int:
    if being.initiative is None or being.initiative.brief is None:
        print("credentials   MISSING: set ANTHROPIC_API_KEY or run `ant auth login`")
        return 1
    print(being.initiative.brief(kind))
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


def configure_logging(settings: Settings) -> None:
    import logging

    if settings.debug:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)
        for noisy in ("httpx", "httpcore", "anthropic", "urllib3"):
            logging.getLogger(noisy).setLevel(logging.INFO)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    configure_logging(settings)
    if args.command == "doctor":
        return doctor(settings)
    if args.command == "memory":
        return memory_command(settings, args)
    if args.command == "consolidate":
        return consolidate_command(settings, args.dry_run)
    if args.command == "world":
        return world_command(settings, args)
    if args.command == "voice":
        return voice_command(settings, args)
    if args.command == "daemon":
        return daemon_command(settings)
    if args.command == "status":
        return status_command(settings)
    if args.command == "stop":
        return stop_command(settings)
    if args.command in ("install", "uninstall"):
        return install_command(settings, remove=args.command == "uninstall")
    if args.command == "telegram":
        return telegram_command(settings)
    if args.command == "menubar":
        from poyi.daemon import DaemonClient
        from poyi.fronts import menubar

        return menubar.run(DaemonClient.for_home(settings.home))
    if args.command in ("chat", "say") and not args.local:
        client = daemon_client(settings)
        if client is not None:
            if args.command == "chat":
                return chat_via_daemon(client, PromptConfirmer().ask)
            render(client.say(" ".join(args.text), confirm=(lambda d: True) if args.yes else None))
            return 0
    if args.command == "eval":
        from poyi.evals.character import add_user_case, run as run_character

        if args.suite == "add":
            if not (args.prompt and args.must):
                print("give --prompt and --must")
                return 1
            case = add_user_case(settings, args.prompt, args.must, args.must_not)
            print(f"added {case.id}: {case.prompt!r}")
            return 0
        return run_character(settings, limit=args.limit, verbose=args.verbose)
    if args.command == "usage":
        return usage_command(settings, args.days)
    if args.command == "chat":
        confirmer = PromptConfirmer()
    elif args.command == "say" and args.yes:
        confirmer = AllowAll()
    else:
        confirmer = DenyAll()
    being = Poyi.default(settings, confirmer=confirmer)
    if args.command == "hands":
        return hands_command(being, args)
    if args.command == "reminders":
        return reminders_command(being)
    if args.command == "tick":
        return tick_command(being)
    if args.command == "watch":
        return watch_command(being, args.interval or settings.tick_s)
    if args.command == "initiative":
        return initiative_command(being, args)
    if args.command == "brief":
        return brief_command(being, args.kind)
    if args.command == "reflect":
        return reflect_command(being)
    if args.command == "chat":
        return chat(being)
    if args.command == "say":
        return say(being, " ".join(args.text))
    return intro(being)


if __name__ == "__main__":
    sys.exit(main())
