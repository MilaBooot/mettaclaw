# Oma monitoring handoff

Last updated: 2026-10-05

## Purpose and scope

The project is an authenticated operational and rule-based security monitoring
surface for Oma. This branch now includes phase 1 status/live logs, phase 2
fixed-target Start/Stop/Restart controls, and an initial optional Falco
JSON-event display with prototype rules. It makes no changes to Oma reasoning,
Telegram behavior, or deployment workflows. No AI/ML is used.

Still deferred: automatic containment, Docker Pause, host/network isolation,
production Falco deployment/tuning, centralized retention/dashboards, multiple
operator roles, and production deployment.

## Repository and base

- Upstream: `https://github.com/iCog-Labs-Dev/Omega.git`
- Collaboration fork: `https://github.com/MilaBooot/mettaclaw.git`
- Branch: `feat/oma-monitor-phase1`
- Base branch: upstream `telegram`
- Base commit: `2aaa207d117254845372b0bf6e0ed36f297c5217`
  (`ci: do not let the untried publisher run the first production release`)
- The fork's `telegram` was verified as an ancestor of this base and was 973
  commits behind at the time of review. The feature must not be rebased onto
  that stale ref.

No push, PR, deployment, production connection, or release was performed.

## Review findings verified

- `scripts/omega start` runs `docker rm -f omega` before `docker run`; it is a
  destructive recreate workflow and is unsuitable for a future Start action.
- Telegram `/kill` calls `os._exit(0)` inside the agent. `/pause` adds/removes a
  chat ID from an in-process paused set. Neither is an external Docker lifecycle
  control.
- `channels/auth.py:is_auth_enabled()` logs a warning and caches auth as disabled
  when its proxy status request fails. Monitor auth is completely independent
  and fails closed during configuration and on every HTTP request.
- Production and staging workflow comments say deployment moved to
  `singnet/Omega_CustomBots`; this branch was not treated as the deployed-system
  source of truth and the workflows were not changed.

## Implementation decisions

- Flask + Waitress and Docker SDK dependencies live only under `monitor/`.
- HTTP Basic auth avoids secrets in URLs, application-managed browser storage,
  and logs. It is appropriate only on localhost, through SSH, or behind HTTPS.
  Missing credentials fail closed and passwords shorter than 12 characters are
  rejected; no development/default login exists.
- Container name is startup configuration; status/log APIs reject all query
  parameters and expose no generic Docker operation.
- Server-sent events provide timestamped log streaming. The backend reattaches
  after stream termination, Docker failure, a missing container, or recreation.
  For a stopped target it sends retained history once and one waiting notice,
  then polls quietly until the container starts; normal restart gaps do not
  flood the browser with reconnect notices.
- Docker log lines receive best-effort credential redaction before SSE encoding.
  The UI assigns records with `textContent`, never HTML parsing.
- No shared server log buffer exists. Partial records are bounded, and the
  browser retains at most 1,000 records.
- Lifecycle routes expose only Start, Stop, and Restart for the startup-configured
  target. They require Basic auth, POST JSON, a random CSRF token in a custom
  header, same-origin browser metadata, explicit UI confirmation, and a lock
  that prevents concurrent actions. Results are audit logged without secrets.
- Start calls Docker's start operation on an existing container. It does not
  create/recreate a missing container and never calls `scripts/omega start`.
- Docker Pause was excluded because freezing a potentially compromised process
  is not reliable containment; Stop is the current emergency action.
- Optional runtime events are read from a server-configured Falco JSON-lines
  file, filtered to the configured container, redacted, and sent through an
  authenticated SSE endpoint. The browser retains at most 500 signals.
- Prototype Falco rules cover outbound connects, namespace/mount operations,
  shell/network-tool execution, and Docker-socket access. They are signals, not
  breach verdicts, and require staging profiling and allowlists.
- Grafana/Axiom/Loki are not integrated. They may later store/query events, but
  they do not replace the runtime sensor or authorization/control boundary.
