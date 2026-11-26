# Proposal: Persistent Subagent Architecture for Omega

## 1. Executive proposal

This proposal requests approval to continue the persistent-subagent MVP as an
Omega capability and evolve it into a backend-neutral plugin architecture with
a native Omega worker executor. The MVP demonstrates that Omega can delegate
bounded work to specialist agents, isolate their contexts, persist sessions and
runs, resume related work, and return structured results through the user's
existing channel.

The implementation follows Omega's extension model. Most functionality remains
in plugins, while Omega owns a small backend-neutral execution-decision contract.
OpenClaw currently performs worker execution through an authenticated adapter;
it can be replaced without redesigning capability selection, context projection,
persistence, lifecycle, budgets, or result delivery.

The requested decision is not whether OpenClaw should become part of Omega core.
It is whether the validated subagent contracts are suitable for Omega and should
proceed to a backend-neutral subagents plugin with a native Omega executor.

## 2. Problem and design objectives

A long-running coordinator is not always the best execution environment for
every task. Research, coding, and review require different instructions, tools,
context, models, and safety boundaries. Combining every capability in the
coordinator increases prompt size, mixes unrelated context, weakens tool
isolation, and makes long-running work harder to inspect or resume.

The architecture has six objectives:

1. Keep Omega as the coordinator and preserve its small, plugin-oriented core.
2. Delegate self-contained bounded tasks, never the coordinator's full history.
3. Route work to specialists with explicit capabilities and tool policies.
4. Persist session and run state for inspection, continuation, and disposal.
5. Return compact outcomes reliably through existing Omega channels.
6. Keep worker and model execution replaceable behind stable contracts.

This is not a recursive autonomous-agent network. The coordinator owns
delegation decisions, specialists cannot recursively delegate in the MVP, and
automatic blind retry is disabled for timed-out or side-effecting work.

## 3. Proposed architecture

Coordination, execution planning, and worker execution are separate:

```text
User channel
    |
    v
Omega coordinator
    |
    v
Execution Decision Interface
    +-- coordinator or subagent execution
    +-- requested capability or explicit worker
    +-- provider-neutral model requirements
    +-- optional resolved provider/model route
    |
    v
Persistent-subagent plugin contract
    +-- specialist registry and selector
    +-- bounded context projector
    +-- session/run lifecycle
    +-- SQLite persistence and durable outbox
    +-- tool policy and execution budgets
    +-- structured results and validation
    |
    v
Executor interface
    +-- OpenClawExecutor (optional MVP adapter)
    +-- NativeOmegaExecutor (proposed)
    +-- future compatible executors
    |
    v
Structured result -> Omega -> original user channel
```

The Execution Decision Interface is Omega-owned. It is the common decision
boundary needed by both subagent selection and future model routing, but it does
not merge those plugins. A worker-selection policy resolves the specialist. A
model-selection policy independently resolves provider and model requirements.
Their results are combined into one `ExecutionPlan`.

The current subagent implementation supplies the worker-selection policy. The
model-selection policy is an optional extension point intended for later
integration with OMEGA-376. Until that integration, the configured coordinator
or worker backend continues choosing its model as it does today.

The initial specialist definitions remain intentionally small:

- `research-agent`: research, comparison, search, and summarisation using
  read-oriented tools.
- `coding-agent`: bounded coding, debugging, repository inspection, and tests
  using explicitly permitted write and execution tools.
- `reviewer-agent`: independent critique and verification using read and test
  evidence.

These are policies around one worker abstraction, not copied implementations.
An evaluator/verifier is a validation component, not a fourth specialist.

## 4. End-to-end execution flow

1. The user sends a request through an Omega channel.
2. Omega creates an `ExecutionRequest`. The decision policy determines whether
   the coordinator should handle the request or delegate it, which capability or
   explicit worker is requested, and which provider-neutral model requirements
   apply.
3. `ExecutionPlanSelector` combines the worker and model policy results. The
   current implementation resolves the worker deterministically; a future
   OMEGA-376 adapter may resolve the model route at the same boundary.
