from datetime import date, datetime

from poyi import cli
from poyi.brain.agent import Brain
from poyi.config import Settings
from poyi.core import Poyi
from poyi.evals.character import CASES, add_user_case, load_user_cases
from poyi.initiative import Event
from poyi.memory import MemoryStore
from poyi.relationship import CareWatcher, GoalsWatcher, PeopleWatcher, Turn, UsageLog, WeeklyWatcher, estimate_cost, make_reflection_fn
from poyi.world.model import World
from tests.fakes import FakeClient, simple_turn

TODAY = date(2026, 9, 7)
TEN = datetime(2026, 9, 7, 10, 5)


# --- usage -----------------------------------------------------------------------------------

def test_cost_and_usage_log(tmp_path):
    assert round(estimate_cost("claude-opus-5", 1000, 100, cache_read=10000, cache_write=0), 6) == round((5000 + 2500 + 5000) / 1e6, 6)
    log = UsageLog(tmp_path / "usage.jsonl")
    log.record(Turn(at="2026-09-07T10:00:00", model="claude-opus-5", input_tokens=1000, output_tokens=100, first_token_ms=800, total_ms=2000))
    log.record(Turn(at="2026-09-07T02:00:00", model="claude-opus-5", input_tokens=1000, output_tokens=100, first_token_ms=400, total_ms=1000))
    log.record(Turn(at="2026-08-01T10:00:00", model="claude-opus-5", input_tokens=1, output_tokens=1))
    rows = log.by_day(7, today=TODAY)
    assert list(rows) == ["2026-09-07"]
    day = rows["2026-09-07"]
    assert day["turns"] == 2 and day["late"] == 1 and day["first_ms"] == 600 and day["total_ms"] == 1500
    assert round(day["cost"], 6) == round(2 * (5000 + 2500) / 1e6, 6)
    assert len(list(log.turns())) == 3


def test_brain_records_turn_stats():
    brain = Brain(Settings(), client=FakeClient([simple_turn("Hello there.")]), tools=[])
    brain.reply("hi")
    stats = brain.last_turn
    assert stats["rounds"] == 1 and stats["input_tokens"] == 10 and stats["output_tokens"] == 5
    assert 0 <= stats["first_token_ms"] <= stats["total_ms"]


def test_poyi_records_usage(tmp_path):
    brain = Brain(Settings(), client=FakeClient([simple_turn("Hello.")]), tools=[])
    usage = UsageLog(tmp_path / "usage.jsonl")
    being = Poyi(brain=brain, usage=usage)
    being.reply("hi")
    (turn,) = list(usage.turns())
    assert turn.model == "claude-opus-5" and turn.output_tokens == 5


# --- watchers --------------------------------------------------------------------------------------

def test_goals_watcher():
    threads = "# Threads\n\n## Goals\n- learn piano (check-in: 2026-09-01)\n- run 5k (check-in: 2026-12-01)\n- no date\n"
    w = GoalsWatcher(lambda: threads)
    assert w.check(World(), TEN.replace(hour=14)) == []
    (event,) = w.check(World(), TEN)
    assert event.title == "Check-in on a goal: learn piano" and event.key == "goals:learn piano:2026-09-01"


def test_people_watcher_birthdays_and_quiet():
    profile = ("# Profile\n\n## People who matter\n- Sam: old friend (birthday: 09-09) (last spoke: 2026-09-05)\n"
               "- Amina, sister (birthday: 09-07)\n- Lee (last spoke: 2026-07-01)\n\n## Preferences\n- tea (birthday: 01-01)\n")
    w = PeopleWatcher(lambda: profile)
    events = w.check(World(), TEN)
    titles = sorted(e.title for e in events)
    assert titles == ["Amina's birthday is today", "It's been 68 days since you spoke to Lee", "Sam's birthday is on Wednesday"]
    assert {e.person for e in events} == {"Sam", "Amina", "Lee"}
    assert w.check(World(), TEN.replace(hour=11)) == []


def test_weekly_watcher():
    w = WeeklyWatcher(weekday=6, at="18:00")
    sunday = datetime(2026, 9, 6, 18, 10)
    (event,) = w.check(World(), sunday)
    assert event.source == "reflection" and event.key == "reflection:2026-W36"
    assert w.check(World(), sunday.replace(hour=19)) == []
    assert w.check(World(), TEN) == []  # Monday


