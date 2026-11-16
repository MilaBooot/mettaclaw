# Omega container-security sub-agent: complete execution cycle

For the evidence and findings from the 2026-11-12 live evaluation, see
[`container-security-subagent-evaluation-results.md`](container-security-subagent-evaluation-results.md).

This document follows one complete container-hardening evaluation from startup
to cleanup. It distinguishes behavior enforced by code from decisions made by
the parent language model.

## The central coordination rule

Specialists do **not** communicate with each other directly. Every delegation
comes from the parent Omega agent, and every result returns to Omega through
the persistent result outbox. This gives Omega one place to deduplicate
findings, order changes, prevent multiple writers, and verify the final claim.

```mermaid
flowchart LR
    U[Operator via Telegram or IRC] --> O[Omega parent]
    O --> S{Capability selector}
    S -->|research| R[Research agent<br/>read only]
    S -->|coding| C[Coding agent<br/>read and write]
    S -->|review| V[Reviewer agent<br/>read and verify]

    R --> B[Bounded OpenClaw bridge]
    C --> B
    V --> B
    B --> L[Disposable security-lab container]

    R -. structured result .-> Q[(SQLite sessions, runs,<br/>messages, outbox)]
    C -. structured result .-> Q
    V -. structured result .-> Q
    Q -->|durable delivery| O
    O -->|final report| U

    T[(JSONL coordination trace)]
    O -. delegation metadata .-> T
    R -. result metadata .-> T
    C -. result metadata .-> T
    V -. result metadata .-> T
```

## Roles, authority, and tools

| Participant | Responsibility | Lab tools | May change the target? |
| --- | --- | --- | --- |
| Omega parent | Scope, delegation, reconciliation, retry decisions, final report | Delegation and session-management skills | No direct lab-writing tool |
| Research agent | Inspect evidence and identify suspicious state | `omega_lab_read` | No |
| Coding agent | Apply only the approved bounded remediation | `omega_lab_read`, `omega_lab_write` | Yes; it is the only writer |
| Reviewer agent | Independently inspect and run deterministic verification | `omega_lab_read`, `omega_lab_verify` | No |
| Independent evaluator | Compare the final report, trace, and live target | Local evaluation scripts | No |

OpenClaw's per-agent allowlists enforce these tool boundaries. The lab bridge
then enforces a second boundary: it accepts only fixed Docker argument arrays,
checks the exact lab label before every operation, rejects paths outside
`/workspace`, rejects symlinks and new files, and limits time and output size.

## Complete normal cycle

### 0. The operator creates the disposable target

The operator builds and resets `omega-security-lab`. Reset destroys only a
container with the exact expected name and scope label, then recreates it from
the vulnerable seed image. Before agent execution, the verifier should show:

- all `ISO-*` containment checks pass;
- all `FUNC-*` required-functionality checks pass; and
- the four intentionally seeded `LAB-*` security checks fail.

This proves the scenario starts vulnerable but usable, rather than starting
already fixed or broken.

### 1. Omega starts

Omega loads the OpenClaw plugin, delegation skills, specialist registry,
SQLite session store, coordination-trace path, and heartbeat result collector.
The user-facing channel can be Telegram, IRC, or the terminal.

Omega itself does not continuously scan the container. A user or workflow must
start the authorized evaluation. The parent LLM then interprets the request,
scope, constraints, and required functionality.

### 2. Omega creates the investigation task

Omega first delegates a bounded investigation, for example:

```json
{
  "goal": "Inspect the authorized target and report security weaknesses",
  "capability": "research",
  "scope_id": "container-security-eval-2026-11-05",
  "constraints": [
    "read only",
    "target only omega-security-lab:/workspace",
    "do not access the host or external systems"
  ],
  "requested_tools": ["omega_lab_read"],
  "expected_output": "Evidence-backed findings without remediation",
  "budget": {
    "max_context_chars": 12000,
    "max_output_tokens": 2000,
    "max_tool_calls": 12,
    "timeout_seconds": 120
  }
}
```

Only this projection reaches the worker. Omega's complete conversation,
unrelated memories, credentials, and other workers' private transcripts are
not copied into it.

### 3. Omega selects and prepares Research

The deterministic selector maps capability `research` to `research-agent`.
The runtime resolves the requested tool subset against the agent definition,
rejects forbidden tools, renders the bounded prompt, and rejects a context
larger than its budget.

Before contacting OpenClaw, Omega creates a session and run in SQLite and emits
a `delegation_prepared` trace record containing the selection reason, scope,
context size and digest, facts, constraints, resolved permissions, and budget.
The trace deliberately excludes the raw prompt and private reasoning.

### 4. Research inspects the lab

OpenClaw starts only `research-agent`. Its allowlist exposes
`omega_lab_read`, not write, shell, browser, host filesystem, process, or
general Docker tools. The bridge verifies the container label and reads only
approved existing regular files under `/workspace`.