4. For delegation, the registry validates the selected worker and Omega creates
   a bounded `ContextProjection`. The full coordinator history is never included
   implicitly.
5. Omega resolves the permitted tool subset, applies budget ceilings, assigns
   session and run identifiers, and stores the prepared run.
6. The executor invokes an isolated worker. New work receives a new session;
   related work may resume the same session while creating a new run.
7. The worker returns a structured outcome. Omega preserves its real status,
   evidence, and remaining work.
8. Completion and delivery metadata are committed to a durable outbox in one
   transaction. Leased delivery is flushed and acknowledged idempotently.
9. Omega returns the compact result through the original channel. Private worker
   prompts, raw transcripts, continuation identifiers, and chain-of-thought are
   not exposed.
10. Workflow success is announced only after the relevant independent evaluator
    validates the report and persists its verdict. Saving a report is not the
    same as validating it.

## 5. Abstract contracts and invariants

This section is normative. A concrete executor may use different internal
technology, but it must preserve these observable inputs, outputs, state
transitions, and safety rules.

### 5.1 Execution decision contract

`ExecutionRequest` is the input to Omega's shared decision boundary:

| Field | Type | Meaning |
| --- | --- | --- |
| `task` | non-empty string | Bounded user or coordinator goal. |
| `capability` | optional string | Requested worker capability such as `research`. |
| `explicit_worker_id` | optional string | Auditable override when the caller knows the worker. |
| `model_request` | `ModelRoutingRequest` | Provider-neutral requirements and optional preferences. |

`ModelRoutingRequest` contains a string-to-string requirements map and optional
preferred provider/model identifiers. Requirements may describe complexity,
latency, cost, privacy, context size, or tool support without binding the
subagent plugin to a provider.

`ExecutionPlanSelector.select(request) -> ExecutionPlan` returns:

| Field | Meaning |
| --- | --- |
| `mode` | `coordinator` or `subagent`. |
| `worker_id` | Selected worker for subagent mode; absent for coordinator mode. |
| `requested_capability` | Original capability request for auditability. |
| `model_request` | Unchanged provider-neutral request. |
| `model_route` | Optional provider/model decision returned by a router policy. |
| `reason` | Deterministic reason such as `capability` or `explicit_worker`. |

Invariants:

- A subagent plan must identify exactly one registered worker.
- A coordinator plan cannot identify a worker.
- Worker and model policies are independently replaceable.
- Model output is a request, not an authorization boundary.
- Registry, tool, context, and budget checks remain code-enforced.
- Failure to resolve a requested worker fails closed before session creation.

### 5.2 Specialist registry and selector contract

`SubagentDefinition` contains:

- stable `id`, name, and description;
- normalized capability set;
- bounded worker instructions;
- allowed tool categories;
- backend worker identifier.

The worker policy accepts `WorkerSelectionRequest(task, capability,
explicit_worker_id)` and returns one worker ID. An explicit ID is validated
against the registry. Otherwise, deterministic capability matching is used.

The selector must reject unknown workers, unsupported capabilities, duplicate
definitions, and empty selection results. Selection does not grant tools or
choose a provider.

### 5.3 Bounded context projection contract

`ContextProjection` is created in memory for each run and contains only:

- goal and task-relevant context;
- facts and constraints;
- artifact references;
- prior evidence with provenance;
- remaining work and required freshness checks;
- expected output and evaluation criteria;
- requested tool categories;
- workflow `scope_id`;
- execution budget.

Structured context must be valid JSON. Malformed JSON is rejected rather than
treated as free text. The rendered prompt must remain within the configured
context ceiling. No other session or unbounded coordinator history is inherited.

### 5.4 Session and run lifecycle contract

A session represents one worker-owned continuation context. A run represents one
invocation within that session.

```text
new task -> create session -> create running run
same task continuation -> validate owner/idle state -> create new running run
running run -> completed | partial | failed | cancelled | blocked | timed_out
idle session -> disposed
idle session -> purged
```

Rules:

