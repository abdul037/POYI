"""Poyi - Prodigy Of Your Invention."""

__version__ = "0.1.0"

from .identity import ACRONYM, FULL_FORM, INTRO, NAME, TAGLINE  # noqa: E402
from .core import Poyi  # noqa: E402

__all__ = ["Poyi", "NAME", "ACRONYM", "FULL_FORM", "TAGLINE", "INTRO", "__version__"]
