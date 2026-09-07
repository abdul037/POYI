"""Build the voice pieces from settings."""

from __future__ import annotations

from poyi.config import Settings
from poyi.voice.stt import STT, make_stt
from poyi.voice.tts import TTS, ElevenLabsTTS, SayTTS, Speaker


def make_tts(settings: Settings) -> TTS:
    if settings.tts == "elevenlabs" and settings.elevenlabs_key and settings.elevenlabs_voice:
        return ElevenLabsTTS(settings.elevenlabs_key, settings.elevenlabs_voice)
    return SayTTS(voice=settings.tts_voice, rate=settings.tts_rate)


def make_speaker(settings: Settings) -> Speaker:
    return Speaker(make_tts(settings))


def make_stt_from_settings(settings: Settings) -> STT | None:
    return make_stt(settings.stt, model=settings.stt_model, command=settings.stt_command)
