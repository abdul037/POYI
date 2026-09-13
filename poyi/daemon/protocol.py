"""JSON lines over a Unix socket. One request per connection.

    -> {"type": "say", "text": "..."}          streams {"type": "text"|"tool"|"refusal", "data": ...}
                                                 and, for confirm-tier hands, {"type": "confirm", "description": ...}
                                                 which the front answers with {"type": "answer", "yes": true|false};
                                                 ends with {"type": "done"}
    -> {"type": "picture"}                       {"type": "picture", "text": "..."}
    -> {"type": "status"}                        {"type": "status", ...}
    -> {"type": "mode", "mode": "focus", "minutes": 90}   {"type": "ok", "text": "..."}
    -> {"type": "tick"}                          {"type": "ok", "events": [...]}
    -> {"type": "stop"}                          {"type": "ok"}
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any, Iterator


def send(sock: socket.socket, message: dict[str, Any]) -> None:
    sock.sendall((json.dumps(message) + "\n").encode())


def lines(sock: socket.socket) -> Iterator[dict[str, Any]]:
    buffer = b""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            break
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            if line.strip():
                try:
                    yield json.loads(line)
                except ValueError:
                    yield {"type": "error", "text": "bad json"}


MAX_UNIX_PATH = 100  # macOS refuses AF_UNIX paths much longer than this


def socket_path(home: Path) -> Path:
    """~/.poyi/poyi.sock, or a short /tmp path when the home path is too long for a socket."""
    path = Path(home) / "poyi.sock"
    if len(str(path)) <= MAX_UNIX_PATH:
        return path
    import hashlib
    import os

    tag = hashlib.sha1(str(Path(home).resolve()).encode()).hexdigest()[:8]
    return Path(f"/tmp/poyi-{os.getuid()}-{tag}.sock")


def alive(path: Path) -> bool:
    if not path.exists():
        return False
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(1.0)
        s.connect(str(path))
        send(s, {"type": "status"})
        return True
    except OSError:
        return False
    finally:
        s.close()
