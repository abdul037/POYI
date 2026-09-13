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

## What works today

All eight phases of the plan have a first implementation. In order of what
makes it a companion rather than a chatbot:

| Phase | What | Section |
|---|---|---|
| 1 | a character with a point of view | below |
| 2 | memory that compounds and deliberately forgets | Memory |
| 3 | the picture: what you're doing right now | The picture |
| 4 | speaking first, and learning when not to | Speaking first |
| 5 | hands with judgment | Hands with judgment |
| 6 | a voice, local by default | Voice |
| 7 | always on, on your phone, in your menubar | Presence |
| 8 | the relationship over years | The relationship |

### Phase 1: character

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

Poyi has the profile, threads, and today's log in front of it every turn
and writes through three plain tools as things happen: `remember`,
`log_today`, and `forget`. (The Anthropic memory tool is also wired, behind
`POYI_MEMORY_TOOL=anthropic`, but it insists on reading the directory before
every turn, which cost a round trip each time.) The nightly pass folds the day
into the profile, and facts not seen for 60 days decay out unless marked
`(keep)`.

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

## Speaking first (Phase 4)

Initiative is delivered as desktop notifications and text first, on purpose,
so the interruption policy gets tuned before Poyi has a voice to be annoying
with. Every tick, watchers turn the picture and the machine into events;
the policy scores each one on importance, time pressure, your mode, and what
it has learned; then it routes:

| Route | What happens |
|---|---|
| speak | a notification now (and a spoken line, once there is a voice) |
| mention | held until your next message, then raised once at a natural pause |
| note | left in the picture and the next brief, quietly |
| log | recorded only |

Hard rules: nothing while you're asleep; nothing in a meeting unless it is
both important and due within ten minutes. Focus raises the bar. Your "not
now" and "thanks", said to Poyi or given with `poyi initiative feedback`,
adjust the weights per source and per mode; a notification nobody reacts to
for 30 minutes counts, slightly, as unwanted.

Watchers today: things in `next` at ten minutes out, promises still open
(one nudge a day, mid-morning), low battery, the morning brief, and the
evening wind-down. The briefs are written by Poyi from memory and the picture.

```bash
poyi tick                              # one pass: sensors, watchers, decisions
poyi watch --interval 30               # keep going in the foreground
poyi initiative                        # what it decided, and why
poyi initiative pending                # waiting for the next pause
poyi initiative feedback <id> not_now  # or thanks
poyi initiative weights                # what it has learned
poyi brief morning                     # or evening; needs credentials
```

## Hands with judgment (Phase 5)

Every tool sits in a tier, and every call is written to `~/.poyi/hands/audit.jsonl`:

| Tier | Rule | Today |
|---|---|---|
| free | runs at once | reminders and timers, the calendar agenda, unread mail, home device states, open an app or URL, clipboard, music, a look at the screen (only when you ask) |
| confirm | Poyi reads back exactly what will happen and waits for your go-ahead | add a calendar event, send mail, send an iMessage, change something in the home |
| locked | refused unless you enable it by name | `run_shell`, and then only allowlisted prefixes |

In `poyi chat` the go-ahead is a `[y/N]` on the terminal. `poyi say` declines
everything that needs one unless you pass `--yes`. Reminders that come due
arrive as high-priority events through initiative, not through the chat.

Calendar, Mail, and Messages go through AppleScript, so macOS will ask you
to allow Automation for your terminal the first time each is used. iMessage
names resolve through `~/.poyi/contacts.json`, which you write by hand:
`{"Sam": "+447700900123"}`. Home Assistant needs `POYI_HA_URL` and a
long-lived token in `POYI_HA_TOKEN`; the token never enters a prompt.

Calendar events and mail from people in your profile's "People who matter"
section become events for initiative; watched Home Assistant doors and
presence do too.

```bash
poyi hands                    # what it can do, by tier
poyi hands audit              # what it did, and what happened
poyi reminders                # pending reminders and timers
POYI_UNLOCK=run_shell POYI_SHELL_ALLOW="git status,ls" poyi chat
```

## Voice (Phase 6)

Local by default. The Mac's built-in voices speak (Daniel, the British one,
is the default), speech-to-text runs on the machine with faster-whisper, and
only text ever leaves. ElevenLabs is the one cloud option, for a much better
voice, when `ELEVENLABS_API_KEY` and a voice id are set.

