"""Persistent specialist sessions built on the existing OpenClaw transport.

This module deliberately remains a plugin concern.  Omega supplies one bounded
task projection and receives one compact result; worker transcripts and
continuation state stay in the SQLite store and OpenClaw session respectively.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
import threading
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence
from uuid import uuid4


logger = logging.getLogger(__name__)
MAX_IN_FLIGHT = 5
MAX_RESULT_CHARS = 4000


class SubagentError(RuntimeError):
    """Base error for a rejected or failed subagent operation."""


class UnknownSubagentError(SubagentError):
    """Raised when no registered worker can perform the requested task."""


class ToolPermissionError(SubagentError):
    """Raised when a task requests a tool outside the worker allowlist."""


class SessionError(SubagentError):
    """Raised for an unknown session or an invalid session/agent pairing."""


@dataclass(frozen=True)
class SubagentDefinition:
    id: str
    name: str
    description: str
    capabilities: frozenset[str]
    instructions: str
    allowed_tools: frozenset[str]
    backend_agent_id: str


@dataclass(frozen=True)
class ContextProjection:
    goal: str
    context: str = ""
    facts: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    expected_output: str = ""
    evaluation_criteria: tuple[str, ...] = ()
    requested_tools: tuple[str, ...] = ()

    @classmethod
    def from_input(cls, goal: str, value: Any = None) -> "ContextProjection":
        if isinstance(value, cls):
            return cls(goal=goal, **{k: v for k, v in asdict(value).items() if k != "goal"})
        payload: Any = value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("{"):
                try:
                    payload = json.loads(stripped)
                except ValueError:
                    payload = {"context": value}
            else:
                payload = {"context": value}
        if payload is None:
            payload = {}
        if not isinstance(payload, Mapping):
            raise SubagentError("context must be text, a JSON object, or ContextProjection")

        def strings(name: str) -> tuple[str, ...]:
            raw = payload.get(name, ())
            if isinstance(raw, str):
                return (raw,) if raw.strip() else ()
            return tuple(str(item) for item in raw if str(item).strip())

        return cls(
            goal=str(goal).strip(),
            context=str(payload.get("context", "")).strip(),
            facts=strings("facts"),
            constraints=strings("constraints"),
            artifacts=strings("artifacts"),
            expected_output=str(payload.get("expected_output", "")).strip(),
            evaluation_criteria=strings("evaluation_criteria"),
            requested_tools=strings("requested_tools"),
        )

    def render(self, definition: SubagentDefinition) -> str:
        sections = [
            ("ROLE", f"{definition.name}: {definition.instructions}"),
            ("GOAL", self.goal),
            ("RELEVANT CONTEXT", self.context),
            ("RELEVANT FACTS", "\n".join(f"- {item}" for item in self.facts)),
            ("CONSTRAINTS", "\n".join(f"- {item}" for item in self.constraints)),
            ("ARTIFACTS / REFERENCES", "\n".join(f"- {item}" for item in self.artifacts)),
            ("EXPECTED OUTPUT", self.expected_output),
            ("EVALUATION CRITERIA", "\n".join(f"- {item}" for item in self.evaluation_criteria)),
            ("ALLOWED TOOL CATEGORIES", ", ".join(sorted(definition.allowed_tools))),
        ]
        body = "\n\n".join(f"{title}\n{text}" for title, text in sections if text)
        return (
            f"{body}\n\n"
            "Return only a JSON object with keys status, summary, findings, "
            "artifacts, evidence, and optional error. Keep it compact. Do not "
            "include your transcript or intermediate reasoning."
        )


@dataclass(frozen=True)
class SubagentResult:
    agent_id: str
    session_id: str
    run_id: str
    status: str
    summary: str
    findings: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["findings"] = list(self.findings)
        value["artifacts"] = list(self.artifacts)
        value["evidence"] = list(self.evidence)
        return value


class SubagentRegistry:
    def __init__(self, definitions: Iterable[SubagentDefinition] = ()):
        self._definitions: dict[str, SubagentDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: SubagentDefinition) -> None:
        if definition.id in self._definitions:
            raise ValueError(f"duplicate subagent id: {definition.id}")
        self._definitions[definition.id] = definition

    def get(self, agent_id: str) -> SubagentDefinition:
        try:
            return self._definitions[str(agent_id)]
        except KeyError as exc:
            raise UnknownSubagentError(f"unknown subagent: {agent_id}") from exc

    def select(
        self,
        capability: str | None = None,
        task: str = "",
        agent_id: str | None = None,
    ) -> SubagentDefinition:
        if agent_id:
            return self.get(agent_id)
        wanted = _normalise(capability or "")
        if not wanted:
            raise UnknownSubagentError("capability or explicit agent_id is required")
        task_words = set(_normalise(task).split())
        scored = []
        for definition in self._definitions.values():
            capabilities = {_normalise(item) for item in definition.capabilities}
            score = 100 if wanted in capabilities else 0
            score += sum(1 for item in capabilities if item in task_words)
            if score:
                scored.append((score, definition.id, definition))
        if not scored:
            raise UnknownSubagentError(f"unsupported capability: {capability}")
        return max(scored, key=lambda item: (item[0], item[1]))[2]

    def all(self) -> tuple[SubagentDefinition, ...]:
        return tuple(self._definitions.values())


DEFAULT_REGISTRY = SubagentRegistry((
    SubagentDefinition(
        id="research-agent",
        name="Research Agent",
        description="Evidence gathering, comparison, and summarisation.",
        capabilities=frozenset({"research", "search", "information gathering", "comparison", "summarize"}),
        instructions="Investigate the bounded question and return concise evidence-backed findings.",
        allowed_tools=frozenset({"web-search", "read-file", "memory-read"}),
        backend_agent_id="research-agent",
    ),
    SubagentDefinition(
        id="coding-agent",
        name="Coding Agent",
        description="Repository inspection, implementation, debugging, and tests.",
        capabilities=frozenset({"code", "coding", "debug", "test", "repository inspection"}),
        instructions="Make only the requested repository changes and report artifacts and tests.",
        allowed_tools=frozenset({"read-file", "write-file", "shell", "test-runner", "git-read"}),
        backend_agent_id="coding-agent",
    ),
    SubagentDefinition(
        id="reviewer-agent",
        name="Reviewer Agent",
        description="Independent validation, critique, and result inspection.",
        capabilities=frozenset({"review", "validate", "validation", "critique"}),
        instructions="Check the supplied work against its criteria and return actionable findings.",
        allowed_tools=frozenset({"read-file", "test-results", "test-runner", "git-read"}),
        backend_agent_id="reviewer-agent",
    ),
))


class ToolResolver:
    """Validates requested tool categories before a worker is invoked."""

    @staticmethod
    def resolve(definition: SubagentDefinition, requested: Sequence[str]) -> tuple[str, ...]:
        requested_set = {str(item) for item in requested}
        denied = requested_set - definition.allowed_tools
        if denied:
            raise ToolPermissionError(
                f"{definition.id} is not allowed tools: {', '.join(sorted(denied))}"
            )
        return tuple(sorted(requested_set or definition.allowed_tools))


class SessionStore:
    """Small SQLite store shared by all subagent identities."""

    def __init__(self, path: str | Path):
        resolved = Path(path).expanduser()
        if not resolved.is_absolute():
            resolved = Path(__file__).resolve().parents[2] / resolved
        self.path = str(resolved.resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS subagent_sessions (
                    session_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    backend_response_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    closed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS subagent_runs (
                    run_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES subagent_sessions(session_id),
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    result_summary TEXT NOT NULL DEFAULT '',
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS subagent_messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES subagent_sessions(session_id),
                    run_id TEXT NOT NULL REFERENCES subagent_runs(run_id),
                    role TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_subagent_runs_session
                    ON subagent_runs(session_id, started_at);
                CREATE INDEX IF NOT EXISTS idx_subagent_messages_session
                    ON subagent_messages(session_id, created_at);
            """)

    def create_session(self, agent_id: str, title: str) -> str:
        session_id, now = f"ses-{uuid4().hex}", _now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO subagent_sessions "
                "(session_id, agent_id, title, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'active', ?, ?)",
                (session_id, agent_id, title[:200], now, now),
            )
        return session_id

    def get_session(self, session_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM subagent_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise SessionError(f"unknown subagent session: {session_id}")
        return dict(row)

    def create_run(self, session_id: str, goal: str) -> str:
        run_id, now = f"run-{uuid4().hex}", _now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO subagent_runs (run_id, session_id, goal, status, started_at) "
                "VALUES (?, ?, ?, 'running', ?)",
                (run_id, session_id, goal, now),
            )
            db.execute(
                "UPDATE subagent_sessions SET status = 'active', updated_at = ?, closed_at = NULL "
                "WHERE session_id = ?",
                (now, session_id),
            )
        return run_id

    def add_message(
        self, session_id: str, run_id: str, role: str, message_type: str, content: str
    ) -> str:
        message_id = f"msg-{uuid4().hex}"
        with self._connect() as db:
            db.execute(
                "INSERT INTO subagent_messages "
                "(message_id, session_id, run_id, role, message_type, content, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (message_id, session_id, run_id, role, message_type, content, _now()),
            )
        return message_id

    def finish(
        self,
        session_id: str,
        run_id: str,
        status: str,
        summary: str,
        backend_response_id: str | None = None,
        error: str | None = None,
    ) -> None:
        now = _now()
        with self._connect() as db:
            db.execute(
                "UPDATE subagent_runs SET status = ?, ended_at = ?, result_summary = ?, error = ? "
                "WHERE run_id = ? AND session_id = ?",
                (status, now, summary, error, run_id, session_id),
            )
            db.execute(
                "UPDATE subagent_sessions SET status = ?, summary = ?, "
                "backend_response_id = COALESCE(?, backend_response_id), updated_at = ?, closed_at = ? "
                "WHERE session_id = ?",
                (status, summary, backend_response_id, now, now, session_id),
            )

    def list_runs(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM subagent_runs WHERE session_id = ? ORDER BY started_at, run_id",
                (session_id,),
            )]

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM subagent_messages WHERE session_id = ? ORDER BY created_at, message_id",
                (session_id,),
            )]