- New independent work creates a new session.
- Resume must use the session's original specialist.
- Only one run may be active in a session.
- Every invocation receives a new run ID.
- Disposal removes private messages and continuation state but may retain run
  metadata; purge removes the complete session record.
- Active sessions cannot be disposed or purged.
- Worker processes may be disposable while session and audit records persist.

### 5.5 Persistence and durable outbox contract

The first implementation uses SQLite tables for sessions, runs, private
messages, and result delivery. Run completion and outbox insertion occur in one
transaction.

An outbox record contains a delivery ID, session/run IDs, bounded payload,
state, attempt count, timestamps, lease deadline, and acknowledgement time.
Delivery follows `pending -> leased -> acknowledged`; an expired lease can
return to pending. Repeated collection must not duplicate an acknowledged result.

The store must use transactional run creation to reject same-session overlap.
Private prompts and raw worker replies remain local and are excluded from
channel-visible inspection.

### 5.6 Tool policy and execution budget contract

The requested tool set must be a subset of the specialist allowlist. The
resolved set is retained in the prepared run, sent to the executor, and enforced
again at the worker boundary.

`ExecutionBudget` contains maximum context characters, output tokens, tool
calls, and elapsed seconds. A request may lower but never raise system ceilings.
The executor must enforce these limits or fail closed when enforcement is not
available.

Timeout does not imply safe rollback. A timed-out side-effecting run requires
inspection of partial effects before one smaller deliberate retry.

### 5.7 Prepared-run and executor contract

The executor receives a `PreparedRun` containing:

- validated worker definition;
- bounded context projection and rendered prompt;
- session and run IDs;
- optional continuation identifier;
- resolved tool categories;
- execution budget;
- Omega `ExecutionPlan`, including optional model route.

Conceptually:

```text
execute(PreparedRun) -> backend response
```

An executor must preserve worker identity, apply the prepared policy, respect
cancellation/timeouts, and return one structured response. It must not silently
broaden tools, context, budget, or model permissions. OpenClaw may continue using
the model configured for its worker until a model-routing adapter is explicitly
connected.

### 5.8 Structured result contract

`SubagentResult` contains:

| Field | Requirement |
| --- | --- |
| `agent_id`, `session_id`, `run_id` | Stable correlation identifiers. |
| `status` | `completed`, `partial`, `failed`, `cancelled`, `blocked`, or `timed_out`. |
| `summary` | Non-empty bounded conclusion. |
| `findings`, `artifacts` | Arrays of non-empty strings when present. |
| `evidence` | Non-empty string entries; required for completed and partial results. |
| `remaining_work` | Required when status is partial. |
| `error` | Bounded error or help request where applicable. |

Null or blank evidence is invalid. A partial result remains partial through
parsing, persistence, trace, delivery, and inspection. It may inform the next
decision but cannot count as successful completion.

### 5.9 Report saving and independent finalization

`save-subagent-report` validates the structural report schema and writes it
atomically. Its response explicitly states that independent validation has not
run.

The finalization path combines the saved report, coordination trace, and
independent live evidence. It runs the evaluator, derives the validated outer
status, and atomically persists the verdict. Only this verdict can support a
workflow-success claim.

The evaluator is a generic validation role in the architecture. A domain may
provide its own checks, but it is not automatically a specialist worker and does
not receive write permissions.

## 6. Implemented capabilities and hardening

The MVP and subsequent hardening already implement:

- deterministic specialist registry and capability selection;
- shared Omega execution-plan contract with independently pluggable worker and
  model policies;
- bounded JSON context projection and explicit handoffs;
- persistent session/run/message state and continuation;
- safe disposal and workflow-scope cleanup;
- same-session concurrency protection;
- durable leased/acknowledged result delivery;
- role-specific tool policies;
- bounded context, output, tool-call, and elapsed-time budgets;
- accurate terminal outcomes, including partial evidence and remaining work;
- strict non-empty evidence validation;
- schema-valid report persistence separated from independent finalization.

