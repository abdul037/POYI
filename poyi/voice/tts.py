"""Text to speech, sentence by sentence, interruptible.

`SayTTS` uses the Mac's built-in voices and needs nothing installed.
`ElevenLabsTTS` streams a much better voice from the API when a key is set.
Both return a `Playback` you can wait on or stop. `Speaker` queues sentences
so the first one plays while the brain is still writing the second.
"""

from __future__ import annotations

import queue
import re
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]*\s+|\n+")
MIN_SENTENCE = 12  # characters; shorter fragments wait for more text


def split_sentences(buffer: str) -> tuple[list[str], str]:
    """Complete sentences from the front of `buffer`, and what's left."""
    complete: list[str] = []
    rest = buffer
    while True:
        m = SENTENCE_END.search(rest)
        if not m:
            break
        head, rest = rest[: m.end()].strip(), rest[m.end():]
        if head:
            if complete and len(complete[-1]) < MIN_SENTENCE:
                complete[-1] = f"{complete[-1]} {head}"
            else:
                complete.append(head)
    return complete, rest


def clean_for_speech(text: str) -> str:
    """Strip the markdown a model might still produce."""
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"[ \t]+", " ", text).strip()


class Playback(Protocol):
    def wait(self) -> None: ...
    def stop(self) -> None: ...


@dataclass
class ProcessPlayback:
    process: Any

    def wait(self) -> None:
        try:
            self.process.wait()
        except Exception:  # noqa: BLE001
            pass

    def stop(self) -> None:
        try:
            self.process.terminate()
        except Exception:  # noqa: BLE001
            pass


class TTS(Protocol):
    name: str

    def speak(self, text: str) -> Playback: ...


class SayTTS:
    """macOS `say`. Daniel is the British voice; Samantha the American one."""

    name = "say"

    def __init__(self, voice: str = "Daniel", rate: int = 185, popen: Callable[..., Any] | None = None) -> None:
        self.voice = voice
        self.rate = rate
        self.popen = popen

    def speak(self, text: str) -> Playback:
        popen = self.popen or subprocess.Popen
        proc = popen(["say", "-v", self.voice, "-r", str(self.rate), clean_for_speech(text)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return ProcessPlayback(proc)


class ElevenLabsTTS:
    name = "elevenlabs"

    def __init__(self, api_key: str, voice_id: str, model_id: str = "eleven_multilingual_v2",
                 popen: Callable[..., Any] | None = None, fetch: Callable[[str, dict[str, str], bytes], bytes] | None = None) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.popen = popen
        self.fetch = fetch or self._fetch

    @staticmethod
    def _fetch(url: str, headers: dict[str, str], body: bytes) -> bytes:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed API host
                return resp.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"ElevenLabs said {exc.code}") from exc

    def speak(self, text: str) -> Playback:
        import json

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}?output_format=mp3_44100_128"
        body = json.dumps({"text": clean_for_speech(text), "model_id": self.model_id}).encode()
        audio = self.fetch(url, {"xi-api-key": self.api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"}, body)
        path = Path(tempfile.gettempdir()) / f"poyi-{threading.get_ident()}-{abs(hash(text)) % 10**8}.mp3"
        path.write_bytes(audio)
        proc = (self.popen or subprocess.Popen)(["afplay", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return ProcessPlayback(proc)


class Speaker:
    """Speaks sentences in order on a background thread. `interrupt()` is barge-in."""

    def __init__(self, tts: TTS) -> None:
        self.tts = tts
        self.queue: queue.Queue[str | None] = queue.Queue()
        self.current: Playback | None = None
        self.spoken: list[str] = []
        self._lock = threading.Lock()
        self._interrupted = False
        self._thread: threading.Thread | None = None

    def _worker(self) -> None:
        while True:
            item = self.queue.get()
            if item is None:
                return
            if self._interrupted:
                continue
            with self._lock:
                self.current = self.tts.speak(item)
            self.spoken.append(item)
            self.current.wait()
            with self._lock:
                self.current = None

    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._interrupted = False
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

    def enqueue(self, sentence: str) -> None:
        self.start()
        self.queue.put(sentence)

    def finish(self) -> None:
        """Wait for everything queued to be spoken, then stop the thread."""
        if self._thread is None:
            return
        self.queue.put(None)
        self._thread.join()
        self._thread = None

    def interrupt(self) -> None:
        self._interrupted = True
        with self._lock:
            if self.current is not None:
                self.current.stop()
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        self.finish()

    @property
    def speaking(self) -> bool:
        return self.current is not None or not self.queue.empty()

    def speak_stream(self, deltas: Iterable[str], on_text: Callable[[str], None] | None = None) -> str:
        """Consume text as it streams, speaking each sentence as soon as it's complete."""
        buffer = ""
        full: list[str] = []
        for delta in deltas:
            if self._interrupted:
                break
            full.append(delta)
            if on_text:
                on_text(delta)
            buffer += delta
            complete, buffer = split_sentences(buffer)
            for sentence in complete:
                self.enqueue(sentence)
        tail = buffer.strip()
        if tail and not self._interrupted:
            self.enqueue(tail)
        self.finish()
        return "".join(full)
