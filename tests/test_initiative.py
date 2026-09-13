from datetime import datetime, timedelta
from types import SimpleNamespace

from poyi import cli
from poyi.brain.character import build_system_prompt
from poyi.config import Settings
from poyi.core import Poyi
from poyi.initiative import Event, EventLog, Initiative, Notifier, Weights, decide
from poyi.initiative.brief import make_brief_fn
from poyi.initiative.loop import RouteChoice, make_model_tiebreak
from poyi.initiative.policy import Decision, time_pressure
from poyi.initiative.tool import make_feedback_tool
from poyi.initiative.watchers import (
    BATTERY,
    BatteryWatcher,
    NextWatcher,
    ScheduledWatcher,
    ThreadsWatcher,
    parse_next_item,
)
from poyi.memory import MemoryStore
from poyi.world import Refresher, World, WorldStore
from tests.fakes import FakeClient, simple_turn

NOW = datetime(2026, 9, 7, 14, 0)  # Monday afternoon


def world(mode="relaxed"):
    w = World()
    w.now.mode = mode
    return w


def iso(dt):
    return dt.isoformat(timespec="seconds")


# --- events ------------------------------------------------------------------------

def test_event_log_later_lines_win_and_helpers(tmp_path):
    log = EventLog(tmp_path)
    e = Event(source="next", title="Dentist", key="k1", route="mention")
    log.append(e)
    e.delivered_at = iso(NOW)
    e.feedback = "mentioned"
    log.append(e)
    assert log.seen_keys() == {"k1"}
    assert [x.feedback for x in log.iter()] == ["mentioned"]
    assert log.pending_mentions() == []
    assert log.get(e.id[:4]).title == "Dentist" and log.get("nope") is None
    assert Event.from_dict({"source": "x", "title": "y", "bogus": 1}).title == "y"


# --- policy -------------------------------------------------------------------------

def test_time_pressure_bands():
    e = Event(source="next", title="x")
    assert time_pressure(e, NOW) == 0.0
    e.due = iso(NOW + timedelta(minutes=5))
    assert time_pressure(e, NOW) == 0.9
    e.due = iso(NOW + timedelta(minutes=30))
    assert time_pressure(e, NOW) == 0.5
    e.due = iso(NOW + timedelta(hours=5))
    assert time_pressure(e, NOW) == 0.2
    e.due = iso(NOW - timedelta(minutes=1))
    assert time_pressure(e, NOW) == 1.0


def test_decide_by_mode(tmp_path):
    w = Weights(tmp_path / "w.json")
    important = Event(source="next", title="Call", importance=0.9, due=iso(NOW + timedelta(minutes=8)))
    assert decide(important, world("relaxed"), w, NOW).route == "speak"
    assert decide(important, world("meeting"), w, NOW).route == "speak"  # urgent overrides the hard rule
    assert decide(important, world("asleep"), w, NOW).route == "note"    # never while asleep
    mild = Event(source="threads", title="Still open", importance=0.45)
    assert decide(mild, world("relaxed"), w, NOW).route == "note"
    assert decide(mild, world("focus"), w, NOW).route == "log"
    assert decide(mild, world("meeting"), w, NOW).route == "note"
    d = decide(Event(source="system", title="Battery", importance=0.6), world("relaxed"), w, NOW)
    assert d.route == "note" and "mode relaxed" in d.reason


def test_weights_learn_and_clamp(tmp_path):
    w = Weights(tmp_path / "w.json")
    for _ in range(10):
        w.learn("threads", "focus", "not_now")
    assert w.get("threads", "focus") == -1.0  # -0.5 source + -0.5 source:mode
    assert w.get("threads", "relaxed") == -0.5
    w.learn("threads", "relaxed", "thanks")
    assert round(w.get("threads", "relaxed"), 3) == round(-0.475 + 0.05, 3)
    assert Weights(tmp_path / "w.json").data == w.data  # persisted
    mild = Event(source="threads", title="x", importance=0.7)
    assert decide(mild, world("relaxed"), w, NOW).route != "speak"


