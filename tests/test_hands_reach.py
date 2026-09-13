"""Hands that reach beyond the machine: calendar, mail, messages, home."""

from datetime import datetime, timedelta
from pathlib import Path

from poyi.config import Settings
from poyi.hands import AllowAll, AuditLog, DenyAll, Registry, build_hands
from poyi.hands import calendar, home, mail, messages
from poyi.hands.calendar import CalendarSensor, parse_events
from poyi.hands.home import HomeAssistant, HomeSensor, HomeWatcher
from poyi.hands.mail import MailWatcher, people_from_profile
from poyi.hands.messages import Contacts
from poyi.world.model import World

NOW = datetime(2026, 9, 7, 14, 0)


def registry(tmp_path, confirmer=None):
    return Registry(AuditLog(tmp_path / "audit.jsonl"), confirmer or AllowAll(), set())


# --- calendar --------------------------------------------------------------------------------

CAL_OUT = "2026-09-07 15:30\tDentist\tHome\n2026-09-08 09:00\tStandup\tWork\ngarbage line\n2026-09-07 09:00\tAlready gone\tHome\n"


def test_parse_events_sorts_and_skips_junk():
    events = parse_events(CAL_OUT)
    assert [e.title for e in events] == ["Already gone", "Dentist", "Standup"]
    assert events[1].calendar == "Home" and events[1].line(NOW) == "15:30 Dentist"
    assert events[2].line(NOW) == "09:00 Tue Standup"


def test_calendar_hands(tmp_path):
    scripts = []

    def runner(argv):
        scripts.append(argv[2])
        return CAL_OUT if "every event of c" in argv[2] else "ok"

    reg = registry(tmp_path)
    calendar.register(reg, calendar_name="Home", runner=runner, now_fn=lambda: NOW)
    out = reg.call("calendar_agenda", days=2)
    assert "Dentist" in out and "[Work]" in out and "(2 * days)" in scripts[-1]
    out = reg.call("calendar_create", title='Coffee with "Sam"', when="tomorrow 9:00", minutes=30)
    assert out.startswith("Added 'Coffee with \"Sam\"' on Tuesday 08 September at 09:00")
    script = scripts[-1]
    assert 'calendar "Home"' in script and 'summary:"Coffee with \\"Sam\\""' in script and "set hours of d to 9" in script
    assert reg.audit.recent()[-1]["confirmed"] is True


def test_calendar_create_needs_confirmation_and_reports_failures(tmp_path):
    reg = registry(tmp_path, DenyAll())
    calendar.register(reg, runner=lambda argv: "", now_fn=lambda: NOW)
    assert reg.call("calendar_create", title="x", when="18:00").startswith("They declined")
    reg.confirmer = AllowAll()
    assert reg.call("calendar_create", title="x", when="18:00").startswith("Failed: RuntimeError")
    assert reg.call("calendar_agenda").startswith("Nothing on the calendar")


def test_calendar_sensor_caches_and_tags():
    calls = []

    def runner(argv):
        calls.append(1)
        return CAL_OUT

    sensor = CalendarSensor(runner=runner)
    w = World(next=["14:20 call mum (reminder)", "old (calendar)"])
    out = sensor.read(w, NOW)
    assert out["next"] == ["14:20 call mum (reminder)", "15:30 Dentist (calendar)", "09:00 Tue Standup (calendar)"]
    sensor.read(w, NOW + timedelta(minutes=5))
    assert len(calls) == 1
    sensor.read(w, NOW + timedelta(minutes=11))
    assert len(calls) == 2


# --- mail ------------------------------------------------------------------------------------------

MAIL_OUT = "Sam Lee <sam@example.com>\tFriday?\tMonday 7 September 2026 at 13:40\nNewsletter <news@x.com>\tDeals\t\n"


def test_mail_hands(tmp_path):
    scripts = []

    def runner(argv):
        scripts.append(argv[2])
        return MAIL_OUT if "read status is false" in argv[2] else "ok"

    reg = registry(tmp_path)
    mail.register(reg, runner=runner)
    out = reg.call("mail_unread", limit=5)
    assert "Sam Lee" in out and "Friday?" in out and "is greater than or equal to 5" in scripts[-1]
    out = reg.call("mail_send", to="sam@example.com", subject="Re: Friday?", body='Yes, "7pm" works')
    assert out == "Sent 'Re: Friday?' to sam@example.com."
    assert 'content:"Yes, \\"7pm\\" works"' in scripts[-1]
    assert reg.call("mail_send", to="sam", subject="x", body="y").startswith("Failed: ValueError")


def test_people_from_profile():
    text = "# Profile\n\n## Who they are\n- Abdul, builder (seen: 2026-09-07)\n\n## People who matter\n- Sam: old friend (seen: 2026-09-07)\n- Amina Khan, sister\n\n## Preferences\n- tea\n"
    assert people_from_profile(text) == ["Sam", "Amina"]


def test_mail_watcher_matches_people_and_rate_limits():
    calls = []

    def runner(argv):
        calls.append(1)
        return MAIL_OUT

    w = MailWatcher(people=lambda: ["Sam", "Amina"], runner=runner)
    events = w.check(World(), NOW)
    assert [e.title for e in events] == ["Mail from Sam Lee <sam@example.com>: Friday?"]
    assert events[0].person.startswith("Sam") and events[0].key.startswith("mail:")
    assert w.check(World(), NOW + timedelta(minutes=1)) == [] and len(calls) == 1
    assert MailWatcher(people=lambda: [], runner=runner).check(World(), NOW) == []


