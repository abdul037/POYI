"""Speech to text. Local by default; only text leaves the machine."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Protocol


class STT(Protocol):
    name: str

    def transcribe(self, wav_path: Path) -> str: ...


class FasterWhisperSTT:
    """faster-whisper on the CPU. First use downloads the model (~75 MB for base.en)."""

    name = "faster-whisper"

    def __init__(self, model_size: str = "base.en", language: str = "en") -> None:
        self.model_size = model_size
        self.language = language
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError("faster-whisper is not installed: pip install 'poyi[voice]'") from exc
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return self._model

    def transcribe(self, wav_path: Path) -> str:
        model = self._load()
        segments, _info = model.transcribe(str(wav_path), language=self.language, beam_size=1, vad_filter=True)
        return " ".join(seg.text.strip() for seg in segments).strip()


class CommandSTT:
    """Any command that prints a transcript: the template gets {wav} substituted."""

    name = "command"

    def __init__(self, template: str, runner: Callable[[list[str]], str] | None = None) -> None:
        self.template = template
        self.runner = runner

    def transcribe(self, wav_path: Path) -> str:
        import shlex

        argv = [part.replace("{wav}", str(wav_path)) for part in shlex.split(self.template)]
        if self.runner:
            return self.runner(argv).strip()
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
        return proc.stdout.strip()


class TypedSTT:
    """No microphone: the person types. Useful to test the loop and the voice."""

    name = "typed"

    def __init__(self, ask: Callable[[str], str] = input) -> None:
        self.ask = ask

    def transcribe(self, wav_path: Path) -> str:
        return self.ask("you  > ").strip()


def make_stt(kind: str, *, model: str = "base.en", command: str = "") -> STT | None:
    kind = (kind or "").strip().lower()
    if kind in {"faster-whisper", "whisper"}:
        return FasterWhisperSTT(model_size=model)
    if kind == "command" and command:
        return CommandSTT(command)
    if kind == "typed":
        return TypedSTT()
    return None
