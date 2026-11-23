# Cybersecurity knowledge delivery A/B evaluation

## Decision summary

Omega's bounded cybersecurity knowledge delivery worked and produced a small
positive result, but this six-run evaluation does not yet justify enabling the
feature by default in production.

- Treatment fixed **9 of 12 seeded findings (75.0%)**.
- Control fixed **8 of 12 seeded findings (66.7%)**.
- Treatment produced the only fully remediated run: **1/3 versus 0/3**.
- Both conditions preserved **9/9 required functionality checks (100%)**.
- Neither condition produced a valid automatic report: **0/3 versus 0/3**;
  all six reports needed a report-only correction.
- Treatment startup embedded 27,882 records; one observed import took about
  31 minutes.

The result demonstrates technical feasibility and a narrow effectiveness
signal. The observed advantage was one additional fixed finding across twelve
opportunities, with only three runs per condition. The recommended decision is
to keep the capability experimental or feature-gated, reduce its indexing and
coordination cost, and repeat the evaluation at larger scale.

## Evaluation design

The experiment compared the same Research, Coding, and Reviewer subagents in
two conditions:

- **Control:** no cybersecurity knowledge references were supplied.
- **Treatment:** each bounded delegation could receive retrieved references
  from the staged cybersecurity library.

Both conditions used the same vulnerable `omega-security-lab:/workspace`
target, model, evaluation prompt, specialist tool policies, execution budgets,
required functionality, and independent verifier. Research was read-only,
Coding was the designated writer, and Reviewer was read-only. The host, Docker
daemon, external systems, and production credentials were out of scope.

Before accepted runs, the reset target was expected to have all four `LAB-*`
checks failing and all three `FUNC-*` checks passing. Baseline JSON snapshots
were retained for five of six accepted runs. `treatment-01` followed the same
reset procedure, but its baseline JSON was not retained; this is an evidence
limitation. Every accepted run has a final live-verification snapshot and a
coordination trace.

The independent evaluator compared each final report with fresh live checks
and trace evidence. Automatic report failures were preserved. Corrected reports
were generated without additional target remediation so execution effectiveness
and reporting reliability could be evaluated separately.

## Accepted and excluded runs

Accepted treatment runs:

- `treatment-01`
- `treatment-02`
- `treatment-03`

Accepted control runs:

- `control-03`
- `control-04`
- `control-05`

Excluded runs were retained locally but did not contribute to the comparison:

- `control-01`: live verification was collected after a later target reset.
- `control-02`: its baseline already contained treatment remediations; all
  four `LAB-*` checks passed before control execution.
- Earlier smoke runs: provider, schema, or setup failures made them unsuitable
  for an effectiveness comparison.

## Comparative results

| Metric | Treatment | Control |
|---|---:|---:|
| Clean accepted runs | 3 | 3 |
| Fully remediated runs | 1/3 (33.3%) | 0/3 (0%) |
| Seeded findings fixed | 9/12 (75.0%) | 8/12 (66.7%) |
| Required functionality passed | 9/9 (100%) | 9/9 (100%) |
| Valid automatic reports | 0/3 | 0/3 |
| Corrected reports matching live state | 3/3 | 3/3 |
| Worker delegations | 18 | 19 |
| Completed worker results | 8/18 (44.4%) | 5/19 (26.3%) |
| Knowledge references supplied | 54 | 0 |

Per-finding success:

| Finding | Treatment | Control |
|---|---:|---:|
| `LAB-001`: required file permissions | 1/3 | 0/3 |
| `LAB-002`: debug configuration disabled | 3/3 | 3/3 |
| `LAB-003`: synthetic secret not exposed | 3/3 | 3/3 |
| `LAB-004`: unnecessary service disabled | 2/3 | 2/3 |

Per-run outcome:

| Run | Fixed findings | Functionality | Validated status |
|---|---:|---:|---|
| `treatment-01` | 4/4 | 3/3 | completed |
| `treatment-02` | 3/4 | 3/3 | partial |
| `treatment-03` | 2/4 | 3/3 | partial |
| `control-03` | 2/4 | 3/3 | partial |
| `control-04` | 3/4 | 3/3 | partial |
| `control-05` | 3/4 | 3/3 | partial |

The treatment advantage was concentrated in `LAB-001`. Debug disabling and
secret removal were identical across conditions, and each condition disabled
the unnecessary service in two of three runs. This is a narrow benefit rather
than broad evidence that knowledge retrieval improves every security task.

## Knowledge-delivery evidence

Treatment traces recorded 54 supplied references across 18 delegations.
Completed workers cited:

- `assessment-and-evidence-contract.md`
- `authorization-and-agent-boundaries.md`
- `container-isolation-and-hardening.md`
- `evidence-integrity-and-reproducibility.md`
- `linux-host-assessment.md`

Control traces supplied and used no cybersecurity references. This confirms
that knowledge retrieval was active only in the intended condition.

## Reliability findings

1. **Every automatic report required correction.** Failures included missing
   template fields, string findings instead of structured objects, swapped
   identities, unsupported completion claims, inaccurate dispositions, and
   overstated overall status.
2. **Tool budgets were inefficient.** Repeated reads, schema discovery, and
   unsupported directory-mode attempts exhausted 12- and 20-call budgets.
3. **Worker result validation remained fragile.** Useful side effects were
   sometimes followed by `invalid_result: invalid or missing status`.
4. **Retry and phase policies were not consistently enforced.** Several runs
   exceeded the intended single retry; `control-05` also ran Coding after
   Reviewer.
5. **Scope expanded beyond the benchmark.** Some workers changed server
   disclosure and request-size behavior before completing all required checks.
6. **Manual orchestration was still needed.** Humans advanced stalled parent
   workflows or requested report-only corrections. No human modified the
   target, so final security states remain attributable to agent actions.
7. **Treatment added substantial startup cost.** The implementation imported
   the wider 27,882-record collection rather than only the six staged
   cybersecurity documents.

Trace wall-clock duration, including orchestration stalls but excluding
startup import, had a median of approximately 28.9 minutes for treatment and
19.1 minutes for control.

## Security review of evidence

A local credential-pattern scan covered 98 raw evidence files and found no
Telegram bot token, OpenRouter key, Gateway credential, Bearer credential, or
generic API-key pattern. The synthetic lab credential is intentionally fake
and is not production data.

Raw logs and full traces are not included in the reviewable source change.
They are noisy, contain operational prompts and URLs, and provide no additional
claim beyond the sanitized summary. They remain local, with SHA-256 hashes in
the machine-readable summary. The tracked evidence consists of this report and
[`cybersecurity-knowledge-ab-evaluation-summary.json`](cybersecurity-knowledge-ab-evaluation-summary.json).

## Interpretation and next steps

The evaluation supports keeping the knowledge-delivery implementation for
further work, but not enabling it by default yet. Recommended next steps are:

1. Validate `report-template.json` programmatically before persistence.
2. Validate worker result JSON before accepting a terminal result and return
   bounded schema-repair guidance rather than starting an unrestricted retry.
3. Require Reviewer to call `omega_lab_verify {}` first and allocate budgets
   by phase.
4. Enforce one retry and a strict Research -> Coding -> Reviewer transition.
5. Prevent optional scope expansion until required findings are resolved.
6. Build or reuse a hash-addressed cybersecurity-only index instead of
   embedding all 27,882 records at every clean treatment startup.
7. Repeat at least 10 randomized runs per condition after hardening, reporting
   confidence intervals, token/tool usage, provider failures, startup cost,
   and manual-intervention rate.

The detailed execution model remains in
[`container-security-subagent-full-cycle.md`](container-security-subagent-full-cycle.md),
and the reproducible lab commands remain in
[`evals/container_security/README.md`](../evals/container_security/README.md).
