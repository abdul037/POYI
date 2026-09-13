from datetime import datetime, timedelta

import pytest

from poyi import cli
from poyi.brain.character import build_system_prompt
from poyi.config import Settings
from poyi.core import Poyi
from poyi.hands import AllowAll, AuditLog, DenyAll, Hand, PromptConfirmer, Registry, build_hands
from poyi.hands import macos, reminders, shell
from poyi.hands.assemble import RemindersSensor
from poyi.hands.reminders import ReminderStore, ReminderWatcher, parse_when
from poyi.initiative.watchers import NextWatcher
from poyi.world.model import World

NOW = datetime(2026, 9, 7, 14, 0)  # Monday


def make_registry(tmp_path, confirmer=None, unlocked=()):
    return Registry(AuditLog(tmp_path / "audit.jsonl"), confirmer or DenyAll(), set(unlocked))


# --- registry ------------------------------------------------------------------------------

def test_free_hand_runs_and_is_audited(tmp_path):
    reg = make_registry(tmp_path)
    reg.add(Hand("echo", "free", lambda text: f"echo {text}", lambda text: text.upper()))
    assert reg.call("echo", text="hi") == "HI"
    (entry,) = reg.audit.recent()
    assert entry["hand"] == "echo" and entry["outcome"] == "ok" and entry["result"] == "HI" and entry["args"] == {"text": "hi"}


def test_confirm_hand_asks_and_respects_decline(tmp_path):
    asked = []

    class Ask:
        def __init__(self, answer):
            self.answer = answer

        def ask(self, description):
            asked.append(description)
            return self.answer

    reg = make_registry(tmp_path, Ask(False))
    reg.add(Hand("send", "confirm", lambda to, text: f"send {to} {text!r}", lambda to, text: "sent"))
    out = reg.call("send", to="Sam", text="late")
    assert out.startswith("They declined: send Sam 'late'") and asked == ["send Sam 'late'"]
    assert reg.audit.recent()[-1]["outcome"] == "declined"
    reg.confirmer = Ask(True)
    assert reg.call("send", to="Sam", text="late") == "sent"
    assert reg.audit.recent()[-1]["confirmed"] is True


def test_locked_hand_refuses_unless_unlocked(tmp_path):
    reg = make_registry(tmp_path)
    reg.add(Hand("danger", "locked", lambda: "danger", lambda: "did it"))
    assert reg.call("danger").startswith("Refused: danger is locked")
    assert reg.audit.recent()[-1]["outcome"] == "refused: locked"
    reg.unlocked.add("danger")
    assert reg.call("danger") == "did it"
    assert reg.summary() == [("danger", "locked", True)]


def test_hand_errors_are_reported_not_raised(tmp_path):
    reg = make_registry(tmp_path)

    def boom():
        raise RuntimeError("nope")

    reg.add(Hand("boom", "free", lambda: "boom", boom))
    assert reg.call("boom") == "Failed: RuntimeError: nope"
    assert reg.audit.recent()[-1]["outcome"].startswith("error: RuntimeError")
    with pytest.raises(ValueError):
        reg.add(Hand("x", "weird", lambda: "", lambda: ""))


def test_prompt_confirmer():
    out = []
    assert PromptConfirmer(ask_fn=lambda q: "y", out=out.append).ask("do it") is True
    assert PromptConfirmer(ask_fn=lambda q: "", out=out.append).ask("do it") is False

    def eof(q):
        raise EOFError

    assert PromptConfirmer(ask_fn=eof, out=out.append).ask("do it") is False
    assert AllowAll().ask("x") is True and DenyAll().ask("x") is False


# --- reminders --------------------------------------------------------------------------------

