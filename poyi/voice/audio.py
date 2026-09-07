"""Microphone capture and a small energy-based voice activity detector.

No numpy in the interface: audio is 16 kHz mono int16 bytes. sounddevice is
imported lazily so everything else works without it.
"""

from __future__ import annotations

import math
import time
import wave
from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = RATE * FRAME_MS // 1000


def write_wav(path: Path, pcm: bytes, rate: int = RATE) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return path


def rms(frame: bytes) -> float:
    samples = array("h")
    samples.frombytes(frame[: len(frame) - len(frame) % 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


@dataclass
class EnergyVAD:
    """Speech starts after `start_frames` loud frames; ends after `silence_ms` of quiet."""

    threshold: float = 500.0     # RMS on int16; a quiet room is ~50-200, speech ~1000+
    start_frames: int = 3
    silence_ms: int = 700
    max_seconds: float = 30.0
    _loud: int = field(default=0, repr=False)
    _quiet_ms: int = field(default=0, repr=False)
    _speaking: bool = field(default=False, repr=False)

    def reset(self) -> None:
        self._loud = self._quiet_ms = 0
        self._speaking = False

    @property
    def speaking(self) -> bool:
        return self._speaking

    def feed(self, frame: bytes) -> str:
        """Returns "start" when speech begins, "end" when it ends, else ""."""
        loud = rms(frame) >= self.threshold
        if not self._speaking:
            self._loud = self._loud + 1 if loud else 0
            if self._loud >= self.start_frames:
                self._speaking = True
                self._quiet_ms = 0
                return "start"
            return ""
        if loud:
            self._quiet_ms = 0
        else:
            self._quiet_ms += FRAME_MS
            if self._quiet_ms >= self.silence_ms:
                self.reset()
                return "end"
        return ""


class Recorder:
    """Yields 30 ms int16 frames from the default microphone."""

    def __init__(self, rate: int = RATE, device: Any | None = None) -> None:
        self.rate = rate
        self.device = device

    def frames(self) -> Iterator[bytes]:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("sounddevice is not installed: pip install 'poyi[voice]'") from exc
        with sd.RawInputStream(samplerate=self.rate, channels=1, dtype="int16", blocksize=FRAME_SAMPLES,
                               device=self.device) as stream:
            while True:
                data, _overflowed = stream.read(FRAME_SAMPLES)
                yield bytes(data)


def record_until_silence(frames: Iterator[bytes], vad: EnergyVAD, *, wait_for_start: bool = True,
                         max_seconds: float | None = None, clock: Callable[[], float] = time.monotonic) -> bytes:
    """Collect one utterance. Returns b"" if nothing was said before max_seconds."""
    vad.reset()
    limit = max_seconds or vad.max_seconds
    started_at = clock()
    pre: list[bytes] = []
    out: list[bytes] = []
    speaking = not wait_for_start
    if speaking:
        vad._speaking = True  # noqa: SLF001 - caller says speech already began
    for frame in frames:
        if clock() - started_at > limit:
            break
        state = vad.feed(frame)
        if not speaking:
            pre.append(frame)
            del pre[:-10]  # keep ~300 ms before the onset
            if state == "start":
                speaking = True
                out.extend(pre)
        else:
            out.append(frame)
            if state == "end":
                break
    return b"".join(out) if speaking else b""


def record_while(frames: Iterator[bytes], keep_going: Callable[[], bool], max_seconds: float = 60.0,
                 clock: Callable[[], float] = time.monotonic) -> bytes:
    """Push-to-talk: record while `keep_going()` is true."""
    started_at = clock()
    out: list[bytes] = []
    for frame in frames:
        if not keep_going() or clock() - started_at > max_seconds:
            break
        out.append(frame)
    return b"".join(out)
