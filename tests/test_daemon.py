import json
import plistlib
import threading
import time
from datetime import datetime
from pathlib import Path

from poyi import cli
from poyi.brain.agent import Event
from poyi.config import Settings
from poyi.daemon import Daemon, DaemonClient
from poyi.daemon import launchd
from poyi.daemon.protocol import alive
from poyi.fronts.menubar import status_lines, title_for
from poyi.fronts.telegram import TelegramBot, TelegramChannel, TelegramFront, parse_message
from poyi.hands import AuditLog, DenyAll, Hand, Registry
from poyi.hands.assemble import Hands
from poyi.initiative import Notifier
from poyi.world import Refresher, WorldStore

NOW = datetime(2026, 9, 7, 3, 5)


class FakeBeing:
    """Enough of Poyi for the daemon: stream, reply, hands with a registry, world, initiative."""

    awake = True

    def __init__(self, tmp_path, reply="Hello from the daemon."):
        self.history = []
        self.reply_text = reply
        self.memory = None
        self.world = Refresher(WorldStore(tmp_path), [], Settings(home=tmp_path, world_refresh_s=0))
        self.world.refresh(NOW, force=True)
        registry = Registry(AuditLog(tmp_path / "audit.jsonl"), DenyAll(), set())
        registry.add(Hand("send", "confirm", lambda to: f"message {to}", lambda to: f"sent to {to}"))
        self.hands = Hands(registry=registry, reminders=None, watchers=[], sensors=[])
        self.initiative = None
        self.brain = None

    def stream(self, text):
        self.history.append(("user", text))
        if text.startswith("send "):
            result = self.hands.registry.call("send", to=text[5:])
            yield Event("tool", "send")
            yield Event("text", result)
            self.history.append(("poyi", result))
        else:
            for word in self.reply_text.split(" "):
                yield Event("text", word + " ")
            self.history.append(("poyi", self.reply_text))
        yield Event("done")

    def reply(self, text):
        for _ in self.stream(text):
            pass
        return self.history[-1][1]


def running_daemon(tmp_path, being=None):
    from poyi.daemon.protocol import socket_path

    being = being or FakeBeing(tmp_path)
    settings = Settings(home=tmp_path, tick_s=1)
    daemon = Daemon(being, settings, path=socket_path(tmp_path), clock=lambda: NOW)
    t = threading.Thread(target=daemon.serve, daemon=True)
    t.start()
    for _ in range(50):
        if daemon.path.exists():
            break
        time.sleep(0.02)
    client = DaemonClient(daemon.path, timeout=5)
    return daemon, client, being


def test_client_says_and_streams(tmp_path):
    daemon, client, being = running_daemon(tmp_path)
    try:
        assert client.alive()
        events = list(client.say("hi"))
        assert "".join(e.data for e in events if e.kind == "text").strip() == "Hello from the daemon."
        assert events[-1] == Event("done")
        assert being.history[0] == ("user", "hi")
        status = client.status()
        assert status["awake"] and status["turns"] == 1 and status["mode"] == "relaxed" and status["pid"]
        assert client.picture().startswith("now:")
    finally:
        daemon.stop_event.set()


def test_confirm_round_trip_over_the_socket(tmp_path):
    daemon, client, being = running_daemon(tmp_path)
    try:
        asked = []
        events = list(client.say("send Sam", confirm=lambda d: asked.append(d) or True))
        assert asked == ["message Sam"]
        assert "sent to Sam" in "".join(e.data for e in events if e.kind == "text")
        events = list(client.say("send Sam", confirm=lambda d: False))
        assert "They declined" in "".join(e.data for e in events if e.kind == "text")
        events = list(client.say("send Sam"))  # no confirm callback: declined
        assert "They declined" in "".join(e.data for e in events if e.kind == "text")
        assert isinstance(being.hands.registry.confirmer, DenyAll)  # restored after each request
    finally:
        daemon.stop_event.set()


def test_mode_tick_and_stop(tmp_path):
    daemon, client, being = running_daemon(tmp_path)
    try:
        assert client.mode("focus", 30) == "focus until 03:35"
        assert being.world.world.now.mode == "focus"
        assert client.mode("off") == "inferring again"
        assert client.mode("weird").startswith("mode must be")
        assert client.tick() == []
        assert client.request({"type": "nope"})["type"] == "error"
        client.stop()
        assert daemon.stop_event.is_set()
    finally:
        daemon.stop_event.set()
    for _ in range(60):  # the accept loop wakes every 0.5 s; give it up to 3 s to close and unlink
        if not daemon.path.exists():
            break
        time.sleep(0.05)
    assert not alive(daemon.path)