def test_parse_when():
    assert parse_when("in 20m", NOW) == NOW + timedelta(minutes=20)
    assert parse_when("in 2 hours", NOW) == NOW + timedelta(hours=2)
    assert parse_when("18:00", NOW) == NOW.replace(hour=18)
    assert parse_when("6pm", NOW) == NOW.replace(hour=18)
    assert parse_when("12am", NOW) == NOW.replace(hour=0) + timedelta(days=1)
    assert parse_when("9:00", NOW) == NOW.replace(hour=9) + timedelta(days=1)  # already past today
    assert parse_when("tomorrow 9:00", NOW) == NOW.replace(hour=9) + timedelta(days=1)
    assert parse_when("2026-09-08T10:00:00", NOW) == datetime(2026, 9, 8, 10)
    with pytest.raises(ValueError):
        parse_when("soonish", NOW)
    with pytest.raises(ValueError):
        parse_when("25:00", NOW)


def test_reminder_store_and_tools(tmp_path):
    reg = make_registry(tmp_path)
    store = ReminderStore(tmp_path / "reminders.json")
    reminders.register(reg, store, now_fn=lambda: NOW)
    assert {t.name for t in reg.tools()} == {"set_reminder", "list_reminders", "cancel_reminder"}
    out = reg.call("set_reminder", text="call mum", when="in 20m")
    assert out.startswith("Reminder [") and "call mum" in out
    reg.call("set_reminder", text="gym", when="18:00")
    listed = reg.call("list_reminders")
    assert "call mum" in listed and "gym" in listed and listed.index("call mum") < listed.index("gym")
    assert reg.call("cancel_reminder", ref="gym").startswith("Cancelled")
    assert reg.call("cancel_reminder", ref="zzz").startswith("No pending reminder")
    assert [r.text for r in store.pending()] == ["call mum"]
    assert reg.call("set_reminder", text="x", when="never").startswith("Failed: ValueError")


def test_reminder_watcher_and_sensor(tmp_path):
    store = ReminderStore(tmp_path / "reminders.json")
    store.add("call mum", NOW + timedelta(minutes=20))
    store.add("dentist", NOW + timedelta(days=2))
    watcher = ReminderWatcher(store)
    assert watcher.check(World(), NOW) == []
    sensor = RemindersSensor(watcher)
    w = World(next=["09:00 Tue Standup"])
    assert sensor.read(w, NOW) == {"next": ["09:00 Tue Standup", "14:20 call mum (reminder)"]}
    w.next = sensor.read(w, NOW)["next"]
    assert NextWatcher(lead_minutes=30).check(w, NOW) == []  # reminders don't get a heads-up
    (event,) = watcher.check(World(), NOW + timedelta(minutes=21))
    assert event.source == "reminder" and event.title == "call mum" and event.importance == 0.9
    assert watcher.check(World(), NOW + timedelta(minutes=22)) == []  # marked done
    assert [r.text for r in store.pending()] == ["dentist"]


# --- macOS hands ----------------------------------------------------------------------------------

def test_macos_hands_build_the_right_commands(tmp_path):
    calls = []

    def runner(argv):
        calls.append(argv)
        return "clip text" if argv == ["pbpaste"] else ""

    reg = make_registry(tmp_path)
    macos.register(reg, runner=runner, screenshot_dir=tmp_path)
    assert reg.call("open_app", name="Spotify") == "Opened Spotify." and calls[-1] == ["open", "-a", "Spotify"]
    assert reg.call("open_app", name="x; rm -rf /").startswith("Failed: ValueError")
    assert reg.call("open_url", url="https://example.com") == "Opened https://example.com."
    assert reg.call("open_url", url="file:///etc/passwd").startswith("Failed")
    assert reg.call("clipboard_read") == "clip text"
    assert reg.call("clipboard_write", text="it's here") == "Copied to the clipboard."
    assert "pbcopy" in calls[-1][2] and "'\"'\"'" in calls[-1][2]
    assert reg.call("media", action="pause") == "Toggled play/pause."
    assert reg.call("media", action="volume 140") == "Volume 100." and "set volume output volume 100" in calls[-1][2]
    assert reg.call("media", action="dance").startswith("Failed: ValueError")
    assert reg.call("look_at_screen").startswith("Couldn't capture")


