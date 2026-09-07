from poyi import Poyi, identity


def test_full_form_still_spells_the_name():
    assert identity.acronym_letters() == identity.ACRONYM


def test_intro_uses_the_name():
    assert identity.NAME in Poyi().introduce()


def test_reply_records_both_sides_even_without_a_brain():
    being = Poyi()
    being.reply("hello")
    assert being.history[0] == ("user", "hello")
    assert len(being.history) == 2
