from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


_CONTAINER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class ConfigurationError(ValueError):
    """Raised when the monitor cannot start safely."""


@dataclass(frozen=True)
class MonitorConfig:
    username: str
    password: str
    container_name: str = "omega"
    host: str = "127.0.0.1"
    port: int = 8765
    reconnect_seconds: float = 2.0
    browser_log_limit: int = 1_000
    security_events_file: Path | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "MonitorConfig":
        values = os.environ if environ is None else environ
        username = values.get("OMA_MONITOR_USERNAME", "").strip()
        password = values.get("OMA_MONITOR_PASSWORD", "")
        container_name = values.get("OMA_MONITOR_CONTAINER", "omega").strip()
        host = values.get("OMA_MONITOR_HOST", "127.0.0.1").strip()

        if not username or not password:
            raise ConfigurationError(
                "OMA_MONITOR_USERNAME and OMA_MONITOR_PASSWORD are required"
            )
        if any(ord(character) < 32 for character in username + password):
            raise ConfigurationError("monitor credentials cannot contain control characters")
        if len(password) < 12:
            raise ConfigurationError("OMA_MONITOR_PASSWORD must be at least 12 characters")
        if not _CONTAINER_NAME.fullmatch(container_name):
            raise ConfigurationError("OMA_MONITOR_CONTAINER is not a valid Docker container name")
        if not host:
            raise ConfigurationError("OMA_MONITOR_HOST cannot be empty")

        try:
            port = int(values.get("OMA_MONITOR_PORT", "8765"))
        except ValueError as exc:
            raise ConfigurationError("OMA_MONITOR_PORT must be an integer") from exc
        if not 1 <= port <= 65535:
            raise ConfigurationError("OMA_MONITOR_PORT must be between 1 and 65535")

        return cls(
            username=username,
            password=password,
            container_name=container_name,
            host=host,
            port=port,
            security_events_file=(
                Path(values["OMA_MONITOR_SECURITY_EVENTS_FILE"]).expanduser()
                if values.get("OMA_MONITOR_SECURITY_EVENTS_FILE", "").strip()
                else None
            ),
        )