@dataclass(frozen=True)
class PreparedRun:
    definition: SubagentDefinition
    projection: ContextProjection
    session_id: str
    run_id: str
    prompt: str
    previous_response_id: str | None


class OpenClawExecutor:
    def __init__(self, openclaw_url: str):
        self.openclaw_url = openclaw_url

    def __call__(self, prepared: PreparedRun) -> Mapping[str, Any]:
        import openclaw

        raw = openclaw._send_with_startup_retry(
            message=prepared.prompt,
            openclaw_url=self.openclaw_url,
            openclaw_agent=prepared.definition.backend_agent_id,
            previous_response_id=prepared.previous_response_id,
        )
        return json.loads(raw)


class SubagentRuntime:
    def __init__(
        self,
        store: SessionStore,
        executor: Callable[[PreparedRun], Mapping[str, Any]],
        registry: SubagentRegistry = DEFAULT_REGISTRY,
    ):
        self.store = store
        self.executor = executor
        self.registry = registry

    def prepare(
        self,
        task: str,
        context: Any = None,
        capability: str | None = None,
        session_id: str | None = None,
        agent_id: str | None = None,
    ) -> PreparedRun:
        goal = str(task).strip()
        if not goal:
            raise SubagentError("task is empty")
        projection = ContextProjection.from_input(goal, context)
        previous_response_id = None
        if session_id:
            session = self.store.get_session(session_id)
            definition = self.registry.get(session["agent_id"])
            if agent_id and agent_id != definition.id:
                raise SessionError(
                    f"session {session_id} belongs to {definition.id}, not {agent_id}"
                )
            previous_response_id = session["backend_response_id"]
        else:
            definition = self.registry.select(capability, goal, agent_id)
        ToolResolver.resolve(definition, projection.requested_tools)
        if not session_id:
            session_id = self.store.create_session(definition.id, goal)
        run_id = self.store.create_run(session_id, goal)
        prompt = projection.render(definition)
        self.store.add_message(session_id, run_id, "user", "context_projection", prompt)
        logger.info(
            "Subagent run prepared agent=%s session=%s run=%s resumed=%s",
            definition.id,
            session_id,
            run_id,
            previous_response_id is not None,
        )
        return PreparedRun(
            definition, projection, session_id, run_id, prompt, previous_response_id
        )

    def execute(self, prepared: PreparedRun) -> SubagentResult:
        try:
            backend = dict(self.executor(prepared))
            if backend.get("status") not in ("ok", "completed"):
                raise SubagentError(str(backend.get("message") or "worker failed"))
            reply = str(backend.get("reply", "")).strip()
            if not reply:
                raise SubagentError("worker returned an empty result")
            self.store.add_message(
                prepared.session_id, prepared.run_id, "assistant", "worker_reply", reply
            )
            result = _parse_result(prepared, reply)
            self.store.finish(
                prepared.session_id,
                prepared.run_id,
                result.status,
                result.summary,
                str(backend.get("responseId") or "") or None,
                result.error,
            )
            return result
        except Exception as exc:
            error = str(exc)[:1000]
            result = SubagentResult(
                agent_id=prepared.definition.id,
                session_id=prepared.session_id,
                run_id=prepared.run_id,
                status="failed",
                summary="Subagent run failed.",
                error=error,
            )
            self.store.add_message(
                prepared.session_id, prepared.run_id, "system", "error", error
            )
            self.store.finish(
                prepared.session_id, prepared.run_id, "failed", result.summary, error=error
            )
            return result

    def run_subagent(self, **kwargs: Any) -> SubagentResult:
        return self.execute(self.prepare(**kwargs))