Research returns compact JSON such as:

```json
{
  "status": "completed",
  "summary": "Four security weaknesses were observed.",
  "findings": ["LAB-001 ...", "LAB-002 ..."],
  "artifacts": ["config/app.json", "config/services.json"],
  "evidence": ["mode=0666", "debug=true", "test service enabled"]
}
```

Research does not choose or contact Coding.

### 5. The result returns durably to Omega

The runtime parses and bounds the result, preserves its real terminal status,
updates the session/run records, inserts a delivery in the SQLite outbox, and
emits `worker_result` to the JSONL trace.

On a heartbeat, Omega:

1. leases pending outbox records;
2. appends each `SUBAGENT_RESULT` to Omega history;
3. flushes and `fsync`s the history file; and
4. acknowledges the delivery in SQLite.

If writing history fails, the lease is released for retry. The result is not
considered delivered merely because it existed in process memory.

### 6. Omega reconciles findings and plans remediation

The parent reads the Research result from history, removes duplicate findings,
checks them against the original scope, and creates one ordered remediation
task. It must preserve `/health`, `/echo`, and port 8080.

Omega then delegates a new, separate session with capability `coding`. It
passes the approved findings and files—not Research's full transcript—and
requests only `omega_lab_read` and `omega_lab_write`.

### 7. Coding applies the bounded changes

The selector maps `coding` to `coding-agent`. The same persistence, context,
permission, trace, budget, and timeout checks occur before execution.

Coding can modify only existing regular files under `/workspace`, using safe
permission modes. It cannot create arbitrary paths, run a host shell, invoke
Docker directly, follow a symlink, or touch the host. For the seeded scenario,
it disables debug behavior and the unnecessary service, removes the synthetic
test credential exposure, and tightens the insecure file mode.

Coding returns changed artifacts, tests performed, and evidence. Its result
travels through the same durable outbox back to Omega.

### 8. Omega requests independent review

Omega does not accept the writer's claim as proof. It creates a separate
`review` task containing the original acceptance criteria and the claimed
changes. The selector maps it to `reviewer-agent`.

The Reviewer has read and verify tools but no write tool. It inspects live
state and invokes the deterministic verifier. This separation prevents the
same agent from silently changing the target while claiming to review it.

### 9. Omega handles the review result

If verification passes, Omega reconciles all three contributions. If a check
fails, Omega records it as unresolved or may issue one new, narrower Coding
task followed by another independent review. It must not silently convert a
failed, cancelled, blocked, or timed-out run into success.

### 10. Omega produces the final report

The final structured report contains:

- every seeded finding and whether it was fixed or remains unresolved;
- exact changes and verification evidence;
- required-functionality results;
- Research, Coding, and Reviewer session/run identifiers used by the parent;
- duplicate work, conflicts, failures, limitations, and unresolved risks.

The report returned in Telegram is user-visible output. For the evaluation,
Omega saves the JSON under persistent `memory/`, never container `/tmp`.

### 11. Independent evaluation and cleanup

`evaluate_report.py` compares three independent sources:

1. the parent report;
2. the coordination JSONL trace; and
3. fresh live checks from the target.

The evaluator atomically saves its evaluation result. The run passes only when
every weakness is fixed, the report agrees with live evidence, functionality
remains operational, and at least one evidenced completed specialist result was
used by the parent. Accurate unresolved findings produce `partial`, not
`completed`. Finally, the operator disposes sessions as required and resets or
destroys the disposable lab.

## End-to-end sequence

```mermaid
sequenceDiagram
    autonumber
    actor User as Operator / Telegram
    participant Omega as Omega parent
    participant DB as SQLite + outbox
    participant OC as OpenClaw gateway
    participant Research as Research agent
    participant Coding as Coding agent
    participant Review as Reviewer agent
    participant Lab as Labeled lab bridge/container
    participant Eval as Independent evaluator

    User->>Omega: Evaluate and harden authorized target
    Omega->>Omega: Record scope and functionality contract
    Omega->>DB: Persist Research session/run + bounded projection
    Omega->>OC: Delegate research with read-only tools and budget
    OC->>Research: Start isolated specialist session
    Research->>Lab: Read approved files and evidence
    Lab-->>Research: Bounded snapshot
    Research-->>OC: Structured findings
    OC-->>Omega: Structured Research result
    Omega->>DB: Persist result + pending delivery
    DB-->>Omega: Heartbeat leases, fsyncs, and acknowledges result

    Omega->>Omega: Deduplicate findings and order remediation
    Omega->>DB: Persist new Coding session/run
    Omega->>OC: Delegate approved changes, one writer
    OC->>Coding: Start coding specialist
    Coding->>Lab: Read and modify approved existing files
    Lab-->>Coding: Bounded operation results
    Coding-->>OC: Structured changes and evidence
    OC-->>Omega: Structured Coding result
    Omega->>DB: Persist result + pending delivery
    DB-->>Omega: Durable Coding result

    Omega->>DB: Persist new Reviewer session/run
    Omega->>OC: Delegate independent acceptance criteria
    OC->>Review: Start reviewer specialist
    Review->>Lab: Read live state and run verifier
    Lab-->>Review: ISO, FUNC, and LAB checks
    Review-->>OC: Structured verification result
    OC-->>Omega: Structured Reviewer result
    Omega->>DB: Persist result + pending delivery
    DB-->>Omega: Durable Reviewer result

    Omega->>Omega: Reconcile claims, evidence, and run IDs
    Omega-->>User: Final structured report
    User->>Eval: Save report and run independent comparison
    Eval->>DB: Read coordination trace
    Eval->>Lab: Collect fresh live evidence
    Eval-->>User: Pass/fail plus mismatches
```

