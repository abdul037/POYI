"""Home Assistant over its REST API. Reads are free; calling a service asks first.

The token comes from settings (the environment), never from the model.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from anthropic import beta_tool

from poyi.hands.registry import Hand, Registry
from poyi.initiative.events import Event
from poyi.world.model import World

Fetch = Callable[[str, str, dict[str, Any] | None], Any]  # (method, path, body) -> parsed JSON


class HomeAssistant:
    def __init__(self, url: str, token: str, fetch: Fetch | None = None, timeout: float = 5.0) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.fetch = fetch or self._fetch

    def _fetch(self, method: str, path: str, body: dict[str, Any] | None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 - user-configured URL
                text = resp.read().decode()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Home Assistant said {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"couldn't reach Home Assistant: {exc}") from exc
        return json.loads(text) if text else None

    def state(self, entity_id: str) -> dict[str, Any]:
        return self.fetch("GET", f"/api/states/{entity_id}", None)

    def states(self) -> list[dict[str, Any]]:
        return self.fetch("GET", "/api/states", None) or []

    def call(self, domain: str, service: str, entity_id: str, data: dict[str, Any] | None = None) -> Any:
        return self.fetch("POST", f"/api/services/{domain}/{service}", {"entity_id": entity_id, **(data or {})})


def _friendly(state: dict[str, Any]) -> str:
    name = (state.get("attributes") or {}).get("friendly_name") or state.get("entity_id", "?")
    return f"{name}: {state.get('state', '?')}"


def register(registry: Registry, ha: HomeAssistant) -> None:
    def home_state(entity_id: str) -> str:
        return _friendly(ha.state(entity_id))

    def home_list(domain: str = "") -> str:
        items = [s for s in ha.states() if not domain or str(s.get("entity_id", "")).startswith(domain + ".")]
        if not items:
            return "Nothing found."
        return "\n".join(f"{s.get('entity_id')}  {_friendly(s)}" for s in items[:60])

    def home_call(domain: str, service: str, entity_id: str, data_json: str = "") -> str:
        data = json.loads(data_json) if data_json.strip() else {}
        ha.call(domain, service, entity_id, data)
        return f"Called {domain}.{service} on {entity_id}."

    s = registry.add(Hand("home_state", "free", lambda entity_id: f"check {entity_id}", home_state))
    l = registry.add(Hand("home_list", "free", lambda domain="": f"list home devices{' in ' + domain if domain else ''}", home_list))
    c = registry.add(Hand("home_call", "confirm",
                          lambda domain, service, entity_id, data_json="": f"{domain}.{service} on {entity_id}" + (f" with {data_json}" if data_json else ""),
                          home_call))

    @beta_tool
    def home_state(entity_id: str) -> str:  # noqa: F811
        """The current state of one Home Assistant entity.

        Args:
            entity_id: e.g. "light.office" or "binary_sensor.front_door".
        """
        return registry.call("home_state", entity_id=entity_id)

    @beta_tool
    def home_list(domain: str = "") -> str:  # noqa: F811
        """List Home Assistant entities and their states, optionally in one domain.

        Args:
            domain: e.g. "light", "switch", "climate"; empty for everything.
        """
        return registry.call("home_list", domain=domain)

    @beta_tool
    def home_call(domain: str, service: str, entity_id: str, data_json: str = "") -> str:  # noqa: F811
        """Change something in the home: lights, switches, scenes, climate. Asks them first.

        Args:
            domain: e.g. "light".
            service: e.g. "turn_on", "turn_off", "toggle".
            entity_id: e.g. "light.office".
            data_json: optional JSON with extra fields, e.g. {"brightness_pct": 30}.
        """
        return registry.call("home_call", domain=domain, service=service, entity_id=entity_id, data_json=data_json)

    s.tool, l.tool, c.tool = home_state, home_list, home_call


@dataclass
class HomeSensor:
    """A few watched entities ride the picture's home section."""

    ha: HomeAssistant
    entities: list[str]
    name: str = "home"

    def read(self, world: World, now: datetime) -> dict[str, Any]:
        out: dict[str, str] = {}
        for entity_id in self.entities:
            try:
                state = self.ha.state(entity_id)
            except Exception:  # noqa: BLE001 - one unreachable entity shouldn't break the picture
                continue
            name = (state.get("attributes") or {}).get("friendly_name") or entity_id
            out[str(name).lower()] = str(state.get("state", "?"))
        return {"home": out} if out else {}


@dataclass
class HomeWatcher:
    """Doors and presence changing state become events."""

    ha: HomeAssistant
    entities: list[str]
    name: str = "home"
    _last: dict[str, str] = field(default_factory=dict)

    def check(self, world: World, now: datetime) -> list[Event]:
        out = []
        for entity_id in self.entities:
            if not entity_id.startswith(("binary_sensor.", "person.", "device_tracker.", "lock.")):
                continue
            try:
                state = self.ha.state(entity_id)
            except Exception:  # noqa: BLE001
                continue
            value = str(state.get("state", "?"))
            previous = self._last.get(entity_id)
            self._last[entity_id] = value
            if previous is not None and previous != value:
                name = (state.get("attributes") or {}).get("friendly_name") or entity_id
                out.append(Event(source="home", title=f"{name} is now {value}", importance=0.6,
                                 key=f"home:{entity_id}:{value}:{now.isoformat(timespec='minutes')}"))
        return out