- `.gitattributes` pins the WSL/Docker launchers (`scripts/omega`,
  `entrypoint.sh`, and `proxy/nginx.sh`) to LF endings. Without this, Windows
  `core.autocrlf=true` produced `/usr/bin/env: bash\r: No such file or
  directory` in WSL.

## Validation record

Executed on Windows with Python 3.11.9:

- `python -m compileall -q monitor`: passed.
- `monitor\.venv\Scripts\python -m pytest monitor\tests -q`: **37 passed, 3
  skipped**. The skips are the two opt-in real Docker tests and the opt-in
  combined acceptance test, executed separately in WSL as recorded below.
  Coverage includes fail-closed configuration/authentication, fixed-target API
  behavior, all required Docker states, safe text rendering, recognizable-secret
  redaction, bounded partial lines, timestamp/follow options, stream recovery,
  and container recreation using mocked Docker clients.
- A request through the real Flask status route and real Docker SDK returned
  HTTP 200 with `state: docker-unavailable`, no internal error detail, and
  `agent_healthy: null`: passed.
- Disposable-container integration: **passed in WSL on 2026-10-04** after Docker
  Desktop WSL integration was enabled. An `alpine:3.20` container named
  `oma-monitor-test` was discovered and its repeating timestamp/test records
  were shown through the authenticated live-log page. The disposable container
  was then removed. Oma itself was not started and no Telegram/model credentials
  were used. Stop/restart/recreation behavior remains covered by mocked tests
  rather than this manual check.
- The earlier Windows-host attempt returned `docker-unavailable` correctly when
  Docker Desktop's engine was inaccessible; this failure path was also verified.
- Real lifecycle integration in WSL: **passed**. A uniquely named disposable
  `alpine:3.20` container was stopped, started, and restarted through
  `DockerBackend.perform_action`; all reported states matched, and the test
  container was removed afterward.
- Real no-credentials Oma monitor integration: **passed for the cached image**
  `singularitynet/omegaclaw:latest`. After supplying the older image's actual
  `/PeTTa/repos/OmegaClaw-Core` paths and required TTY, Oma stayed running and
  emitted real logs. Oma and a deterministic mock-service container were placed
  on `oma-monitor-test-net`; Oma connected to `omega-mocks` on both 9765 and
  9766, produced `CHARS_SENT` records, and logged zero `Network is unreachable`
  errors. The monitor's opt-in integration passed two tests against it:
  status/log retrieval and Stop/Start/Restart.
- Current-checkout image build: **passed** as `omega:monitor-live` on
  2026-10-05 after enforcing LF line endings for the executable shell files.
  A live OpenRouter/Telegram runtime still requires the operator to export the
  real credentials in the same WSL shell that launches `scripts/omega`.
- Combined acceptance against the real current-source `omega` container:
  **passed on 2026-10-06** (`1 passed in 3.95s`). It covered authenticated page
  and APIs, real Docker status/logs, fixed-target rejection, Stop/Start/Restart,
  controlled Falco-format outbound events, other-container filtering, and
  redaction, then restored Oma's initial running state.
- Falco 0.45 semantic validation: **passed on 2026-10-06**
  (`/rules/oma_rules.yaml: Ok`) using the official Falco image and WSL2. This
  validates rule semantics only, not kernel capture.
- Falco runtime deployment: **not run**. The required privileged launch was not
  approved. Falco's official quickstart also excludes Docker Desktop; a valid
  syscall end-to-end test should run Oma and Falco on the same native Linux
  kernel following TESTING.md.

## Next milestone

Review the lifecycle controls and tune the Falco prototype on a staging Linux
host. Establish Oma's expected provider/DNS destinations and processes, convert
the alert-all outbound rule into a reviewed allowlist, validate false-positive
volume and dropped-event metrics, and choose durable audit/security-event
retention. Automatic stop or network isolation on an alert must not be enabled
until false-positive and recovery procedures are approved.
