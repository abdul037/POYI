from datetime import datetime, time, timedelta

from poyi import cli
from poyi.brain.agent import Brain
from poyi.brain.character import build_system_prompt
from poyi.config import Settings
from poyi.core import Poyi
from poyi.world import Refresher, World, WorldStore
from poyi.world.mode import Override, infer_mode, in_window, parse_duration, parse_quiet_hours
from poyi.world.refresh import apply
from poyi.world.sensors import (
    FRONT_APP,
    FRONT_WINDOW,
    IDLE_SECONDS,
    SSID_IPCONFIG,
    SSID_NETWORKSETUP,
    ActiveAppSensor,
    ClockSensor,
    PlaceSensor,
    ThreadsSensor,
    part_of_day,
    run,
)
from poyi.world.tool import make_update_world_tool
from tests.fakes import FakeClient, simple_turn

NOW = datetime(2026, 9, 7, 21, 40)


def fake_runner(table):
    def runner(argv):
        return table.get(tuple(argv), "")
    return runner


# --- model ---------------------------------------------------------------------------

def test_render_is_compact_and_in_order():
    w = World()
    w.now.time, w.now.part_of_day, w.now.place, w.now.activity, w.now.app, w.now.window = (
        "Monday 7 September 2026, 21:40", "evening", "home", "coding", "Code", "agent.py")
    w.now.idle_minutes = 7
    w.next = ["09:00 Mon Standup"]
    w.people = ["Sam: unanswered"]
    w.threads = [f"promised: t{i}" for i in range(8)]
    w.home = {"office lights": "on"}
    text = w.render(max_items=3)
    assert text.splitlines()[0] == "now:"
    assert "  activity: coding (Code: agent.py)" in text
    assert "  idle: 7 min" in text
    assert "  - (+5 more)" in text
    assert "home:\n  office lights: on" in text
    assert len(text) < 3200  # comfortably under the 800-token budget


def test_round_trip_and_unknown_keys_ignored():
    w = World(next=["x"], updated="2026-09-07T21:40:00")
    w.now.place = "home"
    data = w.to_dict()
    data["now"]["bogus"] = 1
    data["bogus"] = 2
    back = World.from_dict(data)
    assert back.now.place == "home" and back.next == ["x"] and back.updated == w.updated


# --- mode ------------------------------------------------------------------------------

def test_quiet_hours_parsing_and_wrap():
    win = parse_quiet_hours("23:00-07:00")
    assert win == (time(23), time(7))
    assert in_window(time(23, 30), win) and in_window(time(3), win) and not in_window(time(12), win)
    assert parse_quiet_hours("garbage") is None and parse_quiet_hours("") is None


def test_parse_duration():
    assert parse_duration("90m") == timedelta(minutes=90)
    assert parse_duration("2h") == timedelta(hours=2)
    assert parse_duration("1h30m") == timedelta(minutes=90)
    assert parse_duration("45") == timedelta(minutes=45)
    import pytest
    with pytest.raises(ValueError):
        parse_duration("soon")


def test_infer_mode_rules():
    w = World()
    assert infer_mode(w, now=NOW) == ("relaxed", "inferred")
    w.now.activity = "meeting"
    assert infer_mode(w, now=NOW)[0] == "meeting"
    w.now.activity = "coding"
    assert infer_mode(w, now=NOW, same_activity_minutes=10)[0] == "relaxed"
    assert infer_mode(w, now=NOW, same_activity_minutes=30)[0] == "focus"
    w.now.idle_minutes = 6
    assert infer_mode(w, now=NOW, same_activity_minutes=30)[0] == "relaxed"
    w.now.place = "away"
    assert infer_mode(w, now=NOW)[0] == "away"
    w.now.place = "home"
    w.now.idle_minutes = 20
    assert infer_mode(w, now=datetime(2026, 9, 8, 2, 0))[0] == "asleep"
    assert infer_mode(w, now=datetime(2026, 9, 8, 2, 0), quiet_hours="")[0] == "relaxed"


def test_manual_override_wins_until_it_expires():
    w = World()
    w.now.activity = "meeting"
    ov = Override(mode="relaxed", until=NOW + timedelta(hours=1))
    assert infer_mode(w, now=NOW, override=ov) == ("relaxed", "manual")
    assert infer_mode(w, now=NOW + timedelta(hours=2), override=ov)[0] == "meeting"
    assert Override.from_dict({"mode": "focus", "until": "bad"}) is None
    assert Override.from_dict(None) is None