def test_look_at_screen_returns_an_image_block(tmp_path):
    def runner(argv):
        if argv[0] == "screencapture":
            (tmp_path / "poyi-screen.png").write_bytes(b"\x89PNG fake")
        return ""

    reg = make_registry(tmp_path)
    macos.register(reg, runner=runner, screenshot_dir=tmp_path)
    result = reg.call("look_at_screen")
    assert result[0]["type"] == "image" and result[0]["source"]["media_type"] == "image/png"
    assert not (tmp_path / "poyi-screen.png").exists()
    assert reg.audit.recent()[-1]["result"] == "(non-text)"


# --- shell -------------------------------------------------------------------------------------------

def test_shell_is_locked_and_allowlisted(tmp_path):
    calls = []
    reg = make_registry(tmp_path)
    shell.register(reg, ["git status", "ls"], runner=lambda argv: calls.append(argv) or "out")
    assert reg.call("run_shell", command="git status").startswith("Refused")
    reg.unlocked.add("run_shell")
    assert reg.call("run_shell", command="git status --short") == "out" and calls[-1] == ["git", "status", "--short"]
    assert reg.call("run_shell", command="git push").startswith("Not allowed")
    assert reg.call("run_shell", command="rm -rf /").startswith("Not allowed")
    assert reg.call("run_shell", command="").startswith("Not allowed")


# --- assembly and wiring ------------------------------------------------------------------------------

def test_build_hands_and_settings(tmp_path):
    settings = Settings.from_env({"POYI_HOME": str(tmp_path), "POYI_UNLOCK": "run_shell", "POYI_SHELL_ALLOW": "git status, ls -la"})
    assert settings.unlock == ["run_shell"] and settings.shell_allow == ["git status", "ls -la"]
    hands = build_hands(settings, confirmer=AllowAll(), runner=lambda argv: "")
    names = {t.name for t in hands.tools()}
    assert {"set_reminder", "open_app", "media", "look_at_screen", "run_shell"} <= names
    assert ("run_shell", "locked", True) in hands.registry.summary()
    assert len(hands.watchers) == 1 and len(hands.sensors) == 2  # reminders and calendar


def test_prompt_hands_section_is_opt_in():
    assert "look_at_screen" not in build_system_prompt(Settings())
    assert "look_at_screen" in build_system_prompt(Settings(), hands=True)


def test_default_assembles_hands(tmp_path, monkeypatch):
    monkeypatch.setattr("poyi.core.has_credentials", lambda: False)
    monkeypatch.setattr("poyi.world.sensors.run", lambda argv, timeout=3.0: "")
    being = Poyi.default(Settings(home=tmp_path, world_refresh_s=0), confirmer=AllowAll())
    assert being.hands is not None and being.initiative is not None
    assert any(getattr(w, "name", "") == "reminder" for w in being.initiative.watchers)


def test_hands_and_reminders_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("POYI_HOME", str(tmp_path))
    monkeypatch.setattr("poyi.core.has_credentials", lambda: False)
    monkeypatch.setattr("poyi.world.sensors.run", lambda argv, timeout=3.0: "")
    assert cli.main(["hands"]) == 0
    out = capsys.readouterr().out
    assert "free     set_reminder" in out and "locked   run_shell  (locked" in out
    assert cli.main(["reminders"]) == 0
    assert "no reminders pending" in capsys.readouterr().out
    ReminderStore(tmp_path / "reminders.json").add("call mum", NOW + timedelta(minutes=5))
    assert cli.main(["reminders"]) == 0
    assert "call mum" in capsys.readouterr().out
    assert cli.main(["hands", "audit"]) == 0
    assert "no actions yet" in capsys.readouterr().out
