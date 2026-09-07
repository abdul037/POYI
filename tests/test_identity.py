from poyi import Poyi, identity
from poyi.cli import main


def test_full_form_still_spells_the_name():
    assert identity.acronym_letters() == identity.ACRONYM


def test_intro_uses_the_name():
    assert identity.NAME in Poyi().introduce()


def test_reply_records_both_sides():
    being = Poyi()
    being.reply("hello")
    assert being.history[0] == ("user", "hello")
    assert len(being.history) == 2


def test_cli_default_prints_full_form(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert identity.FULL_FORM in out
    assert identity.INTRO in out