# --- messages -------------------------------------------------------------------------------------------

def test_contacts_resolve(tmp_path):
    path = tmp_path / "contacts.json"
    c = Contacts(path)
    assert c.resolve("Sam") is None
    path.write_text('{"Sam": "+447700900123", "Mum": "mum@example.com"}')
    assert c.resolve("sam") == "+447700900123" and c.resolve("MUM") == "mum@example.com"
    assert c.resolve("+15551234") == "+15551234" and c.resolve("x@y.z") == "x@y.z"
    path.write_text("not json")
    assert c.resolve("Sam") is None


def test_send_message(tmp_path):
    scripts = []
    (tmp_path / "contacts.json").write_text('{"Sam": "+447700900123"}')
    reg = registry(tmp_path)
    messages.register(reg, Contacts(tmp_path / "contacts.json"), runner=lambda argv: scripts.append(argv[2]) or "ok")
    assert reg.call("send_message", to="Sam", text="Running late, sorry") == "Sent to Sam: 'Running late, sorry'"
    assert 'participant "+447700900123"' in scripts[-1] and 'send "Running late, sorry"' in scripts[-1]
    assert reg.call("send_message", to="Nobody", text="hi").startswith("I don't have a number")
    assert reg.audit.recent()[-1]["description"] == "message Nobody: 'hi'"


# --- home ----------------------------------------------------------------------------------------------

class FakeHA:
    def __init__(self):
        self.calls = []
        self.states = {
            "light.office": {"entity_id": "light.office", "state": "on", "attributes": {"friendly_name": "Office lights"}},
            "binary_sensor.front_door": {"entity_id": "binary_sensor.front_door", "state": "off", "attributes": {"friendly_name": "Front door"}},
        }

    def fetch(self, method, path, body):
        self.calls.append((method, path, body))
        if path == "/api/states":
            return list(self.states.values())
        if path.startswith("/api/states/"):
            entity = path.rsplit("/", 1)[1]
            if entity not in self.states:
                raise RuntimeError("Home Assistant said 404")
            return self.states[entity]
        return []


def test_home_hands(tmp_path):
    fake = FakeHA()
    ha = HomeAssistant("http://ha.local:8123/", "tok", fetch=fake.fetch)
    reg = registry(tmp_path)
    home.register(reg, ha)
    assert reg.call("home_state", entity_id="light.office") == "Office lights: on"
    assert "binary_sensor.front_door" in reg.call("home_list") and "light.office" not in reg.call("home_list", domain="binary_sensor")
    assert reg.call("home_call", domain="light", service="turn_off", entity_id="light.office", data_json='{"transition": 2}') == "Called light.turn_off on light.office."
    assert fake.calls[-1] == ("POST", "/api/services/light/turn_off", {"entity_id": "light.office", "transition": 2})
    assert reg.call("home_state", entity_id="light.nope").startswith("Failed: RuntimeError")
    assert ha.url == "http://ha.local:8123"


def test_home_sensor_and_watcher():
    fake = FakeHA()
    ha = HomeAssistant("http://ha.local:8123", "tok", fetch=fake.fetch)
    sensor = HomeSensor(ha, ["light.office", "binary_sensor.front_door", "light.missing"])
    assert sensor.read(World(), NOW) == {"home": {"office lights": "on", "front door": "off"}}
    watcher = HomeWatcher(ha, ["binary_sensor.front_door", "light.office"])
    assert watcher.check(World(), NOW) == []  # first sight, nothing to compare
    fake.states["binary_sensor.front_door"]["state"] = "on"
    (event,) = watcher.check(World(), NOW + timedelta(minutes=1))
    assert event.title == "Front door is now on" and event.source == "home"
    assert watcher.check(World(), NOW + timedelta(minutes=2)) == []


# --- assembly ---------------------------------------------------------------------------------------------

def test_build_hands_wires_reach(tmp_path):
    settings = Settings.from_env({"POYI_HOME": str(tmp_path), "POYI_HA_URL": "http://ha.local:8123", "POYI_HA_TOKEN": "t", "POYI_HA_WATCH": "binary_sensor.front_door", "POYI_CALENDAR": "Home"})
    assert settings.calendar_name == "Home" and settings.ha_watch == ["binary_sensor.front_door"]
    fake = FakeHA()
    hands = build_hands(settings, runner=lambda argv: "", read_profile=lambda: "## People who matter\n- Sam\n",
                        ha=HomeAssistant(settings.ha_url, settings.ha_token, fetch=fake.fetch))
    names = {t.name for t in hands.tools()}
    assert {"calendar_agenda", "calendar_create", "mail_unread", "mail_send", "send_message", "home_state", "home_call"} <= names
    assert {getattr(w, "name", "") for w in hands.watchers} == {"reminder", "mail", "home"}
    assert {getattr(s, "name", "") for s in hands.sensors} == {"reminders", "calendar", "home"}
    tiers = dict((n, t) for n, t, _ in hands.registry.summary())
    assert tiers["mail_send"] == "confirm" and tiers["send_message"] == "confirm" and tiers["home_call"] == "confirm"
    assert tiers["calendar_create"] == "confirm" and tiers["calendar_agenda"] == "free"


def test_build_hands_without_home(tmp_path):
    hands = build_hands(Settings(home=tmp_path), runner=lambda argv: "")
    assert not any(t.name.startswith("home_") for t in hands.tools())
    assert {getattr(w, "name", "") for w in hands.watchers} == {"reminder"}
