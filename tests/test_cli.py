import io

from poyi import cli
from poyi.brain.agent import Event
from poyi.core import NO_MIND, Poyi
from poyi.identity import FULL_FORM, INTRO, NAME
from tests.fakes import FakeClient, simple_turn
from poyi.brain.agent import Brain
from poyi.config import Settings


def test_default_prints_full_form(capsys):
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert FULL_FORM in out and INTRO in out


def test_say_without_credentials_is_honest(monkeypatch, capsys):
    monkeypatch.setattr("poyi.core.has_credentials", lambda: False)
    assert cli.main(["say", "hello", "there"]) == 0
    out = capsys.readouterr().out
    assert NO_MIND in out


def test_render_streams_text_and_marks_tools():
    out = io.StringIO()
    cli.render([Event("tool", "web_search"), Event("text", "Two "), Event("text", "words."), Event("done")], out=out)
    text = out.getvalue()
    assert "(searching...)" in text
    assert f"{NAME.lower()} > Two words." in text


def test_render_refusal():
    out = io.StringIO()
    cli.render([Event("refusal", "No."), Event("done")], out=out)
    assert f"{NAME.lower()} > No." in out.getvalue()


def test_say_with_a_brain(monkeypatch, capsys):
    brain = Brain(Settings(), client=FakeClient([simple_turn("Evening, Abdul.")]), tools=[])
    monkeypatch.setattr(Poyi, "default", classmethod(lambda cls, settings=None, **kw: cls(brain=brain)))
    assert cli.main(["say", "evening"]) == 0
    assert "Evening, Abdul." in capsys.readouterr().out


def test_doctor_without_credentials_fails_cleanly(monkeypatch, capsys):
    monkeypatch.setattr("poyi.cli.has_credentials", lambda: False)
    assert cli.main(["doctor"]) == 1
    assert "MISSING" in capsys.readouterr().out
