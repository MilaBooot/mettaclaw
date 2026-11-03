# Tutorial 09 — Persistent subagents from Telegram or IRC

This tutorial demonstrates the coordinator-to-specialist flow through a normal
OmegaClaw chat channel. Telegram, IRC, Slack, Mattermost, and WebSocket all use
the same `send`/`receive` interface, so subagent behavior does not depend on the
selected channel.

The main Omega agent does not turn into a specialist. It remains the
coordinator, selects an OpenClaw worker, sends only bounded task context, and
later receives a compact result. Worker prompts and raw replies stay out of the
chat channel.

## Before the demo

Complete the OpenClaw and OmegaClaw setup in
[`plugins/openclaw/README.md`](../plugins/openclaw/README.md):

1. Enable the OpenResponses endpoint.
2. Configure `research-agent`, `coding-agent`, and `reviewer-agent` in OpenClaw.
3. Enable the OmegaClaw `openclaw` plugin.
4. Start OmegaClaw with the Gateway URL and token.
5. Select and authenticate your Telegram or IRC channel normally.

The container log should contain:

```text
openclaw-plugin | "OpenClaw integration is enabled"
```

## Delegate from chat

Send this message to the Omega bot:

```text
Delegate this to the research specialist: compare SQLite WAL mode with the
default journal mode for this MVP. Use only relevant context, tell me which
specialist and session you selected, and report the result when it finishes.
```

Omega should acknowledge the asynchronous run with identifiers similar to:

```text
Selected research-agent. Session ses-... is running as run-....
```

This acknowledgement proves the capability selector chose the research
definition. The exact wording is model-generated; the `agent`, `session`, and
`run` identifiers are the stable evidence.

After OpenClaw finishes, Omega receives a `SUBAGENT_RESULT` and should send one
completion message through the same channel:

```text
research-agent completed run-... in session ses-.... Summary: ...
```

Results are asynchronous. If Omega is idle, delivery occurs on the next
heartbeat or incoming message.

## Inspect status from chat

Use the session id from the acknowledgement:

```text
Inspect subagent session ses-... and tell me its selected agent, status, and
all run ids. Do not show private worker context.
```

Omega can call `inspect-subagent-session`. Its result includes the session
metadata and up to 20 recent runs, but deliberately excludes projected prompts,
raw worker replies, and the OpenClaw continuation token.

## Resume the same specialist

Send:

```text
Resume subagent session ses-... and verify the recommendation against our
current persistence requirements. Tell me the new run id.
```

Expected behavior:

- The `session_id` remains unchanged.
- A new `run_id` is created.
- The selected agent remains `research-agent`.
- OpenClaw receives the earlier `previous_response_id` and continues that
  worker conversation.

An unrelated coding or review task should use a new delegation instead of
resuming the research session:

```text
Delegate a read-only review of the persistence implementation to the reviewer
specialist. Report the selected agent, session id, run id, and final verdict.
```

The expected selected id is `reviewer-agent` and the session id must differ
from the research session.

## Verify hardening behavior

Use a `scope_id` such as `demo-review` in the delegation context, then ask
Omega to clean up that scope. Idle sessions in that scope should be disposed
or purged, while sessions from other scopes remain available. Attempting two
overlapping resumes of one session should accept only one run; the other
returns a busy error. Completed results remain in the SQLite outbox until the
history append is acknowledged, and inspection preserves `failed`,
`cancelled`, `blocked`, and `timed_out` outcomes.

For a bounded run, supply a context object with a smaller `budget`, for
example `max_context_chars: 8000`, `max_output_tokens: 1000`,
`max_tool_calls: 5`, and `timeout_seconds: 120`. Context and timeout ceilings
are enforced by Omega. The current OpenClaw adapter forwards the output-token
and tool-call values, but exact tool-call counting is not supported by its
OpenResponses endpoint; configure strict per-agent tool policies as well.

Use roughly 120 seconds for a quick lookup/review, the 300-second default for
a normal task, and at most 600 seconds for a bounded long task. A timeout is
returned as `status=timed_out retryable=true`; Omega should inspect partial
effects and reformulate or split the task before one deliberate retry. It
must not blindly repeat coding, shell, or other side-effecting work.

## Operator evidence

Chat is the user-facing view. Operators can also watch lifecycle events without
revealing task content:

```bash
docker logs -f omegaclaw 2>&1 | grep -E "Subagent run|SUBAGENT_RESULT"
```

Expected lifecycle:

```text
Subagent run prepared agent=research-agent session=ses-... run=run-... resumed=False
Subagent run finished agent=research-agent session=ses-... run=run-...
SUBAGENT_RESULT agent=research-agent session=ses-... run=run-... status=completed ...
```

The persistent source of truth is
`memory/subagent_sessions.sqlite3`. The focused automated Docker test checks
the same channel-independent path:

```bash
cd Autotests
OMEGACLAW_CONTAINER=omegaclaw \
OMEGACLAW_OPENCLAW_TOKEN=<token> \
python -m pytest mock/test_subagent_sessions_mock.py -s -v
```

## Current MVP limits

- There is no graphical dashboard or live streaming of child reasoning.
- The coordinator reports accepted and completed states, not every internal
  worker action.
- In-flight worker threads do not survive an OmegaClaw container restart.
- Searchable history, ranking, parallel orchestration policy, and crash
  recovery/reconciliation belong to later phases.
- Workflow and space teardown must call `cleanup-subagent-scope`; Omega does
  not yet publish a generic automatic teardown event to plugins.
- Exact per-run tool-call limits require a backend that enforces that field;
  OpenClaw currently relies on its server-side agent tool policy.