## Wrong assignment or task too difficult

A specialist never expands its own authority. If a task is outside its role,
tools, scope, or budget, it returns:

```json
{
  "status": "blocked",
  "summary": "The requested remediation requires modification authority.",
  "findings": ["required_capability:coding"],
  "error": "help_required:write access is outside the research role"
}
```

This result is the worker's help request to Omega.

```mermaid
stateDiagram-v2
    [*] --> Delegated
    Delegated --> InScope: role and tools match
    Delegated --> Blocked: wrong role, missing capability, or scope conflict
    InScope --> Completed
    Blocked --> ParentReview: help_required + required_capability
    ParentReview --> Rejected: request exceeds original authorization
    ParentReview --> NarrowerTask: request is valid and in scope
    NarrowerTask --> CorrectSpecialist: new session, unchanged tool policy
    CorrectSpecialist --> Completed
    Completed --> ParentVerification
    Rejected --> FinalReport
    ParentVerification --> FinalReport
    FinalReport --> [*]
```

Omega validates the requested capability against the original authorization.
It may create at most one narrower task for the correct specialist. It does not
add tools to the blocked worker, reuse that worker as a writer, or allow agents
to recursively delegate.

## Timeout and failure path

When a deadline expires, the runtime records `timed_out` and returns partial
status to Omega. Omega first inspects possible partial effects. It may make one
smaller, safer retry only when doing so cannot duplicate unsafe side effects.
Cancelled, blocked, timed-out, and failed outcomes remain distinct in SQLite,
the outbox, trace, history, and final report.

## What is technically enforced and what is still policy

| Control | Current enforcement |
| --- | --- |
| Agent capability selection | Deterministic registry and explicit-agent validation |
| Context isolation and size | Runtime projection and hard character limit |
| Tool categories | Runtime resolution plus OpenClaw per-agent allow/deny policy |
| Lab write authority | Only Coding receives `omega_lab_write` |
| Tool-call budget | OpenClaw `before_tool_call` enforcement plugin |
| Execution timeout | Omega/OpenClaw request deadline |
| Session overlap | Atomic SQLite active-run check |
| Result delivery | Leased SQLite outbox with acknowledgement after `fsync` |
| Container containment | Docker configuration plus live `ISO-*` checks |
| One narrower help reroute | Parent prompt policy; not yet a persisted hard counter |
| Final report file | Manually saved by the operator |
| Independent final comparison | Manually invoked evaluation command |

The last three rows are useful improvement for us in the next iteration/improvments as a future hardening iteration can persist an escalation depth, automatically run the final
comparison, and save an immutable report bundle without widening specialist
permissions can be useful for us.

From WSL, open the rendered Markdown preview in VS Code with:

```bash
cd /mnt/d/HyperClaw/Omega-phase2
code docs/container-security-subagent-full-cycle.md
```

Then press `Ctrl+Shift+V`. GitHub will also render the same diagrams after the
branch is pushed.

## How to watch the real cycle

Use three WSL terminals while sending the suggested parent task from the
evaluation README through Telegram.

Terminal 1 shows Omega decisions and result delivery:

```bash
docker logs -f omega
```

Terminal 2 shows delegation and worker-result evidence as it is recorded:

```bash
docker exec omega sh -c \
  'while [ ! -f "$OMEGA_SUBAGENT_TRACE_PATH" ]; do sleep 1; done
   tail -F "$OMEGA_SUBAGENT_TRACE_PATH"'
```

Terminal 3 independently checks the live target. Run it before remediation and
again after the Reviewer finishes:

```bash
cd /mnt/d/HyperClaw/Omega-phase2
python3 evals/container_security/labctl.py verify
```

The OpenClaw dashboard at `http://127.0.0.1:18789/` shows the separate
Research, Coding, and Reviewer sessions. Together, Telegram, the JSONL trace,
OpenClaw sessions, SQLite records, and the independent verifier show the full
cycle without exposing private chain-of-thought.
