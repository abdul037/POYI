import math
import struct
import wave
from pathlib import Path
from types import SimpleNamespace

from poyi import cli
from poyi.brain.agent import Event
from poyi.brain.character import build_system_prompt
from poyi.config import Settings
from poyi.core import Poyi
from poyi.initiative import Notifier
from poyi.voice import (
    CommandSTT,
    ElevenLabsTTS,
    EnergyVAD,
    SayTTS,
    Speaker,
    TypedSTT,
    clean_for_speech,
    make_stt,
    record_until_silence,
    record_while,
    split_sentences,
    write_wav,
)
from poyi.voice.assemble import make_tts
from poyi.voice.audio import FRAME_SAMPLES, rms
from poyi.voice.loop import VoiceLoop


# --- text ------------------------------------------------------------------------------------

def test_split_sentences():
    assert split_sentences("Hello there. How are") == (["Hello there."], "How are")
    assert split_sentences("Yes. It's fine, really! Next?\nMore") == (["Yes. It's fine, really!", "Next?"], "More")
    assert split_sentences("no end yet") == ([], "no end yet")
    assert split_sentences('He said "stop." Then left. ') == (['He said "stop."', "Then left."], "")


def test_clean_for_speech():
    assert clean_for_speech("**Bold** and `code` with [a link](http://x) # heading") == "Bold and code with a link heading"


# --- speaker -------------------------------------------------------------------------------------

class FakePlayback:
    def __init__(self, log, text):
        self.log, self.text, self.stopped = log, text, False

    def wait(self):
        self.log.append(("done", self.text))

    def stop(self):
        self.stopped = True
        self.log.append(("stopped", self.text))


class FakeTTS:
    name = "fake"

    def __init__(self):
        self.log = []

    def speak(self, text):
        self.log.append(("speak", text))
        return FakePlayback(self.log, text)


def test_speaker_speaks_sentences_in_order_as_they_complete():
    tts = FakeTTS()
    sp = Speaker(tts)
    seen = []
    text = sp.speak_stream(["It's four", " in the afternoon. ", "Sam messaged", " you. Reply?"], on_text=seen.append)
    assert text == "It's four in the afternoon. Sam messaged you. Reply?"
    assert sp.spoken == ["It's four in the afternoon.", "Sam messaged you.", "Reply?"]
    assert [e for e in tts.log if e[0] == "speak"] == [("speak", "It's four in the afternoon."), ("speak", "Sam messaged you."), ("speak", "Reply?")]
    assert "".join(seen) == text


def test_speaker_interrupt_stops_and_drops_the_queue():
    class SlowTTS(FakeTTS):
        def speak(self, text):
            self.log.append(("speak", text))
            pb = FakePlayback(self.log, text)
            pb.wait = lambda: __import__("time").sleep(0.05)
            return pb

    tts = SlowTTS()
    sp = Speaker(tts)
    sp.enqueue("one one one one.")
    sp.enqueue("two two two two.")
    sp.enqueue("three three three.")
    __import__("time").sleep(0.02)
    sp.interrupt()
    spoken = [e[1] for e in tts.log if e[0] == "speak"]
    assert spoken[0] == "one one one one." and len(spoken) <= 2
    assert not sp.speaking


def test_say_tts_builds_argv(tmp_path):
    calls = []

    def popen(argv, **kw):
        calls.append(argv)
        return SimpleNamespace(wait=lambda: None, terminate=lambda: None)

    pb = SayTTS(voice="Daniel", rate=190, popen=popen).speak("**Hello** there.")
    pb.wait()
    pb.stop()
    assert calls == [["say", "-v", "Daniel", "-r", "190", "Hello there."]]


