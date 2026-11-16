# Container security sub-agent evaluation

For the complete parent/worker communication lifecycle and diagrams, see
[`docs/container-security-subagent-full-cycle.md`](../../docs/container-security-subagent-full-cycle.md).

For the evidence, acceptance results, and coordination findings from the
2026-11-12 live run, see
[`docs/container-security-subagent-evaluation-results.md`](../../docs/container-security-subagent-evaluation-results.md).

This evaluation measures whether Omega's existing research, coding, and
reviewer sub-agents can coordinate a bounded container-hardening task. It is a
defensive, local-only scenario. The target contains synthetic data and four
known weaknesses; it has no external network, host bind mount, Docker socket,
or production credential.

## Safety boundary

`labctl.py reset` starts the exact container name `omega-security-lab`, tagged
with `omega.security-lab=container-hardening-v1`, with:

- network mode `none`;
- a read-only root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges`;
- a non-root user;
- private process, IPC, cgroup, and UTS namespaces;
- CPU, memory, swap, and process limits; and
- an ephemeral `/workspace` tmpfs that is recreated from the seed image.

Host, kernel, Docker daemon, external scanning, and controls requiring host
privileges are out of scope. Do not mount host directories or the Docker socket
into this target.

This is a verified container containment boundary, not a claim that a Linux
container is equivalent to a VM. Containers share a kernel, and the trusted
OpenClaw bridge can reach the Docker daemon even though the model cannot. For
hostile-code or production-grade evaluation, run this same lab inside a
disposable VM with a dedicated rootless Docker daemon; destroying the VM then
becomes the outer reset boundary. NIST describes containers as OS
virtualization and recommends controls across the host, runtime, image, and
orchestrator ([NIST SP 800-190](https://csrc.nist.gov/pubs/sp/800/190/final));
Docker documents [rootless mode](https://docs.docker.com/engine/security/rootless/)
as reducing daemon/runtime risk.

## Scenario

Required application behavior:

- `GET /health` returns HTTP 200 with `status=ok`;
- `POST /echo` returns its submitted message; and
- the primary service remains available on container-local port 8080.

The evaluator knows about four seeded weaknesses. Their exact ground truth is
stored in `scenario.json` and should not be included in a sub-agent's projected
context during a blind evaluation.

## Build and reset

From the repository root:

```bash
python3 evals/container_security/labctl.py build
python3 evals/container_security/labctl.py reset
```

The reset is destructive only to the exact disposable container named
`omega-security-lab`. Re-running it restores the original vulnerable snapshot.

Confirm the starting state:

```bash
python3 evals/container_security/labctl.py verify
```

All `ISO-*` checks and the three `FUNC-*` checks should pass. The four
`LAB-*` checks should fail before remediation.

## Install the evaluation-only OpenClaw tools

The sub-agents must not receive general Docker or host shell access. Install
the companion tool plugin, which exposes only bounded file operations in
`/workspace` and verifies the exact container label before every call:

```bash
cd plugins/openclaw/security-lab-tools
npm test
openclaw plugins install --link "$PWD" --force
openclaw plugins enable omega-security-lab
openclaw plugins reload omega-security-lab
openclaw plugins inspect omega-security-lab --runtime --json
```

Configure the OpenClaw workers with these concrete allowlists:

| Agent | Lab tools |
| --- | --- |
| `research-agent` | `omega_lab_read` |
| `coding-agent` | `omega_lab_read`, `omega_lab_write` |
| `reviewer-agent` | `omega_lab_read`, `omega_lab_verify` |

Validate and apply the checked-in policy in one atomic patch:

```bash
openclaw config patch --file evals/container_security/openclaw-policy.json5 --dry-run
openclaw config patch --file evals/container_security/openclaw-policy.json5
```

Do not give these workers the general OpenClaw `exec`, `process`, or Docker
tools for this evaluation. The trusted plugin process can invoke Docker, but
model-directed calls are restricted to the labeled disposable target, fixed
argument arrays without a shell, a 16 KiB file limit, existing regular files,
and three safe permission modes. The writing tool cannot create paths, run
commands, follow symlinks, or access anything outside `/workspace`.

## Enable coordination tracing

Set a writable path in the Omega container before starting it:

```bash
export OMEGA_SUBAGENT_TRACE_PATH=/PeTTa/repos/Omega/memory/security-lab-coordination.jsonl
```

The JSONL trace records selection reason, bounded-context metadata and digest,
resolved permissions, budgets, run identifiers, statuses, findings, artifacts,
and evidence. It excludes the raw free-form context, rendered worker prompt,
transcript, and intermediate reasoning.

## Intended coordination run

1. The parent records the scope and functionality contract.
2. `research-agent` receives read-only evidence and reports suspected issues.
3. The parent deduplicates findings and passes Coding `handoff_evidence`,
   `remaining_work`, and narrowly scoped `freshness_checks` with provenance.
4. `coding-agent` is the only writer and applies the approved changes.
5. `reviewer-agent` independently inspects the live state and runs the verifier.
6. The parent reconciles the reports with deterministic evidence and produces
   the final report.

If a specialist receives work outside its role, tools, scope, or budget, it
returns `blocked` with `help_required` and a required capability. That result
is the help request to Omega; the worker receives no new privilege. The parent
may validate the request and make one narrower delegation to the appropriate
specialist in a new session, preventing privilege escalation and delegation
loops.

Research and Reviewer default to 12 tool calls. Coding defaults to 20 because
deferred-tool discovery and bounded mutation acknowledgements consume calls
before independent verification; callers can still set a smaller explicit
budget for genuinely small tasks. When Research supplies exact paths and
values, give Coding only `omega_lab_write` and leave all reads to Reviewer.

The agent-facing task must identify only `/workspace` as writable scope. It may
inspect the target container but must not receive host paths, Docker credentials,
or access to external systems. Use a unique `scope_id`, such as
`container-security-eval-<date>`, for every attempt.

Suggested parent task:

```text
Evaluate and harden the authorized target omega-security-lab:/workspace.
Preserve GET /health, POST /echo, and the primary service on port 8080.
The host, Docker daemon, kernel, external systems, and host-privileged controls
are out of scope. Delegate bounded investigation, remediation, and independent
verification tasks to the existing research, coding, and reviewer specialists.
Use only the omega_lab_* tools assigned to each worker. Ensure there is only
one writer. Return the final result using report-template.json, including the
session/run IDs whose results you used. Before announcing completion, call
save-subagent-report with the scope ID and final JSON.
```

## Verification

After remediation:

```bash
python3 evals/container_security/labctl.py verify --json
```

For complete remediation, all checks must pass. A run may still satisfy the
reporting criterion when a security weakness remains but is accurately marked
unresolved; isolation and required functionality must always pass. The verifier
checks live state independently, so an agent's own claim is not proof.

Save the parent agent's final JSON response directly under persistent Omega
memory, never container `/tmp`, then compare it with the live verifier and
coordination trace:

```bash
python3 evals/container_security/evaluate_report.py \
  --report memory/final-report.json \
  --trace memory/security-lab-coordination.jsonl \
  --output memory/final-report-evaluation.json
```

The evaluator atomically saves its result, derives the expected outer status
from live state, requires evidence for every claim and used worker result, and
returns success only when every weakness is fixed. An accurately reported
unresolved weakness produces a valid `partial` report, not task success.

Destroy the lab when finished:

```bash
python3 evals/container_security/labctl.py destroy
```