def test_care_watcher_is_conservative():
    heavy = {f"2026-09-{d:02d}": {"turns": 200, "late": 100, "cost": 0, "first_ms": 0, "total_ms": 0} for d in range(1, 8)}
    quiet_logs = [(TODAY, "- 10:00 worked on poyi\n- 23:00 more poyi")]
    w = CareWatcher(by_day=lambda days: heavy, read_logs=lambda days: quiet_logs)
    assert w.check(World(), TEN) == []  # wrong hour
    (event,) = w.check(World(), TEN.replace(hour=20))
    assert event.source == "care" and event.key == "care:2026-09" and "after midnight" in event.body
    social_logs = [(TODAY, "- met Sam for coffee, called mum, dinner with friends")]
    assert CareWatcher(by_day=lambda days: heavy, read_logs=lambda days: social_logs).check(World(), TEN.replace(hour=20)) == []
    light = {"2026-09-07": {"turns": 20, "late": 0, "cost": 0, "first_ms": 0, "total_ms": 0}}
    assert CareWatcher(by_day=lambda days: light, read_logs=lambda days: quiet_logs).check(World(), TEN.replace(hour=20)) == []


# --- reflection ----------------------------------------------------------------------------------------

def test_reflection_reads_logs_and_decisions(tmp_path):
    memory = MemoryStore(tmp_path / "memory", today=lambda: TODAY).ensure()
    memory.append_log("Abdul shipped phase 7", when=datetime(2026, 9, 6, 22, 0))
    events = [Event(source="next", title="Call in 5", route="speak", feedback="not_now"),
              Event(source="threads", title="Still open", route="note")]
    client = FakeClient([simple_turn("You shipped a lot. I interrupted a call. I'm holding Sam's reply.")])
    reflect = make_reflection_fn(Settings(), memory, lambda: "now:\n  place: home", lambda: events, client=client, root=tmp_path)
    text = reflect()
    assert text.startswith("You shipped a lot")
    prompt = client.calls[0]["messages"][-1]["content"][1]["text"]
    assert "Abdul shipped phase 7" in prompt and "speak   not_now   Call in 5" in prompt and "Still open" not in prompt
    assert list((tmp_path / "reflections").glob("*-W*.md"))


def test_reflection_event_gets_a_body(tmp_path):
    from tests.test_initiative import make_initiative

    ev = Event(source="reflection", title="Weekly reflection", importance=0.9, key="r")
    ini, _, _ = make_initiative(tmp_path, [ev])
    ini.reflection = lambda: "What I noticed."
    (e,) = ini.tick(datetime(2026, 9, 6, 18, 0))
    assert e.body == "What I noticed."


# --- evals grow ---------------------------------------------------------------------------------------------

def test_user_cases(tmp_path):
    settings = Settings(home=tmp_path)
    assert load_user_cases(settings) == []
    case = add_user_case(settings, "what's the weather", must="Says it can't see the weather yet", must_not="Invents a forecast")
    assert case.id == "user-1"
    (loaded,) = load_user_cases(settings)
    assert loaded.prompt == "what's the weather" and loaded.must_not == "Invents a forecast"
    assert add_user_case(settings, "x", "y").id == "user-2"
    assert len(CASES) == 20


# --- wiring and cli ----------------------------------------------------------------------------------------

def test_default_wires_relationship(tmp_path, monkeypatch):
    monkeypatch.setattr("poyi.core.has_credentials", lambda: False)
    being = Poyi.default(Settings(home=tmp_path))
    names = {getattr(w, "name", "") for w in being.initiative.watchers}
    assert {"goals", "people", "weekly", "care"} <= names
    assert being.usage is not None and being.initiative.reflection is None


def test_usage_reflect_and_eval_add_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("POYI_HOME", str(tmp_path))
    monkeypatch.setattr("poyi.core.has_credentials", lambda: False)
    assert cli.main(["usage"]) == 0
    assert "no turns" in capsys.readouterr().out
    UsageLog(tmp_path / "usage.jsonl").record(Turn(at=datetime.now().isoformat(timespec="seconds"), model="claude-opus-5", input_tokens=2000, output_tokens=200, first_token_ms=700, total_ms=1900))
    assert cli.main(["usage", "--days", "1"]) == 0
    out = capsys.readouterr().out
    assert "700 ms" in out and "total" in out
    assert cli.main(["reflect"]) == 1
    assert cli.main(["eval", "add", "--prompt", "hey", "--must", "short"]) == 0
    assert "added user-1" in capsys.readouterr().out
    assert cli.main(["eval", "add"]) == 1
