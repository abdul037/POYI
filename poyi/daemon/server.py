"""The daemon: one Poyi, always on.

It runs the initiative tick, the nightly memory pass, and a socket server
that the fronts (terminal, menubar, phone) talk to. Conversations are
serialised: the brain holds one history, and one front speaks at a time.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from poyi.config import Settings
from poyi.daemon.protocol import lines, send, socket_path
from poyi.hands.registry import Confirmer, DenyAll
from poyi.identity import NAME
from poyi.memory.consolidate import consolidate

log = logging.getLogger(__name__)


class SocketConfirmer:
    """Asks the connected front and waits for its answer."""

    def __init__(self, sock: socket.socket, incoming: Any) -> None:
        self.sock = sock
        self.incoming = incoming  # iterator of parsed lines from the front

    def ask(self, description: str) -> bool:
        send(self.sock, {"type": "confirm", "description": description})
        for message in self.incoming:
            if message.get("type") == "answer":
                return bool(message.get("yes"))
        return False


class Daemon:
    def __init__(self, being: Any, settings: Settings, *, path: Path | None = None, clock: Callable[[], datetime] = datetime.now) -> None:
        self.being = being
        self.settings = settings
        self.path = path or socket_path(settings.home)
        self.clock = clock
        self.started = clock()
        self.lock = threading.Lock()   # one conversation at a time
        self.stop_event = threading.Event()
        self.last_consolidated: str = ""
        self.threads: list[threading.Thread] = []
        self._server: socket.socket | None = None

    # --- background work ------------------------------------------------------------------

    def tick_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                if self.being.initiative is not None:
                    with self.lock:
                        self.being.initiative.tick(self.clock())
            except Exception as exc:  # noqa: BLE001 - the loop must survive anything
                log.warning("tick failed: %s", exc)
            self.maybe_consolidate()
            self.stop_event.wait(self.settings.tick_s)

    def consolidation_due(self, now: datetime) -> bool:
        try:
            hour, minute = (int(x) for x in self.settings.consolidate_at.split(":"))
        except ValueError:
            return False
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return due <= now < due + timedelta(minutes=30) and self.last_consolidated != now.date().isoformat()

    def maybe_consolidate(self) -> None:
        now = self.clock()
        if not self.consolidation_due(now) or self.being.memory is None or not self.being.awake:
            return
        self.last_consolidated = now.date().isoformat()
        try:
            with self.lock:
                consolidate(self.being.memory, self.settings, client=self.being.brain.client)
            log.info("nightly pass done")
        except Exception as exc:  # noqa: BLE001
            log.warning("nightly pass failed: %s", exc)

    # --- the socket ---------------------------------------------------------------------------

    def serve(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.path))
        os.chmod(self.path, 0o600)
        server.listen(8)
        server.settimeout(0.5)
        self._server = server
        while not self.stop_event.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self.handle, args=(conn,), daemon=True).start()
        server.close()
        if self.path.exists():
            self.path.unlink()

    def handle(self, conn: socket.socket) -> None:
        incoming = lines(conn)
        try:
            request = next(incoming, None)
            if request is None:
                return
            kind = request.get("type")
            if kind == "say":
                self.handle_say(conn, incoming, str(request.get("text", "")))
            elif kind == "picture":
                text = self.being.brain.turn_context() if self.being.brain and self.being.brain.turn_context else (self.being.world.render() if self.being.world else "")
                send(conn, {"type": "picture", "text": text})
            elif kind == "status":
                send(conn, {"type": "status", **self.status()})
            elif kind == "mode":
                send(conn, {"type": "ok", "text": self.set_mode(str(request.get("mode", "")), int(request.get("minutes", 120)))})
            elif kind == "tick":
                with self.lock:
                    events = self.being.initiative.tick(self.clock()) if self.being.initiative else []
                send(conn, {"type": "ok", "events": [e.to_dict() for e in events]})
            elif kind == "stop":
                send(conn, {"type": "ok"})
                self.stop_event.set()
            else:
                send(conn, {"type": "error", "text": f"unknown request {kind!r}"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001
            try:
                send(conn, {"type": "error", "text": f"{type(exc).__name__}: {exc}"})
            except OSError:
                pass
        finally:
            conn.close()

    def handle_say(self, conn: socket.socket, incoming: Any, text: str) -> None:
        with self.lock:
            registry = self.being.hands.registry if self.being.hands else None
            previous: Confirmer | None = registry.confirmer if registry else None
            if registry:
                registry.confirmer = SocketConfirmer(conn, incoming)
            try:
                for event in self.being.stream(text):
                    if event.kind == "done":
                        break
                    send(conn, {"type": event.kind, "data": event.data})
            finally:
                if registry:
                    registry.confirmer = previous or DenyAll()
        send(conn, {"type": "done"})

    def set_mode(self, mode: str, minutes: int) -> str:
        from poyi.world.mode import Override
        from poyi.world.model import MODES

        if self.being.world is None:
            return "no world"
        store = self.being.world.store
        if mode == "off":
            store.set_override(None)
            self.being.world.refresh(self.clock(), force=True)
            return "inferring again"
        if mode not in MODES:
            return f"mode must be one of {', '.join(MODES)} or off"
        until = self.clock() + timedelta(minutes=minutes)
        store.set_override(Override(mode=mode, until=until))
        self.being.world.refresh(self.clock(), force=True)
        return f"{mode} until {until:%H:%M}"

    def status(self) -> dict[str, Any]:
        world = self.being.world.world if self.being.world else None
        return {
            "name": NAME,
            "awake": bool(self.being.awake),
            "since": self.started.isoformat(timespec="seconds"),
            "mode": world.now.mode if world else "",
            "activity": world.now.activity if world else "",
            "place": world.now.place if world else "",
            "pending": len(self.being.initiative.log.pending_mentions()) if self.being.initiative else 0,
            "turns": len(self.being.history) // 2,
            "pid": os.getpid(),
        }

    # --- lifecycle -----------------------------------------------------------------------------------

    def start(self, *, threads: bool = True) -> None:
        self.stop_event.clear()
        if threads:
            for target in (self.tick_loop, self.serve):
                t = threading.Thread(target=target, daemon=True)
                t.start()
                self.threads.append(t)

    def stop(self) -> None:
        self.stop_event.set()
        for t in self.threads:
            t.join(timeout=3)
        self.threads.clear()

    def run_forever(self, extra: list[Callable[[], None]] | None = None) -> int:
        """Blocks until stopped by a signal or a `stop` request."""
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: self.stop_event.set())
        self.start()
        for fn in extra or []:
            t = threading.Thread(target=fn, daemon=True)
            t.start()
            self.threads.append(t)
        log.info("%s daemon up at %s", NAME, self.path)
        while not self.stop_event.is_set():
            time.sleep(0.5)
        self.stop()
        return 0
