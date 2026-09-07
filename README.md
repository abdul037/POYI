# Poyi

**POYI - Prodigy Of Your Invention.**

Poyi is a human-like, highly intelligent companion. A prodigy, so it is sharper
than it has any right to be. Of your invention, so it is a made thing, and it is
yours.

## The name

- Say it **POY-ee**, like "toy" plus "ee".
- Write **Poyi** in prose and the app, **poyi** on the command line, and **POYI**
  only when spelling out the full form.
- Its first line to anyone: *"I'm Poyi. A prodigy of your invention."*

The name, full form, tagline, and intro live in one file,
[`poyi/identity.py`](poyi/identity.py). A test checks that the full form still
spells POYI, so you can reword it without losing the acronym.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

poyi          # how Poyi introduces itself
poyi chat     # talk to it (Ctrl-D to leave)
pytest
```

## Layout

| Path | What it is |
|---|---|
| `poyi/identity.py` | name, full form, tagline, intro line |
| `poyi/core.py` | the `Poyi` class; `reply()` is where a language model goes |
| `poyi/cli.py` | the `poyi` command |
| `tests/` | identity and CLI tests |

## Next

- Wire a language model into `Poyi.reply()`. The history list is already kept
  for you, so the model can see the whole conversation.