# --- watchers --------------------------------------------------------------------------

def test_parse_next_item():
    assert parse_next_item("11:30 Dentist", NOW) == NOW.replace(hour=11, minute=30) + timedelta(days=1)
    assert parse_next_item("14:20 Call", NOW) == NOW.replace(hour=14, minute=20)
    assert parse_next_item("09:00 Wed Standup", NOW) == datetime(2026, 9, 9, 9, 0)
    assert parse_next_item("09:00 Mon Standup", NOW) == datetime(2026, 9, 14, 9, 0)
    assert parse_next_item("no time here", NOW) is None
    assert parse_next_item("25:99 nope", NOW) is None


def test_next_watcher_fires_in_lead_window():
    w = World(next=["14:08 Call with Sam", "18:00 Gym", "garbage"])
    events = NextWatcher(lead_minutes=10).check(w, NOW)
    assert len(events) == 1
    assert events[0].title == "14:08 Call with Sam in 8 minutes" and events[0].key.startswith("next:14:08 Call with Sam:")
    assert NextWatcher().check(w, NOW + timedelta(minutes=9)) == []


def test_threads_watcher_only_mid_morning_and_only_promises():
    text = "# Threads\n\n## Promised\n- reply to Sam\n\n## Goals\n- ship\n"
    tw = ThreadsWatcher(read_threads=lambda: text)
    assert tw.check(World(), NOW) == []
    events = tw.check(World(), NOW.replace(hour=10))
    assert [e.title for e in events] == ["Still open: reply to Sam"]


def test_battery_watcher():
    bw = BatteryWatcher(runner=lambda argv: "12%; discharging" if argv == BATTERY else "")
    assert bw.check(World(), NOW)[0].title == "Battery at 12%"
    assert BatteryWatcher(runner=lambda argv: "12%; charging").check(World(), NOW) == []
    assert BatteryWatcher(runner=lambda argv: "").check(World(), NOW) == []


def test_scheduled_watcher_window():
    sw = ScheduledWatcher(at="08:00", source="brief", title="Morning brief")
    assert sw.check(World(), NOW.replace(hour=8, minute=3))[0].key.endswith("2026-09-07")
    assert sw.check(World(), NOW.replace(hour=8, minute=20)) == []
    assert ScheduledWatcher(at="bad", source="x", title="y").check(World(), NOW) == []


# --- notify ------------------------------------------------------------------------------

def test_notifier_prints_and_calls_osascript():
    seen = []
    calls = []
    n = Notifier(desktop=True, printer=seen.append, runner=lambda argv: calls.append(argv) or "")
    assert n.send("Title", 'say "hi"')
    assert seen == ['Poyi: Title — say "hi"']
    assert calls[0][0] == "osascript" and 'say \\"hi\\"' in calls[0][2]
    assert Notifier(desktop=False).send("x") is False


# --- the loop --------------------------------------------------------------------------------

class StubWatcher:
    name = "stub"

    def __init__(self, events):
        self.events = events

    def check(self, world, now):
        return list(self.events)


def make_initiative(tmp_path, events, mode="relaxed", **kw):
    store = WorldStore(tmp_path)
    w = store.load()
    w.now.mode = mode
    store.save(w)
    store.set_override(None)
    from poyi.world.mode import Override
    store.set_override(Override(mode=mode, until=NOW + timedelta(days=1)))
    refresher = Refresher(store, [], Settings(home=tmp_path, world_refresh_s=0))
    notifier = Notifier(desktop=False, printer=lambda s: None)
    ini = Initiative(tmp_path, refresher, [StubWatcher(events)], notifier, **kw)
    return ini, notifier, refresher