def test_elevenlabs_tts_posts_and_plays(tmp_path):
    seen = {}

    def fetch(url, headers, body):
        seen["url"], seen["headers"], seen["body"] = url, headers, body
        return b"ID3fake"

    played = []
    tts = ElevenLabsTTS("key", "voice123", popen=lambda argv, **kw: played.append(argv) or SimpleNamespace(wait=lambda: None, terminate=lambda: None), fetch=fetch)
    tts.speak("Hi there.").wait()
    assert "voice123" in seen["url"] and seen["headers"]["xi-api-key"] == "key" and b'"text": "Hi there."' in seen["body"]
    assert played[0][0] == "afplay" and Path(played[0][1]).read_bytes() == b"ID3fake"


def test_make_tts_falls_back_to_say():
    assert make_tts(Settings(tts="elevenlabs")).name == "say"
    assert make_tts(Settings(tts="elevenlabs", elevenlabs_key="k", elevenlabs_voice="v")).name == "elevenlabs"
    assert make_tts(Settings()).voice == "Daniel"


# --- audio -------------------------------------------------------------------------------------------

def tone(amplitude, samples=FRAME_SAMPLES):
    return b"".join(struct.pack("<h", int(amplitude * math.sin(i / 3))) for i in range(samples))


def silence(samples=FRAME_SAMPLES):
    return b"\x00\x00" * samples


def test_rms_and_wav_round_trip(tmp_path):
    assert rms(silence()) == 0.0 and rms(tone(10000)) > 5000
    path = write_wav(tmp_path / "a" / "x.wav", tone(1000) * 3)
    with wave.open(str(path)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 16000, FRAME_SAMPLES * 3)


def test_energy_vad_start_and_end():
    vad = EnergyVAD(threshold=500, start_frames=3, silence_ms=90)
    assert [vad.feed(silence()) for _ in range(5)] == [""] * 5
    assert [vad.feed(tone(3000)) for _ in range(3)] == ["", "", "start"]
    assert vad.speaking
    assert vad.feed(tone(3000)) == ""
    assert [vad.feed(silence()) for _ in range(3)] == ["", "", "end"]
    assert not vad.speaking


def test_record_until_silence_includes_preroll_and_stops():
    frames = [silence()] * 5 + [tone(3000)] * 6 + [silence()] * 30
    vad = EnergyVAD(threshold=500, start_frames=3, silence_ms=90)
    pcm = record_until_silence(iter(frames), vad)
    n = len(pcm) // (FRAME_SAMPLES * 2)
    assert 8 <= n <= 14  # pre-roll + speech + the silence tail before "end"
    assert record_until_silence(iter([silence()] * 5), vad) == b""


def test_record_until_silence_respects_max_seconds():
    clock = iter([0.0, 0.0, 0.0, 100.0, 100.0])
    pcm = record_until_silence(iter([tone(3000)] * 50), EnergyVAD(threshold=500, start_frames=1, silence_ms=900),
                               max_seconds=5, clock=lambda: next(clock))
    assert len(pcm) // (FRAME_SAMPLES * 2) <= 3


def test_record_while():
    count = {"n": 0}

    def keep():
        count["n"] += 1
        return count["n"] <= 4

    assert len(record_while(iter([tone(100)] * 10), keep)) == FRAME_SAMPLES * 2 * 4


# --- stt -----------------------------------------------------------------------------------------------

def test_command_and_typed_stt(tmp_path):
    stt = CommandSTT("whisper-cli -f {wav} --no-timestamps", runner=lambda argv: f" heard {argv[2]} \n")
    assert stt.transcribe(tmp_path / "u.wav") == f"heard {tmp_path / 'u.wav'}"
    assert TypedSTT(ask=lambda prompt: "  typed text ").transcribe(Path()) == "typed text"
    assert make_stt("typed").name == "typed"
    assert make_stt("command", command="x {wav}").name == "command"
    assert make_stt("faster-whisper", model="tiny.en").model_size == "tiny.en"
    assert make_stt("") is None and make_stt("command") is None


# --- the loop --------------------------------------------------------------------------------------------

