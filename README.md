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
| `POYI_HOME` | `~/.poyi` | where memory and state will live |

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
| `poyi/evals/character.py` | the character eval set |
| `tests/` | fast tests with a fake client |
