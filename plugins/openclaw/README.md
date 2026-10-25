# OpenClaw plugin

> **OpenClaw is used only as the MVP worker-execution adapter. It lets the
> team validate persistent multi-agent delegation against a real runtime; it
> is not proposed as a mandatory Omega core dependency. Selection, bounded
> context, persistence, and structured results are Omega-owned contracts, and
> the next architecture phase will add a native Omega executor behind an
> explicit replaceable backend interface.**

Adds the `delegate-task-to-openclaw-agent` skill, which hands a self-contained
task to an agent running on an external [OpenClaw](https://docs.openclaw.ai)
Gateway and reports its reply.

It also contains the experimental persistent-subagent MVP. The MVP keeps
Omega as the continuous orchestrator and adds three definitions around one
runtime:

| Definition | Capabilities | Tool categories |
| --- | --- | --- |
| `research-agent` | research, search, comparison, summarisation | web search, file/memory reads |
| `coding-agent` | coding, debugging, testing, repository inspection | file reads/writes, shell, tests, git reads |
| `reviewer-agent` | review, validation, critique | file/test/result inspection |

The definitions are routing and policy metadata, not three copied agent
implementations. All three use the same selector, context projector, OpenClaw
executor, SQLite session store, and structured result contract.

Each delegation runs in its own OpenClaw session: the
[OpenResponses HTTP API](https://docs.openclaw.ai/gateway/openresponses-http-api)
is stateless per request and generates a fresh session key for every call, so
delegated tasks never inherit context from each other.

Persistent subagent calls are the deliberate exception: a new task still gets
a new session, while `resume-subagent-session` sends the stored
`previous_response_id`. OpenClaw then continues that one worker session. The
session id, run records, projected prompts, raw worker replies, compact
summaries, and continuation id are indexed in one local SQLite database.

Delegation is **asynchronous**. A Gateway turn can take minutes while the agent
loop is single-threaded, so the skill hands the task to a worker thread and
returns straight away; the agent keeps answering messages and running other
skills meanwhile. The reply is appended to the agent's history on a later
iteration - see [Skill result](#skill-result).

## Configure the OpenClaw side

### 1. Enable the OpenResponses endpoint

The endpoint is **disabled by default** and must be turned on:

```bash
# Docker install, from the OpenClaw repository root
docker compose run --rm openclaw-cli config set --batch-json \
  '[{"path":"gateway.http.endpoints.responses.enabled","value":true}]'
docker compose restart openclaw-gateway

# Native install
openclaw config set --batch-json \
  '[{"path":"gateway.http.endpoints.responses.enabled","value":true}]'
```

It is served on the Gateway's own port (`18789` by default), alongside the
WebSocket surface.

> **Why HTTP and not the Gateway WebSocket protocol?**
> On the WebSocket path a client that presents only a shared token, without a
> paired device identity, has its requested scopes cleared to an empty set, and
> every call then fails with `missing scope: operator.write (MISSING_SCOPE)`.
> Shared-secret bearer auth on the HTTP surfaces keeps the full default
> operator scope set, so no device keypair or pairing approval is needed.

### 2. Have an agent to delegate to

The target agent must exist in `openclaw.json` under `agents.entries`. The
default install provides `main`. The run uses whatever model that agent is
configured with - the plugin never overrides it.

For the persistent-subagent skills, configure agents with these exact ids:
`research-agent`, `coding-agent`, and `reviewer-agent`. Give each a separate
workspace and an OpenClaw `tools.allow`/`tools.deny` policy matching the table
above. The HyperClaw runtime rejects explicitly requested tool categories that
are outside its definition, while the Gateway policy is the enforcement layer
for tools the worker can actually invoke. Specialists should not be allowed to
delegate recursively in this MVP.

### 3. Get the Gateway token

Token auth is the default (`gateway.auth.mode: "token"`). The value lives in
the Gateway's `.env` as `OPENCLAW_GATEWAY_TOKEN`.

## Configure the OmegaClaw side

`config/config.yaml`:

```yaml
openClawEnabled: enabled
openClawURL: "http://172.17.0.1:18789"
openClawAgent: "main"
subagentStorePath: "./memory/subagent_sessions.sqlite3"
```

`config/plugins.yaml`:

```yaml
- name: openclaw
  loader: metta
  location: "{REPO}/plugins/openclaw"
```

### The token never reaches the agent process

Unlike a bare Python deployment, the Docker image never lets the agent
process hold the Gateway token. `OMEGACLAW_OPENCLAW_TOKEN` must still be
passed through the environment, never through config files:

```bash
docker run ... -e OMEGACLAW_OPENCLAW_TOKEN="<token>" openclaw_url="<gateway URL>" ...
```

(with `scripts/omegaclaw`: `OMEGACLAW_OPENCLAW_TOKEN=<token> ./scripts/omegaclaw start -g "<gateway URL>" ...`)

but the local Nginx proxy (`proxy/nginx.conf.template`, `location /openclaw/`)
reads it *before* the agent's environment is scrubbed (see `entrypoint.sh`)
and injects the `Authorization` header itself. The plugin then always talks
to `http://localhost:8080/openclaw/...` - it never sees the raw token, the
same way the built-in LLM providers never see `ANTHROPIC_API_KEY` /
`OPENAI_API_KEY` / etc. The real Gateway address you pass to `openclaw_url=`
(or `-g`) is what Nginx forwards to; `openClawURL` in `config.yaml` becomes a
plain fallback, used only when `GATEWAY_URL` isn't set (i.e. running the
Python code directly, outside this Docker image) - keep it pointed at the
same Gateway for that case to keep working.

### Choosing the Gateway URL

| OmegaClaw runs | Gateway runs | Use |
| --- | --- | --- |
| in Docker | on the host | `http://172.17.0.1:18789` (the `docker0` bridge address) |
| in Docker | in Docker, same user-defined network | `http://<gateway-container>:18789` |
| on the host | on the host | `http://127.0.0.1:18789` |
| anywhere | on another machine | `https://openclaw.example.com` or `http://10.0.0.5:18789` |

Anything but the loopback case needs the Gateway to listen beyond loopback -
see `gateway.bind` in `openclaw.json`. Across a network, prefer `https://`.

In the fallback (non-Docker) path, `ws://` and `wss://` URLs are also
accepted and rewritten to `http://` / `https://`, so a value left over from
the previous WebSocket transport keeps working. The Nginx `proxy_pass`
target does not do this rewrite, so pass a plain `http://`/`https://` URL to
`openclaw_url=` / `-g`.

## Verify

```bash
# Gateway is up
curl -fsS http://127.0.0.1:18789/healthz

# Endpoint is enabled and the token is accepted (404 = still disabled)
curl -sS http://127.0.0.1:18789/v1/responses \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'x-openclaw-agent-id: main' \
  -d '{"model":"openclaw","input":"Reply with exactly: PONG"}'
```

On OmegaClaw startup the log should show
`openclaw-plugin: OpenClaw integration is enabled`, and the agent should offer
the `delegate-task-to-openclaw-agent` skill.

## Skill result

The result arrives in two stages.

**1. Immediately** the skill returns an acceptance envelope, which the agent
sees in `LAST_SKILL_USE_RESULTS` on its next iteration:

```json
{"status": "accepted", "id": "oc-1", "task": "first 80 characters of the task"}
```

Two cases are rejected up front instead, without contacting the Gateway -
`invalid_input` for an empty message, `busy` when `MAX_IN_FLIGHT` delegations
are already running:

```json
{"status": "error", "type": "invalid_input", "message": "message is empty"}
```

**2. Once the Gateway answers**, the worker's record is picked up on the next
loop iteration and appended to the agent's history as a single line:

```
OPENCLAW_RESULT id=oc-1 status=ok responseId=resp_... task=<echo> reply=<reply>
```

Failures land the same way, carrying the reason instead of a reply:

```
OPENCLAW_RESULT id=oc-1 status=error task=<echo> reply=HTTP 401: Unauthorized (unauthorized)
```

The `id` and `task` echo let the agent match a record to the task it asked for,
so out-of-order arrivals are unambiguous. History is used rather than a prompt
extension because it also holds results that arrive while the agent is idle,
and it survives a restart.

Two consequences worth knowing:

- Results are **not** delivered instantly. A record that lands while the agent
  is idle waits for the next wake-up (`wakeupInterval`) or the next user
  message.
- Delegations still in flight are **lost if the container restarts** - the
  worker threads die with the process and no record is ever produced.

`reply` is truncated to `MAX_REPLY_CHARS` so that one large answer cannot evict
the rest of the history window (`maxHistory`).

## Persistent subagent MVP

### Delegate a new task

The selector is deterministic. `research`, `coding`, and `review` select the
matching definition; an explicit-agent skill is available for tests or when
Omega already knows the desired worker.

```text
delegate-task-to-subagent(
  task="Research persistent OpenClaw sessions",
  capability="research",
  context="Only compare session creation and continuation; cite evidence"
)
```

At the MeTTa skill surface this is:

```metta
(delegate-task-to-subagent
  "Research persistent OpenClaw sessions"
  "research"
  "Only compare session creation and continuation; cite evidence")
```

The third argument can instead be a JSON object with `context`, `facts`,
`constraints`, `artifacts`, `expected_output`, `evaluation_criteria`, and
`requested_tools`. Nothing from Omega's full history is added implicitly.

The immediate result identifies the persisted work:

```json
{
  "status": "accepted",
  "agent_id": "research-agent",
  "session_id": "ses-...",
  "run_id": "run-..."
}
```

When the worker finishes, the heartbeat adds one bounded line to Omega's
history. The full projected prompt and raw reply remain only in SQLite:

```text
SUBAGENT_RESULT agent=research-agent session=ses-... run=run-... status=completed summary=... findings=... evidence=...
```

### Resume the same task

Use the earlier `session_id`. This creates a different `run_id` and sends the
last OpenClaw response id as `previous_response_id`:

```metta
(resume-subagent-session
  "ses-..."
  "Continue the research and verify restart persistence"
  "Limit the follow-up to continuation behavior")
```

Use a new delegation, not resume, for unrelated work. A session cannot be
resumed as a different agent.

### Inspect progress

The coordinator can inspect one known session without loading its private
worker messages into the main context:

```metta
(inspect-subagent-session "ses-...")
```

The result contains the selected agent, current session status, summary, total
run count, and up to 20 recent run records. It excludes projected prompts, raw
worker replies, and the OpenClaw continuation id. This makes questions such as
"which specialist is handling this?" and "did the resumed run finish?"
answerable through Telegram, IRC, or any other configured channel.

For an end-to-end chat demonstration and expected messages, see
[`docs/tutorial-09-persistent-subagents.md`](../../docs/tutorial-09-persistent-subagents.md).

### Explicit worker override

```metta
(delegate-task-to-specific-subagent
  "Review the implementation against the acceptance criteria"
  "reviewer-agent"
  "Inspect only the supplied patch and test results")
```

### Stored model

The single SQLite file has three tables:

- `subagent_sessions`: worker ownership, title/status/summary, and the latest
  OpenClaw continuation id;
- `subagent_runs`: one row for every initial invocation or resume;
- `subagent_messages`: the bounded input projection, raw reply, and failures.

OpenClaw remains the source of truth for the worker's internal tool transcript;
the local table records what HyperClaw sent and what the worker returned. This
avoids copying large child traces into Omega while keeping enough local state
for audit, selection, and resume.

There is intentionally no FTS table in this first MVP. Search, learned ranking,
parallel orchestration policy, child-to-child messaging, recursive delegation,
same-session concurrency control, and crash recovery for in-flight threads are
follow-up work.

### Run the focused MVP tests

From the repository root:

```bash
python -m pytest Autotests/unit/test_subagents_unit.py \
  Autotests/unit/test_openclaw_unit.py -q
```

These tests require no live Gateway. For a live demo, enable the plugin and
OpenResponses endpoint, create the three OpenClaw agents, delegate a research
task, copy its returned `session_id`, and call the resume skill. Inspect run
separation with:

```bash
sqlite3 memory/subagent_sessions.sqlite3 \
  "select session_id, agent_id, status, summary from subagent_sessions;"
sqlite3 memory/subagent_sessions.sqlite3 \
  "select run_id, session_id, goal, status from subagent_runs order by started_at;"
```

## Troubleshooting

| Error | Cause |
| --- | --- |
| `HTTP 404` | `gateway.http.endpoints.responses.enabled` is not set, or the Gateway was not restarted after setting it |
| `HTTP 401: Unauthorized` | `OMEGACLAW_OPENCLAW_TOKEN` is empty or does not match `OPENCLAW_GATEWAY_TOKEN` |
| `HTTP 400: Unknown agent '<id>'` | `openClawAgent` does not exist in `agents.entries` |
| `Cannot reach OpenClaw Gateway` | Wrong `openClawURL`, or the Gateway is bound to loopback only |
| `missing scope ... (MISSING_SCOPE)` | The request went to the WebSocket surface instead of `/v1/responses` |
| `HTTP 504` | The Gateway took longer than the proxy's `proxy_read_timeout` to answer |
| `busy` and no delegation starts | `MAX_IN_FLIGHT` tasks are still running; they clear as the Gateway answers |
| No `OPENCLAW_RESULT` ever appears | The container restarted mid-flight, or the plugin's heartbeat listener was not registered - check for `openclaw-plugin: OpenClaw integration is enabled` on startup |

These errors surface in the `OPENCLAW_RESULT` history line, since the skill
returns before the Gateway answers.

A Gateway that is still booting answers `503`; the worker retries such a
response up to `STARTUP_RETRY_ATTEMPTS` times before giving up. The retry runs
on the worker thread, so it does not stall the agent.
