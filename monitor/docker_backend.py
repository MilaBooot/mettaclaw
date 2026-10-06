from __future__ import annotations

import time
import threading
from collections.abc import Callable, Generator, Iterable
from datetime import datetime, timezone
from typing import Any

import docker
from docker.errors import DockerException, NotFound

from .redaction import redact


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _bounded_lines(chunks: Iterable[bytes], limit: int = 16_384) -> Generator[str, None, None]:
    """Turn Docker chunks into lines without retaining an unbounded partial line."""
    pending = ""
    for chunk in chunks:
        pending += chunk.decode("utf-8", errors="replace")
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            if line.endswith("\r"):
                line = line[:-1]
            while len(line) > limit:
                yield line[:limit] + " [line truncated]"
                line = line[limit:]
            yield line
        while len(pending) > limit:
            yield pending[:limit] + " [line truncated]"
            pending = pending[limit:]
    if pending:
        yield pending


class DockerBackend:
    """The only component allowed to communicate with the Docker API."""

    def __init__(
        self,
        container_name: str,
        reconnect_seconds: float = 2.0,
        client_factory: Callable[[], Any] = docker.from_env,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.container_name = container_name
        self.reconnect_seconds = reconnect_seconds
        self._client_factory = client_factory
        self._sleep = sleeper
        self._action_lock = threading.Lock()

    def status(self) -> dict[str, str | bool | None]:
        client = None
        try:
            client = self._client_factory()
            client.ping()
            container = client.containers.get(self.container_name)
            container.reload()
            state = container.attrs.get("State", {})
            docker_status = str(state.get("Status") or container.status or "").lower()
            if docker_status == "restarting" or state.get("Restarting") is True:
                display_state = "restarting"
            elif docker_status == "running":
                display_state = "running"
            else:
                display_state = "stopped"
            return {
                "state": display_state,
                "container": self.container_name,
                "container_id": container.id[:12],
                "docker_status": docker_status or None,
                "agent_healthy": None,
                "checked_at": _utc_now(),
            }
        except NotFound:
            return self._failure_status("missing")
        except DockerException:
            return self._failure_status("docker-unavailable")
        finally:
            self._close_client(client)

    def _failure_status(self, state: str) -> dict[str, str | bool | None]:
        return {
            "state": state,
            "container": self.container_name,
            "container_id": None,
            "docker_status": None,
            "agent_healthy": None,
            "checked_at": _utc_now(),
        }

    def perform_action(self, action: str, timeout: int = 10) -> dict[str, str | bool | None]:
        """Run one explicitly allowed lifecycle action on the configured target."""
        if action not in {"start", "stop", "restart"}:
            raise DockerActionError("unsupported-action", 400)
        if not self._action_lock.acquire(blocking=False):
            raise DockerActionError("action-in-progress", 409)

        client = None
        try:
            client = self._client_factory()
            client.ping()
            container = client.containers.get(self.container_name)
            if action == "start":
                container.start()
            elif action == "stop":
                container.stop(timeout=timeout)
            else:
                container.restart(timeout=timeout)
        except NotFound as exc:
            raise DockerActionError("missing", 404) from exc
        except DockerException as exc:
            raise DockerActionError("docker-unavailable", 503) from exc
        finally:
            try:
                self._close_client(client)
            finally:
                self._action_lock.release()

        result = self.status()
        result["action"] = action
        return result

    def log_events(self) -> Generator[dict[str, str], None, None]:
        """Follow logs forever, reconnecting after failures or container replacement."""
        last_container_id: str | None = None
        last_notice: str | None = None
        while True:
            client = None
            try:
                client = self._client_factory()
                client.ping()
                container = client.containers.get(self.container_name)
                container_id = container.id
                is_new_container = container_id != last_container_id
                tail = 200 if is_new_container else 0
                if last_container_id is not None and is_new_container:
                    yield self._system_event("Container recreation detected; attached to the replacement.")
                last_container_id = container_id
                container.reload()
                docker_status = str(
                    container.attrs.get("State", {}).get("Status")
                    or container.status
                    or ""
                ).lower()
                if docker_status not in {"running", "restarting"}:
                    if is_new_container:
                        historical_chunks = container.logs(
                            stdout=True,
                            stderr=True,
                            stream=True,
                            follow=False,
                            timestamps=True,
                            tail=tail,
                        )
                        for line in _bounded_lines(historical_chunks):
                            last_notice = None
                            yield {"type": "log", "text": redact(line)}
                    notice = "Target container is stopped; waiting for it to start."
                    if notice != last_notice:
                        yield self._system_event(notice)
                        last_notice = notice
                    self._sleep(self.reconnect_seconds)
                    continue
                chunks = container.logs(
                    stdout=True,
                    stderr=True,
                    stream=True,
                    follow=True,
                    timestamps=True,
                    tail=tail,
                )
                for line in _bounded_lines(chunks):
                    last_notice = None
                    yield {"type": "log", "text": redact(line)}
                notice = "Log stream ended unexpectedly; reconnecting."
                if notice != last_notice:
                    yield self._system_event(notice)
                    last_notice = notice
            except NotFound:
                notice = "Target container is missing; waiting for it to appear."
                if notice != last_notice:
                    yield self._system_event(notice)
                    last_notice = notice
                last_container_id = None
            except DockerException:
                notice = "Docker is unavailable; retrying the backend connection."
                if notice != last_notice:
                    yield self._system_event(notice)
                    last_notice = notice
            finally:
                self._close_client(client)
            self._sleep(self.reconnect_seconds)

    @staticmethod
    def _system_event(message: str) -> dict[str, str]:
        return {"type": "system", "text": message, "timestamp": _utc_now()}

    @staticmethod
    def _close_client(client: Any | None) -> None:
        if client is None:
            return
        try:
            client.close()
        except DockerException:
            pass


class DockerActionError(RuntimeError):
    def __init__(self, code: str, http_status: int) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status