class FakeBeing:
    awake = True

    def __init__(self, replies):
        self.replies = list(replies)
        self.heard = []

    def stream(self, text):
        self.heard.append(text)
        reply = self.replies.pop(0)
        yield Event("tool", "checking the time")
        for word in reply.split(" "):
            yield Event("text", word + " ")
        yield Event("done")


def test_voice_loop_respond_speaks_and_prints():
    out = []
    being = FakeBeing(["It is four in the afternoon. Nothing else."])
    loop = VoiceLoop(being, TypedSTT(), Speaker(FakeTTS()), out=out.append)
    reply = loop.respond("what time is it")
    assert reply.strip() == "It is four in the afternoon. Nothing else."
    assert loop.speaker.spoken == ["It is four in the afternoon.", "Nothing else."]
    assert out[0] == "you  > what time is it" and "(checking the time...)" in out[1]


def test_voice_loop_push_to_talk_typed_until_eof():
    lines = iter(["hello there"])

    def ask(prompt):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError

    out = []
    being = FakeBeing(["Hi."])
    loop = VoiceLoop(being, TypedSTT(ask=ask), Speaker(FakeTTS()), out=out.append, ask=ask)
    assert loop.run_push_to_talk() == 0
    assert being.heard == ["hello there"] and loop.speaker.spoken == ["Hi."]


def test_voice_loop_transcribe_writes_and_removes_wav(tmp_path):
    seen = {}

    class Stt:
        name = "x"

        def transcribe(self, path):
            seen["exists"] = path.exists()
            return "ok"

    loop = VoiceLoop(FakeBeing([]), Stt(), Speaker(FakeTTS()), wav_dir=tmp_path)
    assert loop.transcribe(tone(100)) == "ok" and seen["exists"] and not (tmp_path / "poyi-utterance.wav").exists()
    assert loop.transcribe(b"") == ""


# --- wiring -------------------------------------------------------------------------------------------------

def test_notifier_speaks_only_when_allowed():
    sp = Speaker(FakeTTS())
    n = Notifier(desktop=False, speaker=sp)
    assert n.send("Call in five", "with Sam", voice=False) is False and sp.spoken == []
    assert n.send("Call in five", "with Sam", voice=True) is True
    assert sp.spoken == ["Call in five. with Sam"] and n.spoken == ["Call in five. with Sam"]


def test_prompt_voice_section_and_settings():
    assert "Out loud" not in build_system_prompt(Settings())
    assert "Out loud" in build_system_prompt(Settings(), voice=True)
    s = Settings.from_env({"POYI_VOICE": "true", "POYI_TTS_VOICE": "Samantha", "POYI_STT": "typed", "ELEVENLABS_API_KEY": "k", "POYI_VAD_THRESHOLD": "800"})
    assert s.voice and s.tts_voice == "Samantha" and s.stt == "typed" and s.elevenlabs_key == "k" and s.vad_threshold == 800.0


def test_default_with_voice_builds_a_speaker(tmp_path, monkeypatch):
    monkeypatch.setattr("poyi.core.has_credentials", lambda: False)
    being = Poyi.default(Settings(home=tmp_path, voice=True))
    assert being.speaker is not None and being.initiative.notifier.speaker is being.speaker
    assert Poyi.default(Settings(home=tmp_path)).speaker is None


def test_voice_cli_say_and_missing_brain(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr("poyi.voice.tts.subprocess.Popen", lambda argv, **kw: calls.append(argv) or SimpleNamespace(wait=lambda: None, terminate=lambda: None))
    monkeypatch.setenv("POYI_HOME", str(tmp_path))
    monkeypatch.setattr("poyi.core.has_credentials", lambda: False)
    assert cli.main(["voice", "--say", "Good evening."]) == 0
    assert calls[-1][:2] == ["say", "-v"] and calls[-1][-1] == "Good evening."
    assert cli.main(["voice", "--typed"]) == 1
    assert "no mind" in capsys.readouterr().out