_lock = threading.Lock()
_completed: list[str] = []
_in_flight = 0


def send(
    task: str,
    capability: str,
    context: Any,
    session_id: str,
    agent_id: str,
    openclaw_url: str,
    store_path: str,
) -> str:
    """Prepare a persisted run and execute it asynchronously off Omega's loop."""
    global _in_flight
    with _lock:
        if _in_flight >= MAX_IN_FLIGHT:
            return json.dumps({
                "status": "error", "type": "busy",
                "message": f"{_in_flight} subagent runs are still active",
            })
        _in_flight += 1
    try:
        runtime = SubagentRuntime(
            SessionStore(store_path), OpenClawExecutor(str(openclaw_url))
        )
        prepared = runtime.prepare(
            task=task,
            context=context,
            capability=str(capability).strip() or None,
            session_id=str(session_id).strip() or None,
            agent_id=str(agent_id).strip() or None,
        )
    except Exception as exc:
        with _lock:
            _in_flight -= 1
        return json.dumps({
            "status": "error", "type": "invalid_request", "message": str(exc)
        }, ensure_ascii=False)
    threading.Thread(
        target=_worker, args=(runtime, prepared), daemon=True
    ).start()
    return json.dumps({
        "status": "accepted",
        "agent_id": prepared.definition.id,
        "session_id": prepared.session_id,
        "run_id": prepared.run_id,
    }, ensure_ascii=False)