def test_socket_path_falls_back_to_tmp_when_long(tmp_path):
    from poyi.daemon.protocol import socket_path

    assert socket_path(Path("/Users/abdul/.poyi")) == Path("/Users/abdul/.poyi/poyi.sock")
    long_home = tmp_path / ("x" * 80)
    short = socket_path(long_home)
    assert str(short).startswith("/tmp/poyi-") and len(str(short)) < 60


def test_consolidation_due_window(tmp_path):
    daemon = Daemon(FakeBeing(tmp_path), Settings(home=tmp_path, consolidate_at="03:00"), path=tmp_path / "s", clock=lambda: NOW)
    assert daemon.consolidation_due(NOW)
    assert not daemon.consolidation_due(NOW.replace(hour=4))
    daemon.last_consolidated = NOW.date().isoformat()
    assert not daemon.consolidation_due(NOW)
    assert not Daemon(FakeBeing(tmp_path), Settings(home=tmp_path, consolidate_at="bad"), path=tmp_path / "s").consolidation_due(NOW)


# --- launchd ----------------------------------------------------------------------------------------

def test_launchd_plist_and_install(tmp_path):
    data = plistlib.loads(launchd.build_plist("/usr/bin/python3", tmp_path / "logs", {"POYI_HOME": "/h"}))
    assert data["Label"] == "com.poyi.daemon" and data["ProgramArguments"] == ["/usr/bin/python3", "-m", "poyi.cli", "daemon"]
    assert data["KeepAlive"] and data["RunAtLoad"] and data["EnvironmentVariables"]["POYI_HOME"] == "/h"
    calls = []
    plist = tmp_path / "LaunchAgents" / "com.poyi.daemon.plist"
    path = launchd.install(tmp_path / "home", python="/py", run=lambda argv: calls.append(argv) or "", plist=plist)
    assert path == plist and plist.exists() and (tmp_path / "home" / "logs").is_dir()
    assert calls == [["launchctl", "unload", str(plist)], ["launchctl", "load", str(plist)]]
    assert launchd.uninstall(run=lambda argv: calls.append(argv) or "", plist=plist) and not plist.exists()
    assert calls[-1] == ["launchctl", "unload", str(plist)]
    assert not launchd.uninstall(run=None, plist=plist)


# --- telegram ---------------------------------------------------------------------------------------

class FakeTelegram:
    def __init__(self, updates=None):
        self.calls = []
        self.updates_batches = list(updates or [])

    def fetch(self, url, body):
        method = url.rsplit("/", 1)[1]
        self.calls.append((method, body))
        if method == "getUpdates":
            return {"ok": True, "result": self.updates_batches.pop(0) if self.updates_batches else []}
        if method == "getFile":
            return {"ok": True, "result": {"file_path": "voice/file_1.oga"}}
        if method == "bad":
            return {"ok": False, "description": "nope"}
        return {"ok": True, "result": {}}


def test_parse_message():
    assert parse_message({"message": {"chat": {"id": 42}, "text": "hi"}}) == ("42", "hi", None)
    assert parse_message({"message": {"chat": {"id": 42}, "voice": {"file_id": "v1"}}}) == ("42", "", "v1")
    assert parse_message({"message": {"chat": {"id": 42}, "sticker": {}}}) is None
    assert parse_message({"edited_message": {}}) is None


def test_telegram_front_answers_only_the_allowed_chat(tmp_path):
    fake = FakeTelegram(updates=[[
        {"update_id": 7, "message": {"chat": {"id": 42}, "text": "hello"}},
        {"update_id": 8, "message": {"chat": {"id": 99}, "text": "intruder"}},
    ]])
    being = FakeBeing(tmp_path, reply="Evening.")
    front = TelegramFront(TelegramBot("tok", fetch=fake.fetch), "42", being)
    assert front.poll_once() == 2
    assert front.offset == 9
    sent = [b for m, b in fake.calls if m == "sendMessage"]
    assert sent == [{"chat_id": "42", "text": "Evening."}]
    assert being.history == [("user", "hello"), ("poyi", "Evening.")]
    assert fake.calls[0] == ("getUpdates", {"timeout": 25, "allowed_updates": ["message"]})