def test_tick_routes_delivers_dedupes_and_logs(tmp_path):
    speak = Event(source="next", title="Call in 5", importance=0.9, due=iso(NOW + timedelta(minutes=5)), key="a")
    mention = Event(source="threads", title="Still open: reply to Sam", importance=0.75, key="b")
    note = Event(source="system", title="Battery at 12%", importance=0.6, key="c")
    ini, notifier, refresher = make_initiative(tmp_path, [speak, mention, note])
    handled = ini.tick(NOW)
    assert [e.route for e in handled] == ["speak", "mention", "note"]
    assert notifier.sent == [("Call in 5", "")]
    assert "Battery at 12%" in refresher.world.notes
    assert all(e.mode == "relaxed" for e in handled)
    assert ini.tick(NOW + timedelta(minutes=1)) == []  # same keys, nothing new
    assert len(list(ini.log.iter())) == 3


def test_mentions_ride_the_picture_then_clear(tmp_path):
    mention = Event(source="threads", title="Still open: reply to Sam", importance=0.75, key="b")
    ini, _, _ = make_initiative(tmp_path, [mention])
    ini.tick(NOW)
    text = ini.render_for_picture(NOW)
    assert text.startswith("mention:") and "Still open: reply to Sam" in text
    assert ini.mark_shown_mentioned(NOW) == 1
    assert ini.log.pending_mentions() == [] and ini.render_for_picture(NOW) == ""


def test_feedback_learns_and_expiry_marks_ignored(tmp_path):
    speak = Event(source="next", title="Call in 5", importance=0.9, due=iso(NOW + timedelta(minutes=5)), key="a")
    ini, _, _ = make_initiative(tmp_path, [speak])
    (e,) = ini.tick(NOW)
    assert "recent:" in ini.render_for_picture(NOW + timedelta(minutes=3))
    assert ini.feedback("zzzz", "thanks") is None
    updated = ini.feedback(e.id, "not_now")
    assert updated.feedback == "not_now" and ini.weights.get("next", "relaxed") < 0
    ini2, _, _ = make_initiative(tmp_path, [Event(source="next", title="Another", importance=0.9, due=iso(NOW + timedelta(minutes=5)), key="z")])
    (e2,) = ini2.tick(NOW + timedelta(minutes=10))
    ini2.watchers = []
    ini2.tick(NOW + timedelta(minutes=50))
    assert ini2.log.get(e2.id).feedback == "ignored"


def test_tiebreak_is_consulted_only_when_ambiguous(tmp_path):
    calls = []

    def tiebreak(event, world, decision):
        calls.append(decision.route)
        return "mention"

    # importance 0.5, no pressure, relaxed: score 0.30 -> note, near the 0.25 line -> ambiguous
    ini, _, _ = make_initiative(tmp_path, [Event(source="x", title="edge", importance=0.5, key="e")], tiebreak=tiebreak)
    (e,) = ini.tick(NOW)
    assert calls == ["note"] and e.route == "mention" and "tiebreak chose mention" in e.reason


def test_model_tiebreak_uses_parse_and_survives_errors():
    client = SimpleNamespace(messages=SimpleNamespace(parse=lambda **kw: SimpleNamespace(parsed_output=RouteChoice(route="Speak", reason="r"))))
    tb = make_model_tiebreak(client, "claude-haiku-4-5")
    assert tb(Event(source="x", title="t"), World(), Decision("note", 0.3, "r")) == "speak"

    def boom(**kw):
        raise RuntimeError("down")

    assert make_model_tiebreak(SimpleNamespace(messages=SimpleNamespace(parse=boom)), "m")(Event(source="x", title="t"), World(), Decision("note", 0.3, "r")) is None


def test_brief_is_generated_and_saved(tmp_path):
    memory = MemoryStore(tmp_path / "memory").ensure()
    client = FakeClient([simple_turn("Standup at nine. Dentist at half eleven.")])
    brief = make_brief_fn(Settings(), memory, lambda: "now:\n  place: home", client=client, root=tmp_path)
    text = brief("morning")
    assert text.startswith("Standup at nine")
    saved = list((tmp_path / "briefs").glob("*-morning.md"))
    assert len(saved) == 1 and "Dentist" in saved[0].read_text()
    sent = client.calls[0]
    assert "morning brief" in sent["messages"][-1]["content"][1]["text"]
    assert sent["messages"][-1]["content"][0]["text"].startswith("<picture>")


