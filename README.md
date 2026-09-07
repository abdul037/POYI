# Poyi

**POYI - Prodigy Of Your Invention.**

Poyi is a companion, not an assistant. It pays attention first, remembers what
mattered, has a point of view, speaks up when something is worth it, stays
quiet when it isn't, and never pretends to be human. The full plan is in
[`docs/PLAN.md`](docs/PLAN.md).

## The name

- Say it **POY-ee**, like "toy" plus "ee".
- **Poyi** in prose, **poyi** on the command line, **POYI** only when spelling
  out the full form.
- Its first line to anyone: *"I'm Poyi. A prodigy of your invention."*

The name, full form, tagline, and intro live in one file,
[`poyi/identity.py`](poyi/identity.py). A test checks the full form still
spells POYI. Who Poyi *is* lives in [`poyi/brain/character.py`](poyi/brain/character.py).

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env          # add ANTHROPIC_API_KEY and POYI_USER
poyi doctor                   # credentials, settings, and a live check
poyi                          # how Poyi introduces itself
poyi say what time is it      # one message
poyi chat                     # a conversation (Ctrl-D to leave)
pytest                        # no network needed
```

Credentials: set `ANTHROPIC_API_KEY` in `.env` or `~/.poyi/env`, or run
`ant auth login` if you have the Anthropic CLI. Without one, Poyi says so
instead of pretending.

## What works today (Phase 1: character)

- Claude Opus 5 through the SDK tool runner, streaming, with adaptive thinking
  and a tunable effort level.
- A stable character prompt that is cached every turn.
- Read-only tools: current time, exact arithmetic, and server-side web search
  and fetch.
- Conversation compaction so a long day never overflows the context window.
- Server-side refusal fallbacks, on by default (`POYI_FALLBACKS=false` to turn off).
- `poyi eval character`: 20 rubric cases graded by a judge model, so prompt
  changes can't quietly break the character. Costs a few cents.

## Memory (Phase 2)

Plain files under `~/.poyi/memory/` that you can open, edit, and delete:

| File | What |
|---|---|
| `profile.md` | standing facts, one per line, each tagged `(seen: YYYY-MM-DD)`; add `(keep)` to a line that must never fade |
| `threads.md` | open loops: promised, waiting on, working on, goals |
| `log/YYYY-MM-DD.md` | what happened that day, in Poyi's words |
| `notes/tomorrow.md` | a short note the nightly pass leaves for the next day |
| `history/` | backups of the profile before each rewrite |

Poyi reads the profile, threads, and today's log at the start of every
session and writes through the Anthropic memory tool as things happen. The
nightly pass folds the day into the profile, and facts not seen for 60 days
decay out unless marked `(keep)`.

```bash
poyi memory                    # list what it holds
poyi memory show profile       # or threads, today, tomorrow, or a path
poyi memory forget log/2026-09-07.md
poyi memory forget --all       # asks you to type "forget"
poyi consolidate --dry-run     # the nightly pass, without writing
poyi consolidate               # run it now (the daemon will schedule it later)
```

## The picture (Phase 3)

Poyi keeps a small, always-current picture of you in `~/.poyi/world.json`:
the time, where you are, what you're doing, your mode, what's next, people
waiting on you, open threads, and notes. Sensors refresh it about once a
minute; Poyi updates it itself when you tell it something that changes the
picture. Every message you send carries it, so Poyi answers "what am I in the
middle of?" without you explaining.

Sensors today, all local: the clock, the frontmost app and window title
(macOS, needs Automation permission for your terminal the first time), idle
time, and home-or-away from the Wi-Fi name (set `POYI_HOME_SSID`). Open
threads come from memory.

Mode is the field that gates everything later: `relaxed`, `focus`,
`meeting`, `away`, or `asleep`. Poyi infers it (quiet hours, meeting apps,
sustained work); you can set it by hand.

```bash
poyi world                       # the picture right now
poyi world refresh               # run the sensors and print it
poyi world mode focus --for 90m  # manual mode, with an expiry
poyi world mode off              # back to inferring
poyi world set place home        # correct a field by hand
```

## Settings

All optional, from the environment, `./.env`, or `~/.poyi/env`:

| Variable | Default | What |
|---|---|---|
| `POYI_USER` | | your name, so Poyi can use it |
| `POYI_ADDRESS` | | how you like to be addressed, e.g. `sir` |
| `POYI_MODEL` | `claude-opus-5` | the brain |
| `POYI_EFFORT` | `medium` | `low` to `max`; lower is faster and cheaper |
| `POYI_FAST_MODEL` | `claude-haiku-4-5` | doctor's live check, later routing |
| `POYI_JUDGE_MODEL` | `claude-sonnet-5` | grades the evals |
| `POYI_WEB` | `true` | web search and fetch tools |
| `POYI_COMPACTION` | `true` | server-side conversation compaction |
| `POYI_FALLBACKS` | `true` | server-side refusal fallbacks |
| `POYI_HOME` | `~/.poyi` | where memory and state live |
| `POYI_HOME_SSID` | | your home Wi-Fi name, for home-or-away |
| `POYI_QUIET_HOURS` | `23:00-07:00` | when Poyi assumes you're asleep if idle |
| `POYI_FOCUS_AFTER_MIN` | `25` | minutes of steady work before mode becomes focus |
| `POYI_WORLD_REFRESH_S` | `60` | how often sensors run, at most |

## Layout

| Path | What |
|---|---|
| `poyi/identity.py` | name, full form, tagline, intro |
| `poyi/config.py` | settings from the environment |
| `poyi/brain/character.py` | the system prompt: who Poyi is |
| `poyi/brain/tools.py` | Phase 1 tools |
| `poyi/brain/agent.py` | the agent loop and streaming |
| `poyi/core.py` | the `Poyi` object the CLI talks to |
| `poyi/cli.py` | `poyi`, `chat`, `say`, `doctor`, `eval` |
| `poyi/memory/store.py` | the memory files and the decay rule |
| `poyi/memory/tool.py` | the memory tool backend Claude writes through |
| `poyi/memory/consolidate.py` | the nightly pass |
| `poyi/world/model.py` | the world model and its prompt rendering |
| `poyi/world/sensors.py` | clock, active app, idle, place, threads |
| `poyi/world/mode.py` | mode inference and manual overrides |
| `poyi/world/refresh.py` | runs sensors, applies brain write-backs, persists |
| `poyi/evals/character.py` | the character eval set |
| `tests/` | fast tests with a fake client |