def test_telegram_voice_note_is_transcribed(tmp_path, monkeypatch):
    fake = FakeTelegram(updates=[[{"update_id": 1, "message": {"chat": {"id": 42}, "voice": {"file_id": "v1"}}}]])
    bot = TelegramBot("tok", fetch=fake.fetch)
    monkeypatch.setattr(bot, "download", lambda file_path, target: target.write_bytes(b"ogg") or target)

    class Stt:
        name = "x"

        def transcribe(self, path):
            return "remind me at six"

    front = TelegramFront(bot, "42", FakeBeing(tmp_path, reply="Done."), stt=Stt())
    front.poll_once()
    sent = [b["text"] for m, b in fake.calls if m == "sendMessage"]
    assert sent == ["you: remind me at six", "Done."]
    front_no_stt = TelegramFront(bot, "42", FakeBeing(tmp_path), stt=None)
    fake.updates_batches = [[{"update_id": 2, "message": {"chat": {"id": 42}, "voice": {"file_id": "v2"}}}]]
    front_no_stt.poll_once()
    assert [b["text"] for m, b in fake.calls if m == "sendMessage"][-1] == "I couldn't make that out."


def test_telegram_channel_and_errors(tmp_path):
    fake = FakeTelegram()
    bot = TelegramBot("tok", fetch=fake.fetch)
    assert TelegramChannel(bot, "42").send("Call in five", "with Sam")
    assert fake.calls[-1] == ("sendMessage", {"chat_id": "42", "text": "Poyi: Call in five\nwith Sam"})
    bot.send("42", "x" * 8001)
    assert len([1 for m, _ in fake.calls if m == "sendMessage"]) == 4
    import pytest
    with pytest.raises(RuntimeError):
        bot.call("bad")
    broken = TelegramChannel(TelegramBot("tok", fetch=lambda url, body: (_ for _ in ()).throw(RuntimeError("down"))), "42")
    assert broken.send("x") is False


def test_notifier_remote_channel():
    class Chan:
        def __init__(self):
            self.got = []

        def send(self, title, body=""):
            self.got.append((title, body))
            return True

    chan = Chan()
    n = Notifier(desktop=False, remote=chan)
    assert n.send("Door", "front door open", remote=False) is False and chan.got == []
    assert n.send("Door", "front door open", remote=True) is True and chan.got == [("Door", "front door open")]


# --- menubar and cli --------------------------------------------------------------------------------------

def test_menubar_text():
    assert title_for({}) == "Poyi ·"
    assert title_for({"mode": "focus", "pending": 2}) == "Poyi ● 2"
    assert status_lines({})[0] == "daemon not running"
    assert status_lines({"mode": "relaxed", "activity": "coding", "place": "home", "awake": True, "pending": 1})[-2:] == ["waiting to mention: 1", "awake"]


def test_status_and_stop_cli_without_daemon(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("POYI_HOME", str(tmp_path))
    assert cli.main(["status"]) == 1
    assert "not running" in capsys.readouterr().out
    assert cli.main(["stop"]) == 1


def test_say_routes_through_a_running_daemon(tmp_path, monkeypatch, capsys):
    daemon, client, being = running_daemon(tmp_path)
    try:
        monkeypatch.setenv("POYI_HOME", str(tmp_path))
        assert cli.main(["status"]) == 0
        assert "daemon: up since" in capsys.readouterr().out
        assert cli.main(["say", "hello", "there"]) == 0
        assert "Hello from the daemon." in capsys.readouterr().out
        assert being.history[-2] == ("user", "hello there")
    finally:
        daemon.stop_event.set()


def test_install_cli_writes_plist(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("POYI_HOME", str(tmp_path))
    calls = []
    monkeypatch.setattr("poyi.daemon.launchd.plist_path", lambda home=None: tmp_path / "LaunchAgents" / "com.poyi.daemon.plist")
    monkeypatch.setattr("poyi.world.sensors.run", lambda argv, timeout=3.0: calls.append(argv) or "")
    assert cli.main(["install"]) == 0
    assert (tmp_path / "LaunchAgents" / "com.poyi.daemon.plist").exists() and calls[-1][:2] == ["launchctl", "load"]
    assert cli.main(["uninstall"]) == 0
    assert "removed" in capsys.readouterr().out
