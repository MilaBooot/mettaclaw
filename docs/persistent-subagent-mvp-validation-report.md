# Persistent Subagent MVP — Validation Report

**Status:** Live MVP validated

**Validation date:** 2026-10-23

**Branch:** `feat/persistent-subagent-mvp`

> **OpenClaw is used only as the MVP worker-execution adapter. It lets the
> team validate Omega's delegation, specialist selection, bounded context,
> persistence, continuation, and channel-visible results against a real agent
> runtime. It is not proposed as a mandatory Omega core dependency; the next
> architecture phase will make the executor interface explicit and add a
> native Omega worker backend.**

## Executive summary

The MVP was validated end to end through a real Telegram conversation. Omega
used OpenRouter as its LLM provider, selected dedicated research, coding, and
reviewer workers, delegated execution through an authenticated OpenClaw
Gateway, persisted session/run state in SQLite, and returned results to the
same Telegram conversation.

The live validation confirms that the coordinator-to-specialist design works.
It does not make OpenClaw part of Omega's small core. OpenClaw is currently one
execution backend behind the subagent runtime, and replacing that backend does
not require replacing the selector, bounded-context contract, persistence
model, or structured-result contract.

## Validated architecture

```text
Telegram user
    |
    v
Omega coordinator (OpenRouter)
    |
    +-- deterministic capability selector
    +-- bounded context projection
    +-- SQLite session/run persistence
    |
    v
OpenClaw executor adapter (MVP backend)
    |
    +-- research-agent
    +-- coding-agent
    +-- reviewer-agent
    |
    v
Structured result -> Omega -> Telegram
```

Omega owns the coordination contract:

- specialist definitions and capability selection;
- explicit bounded task context;
- session and run identifiers;
- local persistence and inspection;
- continuation metadata;
- structured results and channel-visible lifecycle reporting.

OpenClaw currently supplies worker execution, worker workspaces, and the
backend continuation response. The integration is implemented as a plugin and
communicates with the external Gateway over its authenticated OpenResponses
HTTP endpoint.

## Validation environment

| Component | Validated configuration |
| --- | --- |
| Host | Windows with WSL2 |
| Omega | Docker image built from the MVP branch |
| User channel | Real Telegram bot |
| Coordinator LLM | OpenRouter |
| Worker runtime | OpenClaw 2026.10.6 |
| Worker LLM access | OpenRouter |
| Gateway | Token-authenticated, LAN-bound for Docker access |
| Persistence | SQLite in Omega's persistent memory volume |
| Specialists | `research-agent`, `coding-agent`, `reviewer-agent` |

No API keys, bot tokens, Gateway tokens, or Telegram authentication secrets
should be included in screenshots, logs, commits, or review messages.

## Results

The operator completed the live test procedure in
[`tutorial-09-persistent-subagents.md`](./tutorial-09-persistent-subagents.md)
through its observation stage. The following outcomes were observed as
expected:

| Test | Expected behavior | Result |
| --- | --- | --- |
| Gateway health | Real OpenClaw Gateway is reachable and authenticated | Pass |
| Telegram connection | A Telegram message reaches Omega and receives a response | Pass |
| Coordinator model | Omega responds through the configured OpenRouter provider | Pass |
| Research routing | A research task selects `research-agent` | Pass |
| Coding routing | A coding task selects `coding-agent` | Pass |
| Review routing | A review task selects `reviewer-agent` | Pass |
| Bounded delegation | Only the supplied task projection is sent to the worker | Pass |
| Session creation | Delegation returns stable agent, session, and run identifiers | Pass |
| Persistence inspection | Session status and run metadata can be inspected | Pass |
| Continuation | Resume keeps the session and creates a new run | Pass |
| Structured completion | Worker results return through Omega to Telegram | Pass |
| Operator visibility | Omega logs and the OpenClaw dashboard show execution | Pass |

The existing deterministic Docker integration test remains useful because it
is repeatable and requires no external API. The live test adds evidence that
the same integration contract works with real Telegram, OpenRouter, and
OpenClaw services.

## Evidence recommended for team review

Share redacted evidence rather than secrets or full private prompts:

1. Telegram response from the Omega coordinator.
2. Delegation acknowledgement showing selected agent, session ID, and run ID.
3. Completed structured result from the specialist.
4. Session inspection showing stored status and run metadata.
5. Resume result showing the same session ID and a different run ID.
6. Examples selecting each of the three specialist definitions.
7. Redacted Omega lifecycle logs showing `prepared`, `finished`, and
   `SUBAGENT_RESULT` events.
8. OpenClaw agent list or dashboard showing the three isolated workers.
9. Passing unit and deterministic Docker integration test summaries.

Do not share the OpenRouter API key, Telegram bot token, Telegram channel
authentication secret, OpenClaw Gateway token, raw worker transcript, or
unbounded coordinator history.

## Current MVP boundaries

- Selection is deterministic rather than learned or LLM-ranked.
- OpenClaw is the only real worker executor currently implemented.
- In-flight worker threads do not survive an Omega container restart.
- Same-session concurrency protection and durable job recovery are not yet
  implemented.
- Searchable history, advanced ranking, child-to-child messaging, and
  recursive delegation are intentionally outside this MVP.
- Tool categories exist in Omega's definitions, but production deployments
  must also enforce matching allow/deny policies in the worker runtime.
- The channel reports accepted and completed states, not private chain-of-
  thought or every internal worker action.

## Next architecture: replaceable worker backends

The next phase should extract the generic runtime from the OpenClaw plugin and
make worker execution an explicit interface:

```text
Persistent Subagent Plugin
    +-- registry and capability selector
    +-- context projector
    +-- session store
    +-- structured result contract
    +-- executor interface
          +-- OpenClawExecutor (current optional adapter)
          +-- NativeOmegaExecutor (next target)
          +-- DirectLLMExecutor (lightweight fallback)
          +-- A2AExecutor (future interoperability)
```

Recommended implementation order:

1. Move backend-neutral definitions, selection, projection, persistence, and
   result parsing into `plugins/subagents`.
2. Define a small executor protocol around prepared task, continuation token,
   backend response ID, and structured response.
3. Retain OpenClaw as an optional adapter and use it for compatibility tests.
4. Implement `NativeOmegaExecutor` using isolated Omega worker processes or
   containers with separate prompts, workspaces, and tool policies.
5. Run the same contract tests against fake, OpenClaw, and native Omega
   executors.
6. Add durable job recovery and same-session concurrency protection before
   enabling broader parallelism.

The native backend is acceptable when it passes the same observable contract:
identical capability routing, bounded context, session/run persistence,
continuation, structured results, channel delivery, and policy enforcement.

## Review conclusion

The MVP demonstrates that persistent specialist delegation is viable in
Omega's plugin-oriented architecture. The review decision is therefore not
whether Omega must adopt OpenClaw permanently; it is whether the validated
subagent contract should proceed to a backend-neutral implementation with a
native Omega executor.

## Related documentation

- [`tutorial-09-persistent-subagents.md`](./tutorial-09-persistent-subagents.md)
  — channel demonstration and expected outcomes.
- [`../plugins/openclaw/README.md`](../plugins/openclaw/README.md) — current
  adapter configuration, security model, API behavior, and troubleshooting.
- [`reference-internals-extension-points.md`](./reference-internals-extension-points.md)
  — Omega's plugin-oriented extension model.
