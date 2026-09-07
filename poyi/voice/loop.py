"""The voice loop: listen, think, speak, and stop when interrupted.

    push-to-talk   Enter to start, Enter to stop; Ctrl-C while it speaks cuts it off
    hands-free     the VAD decides when you've started and finished; speaking over
                   Poyi interrupts it
"""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Iterator

from poyi.brain.agent import Event
from poyi.identity import NAME
from poyi.voice.audio import EnergyVAD, record_until_silence, record_while, write_wav
from poyi.voice.stt import STT, TypedSTT
from poyi.voice.tts import Speaker


class VoiceLoop:
    def __init__(
        self,
        being: Any,
        stt: STT,
        speaker: Speaker,
        *,
        frames: Callable[[], Iterator[bytes]] | None = None,
        vad: EnergyVAD | None = None,
        out: Callable[[str], None] = print,
        ask: Callable[[str], str] = input,
        wav_dir: Path | None = None,
    ) -> None:
        self.being = being
        self.stt = stt
        self.speaker = speaker
        self.frames = frames
        self.vad = vad or EnergyVAD()
        self.out = out
        self.ask = ask
        self.wav_dir = wav_dir or Path(tempfile.gettempdir())

    # --- one exchange ---------------------------------------------------------------------

    def respond(self, text: str) -> str:
        """Stream the reply through the speaker; return the full text."""
        self.out(f"you  > {text}")
        prefix_written = False

        def deltas() -> Iterator[str]:
            nonlocal prefix_written
            for event in self.being.stream(text):
                if event.kind == "text":
                    yield event.data
                elif event.kind == "tool":
                    self.out(f"     ({event.data}...)")
                elif event.kind == "refusal":
                    yield event.data

        def echo(delta: str) -> None:
            nonlocal prefix_written
            if not prefix_written:
                self.out(f"{NAME.lower():<4} > ")
                prefix_written = True

        try:
            reply = self.speaker.speak_stream(deltas(), on_text=echo)
        except KeyboardInterrupt:
            self.speaker.interrupt()
            reply = "(interrupted)"
        self.out(reply.strip())
        return reply

    def transcribe(self, pcm: bytes) -> str:
        if not pcm:
            return ""
        path = write_wav(self.wav_dir / "poyi-utterance.wav", pcm)
        try:
            return self.stt.transcribe(path)
        finally:
            try:
                path.unlink()
            except OSError:
                pass

    # --- modes ------------------------------------------------------------------------------------

    def run_push_to_talk(self) -> int:
        self.out(f"{NAME}: push to talk. Enter to start, Enter to stop, Ctrl-D to leave.")
        try:
            while True:
                if isinstance(self.stt, TypedSTT):
                    text = self.stt.transcribe(Path())
                else:
                    self.ask("     [Enter to talk] ")
                    stop = threading.Event()
                    threading.Thread(target=lambda: (self.ask("     [recording; Enter to stop] "), stop.set()), daemon=True).start()
                    pcm = record_while(self.frames(), lambda: not stop.is_set())
                    text = self.transcribe(pcm)
                    if not text:
                        self.out("     (heard nothing)")
                        continue
                if not text:
                    continue
                self.respond(text)
        except (EOFError, KeyboardInterrupt):
            self.speaker.interrupt()
            self.out("")
        return 0

    def run_hands_free(self, wake: Callable[[Iterator[bytes]], bool] | None = None) -> int:
        self.out(f"{NAME}: listening. Speak, and speak over me to interrupt. Ctrl-C to leave.")
        try:
            while True:
                frames = self.frames()
                if wake is not None and not wake(frames):
                    continue
                pcm = record_until_silence(frames, self.vad, wait_for_start=wake is None)
                text = self.transcribe(pcm)
                if not text:
                    continue
                self._respond_with_barge_in(text)
        except KeyboardInterrupt:
            self.speaker.interrupt()
            self.out("")
        return 0

    def _respond_with_barge_in(self, text: str) -> None:
        stop = threading.Event()

        def monitor() -> None:
            vad = EnergyVAD(threshold=self.vad.threshold * 2.5, start_frames=6)  # ignore our own voice
            for frame in self.frames():
                if stop.is_set():
                    return
                if vad.feed(frame) == "start":
                    self.speaker.interrupt()
                    return

        watcher = threading.Thread(target=monitor, daemon=True)
        watcher.start()
        try:
            self.respond(text)
        finally:
            stop.set()