def test_brief_event_gets_a_body_when_spoken(tmp_path):
    ev = Event(source="brief", title="Morning brief", importance=0.9, due=iso(NOW), key="m")
    ini, notifier, _ = make_initiative(tmp_path, [ev], brief=lambda kind: f"{kind}: first line\nsecond")
    (e,) = ini.tick(NOW)
    assert e.route == "speak" and e.body.startswith("morning: first line")
    assert notifier.sent == [("Morning brief", "morning: first line")]


def test_feedback_tool(tmp_path):
    ini, _, _ = make_initiative(tmp_path, [Event(source="next", title="Call", importance=0.9, due=iso(NOW), key="a")])
    (e,) = ini.tick(NOW)
    tool = make_feedback_tool(ini.feedback)
    assert tool.name == "interruption_feedback"
    assert tool.call({"event_id": "x", "verdict": "meh"}).startswith("verdict must be")
    assert tool.call({"event_id": "zzzz", "verdict": "thanks"}).startswith("no event")
    assert tool.call({"event_id": f"[{e.id}]", "verdict": "thanks"}) == "Noted thanks for next: Call"


# --- wiring -----------------------------------------------------------------------------------

def test_prompt_initiative_section_is_opt_in():
    assert "interruption_feedback" not in build_system_prompt(Settings())
    assert "interruption_feedback" in build_system_prompt(Settings(), initiative=True)


def test_default_assembles_initiative_and_clears_mentions_after_a_turn(tmp_path, monkeypatch):
    monkeypatch.setattr("poyi.core.has_credentials", lambda: True)
    monkeypatch.setattr("poyi.world.sensors.run", lambda argv, timeout=3.0: "")
    monkeypatch.setattr("anthropic.Anthropic", lambda: FakeClient([simple_turn("Sure.")]))
    being = Poyi.default(Settings(home=tmp_path, world_refresh_s=0, notify=False))
    assert being.initiative is not None and being.initiative.brief is not None and being.initiative.tiebreak is not None
    assert any(getattr(t, "name", "") == "interruption_feedback" for t in being.brain.tools)
    pending = Event(source="threads", title="Still open: x", route="mention", key="p")
    being.initiative.log.append(pending)
    assert "mention:" in being.brain.turn_context()
    being.reply("hi")
    assert being.initiative.log.pending_mentions() == []


def test_initiative_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("POYI_HOME", str(tmp_path))
    monkeypatch.setenv("POYI_NOTIFY", "false")
    monkeypatch.setattr("poyi.core.has_credentials", lambda: False)
    monkeypatch.setattr("poyi.world.sensors.run", lambda argv, timeout=3.0: "")
    monkeypatch.setattr("poyi.initiative.watchers.run", lambda argv, timeout=3.0: "")
    assert cli.main(["tick"]) == 0
    assert "event(s)" in capsys.readouterr().out
    log = EventLog(tmp_path / "initiative")
    e = Event(source="next", title="Call", route="speak", score=0.8, mode="relaxed", delivered_at=iso(NOW), key="c")
    log.append(e)
    log.append(Event(source="threads", title="Open", route="mention", score=0.5, key="d"))
    assert cli.main(["initiative"]) == 0
    out = capsys.readouterr().out
    assert "routes:" in out and "Call" in out and "Open" in out
    assert cli.main(["initiative", "pending"]) == 0
    assert "Open" in capsys.readouterr().out
    assert cli.main(["initiative", "feedback", e.id, "thanks"]) == 0
    assert "noted thanks" in capsys.readouterr().out
    assert cli.main(["initiative", "weights"]) == 0
    assert "next" in capsys.readouterr().out
    assert cli.main(["initiative", "feedback", "nope", "thanks"]) == 1
    assert cli.main(["brief", "morning"]) == 1