Replies are spoken sentence by sentence while the brain is still writing
the next one. In push-to-talk, Ctrl-C cuts Poyi off. Hands-free, speaking
over it does. When `POYI_VOICE=true`, initiative speaks its notifications
aloud too, but only while your mode is relaxed.

```bash
pip install -e ".[voice]"            # sounddevice and faster-whisper
poyi voice --say "Good evening."      # test the voice
poyi voice --typed                    # type, hear the reply
poyi voice                            # push to talk: Enter to start, Enter to stop
poyi voice --hands-free               # it decides when you've started and finished
```

The first run of faster-whisper downloads the `base.en` model (about 75 MB).
macOS will ask for microphone access the first time.

## Presence (Phase 7)

One daemon owns Poyi: it runs the initiative ticks, the nightly memory pass
at `POYI_CONSOLIDATE_AT` (03:00 by default), a Unix socket at
`~/.poyi/poyi.sock`, and the Telegram front if configured. While it's
running, `poyi chat` and `poyi say` go through it, so every front shares one
conversation; `--local` bypasses it. Confirm-tier go-aheads travel over the
socket to whichever front asked.

```bash
poyi daemon                   # in the foreground, Ctrl-C to stop
poyi install                  # start at login and restart on crash (launchd)
poyi status                   # is it up, and what is it doing
poyi stop                     # ask it to stop
poyi uninstall                # remove the launchd agent
poyi menubar                  # status, mode, tick now (pip install 'poyi[menubar]')
poyi telegram                 # the phone front on its own, without the daemon
```

Telegram: make a bot with @BotFather, put its token in `TELEGRAM_BOT_TOKEN`,
and your own chat id in `POYI_TELEGRAM_CHAT_ID`; only that chat is answered.
Voice notes are transcribed with the configured speech-to-text. When the
picture says you're away, notifications go to the phone too.

Later: a Raspberry Pi with a microphone and speaker in another room, running
only the ears and the voice, talking to the daemon over the network.

## The relationship (Phase 8)

The part no one else builds.

- **Weekly reflection**, Sunday evening by default: what Poyi noticed this
  week, what it got wrong (your "not now"s and the notifications you
  ignored count against it), and what it's still holding for you. Two
  minutes to read, and it asks for "less of that" or "more of that".
- **Goals with check-ins**: a goal in `threads.md` tagged
  `(check-in: 2026-10-01)` comes back to you on that day. The nightly pass
  gives goals a date if they lack one.
- **People**: profile lines tagged `(birthday: 09-09)` get a word two days
  out; `(last spoke: 2026-08-01)` gets one gentle line after a month of
  silence, once a month at most. Poyi updates "last spoke" when you mention
  talking to someone.
- **Care**: if two weeks of use look like they are replacing people rather
  than supporting you (many heavy days or a lot after midnight, and almost
  no one else in the logs), Poyi says so once, kindly, and not again for a
  month. The heuristic is deliberately conservative and lives in
  `poyi/relationship/watchers.py`.
- **Evals that grow**: when Poyi gets something wrong, turn it into a case
  and the character eval carries it forever.
- **Usage**: every turn is recorded with latency and an estimated cost.

```bash
poyi reflect                                  # the weekly reflection, now
poyi usage --days 14                          # turns, first-token latency, cost by day
poyi eval add --prompt "what's the weather" --must "says it can't see the weather yet" --must-not "invents a forecast"
```

## Settings

All optional, from the environment, `./.env`, or `~/.poyi/env`:

| Variable | Default | What |
|---|---|---|
| `POYI_USER` | | your name, so Poyi can use it |
| `POYI_ADDRESS` | | how you like to be addressed, e.g. `sir` |
| `POYI_MODEL` | `claude-opus-5` | the brain |
| `POYI_EFFORT` | `low` | conversation effort, `low` to `max`; lower is faster |
| `POYI_DEEP_EFFORT` | `medium` | effort for briefs, reflections, and the nightly pass |
| `POYI_FAST_MODEL` | `claude-haiku-4-5` | doctor's live check, later routing |
| `POYI_JUDGE_MODEL` | `claude-sonnet-5` | grades the evals |
| `POYI_WEB` | `true` | web search and fetch tools |
| `POYI_COMPACTION` | `true` | server-side conversation compaction |
| `POYI_FALLBACKS` | `true` | server-side refusal fallbacks |
| `POYI_HOME` | `~/.poyi` | where memory and state live |
| `POYI_DEBUG` | `false` | log every tool call and result to stderr |
| `POYI_MEMORY_TOOL` | `simple` | `simple` write-only tools, or `anthropic` for the memory tool |
| `POYI_HOME_SSID` | | your home Wi-Fi name, for home-or-away |
| `POYI_QUIET_HOURS` | `23:00-07:00` | when Poyi assumes you're asleep if idle |
| `POYI_FOCUS_AFTER_MIN` | `25` | minutes of steady work before mode becomes focus |
| `POYI_WORLD_REFRESH_S` | `60` | how often sensors run, at most |
| `POYI_NOTIFY` | `true` | desktop notifications |
| `POYI_BRIEF_MORNING` | `08:00` | when the morning brief fires |
| `POYI_BRIEF_EVENING` | `21:30` | when the evening wind-down fires |
| `POYI_TICK_S` | `30` | seconds between ticks in `poyi watch` |
| `POYI_UNLOCK` | | locked hands to enable, comma-separated, e.g. `run_shell` |
| `POYI_SHELL_ALLOW` | | allowed command prefixes for `run_shell`, comma-separated |
| `POYI_CALENDAR` | first calendar | the Apple Calendar new events go into |
| `POYI_HA_URL` | | Home Assistant, e.g. `http://homeassistant.local:8123` |
| `POYI_HA_TOKEN` | | a long-lived access token |
| `POYI_HA_WATCH` | | entities for the picture and the door watcher, comma-separated |
| `POYI_VOICE` | `false` | speak initiative aloud when relaxed |
| `POYI_TTS` | `say` | `say` or `elevenlabs` |
| `POYI_TTS_VOICE` | `Daniel` | a macOS voice name; `say -v ?` lists them |
| `POYI_TTS_RATE` | `185` | words per minute for `say` |
| `ELEVENLABS_API_KEY`, `POYI_ELEVENLABS_VOICE` | | ElevenLabs key and voice id |
| `POYI_STT` | `faster-whisper` | `faster-whisper`, `command`, or `typed` |
| `POYI_STT_MODEL` | `base.en` | the whisper model size |
| `POYI_STT_COMMAND` | | for `command`: a template with `{wav}` |
| `POYI_VAD_THRESHOLD` | `500` | microphone energy that counts as speech; raise it in a noisy room |
| `POYI_CONSOLIDATE_AT` | `03:00` | when the daemon runs the nightly pass |
| `POYI_REFLECT_WEEKDAY`, `POYI_REFLECT_AT` | `6`, `18:00` | the weekly reflection (Monday is 0) |
| `TELEGRAM_BOT_TOKEN`, `POYI_TELEGRAM_CHAT_ID` | | the phone front |

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
| `poyi/initiative/watchers.py` | what turns the picture into events |
| `poyi/initiative/policy.py` | scoring, hard rules, learned weights |
| `poyi/initiative/loop.py` | the tick: decide, deliver, learn |
| `poyi/initiative/brief.py` | the morning brief and evening wind-down |
| `poyi/hands/registry.py` | tiers, confirmation, the audit log |
| `poyi/hands/reminders.py` | reminders and timers, and their watcher |
| `poyi/hands/macos.py` | apps, URLs, clipboard, music, the screen |
| `poyi/hands/calendar.py` | Apple Calendar: agenda, create, and the sensor |
| `poyi/hands/mail.py` | Apple Mail: unread, send, and the watcher |
| `poyi/hands/messages.py` | iMessage, through your contacts file |
| `poyi/hands/home.py` | Home Assistant: state, list, call, sensor, watcher |
| `poyi/hands/shell.py` | the locked, allowlisted shell |
| `poyi/voice/tts.py` | `say` and ElevenLabs, sentence streaming, interruption |
| `poyi/voice/stt.py` | faster-whisper, a command, or typing |
| `poyi/voice/audio.py` | the microphone and the energy VAD |
| `poyi/voice/loop.py` | push-to-talk and hands-free |
| `poyi/daemon/server.py` | the always-on process: ticks, nightly pass, socket |
| `poyi/daemon/client.py` | what fronts use to talk to it |
| `poyi/daemon/launchd.py` | start at login |
| `poyi/fronts/telegram.py` | the phone |
| `poyi/fronts/menubar.py` | the menubar |
| `poyi/relationship/usage.py` | per-turn latency and cost |
| `poyi/relationship/watchers.py` | goals, people, the weekly moment, care |
| `poyi/relationship/reflection.py` | the Sunday reflection |
| `poyi/evals/character.py` | the character eval set, plus your own cases |
| `tests/` | fast tests with a fake client |