# --- sensors -----------------------------------------------------------------------------

def test_run_times_out_and_returns_empty():
    assert run(["sleep", "5"], timeout=0.2) == ""
    assert run(["/no/such/binary"]) == ""
    assert run(["sh", "-c", "exit 1"]) == ""
    assert run(["echo", "hi"]) == "hi"


def test_clock_and_part_of_day():
    out = ClockSensor().read(World(), NOW)
    assert out["time"] == "Monday 7 September 2026, 21:40" and out["part_of_day"] == "evening"
    assert part_of_day(datetime(2026, 1, 1, 6)) == "morning" and part_of_day(datetime(2026, 1, 1, 23)) == "night"


def test_active_app_sensor_maps_activity_and_idle():
    runner = fake_runner({tuple(FRONT_APP): "Code", tuple(FRONT_WINDOW): "agent.py - poyi" + "x" * 100, tuple(IDLE_SECONDS): "125.5"})
    out = ActiveAppSensor(runner=runner).read(World(), NOW)
    assert out["app"] == "Code" and out["activity"] == "coding" and out["idle_minutes"] == 2
    assert len(out["window"]) == 60


def test_active_app_sensor_degrades_when_blocked():
    out = ActiveAppSensor(runner=fake_runner({})).read(World(), NOW)
    assert out == {"idle_minutes": 0}


def test_active_app_sensor_marks_long_idle():
    runner = fake_runner({tuple(FRONT_APP): "Safari", tuple(IDLE_SECONDS): "1200"})
    out = ActiveAppSensor(runner=runner).read(World(), NOW)
    assert out["activity"] == "idle" and out["idle_minutes"] == 20


def test_place_sensor():
    assert PlaceSensor(home_ssid="", runner=fake_runner({})).read(World(), NOW) == {}
    s = PlaceSensor(home_ssid="HomeNet", runner=fake_runner({tuple(SSID_IPCONFIG): "HomeNet"}))
    assert s.read(World(), NOW) == {"place": "home"}
    s = PlaceSensor(home_ssid="HomeNet", runner=fake_runner({tuple(SSID_NETWORKSETUP): "CafeWifi"}))
    assert s.read(World(), NOW) == {"place": "away"}
    assert PlaceSensor(home_ssid="HomeNet", runner=fake_runner({})).read(World(), NOW) == {"place": "unknown"}


def test_threads_sensor_flattens_headings():
    text = "# Threads\n\n## Promised\n- reply to Sam\n\n## Waiting on\n\n## Goals\n- ship phase 3\n"
    out = ThreadsSensor(read_threads=lambda: text).read(World(), NOW)
    assert out == {"threads": ["promised: reply to Sam", "goals: ship phase 3"]}


# --- refresher -------------------------------------------------------------------------------

class StubSensor:
    name = "stub"

    def __init__(self, reads):
        self.reads = reads

    def read(self, world, now):
        return self.reads


class BrokenSensor:
    name = "broken"

    def read(self, world, now):
        raise RuntimeError("boom")


def test_apply_reports_only_real_changes():
    w = World()
    assert apply(w, {"place": "home", "next": ["a"], "home": {"door": "closed"}}) == {"place": "home", "next": ["a"], "home": {"door": "closed"}}
    assert apply(w, {"place": "home", "next": ["a"]}) == {}
    assert apply(w, {"home": {"lights": "on"}}) == {"home": {"door": "closed", "lights": "on"}}


def test_refresher_runs_sensors_infers_mode_persists_and_records(tmp_path):
    store = WorldStore(tmp_path)
    settings = Settings(home=tmp_path, world_refresh_s=60, focus_after_min=25)
    r = Refresher(store, [ClockSensor(), StubSensor({"activity": "coding", "place": "home"}), BrokenSensor()], settings)
    changed = r.refresh(NOW, force=True)
    assert changed["activity"] == "coding" and "broken_error" in changed
    assert r.world.now.mode == "relaxed"
    assert store.load().now.activity == "coding"
    # thirty minutes of the same activity: focus
    assert r.refresh(NOW + timedelta(minutes=30), force=True)["mode"] == "focus"
    history = store.history_path.read_text().splitlines()
    assert len(history) == 2 and '"mode": "focus"' in history[1]
    # rate limited without force
    assert r.refresh(NOW + timedelta(minutes=30, seconds=10)) == {}