The model-routing policy itself is not implemented in this task. The shared
contract and extension point are implemented so OMEGA-376 can attach the router
without changing the subagent contract.

## 7. Security and operational model

The current OpenClaw adapter uses a token-authenticated Gateway. In Docker, the
Gateway token is injected by a local proxy before the agent environment is
scrubbed. Provider keys, channel tokens, and Gateway secrets are configuration;
they must not be stored in prompts, SQLite records, documentation, or source
control.

Worker isolation combines separate identities/workspaces, bounded projections,
and per-agent policies. Native workers should strengthen this with isolated
processes or containers, explicit filesystem roots, direct budget enforcement,
and standard cancellation/reconciliation.

Users see selected worker, session/run identifiers, lifecycle state, and compact
results. They do not see private worker transcripts or chain-of-thought.

## 8. Validation evidence

Validation is performed at three levels:

1. Unit and contract tests cover execution planning, worker selection, context
   validation, persistence/migration, continuation, cleanup, tool restrictions,
   budgets, outcomes, concurrency, outbox delivery, evidence validation, partial
   results, and report finalization.
2. Deterministic Docker integration uses a fake Gateway to test delegation,
   resume, structured context, timeout feedback, persistence, delivery, and
   cleanup without external credentials.
3. Live integration has exercised Telegram, OpenRouter, an authenticated
   OpenClaw Gateway, and all three specialist definitions end to end.

Exact test counts and dates should be generated from the reviewed commit rather
than treated as permanent architectural properties.

## 9. Current boundaries and risks

- OpenClaw remains the only real executor currently implemented.
- The shared model-routing policy is an extension point; OMEGA-376 integration
  remains separate work.
- Selection is deterministic rather than ranked.
- In-flight worker execution is not recovered after Omega process failure.
- Searchable history, recursive delegation, child-to-child messaging, broad
  parallel plans, and a dashboard remain outside this proposal.
- Workflow cleanup remains explicit until Omega exposes plugin teardown events.

The principal risks are adapter behavior leaking into the Omega contract and
model output being mistaken for authorization. Backend-neutral contracts and
code-enforced registry, tool, budget, and isolation checks mitigate those risks.

## 10. Recommended integration path

1. Extract backend-neutral subagent models and lifecycle logic into a dedicated
   plugin package while retaining the Omega execution-decision contract.
2. Keep `ExecutionPlanSelector` as the shared boundary for worker and future
   model policies.
3. Define and test the native executor protocol around `PreparedRun`,
   continuation, cancellation, and `SubagentResult`.
4. Retain OpenClaw as an optional compatibility adapter.
5. Implement isolated native Omega workers.
6. Run identical contract tests against fake, OpenClaw, and native executors.
7. Integrate the OMEGA-376 router by supplying a model-selection policy, without
   modifying worker selection.
8. Add startup reconciliation and deterministic lifecycle acknowledgements.

Only after these foundations are stable should Omega add richer ranking,
searchable history, controlled parallel plans, or more specialist definitions.

## 11. Approval requested

We request approval to:

- accept persistent specialist delegation as an Omega plugin capability;
- accept the current MVP and hardening as evidence that the contract is viable;
- accept the shared execution-decision abstraction as the integration boundary
  for subagent and future model-routing policies;
- proceed with backend-neutral extraction and a native Omega executor;
- keep OpenClaw optional and outside mandatory core dependencies;
- require contract tests and live-channel validation for future executors.

Approval does not commit Omega to OpenClaw, recursive agents, a cybersecurity
specialist, or an expanded core. It authorizes preservation of the validated
contract while replacing the MVP-specific execution dependency.

## Conclusion

The MVP demonstrates that Omega can coordinate persistent specialists without
merging their tools, histories, or execution environments into the coordinator.
The proposal now defines the concrete contracts needed by implementers and the
shared decision boundary needed by both delegation and future model routing.

Omega should adopt the persistent-subagent contract, not the current executor.
That distinction preserves the proven behavior while allowing native workers,
future routing policies, and the small extensible core to evolve independently.
