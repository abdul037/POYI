"""Settings for Poyi. Everything comes from the environment or ~/.poyi/env.

Nothing here reads a secret; the Anthropic SDK reads its own credentials.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _truthy(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def load_env_file(path: Path, environ: dict[str, str]) -> None:
    """Read KEY=VALUE lines into `environ` without overriding existing keys."""
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in environ:
            environ[key] = value


@dataclass
class Settings:
    model: str = "claude-opus-5"
    fast_model: str = "claude-haiku-4-5"
    judge_model: str = "claude-sonnet-5"
    effort: str = "medium"
    max_tokens: int = 16000
    max_tool_rounds: int = 8
    user_name: str = ""
    address: str = ""
    web: bool = True
    compaction: bool = True
    fallbacks: bool = True
    home: Path = field(default_factory=lambda: Path.home() / ".poyi")
    home_ssid: str = ""
    quiet_hours: str = "23:00-07:00"
    focus_after_min: int = 25
    world_refresh_s: int = 60
    notify: bool = True
    brief_morning: str = "08:00"
    brief_evening: str = "21:30"
    tick_s: int = 30
    unlock: list[str] = field(default_factory=list)       # locked hands enabled by name
    shell_allow: list[str] = field(default_factory=list)  # allowed command prefixes for run_shell
    calendar_name: str = ""                                # Apple Calendar to write to; first calendar if empty
    ha_url: str = ""                                       # Home Assistant, e.g. http://homeassistant.local:8123
    ha_token: str = ""                                     # long-lived access token; never enters a prompt
    ha_watch: list[str] = field(default_factory=list)      # entities for the picture and the door watcher
    voice: bool = False                                    # speak initiative aloud (when relaxed) and enable `poyi voice`
    tts: str = "say"                                       # say | elevenlabs
    tts_voice: str = "Daniel"                              # a macOS voice name for `say`
    tts_rate: int = 185
    elevenlabs_key: str = ""
    elevenlabs_voice: str = ""                             # an ElevenLabs voice id
    stt: str = "faster-whisper"                            # faster-whisper | command | typed
    stt_model: str = "base.en"
    stt_command: str = ""                                  # for stt=command: a template with {wav}
    vad_threshold: float = 500.0

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ) if environ is None else dict(environ)
        home = Path(env.get("POYI_HOME") or Path.home() / ".poyi")
        load_env_file(home / "env", env)
        load_env_file(Path.cwd() / ".env", env)
        # Push loaded values into the real environment so the SDK sees them.
        if environ is None:
            for key, value in env.items():
                os.environ.setdefault(key, value)
        return cls(
            model=env.get("POYI_MODEL") or cls.model,
            fast_model=env.get("POYI_FAST_MODEL") or cls.fast_model,
            judge_model=env.get("POYI_JUDGE_MODEL") or cls.judge_model,
            effort=env.get("POYI_EFFORT") or cls.effort,
            max_tokens=int(env.get("POYI_MAX_TOKENS") or cls.max_tokens),
            max_tool_rounds=int(env.get("POYI_MAX_TOOL_ROUNDS") or cls.max_tool_rounds),
            user_name=env.get("POYI_USER", ""),
            address=env.get("POYI_ADDRESS", ""),
            web=_truthy(env.get("POYI_WEB"), True),
            compaction=_truthy(env.get("POYI_COMPACTION"), True),
            fallbacks=_truthy(env.get("POYI_FALLBACKS"), True),
            home=home,
            home_ssid=env.get("POYI_HOME_SSID", ""),
            quiet_hours=env.get("POYI_QUIET_HOURS") or cls.quiet_hours,
            focus_after_min=int(env.get("POYI_FOCUS_AFTER_MIN") or cls.focus_after_min),
            world_refresh_s=int(env.get("POYI_WORLD_REFRESH_S") or cls.world_refresh_s),
            notify=_truthy(env.get("POYI_NOTIFY"), True),
            brief_morning=env.get("POYI_BRIEF_MORNING") or cls.brief_morning,
            brief_evening=env.get("POYI_BRIEF_EVENING") or cls.brief_evening,
            tick_s=int(env.get("POYI_TICK_S") or cls.tick_s),
            unlock=_csv(env.get("POYI_UNLOCK")),
            shell_allow=_csv(env.get("POYI_SHELL_ALLOW")),
            calendar_name=env.get("POYI_CALENDAR", ""),
            ha_url=env.get("POYI_HA_URL", ""),
            ha_token=env.get("POYI_HA_TOKEN", ""),
            ha_watch=_csv(env.get("POYI_HA_WATCH")),
            voice=_truthy(env.get("POYI_VOICE"), False),
            tts=env.get("POYI_TTS") or cls.tts,
            tts_voice=env.get("POYI_TTS_VOICE") or cls.tts_voice,
            tts_rate=int(env.get("POYI_TTS_RATE") or cls.tts_rate),
            elevenlabs_key=env.get("ELEVENLABS_API_KEY", ""),
            elevenlabs_voice=env.get("POYI_ELEVENLABS_VOICE", ""),
            stt=env.get("POYI_STT") or cls.stt,
            stt_model=env.get("POYI_STT_MODEL") or cls.stt_model,
            stt_command=env.get("POYI_STT_COMMAND", ""),
            vad_threshold=float(env.get("POYI_VAD_THRESHOLD") or cls.vad_threshold),
        )

    def ensure_home(self) -> Path:
        self.home.mkdir(parents=True, exist_ok=True)
        return self.home


def has_credentials(environ: dict[str, str] | None = None) -> bool:
    """Best-effort check that the Anthropic SDK will find a credential.

    Mirrors the SDK's order: API key, auth token, then an `ant auth login`
    profile on disk. `poyi doctor` does the real check with a live call.
    """
    env = os.environ if environ is None else environ
    if env.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    profile_dir = Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "anthropic"
    return profile_dir.is_dir() and any(profile_dir.iterdir())