def test_refresher_note_holds_brain_values_and_appends(tmp_path):
    store = WorldStore(tmp_path)
    r = Refresher(store, [StubSensor({"activity": "coding", "place": "home"})], Settings(home=tmp_path))
    r.refresh(NOW, force=True)
    changed = r.note({"place": "away", "__append__": {"notes": ["leaving for the dentist"], "next": ["11:30 Dentist"]}}, NOW)
    assert changed["place"] == "away" and changed["notes"] == ["leaving for the dentist"]
    r.refresh(NOW + timedelta(minutes=5), force=True)
    assert r.world.now.place == "away"  # sensor did not override the hold
    r.refresh(NOW + timedelta(minutes=45), force=True)
    assert r.world.now.place == "home"  # hold expired
    assert r.note({"__append__": {"notes": ["leaving for the dentist"]}}, NOW) == {}


def test_manual_mode_override_via_store(tmp_path):
    store = WorldStore(tmp_path)
    store.set_override(Override(mode="focus", until=NOW + timedelta(hours=1)))
    r = Refresher(store, [], Settings(home=tmp_path))
    r.refresh(NOW, force=True)
    assert (r.world.now.mode, r.world.now.mode_source) == ("focus", "manual")
    store.set_override(None)
    r.refresh(NOW + timedelta(minutes=2), force=True)
    assert r.world.now.mode_source == "inferred"


# --- brain tool and injection ----------------------------------------------------------------

def test_update_world_tool_validates_and_notes(tmp_path):
    r = Refresher(WorldStore(tmp_path), [], Settings(home=tmp_path))
    tool = make_update_world_tool(r.note)
    assert tool.name == "update_world"
    assert tool.call({"place": "mars"}).startswith("place must be")
    assert tool.call({"mode": "grumpy"}).startswith("mode must be")
    out = tool.call({"place": "away", "activity": "Travelling", "next_item": "11:30 Dentist", "note_text": "back by 1"})
    assert out.startswith("Updated:") and "place" in out and "next" in out
    assert r.world.now.activity == "travelling" and r.world.next == ["11:30 Dentist"] and r.world.notes == ["back by 1"]
    assert tool.call({}) == "Nothing changed."


def test_brain_injects_picture_into_latest_user_turn_only():
    client = FakeClient([simple_turn("ok")])
    brain = Brain(Settings(), client=client, tools=[], turn_context=lambda: "now:\n  place: home")
    brain.reply("first")
    client.turns = [simple_turn("ok again")]
    brain.reply("second")
    sent = client.calls[1]["messages"]
    assert sent[0] == {"role": "user", "content": "first"}
    assert sent[-1]["content"][0]["text"].startswith("<picture>\nnow:")
    assert sent[-1]["content"][1]["text"] == "second"
    assert brain.messages[-2]["content"] == "second"  # stored history stays clean


def test_picture_section_is_opt_in():
    assert "<picture>" not in build_system_prompt(Settings())
    assert "update_world" in build_system_prompt(Settings(), world=True)


def test_default_assembles_world(tmp_path, monkeypatch):
    monkeypatch.setattr("poyi.core.has_credentials", lambda: True)
    monkeypatch.setattr("poyi.world.sensors.run", lambda argv, timeout=3.0: "")
    being = Poyi.default(Settings(home=tmp_path, world_refresh_s=0))
    assert being.world is not None and (tmp_path / "world.json").exists()
    assert any(getattr(t, "name", "") == "update_world" for t in being.brain.tools)
    assert "<picture>" in being.brain.system
    assert being.brain.turn_context().startswith("now:")


# --- cli -------------------------------------------------------------------------------------------

def test_world_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("POYI_HOME", str(tmp_path))
    monkeypatch.setattr("poyi.world.sensors.run", lambda argv, timeout=3.0: "")
    assert cli.main(["world"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("now:") and "activity unknown" in out
    assert cli.main(["world", "mode", "focus", "--for", "45m"]) == 0
    out = capsys.readouterr().out
    assert "mode focus until" in out and "mode: focus (set by them)" in out
    assert cli.main(["world", "mode", "off"]) == 0
    assert "inferring again" in capsys.readouterr().out
    assert cli.main(["world", "set", "place", "home"]) == 0
    assert "place: home" in capsys.readouterr().out
    assert cli.main(["world", "set", "place", "mars"]) == 1
    assert cli.main(["world", "mode", "focus", "--for", "soon"]) == 1