def delegate(task: str, capability: str, context: Any, url: str, store_path: str) -> str:
    return send(task, capability, context, "", "", url, store_path)


def delegate_explicit(task: str, agent_id: str, context: Any, url: str, store_path: str) -> str:
    return send(task, "", context, "", agent_id, url, store_path)


def resume(session_id: str, task: str, context: Any, url: str, store_path: str) -> str:
    return send(task, "", context, session_id, "", url, store_path)


def inspect_session(session_id: str, store_path: str) -> str:
    """Return bounded session/run metadata without exposing worker messages."""
    try:
        store = SessionStore(store_path)
        session = store.get_session(str(session_id).strip())
        runs = store.list_runs(session["session_id"])
    except Exception as exc:
        return json.dumps({
            "status": "error", "type": "session_error", "message": str(exc)
        }, ensure_ascii=False)

    visible_session = {
        key: session[key]
        for key in (
            "session_id", "agent_id", "title", "status", "summary",
            "created_at", "updated_at", "closed_at",
        )
    }
    visible_runs = [
        {
            key: run[key]
            for key in (
                "run_id", "goal", "status", "started_at", "ended_at",
                "result_summary", "error",
            )
        }
        for run in runs[-20:]
    ]
    return json.dumps({
        "status": "ok",
        "session": visible_session,
        "run_count": len(runs),
        "runs": visible_runs,
    }, ensure_ascii=False)


