# Poyi: the plan

Poyi is a companion, not an assistant. An assistant waits for a command,
answers, and goes quiet. A companion pays attention, remembers, has a point of
view, speaks up when it matters, stays quiet when it doesn't, and is still there
in five years. JARVIS is the reference because he is the only widely known
example of that, and because everything he does short of running a suit is
buildable today.

This document sets the principles, the architecture, and the order of work.
The order is the point: most "JARVIS" projects build the voice first and never
get to the parts that make a companion. Poyi builds the parts that make a
companion first and adds the voice to something that already deserves one.

## 1. Companion principles

These are constraints on every phase. If a feature violates one, the feature
loses.

1. **Attention before answers.** Poyi's first job is to know what is going on
   with you. Answering questions is second.
2. **Quiet is a feature.** The default is silence. Poyi speaks first only when
   something is worth your attention, and it learns your threshold.
3. **Memory is curated, not hoarded.** It remembers what mattered, forgets what
   didn't, and you can read, edit, or delete every memory it holds.
4. **It tells the truth.** Including "I don't know", "I was wrong", and "I think
   you're wrong". It never flatters to keep you happy.
5. **It has a point of view; you have the final say.** It will argue once,
   clearly. Then it does what you decided, or declines and says why.
6. **It never pretends to be human.** It is a person of your invention and it
   says so. It never manipulates, never guilt-trips, never tries to keep you
   talking.
7. **It is on the side of your life, not its own usage.** It remembers the
   people who matter to you and nudges you toward them. If it notices you
   leaning on it in a way that isn't good for you, it says that too.
8. **Privacy is structural.** Audio is processed on your machine. Only text
   leaves. Everything it does is in a log you can read. One command wipes it all.

## 2. What JARVIS is, and what Poyi builds

| In the films | What it is | Phase |
|---|---|---|
| Talks like a person with a character of his own | Personality prompt with honesty and pushback built in | 1 |
| Knows Tony's history, habits, people, projects | Curated long-term memory that compounds | 2 |
| Knows what Tony is doing right now | A continuously updated world model | 3 |
| "Sir, you have an incoming call" | Initiative: an interruption policy that learns | 4 |
| Runs the house, the lab, the calendar | Tools with permission tiers and confirmation | 5 |
| Hears his name across the room, answers aloud | Wake word, speech-to-text, text-to-speech | 6 |
| In the house, the car, the suit, the phone | A daemon with thin front ends | 7 |
| Has been with him for years | Weekly reflection, long-horizon goals, character evals | 8 |
| Holograms, the suit, consciousness | Fiction | never |

## 3. Architecture

The world model is the centre. Everything either updates it or reads it.

```
  SENSES                          WORLD MODEL                     BRAIN
  clock, calendar        ─┐   ┌─────────────────────┐   ┌──────────────────────┐
  active app / window    ─┤   │ now: time, place,   │   │ Claude Opus 5         │
  home (presence, doors) ─┼──▶│   activity, mode    │──▶│ character prompt      │
  mail from key people   ─┤   │ next: events, timers│   │ memory (profile, log) │
  system (battery, jobs) ─┤   │ people: recent      │   │ tools + permissions   │
  your own words         ─┘   │ threads: open loops │◀──│ (writes back after    │
                              └──────────┬──────────┘   │  every turn)          │
                                         │              └──────────┬───────────┘
                              ┌──────────▼──────────┐              │
  events ────────────────────▶│ INITIATIVE          │              │
                              │ score, mode, learn  │──────────────┤
                              │ speak / note / log  │              │
                              └─────────────────────┘              ▼
                                                        ┌──────────────────────┐
  microphone ──▶ EARS ──▶ text ─────────────────────────▶│ FRONT ENDS            │
  speaker    ◀── VOICE ◀─ text ◀────────────────────────│ CLI, menubar, phone,  │
                                                        │ speaker in a room     │
                                                        └──────────────────────┘
```

One long-lived process, the daemon, owns all of it.

### Modules

