"""Build the voice pieces from settings."""

from __future__ import annotations

from poyi.config import Settings
from poyi.voice.stt import STT, make_stt
from poyi.voice.audio import FfmpegRecorder, Recorder
from poyi.voice.tts import TTS, ElevenLabsTTS, SayTTS, Speaker


def make_tts(settings: Settings) -> TTS:
    if settings.tts == "elevenlabs" and settings.elevenlabs_key and settings.elevenlabs_voice:
        return ElevenLabsTTS(settings.elevenlabs_key, settings.elevenlabs_voice, model_id=settings.elevenlabs_model)
    return SayTTS(voice=settings.tts_voice, rate=settings.tts_rate)


def make_speaker(settings: Settings) -> Speaker:
    primary = make_tts(settings)
    # If the cloud voice fails mid-reply, keep talking with the local one.
    fallback = SayTTS(voice=settings.tts_voice, rate=settings.tts_rate) if getattr(primary, "name", "") == "elevenlabs" else None
    return Speaker(primary, fallback=fallback)


def make_stt_from_settings(settings: Settings) -> STT | None:
    return make_stt(settings.stt, model=settings.stt_model, command=settings.stt_command)


def make_recorder(settings: Settings) -> object:
    """The microphone source: ffmpeg (reliable on macOS) or sounddevice."""
    if settings.recorder == "ffmpeg":
        return FfmpegRecorder(device=settings.audio_input or "0")
    device = int(settings.audio_input) if settings.audio_input.isdigit() else None
    return Recorder(device=device)
