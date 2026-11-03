"""Focused tests for the persistent OpenClaw subagent runtime."""

import importlib.util
import json
import os
import sys
import time

import pytest


_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_PLUGIN_DIR = os.path.join(_REPO_ROOT, "plugins", "openclaw")
_MODULE_PATH = os.path.join(_PLUGIN_DIR, "subagents.py")

if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)


def _load_module():
    spec = importlib.util.spec_from_file_location("subagents_under_test", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sa():
    module = _load_module()
    module._completed = []
    module._in_flight = 0
    yield module
    module._completed = []
    module._in_flight = 0


class FakeExecutor:
    def __init__(self, reply=None, error=None):
        self.calls = []
        self.reply = reply or {
            "status": "completed",
            "summary": "compact conclusion",
            "findings": ["fact one"],
            "artifacts": ["report.md"],
            "evidence": ["test passed"],
        }
        self.error = error

    def __call__(self, prepared):
        self.calls.append(prepared)
        if self.error:
            raise self.error
        return {
            "status": "ok",
            "responseId": f"resp-{len(self.calls)}",
            "reply": json.dumps(self.reply),
        }


def _runtime(sa, tmp_path, executor=None):
    store = sa.SessionStore(tmp_path / "subagents.sqlite3")
    executor = executor or FakeExecutor()
    return sa.SubagentRuntime(store, executor), executor


def test_registry_finds_agents_and_selects_by_capability(sa):
    registry = sa.DEFAULT_REGISTRY
    assert registry.get("research-agent").name == "Research Agent"
    assert registry.select("research", "Investigate sessions").id == "research-agent"
    assert registry.select("coding", "Implement the store").id == "coding-agent"
    assert registry.select("review", "Critique the result").id == "reviewer-agent"


def test_explicit_agent_overrides_selection_and_unknown_capability_fails(sa):
    selected = sa.DEFAULT_REGISTRY.select(
        capability="research", task="research this", agent_id="coding-agent"
    )
    assert selected.id == "coding-agent"
    with pytest.raises(sa.UnknownSubagentError, match="unsupported capability"):
        sa.DEFAULT_REGISTRY.select("astronomy", "look at stars")
    with pytest.raises(sa.UnknownSubagentError, match="unknown subagent"):
        sa.DEFAULT_REGISTRY.select(agent_id="missing-agent")


def test_new_task_creates_session_run_and_structured_result(sa, tmp_path):
    runtime, _ = _runtime(sa, tmp_path)
    result = runtime.run_subagent(
        task="Research persistent sessions",
        capability="research",
        context={"context": "Phase 2", "constraints": ["Do not change Omega"]},
    )
    assert result.agent_id == "research-agent"
    assert result.session_id.startswith("ses-")
    assert result.run_id.startswith("run-")
    assert result.status == "completed"
    assert result.summary == "compact conclusion"
    assert result.findings == ("fact one",)
    assert runtime.store.get_session(result.session_id)["backend_response_id"] == "resp-1"
    assert len(runtime.store.list_runs(result.session_id)) == 1


def test_resume_reuses_session_creates_run_and_continues_backend(sa, tmp_path):
    runtime, executor = _runtime(sa, tmp_path)
    first = runtime.run_subagent(task="Initial research", capability="research")
    second = runtime.run_subagent(
        task="Verify persistence", session_id=first.session_id, context="Only verify storage"
    )
    assert second.session_id == first.session_id
    assert second.run_id != first.run_id
    assert second.agent_id == first.agent_id
    assert len(runtime.store.list_runs(first.session_id)) == 2
    assert executor.calls[0].previous_response_id is None
    assert executor.calls[1].previous_response_id == "resp-1"


def test_sessions_survive_store_and_runtime_recreation(sa, tmp_path):
    path = tmp_path / "durable.sqlite3"
    first_runtime = sa.SubagentRuntime(sa.SessionStore(path), FakeExecutor())
    first = first_runtime.run_subagent(task="Initial research", capability="research")

    second_executor = FakeExecutor()
    second_runtime = sa.SubagentRuntime(sa.SessionStore(path), second_executor)
    second = second_runtime.run_subagent(
        task="Continue after restart", session_id=first.session_id
    )
    assert second.session_id == first.session_id
    assert second_executor.calls[0].previous_response_id == "resp-1"
    assert len(second_runtime.store.list_runs(first.session_id)) == 2


def test_store_releases_database_file_after_each_operation(sa, tmp_path):
    path = tmp_path / "closable.sqlite3"
    store = sa.SessionStore(path)
    session_id = store.create_session("research-agent", "Closable")
    assert store.get_session(session_id)["agent_id"] == "research-agent"
    path.unlink()
    assert not path.exists()


def test_relative_store_path_is_anchored_to_repository(sa, tmp_path, monkeypatch):
    fake_module = tmp_path / "plugins" / "openclaw" / "subagents.py"
    fake_module.parent.mkdir(parents=True)
    monkeypatch.setattr(sa, "__file__", str(fake_module))
    store = sa.SessionStore("memory/subagent_sessions.sqlite3")
    expected = os.path.join(str(tmp_path), "memory", "subagent_sessions.sqlite3")
    assert store.path == os.path.normpath(expected)


def test_session_messages_are_isolated(sa, tmp_path):
    runtime, executor = _runtime(sa, tmp_path)
    research = runtime.run_subagent(
        task="Research private alpha", capability="research", context="ALPHA-ONLY"
    )
    coding = runtime.run_subagent(
        task="Code private beta", capability="coding", context="BETA-ONLY"
    )
    research_messages = json.dumps(runtime.store.list_messages(research.session_id))
    coding_messages = json.dumps(runtime.store.list_messages(coding.session_id))
    assert "ALPHA-ONLY" in research_messages and "BETA-ONLY" not in research_messages
    assert "BETA-ONLY" in coding_messages and "ALPHA-ONLY" not in coding_messages
    assert "BETA-ONLY" not in executor.calls[0].prompt
    assert "ALPHA-ONLY" not in executor.calls[1].prompt


def test_resume_cannot_change_session_owner(sa, tmp_path):
    runtime, _ = _runtime(sa, tmp_path)
    first = runtime.run_subagent(task="Research", capability="research")
    with pytest.raises(sa.SessionError, match="belongs to research-agent"):
        runtime.prepare(
            task="Now code", session_id=first.session_id, agent_id="coding-agent"
        )


def test_tool_allowlist_accepts_allowed_and_rejects_disallowed(sa):
    research = sa.DEFAULT_REGISTRY.get("research-agent")
    assert sa.ToolResolver.resolve(research, ["web-search"]) == ("web-search",)
    with pytest.raises(sa.ToolPermissionError, match="shell"):
        sa.ToolResolver.resolve(research, ["shell"])


def test_requested_tool_is_checked_before_run_creation(sa, tmp_path):
    runtime, executor = _runtime(sa, tmp_path)
    with pytest.raises(sa.ToolPermissionError):
        runtime.prepare(
            task="Research safely",
            capability="research",
            context={"requested_tools": ["shell"]},
        )
    assert executor.calls == []


def test_only_compact_result_is_returned_while_transcript_stays_stored(sa, tmp_path):
    reply = {
        "status": "completed",
        "summary": "public summary",
        "findings": ["finding"],
    }
    runtime, _ = _runtime(sa, tmp_path, FakeExecutor(reply=reply))
    result = runtime.run_subagent(
        task="Bounded review", capability="review", context="PRIVATE CHILD CONTEXT"
    )
    returned = json.dumps(result.to_dict())
    stored = json.dumps(runtime.store.list_messages(result.session_id))
    assert "public summary" in returned
    assert "PRIVATE CHILD CONTEXT" not in returned
    assert "PRIVATE CHILD CONTEXT" in stored


def test_executor_failure_returns_clean_result_and_persists_error(sa, tmp_path):
    runtime, _ = _runtime(sa, tmp_path, FakeExecutor(error=RuntimeError("gateway down")))
    result = runtime.run_subagent(task="Research", capability="research")
    assert result.status == "failed"
    assert result.error == "gateway down"
    run = runtime.store.list_runs(result.session_id)[0]
    assert run["status"] == "failed"
    assert run["error"] == "gateway down"


def test_end_to_end_selection_projection_persistence_and_result(sa, tmp_path):
    runtime, executor = _runtime(sa, tmp_path)
    result = runtime.run_subagent(
        task="Review the implementation",
        capability="review",
        context={
            "facts": ["tests passed"],
            "constraints": ["read only"],
            "expected_output": "A short verdict",
            "requested_tools": ["read-file"],
        },
    )
    assert result.agent_id == "reviewer-agent"
    prompt = executor.calls[0].prompt
    assert "tests passed" in prompt
    assert "read only" in prompt
    assert "A short verdict" in prompt
    assert "Return only a JSON object" in prompt
    assert len(runtime.store.list_messages(result.session_id)) == 2


def test_rendered_omega_result_is_bounded_and_has_no_transcript(sa):
    result = sa.SubagentResult(
        agent_id="research-agent",
        session_id="ses-1",
        run_id="run-1",
        status="completed",
        summary="summary",
        findings=("finding",),
        evidence=("evidence",),
    )
    rendered = sa._render_result(result)
    assert rendered.startswith("SUBAGENT_RESULT agent=research-agent")
    assert "session=ses-1" in rendered
    assert "run=run-1" in rendered
    assert "summary=summary" in rendered
    assert "context_projection" not in rendered


def test_plugin_facing_delegate_and_resume_flow(sa, tmp_path, monkeypatch):
    executor = FakeExecutor()
    monkeypatch.setattr(sa, "OpenClawExecutor", lambda url: executor)
    db = str(tmp_path / "plugin-flow.sqlite3")

    accepted = json.loads(sa.delegate(
        "Research sessions", "research", "Only session facts", "http://gw", db
    ))
    assert accepted["status"] == "accepted"
    assert accepted["agent_id"] == "research-agent"
    for _ in range(100):
        if sa._in_flight == 0:
            break
        time.sleep(0.01)
    completed = sa.take_completed()
    assert f"session={accepted['session_id']}" in completed
    assert f"run={accepted['run_id']}" in completed
    assert "status=completed" in completed

    resumed = json.loads(sa.resume(
        accepted["session_id"], "Verify continuation", "Only verify", "http://gw", db
    ))
    assert resumed["session_id"] == accepted["session_id"]
    assert resumed["run_id"] != accepted["run_id"]
    for _ in range(100):
        if sa._in_flight == 0:
            break
        time.sleep(0.01)
    assert executor.calls[-1].previous_response_id == "resp-1"


def test_inspect_session_returns_bounded_metadata_without_private_messages(sa, tmp_path):
    runtime, _ = _runtime(sa, tmp_path)
    result = runtime.run_subagent(
        task="Research visibility",
        capability="research",
        context="PRIVATE WORKER CONTEXT",
    )

    inspected = json.loads(sa.inspect_session(result.session_id, runtime.store.path))

    assert inspected["status"] == "ok"
    assert inspected["session"]["agent_id"] == "research-agent"
    assert inspected["run_count"] == 1
    assert inspected["runs"][0]["run_id"] == result.run_id
    assert "PRIVATE WORKER CONTEXT" not in json.dumps(inspected)
    assert "backend_response_id" not in json.dumps(inspected)


def test_inspect_unknown_session_returns_clean_error(sa, tmp_path):
    inspected = json.loads(sa.inspect_session(
        "ses-missing", str(tmp_path / "subagents.sqlite3")
    ))
    assert inspected["status"] == "error"
    assert inspected["type"] == "session_error"