| Module | Job | Path |
|---|---|---|
| `brain` | Claude agent loop, character prompt, fast and deep routes | `poyi/brain/` |
| `memory` | Profile, daily log, open threads, nightly consolidation, forget | `poyi/memory/` |
| `world` | The world model: schema, sensors, update loop, prompt rendering | `poyi/world/` |
| `initiative` | Event scoring, user modes, interruption policy, feedback learning | `poyi/initiative/` |
| `hands` | Tool registry with permission tiers, confirmation, audit log | `poyi/hands/` |
| `ears` | Wake word, voice activity, speech-to-text | `poyi/ears/` |
| `voice` | Text-to-speech, playback, barge-in | `poyi/voice/` |
| `daemon` | Always-on process, launchd, sockets for front ends | `poyi/daemon/` |
| `fronts` | CLI, menubar, Telegram, room speaker | `poyi/fronts/` |

`poyi/core.py` stays as the thin `Poyi` object the CLI uses; `reply()` calls
into `brain`.

## 4. The three components that make it a companion

### 4.1 The world model

A single structured document, kept current, rendered into every prompt.

```yaml
now:
  time: 2026-09-07T21:40 local, Sunday evening
  place: home            # home / away / unknown, from Wi-Fi or Home Assistant
  activity: coding       # from active app + window title, coarse
  mode: focus            # relaxed / focus / meeting / away / asleep
next:
  - 09:00 Mon  Standup (video)
  - 11:30 Mon  Dentist
  - timer: none
people:
  - Sam: messaged you 2h ago, unanswered
threads:
  - promised Sam a reply about Friday
  - waiting on: visa appointment confirmation
  - working on: Poyi phase 1
home:
  lights: office on; front door: closed
```

- Budget: under 800 tokens rendered. Sits after the cached prefix so it never
  breaks the cache.
