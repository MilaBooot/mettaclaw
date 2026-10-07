from __future__ import annotations

import json
import time
from collections.abc import Callable, Generator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .redaction import redact


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class SecurityEventReader:
    """Read bounded Falco JSON-lines output for one configured container."""

    def __init__(
        self,
        path: Path | None,
        container_name: str,
        poll_seconds: float = 1.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.path = path
        self.container_name = container_name
        self.poll_seconds = poll_seconds
        self._sleep = sleeper

    def status(self) -> dict[str, str | bool]:
        if self.path is None:
            return {"state": "not-configured", "configured": False}
        try:
            is_file = self.path.is_file()
            if is_file:
                with self.path.open("rb"):
                    pass
        except FileNotFoundError:
            return {"state": "waiting-for-events-file", "configured": True}
        except OSError:
            return {"state": "events-file-unreadable", "configured": True}
        if not is_file:
            return {"state": "waiting-for-events-file", "configured": True}
        return {"state": "available", "configured": True}

    def events(self) -> Generator[dict[str, str], None, None]:
        if self.path is None:
            yield self._system("Runtime detection is not configured.")
            return

        position = 0
        identity: tuple[int, int] | None = None
        waiting_notified = False
        inaccessible_notified = False
        while True:
            try:
                stat = self.path.stat()
                current_identity = (stat.st_dev, stat.st_ino)
                rotated = identity is not None and current_identity != identity
                truncated = current_identity == identity and stat.st_size < position
                if identity is None or rotated or truncated:
                    lines, position = self._tail_lines(self.path, count=100)
                    identity = current_identity
                    if rotated or truncated:
                        yield self._system("Security event file rotated; following the replacement.")
                elif stat.st_size > position:
                    with self.path.open("rb") as stream:
                        stream.seek(position)
                        data = stream.read(min(stat.st_size - position, 1_048_576))
                    end = data.rfind(b"\n") + 1
                    lines = data[:end].splitlines()
                    # Keep an unfinished JSON line until its terminating newline.
                    # Oversized unterminated records are discarded in bounded chunks.
                    position += end or (len(data) if len(data) == 1_048_576 else 0)
                else:
                    lines = []
                waiting_notified = inaccessible_notified = False
                for raw_line in lines:
                    event = self._parse_event(raw_line)
                    if event is not None:
                        yield event
            except FileNotFoundError:
                if not waiting_notified:
                    yield self._system("Waiting for the configured Falco events file.")
                    waiting_notified = True
                identity = None
                position = 0
                self._sleep(self.poll_seconds)
                continue
            except OSError:
                if not inaccessible_notified:
                    yield self._system("Configured security event file is unreadable.")
                    inaccessible_notified = True
                self._sleep(self.poll_seconds)
                continue

            self._sleep(self.poll_seconds)

    def _parse_event(self, raw_line: bytes) -> dict[str, str] | None:
        try:
            payload: Any = json.loads(raw_line.decode("utf-8", errors="replace"))
            fields = payload.get("output_fields") or {}
            event_container = str(
                fields.get("container.name") or fields.get("container_name") or ""
            )
            if event_container != self.container_name:
                return None
            return {
                "type": "security",
                "timestamp": str(payload.get("time") or _utc_now())[:64],
                "priority": str(payload.get("priority") or "Unknown")[:32],
                "rule": str(payload.get("rule") or "Unnamed rule")[:256],
                "text": redact(str(payload.get("output") or ""))[:16_384],
            }
        except (AttributeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _tail_lines(path: Path, count: int, byte_limit: int = 1_048_576) -> tuple[list[bytes], int]:
        with path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            start = max(0, size - byte_limit)
            stream.seek(start)
            data = stream.read(byte_limit)
        end = data.rfind(b"\n") + 1
        lines = data[:end].splitlines()
        if size > byte_limit and lines:
            lines = lines[1:]
        position = start + (end or (len(data) if len(data) == byte_limit else 0))
        return lines[-count:], position

    @staticmethod
    def _system(message: str) -> dict[str, str]:
        return {"type": "system", "timestamp": _utc_now(), "text": message}