def _worker(runtime: SubagentRuntime, prepared: PreparedRun) -> None:
    global _in_flight
    try:
        record = _render_result(runtime.execute(prepared))
    except Exception as exc:
        logger.exception("Subagent worker crashed: %s", exc)
        record = (
            f"SUBAGENT_RESULT agent={prepared.definition.id} "
            f"session={prepared.session_id} run={prepared.run_id} status=failed "
            f"error={_flatten(exc, 800)}"
        )
    finally:
        with _lock:
            if 'record' in locals():
                _completed.append(record)
            _in_flight -= 1
        logger.info(
            "Subagent run finished agent=%s session=%s run=%s",
            prepared.definition.id,
            prepared.session_id,
            prepared.run_id,
        )


def take_completed() -> str:
    global _completed
    with _lock:
        records, _completed = _completed, []
    return "\n".join(records)


def _parse_result(prepared: PreparedRun, reply: str) -> SubagentResult:
    candidate = reply.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(candidate)
    except (TypeError, ValueError):
        payload = {"status": "completed", "summary": reply}
    if not isinstance(payload, Mapping):
        payload = {"status": "completed", "summary": reply}

    def items(name: str) -> tuple[str, ...]:
        value = payload.get(name, ())
        if isinstance(value, str):
            return (value,) if value.strip() else ()
        return tuple(str(item) for item in value or ())

    status = str(payload.get("status", "completed")).lower()
    status = "failed" if status in {"error", "failed"} else "completed"
    summary = str(payload.get("summary") or reply).strip()[:MAX_RESULT_CHARS]
    error = str(payload.get("error", "")).strip() or None
    return SubagentResult(
        agent_id=prepared.definition.id,
        session_id=prepared.session_id,
        run_id=prepared.run_id,
        status=status,
        summary=summary,
        findings=items("findings"),
        artifacts=items("artifacts"),
        evidence=items("evidence"),
        error=error,
    )


def _render_result(result: SubagentResult) -> str:
    fields = [
        "SUBAGENT_RESULT",
        f"agent={result.agent_id}",
        f"session={result.session_id}",
        f"run={result.run_id}",
        f"status={result.status}",
        f"summary={_flatten(result.summary, 1200)}",
    ]
    if result.findings:
        fields.append(f"findings={_flatten(' | '.join(result.findings), 1200)}")
    if result.artifacts:
        fields.append(f"artifacts={_flatten(' | '.join(result.artifacts), 800)}")
    if result.evidence:
        fields.append(f"evidence={_flatten(' | '.join(result.evidence), 800)}")
    if result.error:
        fields.append(f"error={_flatten(result.error, 800)}")
    return " ".join(fields)


def _flatten(value: Any, limit: int) -> str:
    return " ".join(str(value).replace('"', "'").split())[:limit]


def _normalise(value: str) -> str:
    return " ".join(str(value).lower().replace("-", " ").replace("_", " ").split())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