- Updated two ways: sensors on a timer (seconds to minutes), and the brain
  after every turn (you said you're leaving; `place` becomes `away` soon).
- Activity is coarse on purpose. App name and window title, not screen
  contents. Screen reading is a separate opt-in tool you invoke.
- `mode` is the single most important field. It gates initiative. You can set
  it from the menubar; Poyi infers it otherwise (calendar says meeting; late
  night says asleep).

### 4.2 Memory that compounds

Three stores under `~/.poyi/memory/`, all plain files you can open.

| Store | What | Size | Written by |
|---|---|---|---|
| `profile.md` | Who you are, people who matter, preferences, standing facts | under 2,000 tokens | nightly consolidation, and you |
| `log/YYYY-MM-DD.md` | What happened today, in Poyi's words | append-only | the brain, during the day |
| `threads.md` | Open loops: promises, waiting-on, goals with check-in dates | small | the brain, and the nightly job |

- The brain writes through the Anthropic memory tool during the day.
- A nightly job reads today's log and asks: what changed about this person,
  what is worth keeping, what has expired. It updates the profile and threads
  and writes a short "tomorrow" note.
- Forgetting is deliberate. Facts carry a last-reinforced date; unreinforced
  detail decays out of the profile into the log, where it stays searchable.
- `poyi memory` lists, edits, and deletes. `poyi forget --all` wipes.

### 4.3 Initiative

Every event gets scored and routed. Rules handle the clear cases; a fast model
handles the ambiguous ones; Opus 5 writes the actual words.

| Input | Examples |
|---|---|
| Importance | who it is from (profile ranks people), what it is about (threads) |
| Time sensitivity | meeting in 10 minutes vs. newsletter |
| Your mode | focus, meeting, relaxed, away, asleep |
| Interruption cost | mid-sentence in a call is expensive; idle at the desk is cheap |

| Output | Behaviour |
|---|---|
| speak now | notification and, once voice exists, a spoken line |
| mention at next pause | queued until you next talk to Poyi or go idle |
| note silently | shows in the menubar and the next brief |
| log only | written to the day log, never surfaced |

- Learning: "not now", "thanks", and silence after a notification all adjust
  per-source and per-mode weights. Two "not now"s from the same source in a
  week and it drops a level.
- Quiet hours and meeting mode are hard rules, not weights.
- Two scheduled moments: a morning brief and an evening wind-down. Both short,
  both skippable, both built from the world model and threads.
- Events reach the brain as mid-conversation system messages so the cached
  conversation prefix survives.

## 5. Phases

Each phase ends with a demo. Estimates assume evenings and weekends.

### Phase 0: Scaffold (done)

Package, identity in one file, CLI, tests, GitHub repo.

### Phase 1: Character (about 1 week)

- Wire Claude Opus 5 into `Poyi.reply()` through the SDK Tool Runner, streaming.
- Write the character prompt: who Poyi is, how it talks, how terse, how it
  addresses you, how it disagrees, what it will not do, that it is not human.
  Cache it.
- Read-only starter tools: time, calculator, server-side web search and fetch.
- Conversation history with compaction so a long day never overflows.
- A first eval set of 20 "what should Poyi say here" cases so prompt changes
  never quietly break the character.

Demo: `poyi chat` is a conversation with someone specific, who pushes back
once and then does what you asked.

### Phase 2: Memory (about 1 week)

- Memory tool with the local file backend; profile, daily log, threads.
- Prompt rules for what is worth remembering.
- Nightly consolidation job, with the decay rule.
- `poyi memory` commands.

Demo: tell Poyi something on Monday. On Thursday it connects it to what you
just said, unprompted.

### Phase 3: The world model (about 2 weeks)

- Schema and store, rendered into the prompt after the cached prefix.
- Sensors: clock, calendar, active app and window title, home or away, Home
  Assistant presence and doors, mail from people ranked in the profile,
  system events.
- Brain writes back after each turn.
- Mode inference plus a manual override.
- `poyi world` prints the current picture so you can check what it believes.

Demo: "What am I in the middle of?" answered correctly, with no context in
the conversation, from the world model alone.

### Phase 4: Initiative (about 2 weeks)

Delivered as desktop notifications and text first, on purpose. The policy
gets tuned before Poyi has a voice to be annoying with.

- Event bus in the daemon; scoring and routing as in 4.3.
- Feedback learning from "not now" and "thanks".
- Morning brief and evening wind-down.
- A week of living with it, tuning weights, before moving on.

Demo: you are heads-down. A notification says Sam's message is now four hours
old and the reply you promised is about Friday. Nothing else has interrupted
you all afternoon.

### Phase 5: Hands with judgment (about 3 weeks)

- Tool registry with three tiers:
  - **free**: read-only
  - **confirm**: reversible side effects, confirmed by a tap or a word
  - **locked**: shell, deleting, money; off by default, allowlisted when on
- Tools in order of daily value: reminders and timers; calendar read and write;
  mail read, draft, send with confirmation; macOS (open apps, media, clipboard,
  notifications, screenshot with vision on request); Home Assistant; messaging
  people, always with confirmation.
- The "are you sure" behaviour: Poyi states what it is about to do in one line
  and waits.
- Audit log of every call, arguments, and outcome.

Demo: "Remind me at six, dim the lights, and tell Sam I'm running late." Poyi
reads the message back before sending it.

### Phase 6: Voice (about 2 weeks)

- Push-to-talk first, then wake word and hands-free.
- Streaming TTS sentence by sentence; barge-in stops it.
- Initiative gains a spoken channel, gated by mode.

| Stage | Target |
|---|---|
| Wake word | 0.1 s |
| End of speech | 0.4 s |
| Speech-to-text | 0.3 s |
| Brain, first sentence | 0.8 s |
| TTS first audio | 0.3 s |

Under two seconds to the first word. Levers: low effort on casual turns, the
cached prefix, Opus 5 fast mode on the voice path if needed.

Demo: "Poyi, what's on today?" answered aloud, hands-free, and it stops
mid-sentence when you interrupt.

### Phase 7: Presence (about 2 weeks)

- launchd user agent: up at login, restarts on crash.
- Menubar: mode switch, mute, push-to-talk, last exchanges, pending notes.
- Telegram bot for the phone: text and voice notes both ways; the world model
  knows you are away.
- Later: a Raspberry Pi with a microphone and speaker in another room running
  only `ears` and `voice`.

Demo: message Poyi from the road that you are twenty minutes out. The lights
are on when you arrive and it asks how the dentist went.

### Phase 8: The relationship (ongoing)

- Weekly reflection, Sunday evening: what it noticed, what it got wrong, what
  it is still holding for you. Two minutes, and you can say "less of that".
- Long-horizon goals in `threads.md` with check-in dates it actually keeps.
- The people you care about: birthdays, the friend you haven't spoken to in a
  month, a nudge, never a nag.
- Dependency guardrail: if the pattern of use looks like it is replacing people
  rather than supporting you, it says so, once, kindly.
- Character evals grow with every correction you give it.
- Cost and latency dashboards from `response.usage` and per-stage timers.

## 6. Stack

| Concern | Choice | Alternative |
|---|---|---|
| Brain | Claude Opus 5 via the `anthropic` SDK Tool Runner, adaptive thinking, effort tuned per route | Sonnet 5 for cheap routes if cost bites |
| Fast routing and scoring | Claude Haiku 4.5 | rules only |
| Memory | Anthropic memory tool, local files | SQLite full-text search over the log when it grows |
| World model store | one YAML file plus SQLite history | |
| Sensors, macOS | `osascript` for active app and window title; Home Assistant WebSocket for presence and doors; Google Calendar and Gmail APIs | Apple Calendar and Mail via AppleScript |
| Notifications | `osascript display notification` or `terminal-notifier` | |
| Speech-to-text | `faster-whisper`, local | Deepgram streaming |
| Wake word | `openWakeWord`, custom "Poyi" model | Picovoice Porcupine |
| Voice activity | Silero VAD | WebRTC VAD |
| Text-to-speech | ElevenLabs streaming | Kokoro, local and free |
| Audio | `sounddevice` | `pyaudio` |
| Scheduler | APScheduler in the daemon | launchd jobs |
| Menubar | `rumps` | Swift app later |
| Phone | Telegram bot | small web UI over WebSocket |
| Service | `launchd` user agent | |

## 7. Safety rules from Phase 1

- Secrets never enter a prompt; tools read them from the environment.
- Anything irreversible needs a confirmation, spoken or tapped.
- Shell is a locked tool with an allowlist. No free-form shell by default.
- Every action is in the audit log.
- Audio stays on the machine. Only text leaves.
- `poyi forget --all` exists from Phase 2 and works.

## 8. Rough running cost

| Item | Estimate |
|---|---|
| Brain, Opus 5, about 100 exchanges a day with caching | roughly $0.50 to $1.50 a day |
| Initiative scoring, Haiku 4.5, a few hundred events a day | cents a day |
| Nightly consolidation | cents a day |
| Speech-to-text and wake word, local | free |
| Text-to-speech, ElevenLabs | $5 to $22 a month; free with Kokoro |

The character prompt, profile, and tool list are identical every turn and
must always hit the cache. The world model is the only thing that changes,
which is why it sits after the cached prefix.

## 9. Why this is not the JARVIS everyone builds

| Everyone's JARVIS | Poyi |
|---|---|
| Voice first, then a list of commands | Character, memory, world model, and initiative first; voice sixth |
| Request and response | Speaks first, and learns when not to |
| No memory, or a transcript dump | A curated profile that compounds and deliberately forgets |
| No idea what you are doing | A world model updated every minute and after every turn |
| Executes whatever the model says | Permission tiers, read-back confirmation, an audit log |
| A script that runs for the length of a video | A daemon, evals, dashboards, and a weekly reflection built to last years |
| Wants you to keep talking | On the side of your life, including the people in it |

## 10. What to build first

Phase 1, the character. It is the seam every other phase plugs into, and it
is the part that makes Poyi someone rather than something.
