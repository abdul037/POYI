"""Poyi's name, full form, and voice.

This is the only place the name is defined. Change it here and the CLI,
the intro line, and the tests all follow.
"""

NAME = "Poyi"
ACRONYM = "POYI"
FULL_FORM = "Prodigy Of Your Invention"
TAGLINE = "A prodigy of your invention."
INTRO = f"I'm {NAME}. {TAGLINE}"
PRONUNCIATION = "POY-ee"


def acronym_letters() -> str:
    """The initials of FULL_FORM, so a test can check they still spell ACRONYM."""
    return "".join(word[0] for word in FULL_FORM.split() if word[0].isupper())
