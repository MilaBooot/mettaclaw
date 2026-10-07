# Oma monitoring handoff

Last updated: 2026-10-07

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

- Original source upstream: `https://github.com/iCog-Labs-Dev/Omega.git`
- Intended monitor PR destination (operator confirmed):
  `https://github.com/iCog-Labs-Dev/OmegaPulse`
- Collaboration fork: `https://github.com/MilaBooot/mettaclaw.git`
- Branch: `feat/oma-monitor-phase1`
- Original source base branch: upstream `telegram`; the OmegaPulse PR base is
  not yet confirmed and must not be assumed to be `telegram`.
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
- Earlier WSL testing required LF endings for Oma's shell launchers to avoid
  `/usr/bin/env: bash\r: No such file or directory`. The verified pushed
  checkpoint does not contain the previously referenced root `.gitattributes`.
  The monitor now pins its own shell helpers to LF in `monitor/.gitattributes`;
  the monitor-only PR does not modify Oma's launchers.

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
- Earlier WSL Falco runtime attempt: **not run**. The required privileged launch was not
  approved. Falco's official quickstart also excludes Docker Desktop; a valid
  syscall end-to-end test should run Oma and Falco on the same native Linux
  kernel following TESTING.md.

### Native Ubuntu follow-up — 2026-10-07

#### Initial attempt (blocked)

- Read this handoff and `monitor/TESTING.md` completely before testing. The
  checkout was clean on `feat/oma-monitor-phase1`; existing source was preserved.
- Host preflight: native Ubuntu kernel `7.0.0-14-generic`, x86_64;
  `/sys/kernel/btf/vmlinux` and `/sys/kernel/tracing` exist. These are preliminary
  checks only; eBPF probe loading and syscall capture have not been validated.
- Docker CLI is installed (`29.8.2`, default context), but both the sandboxed
  and approved elevated `docker version` attempts failed with permission denied
  on `/var/run/docker.sock`. The subsequent `sudo -n docker version` approval
  request was rejected and did not execute. The daemon version, images, and
  existing containers could therefore not be inspected.
- **Real Falco/eBPF integration: blocked before sensor launch.** No test
  containers were created, stopped, restarted, or removed. No privileged Falco
  process was launched and no real Falco JSON or monitor SSE delivery was
  verified. Previous WSL results remain historical results, not native-Linux
  capture evidence.
- `python3 -m compileall -q monitor`: **passed** on Python 3.14.
- Regression rerun: **blocked by missing dependencies**, not an application
  assertion failure. `python3 -m pytest monitor/tests -q` failed because pytest
  is absent; unittest discovery also encountered missing pytest, Flask, and
  Docker SDK imports. Creating an isolated environment under `/tmp` failed
  because Ubuntu's `python3.14-venv`/ensurepip support is absent. No packages
  were installed and no monitor HTTP server was started.
- Resume prerequisites: provide authorized local Docker access (including the
  dedicated test sensor's privileged launch), install Python venv support, and
  install `monitor/requirements-dev.txt` in an isolated environment. Then inspect
  existing resources before creating a disposable Oma instance, run sections
  A/B/C of `TESTING.md` with the native checkout path
  `/home/mila/Documents/Omega`, and verify all four expected Falco rules from
  actual syscall output through the authenticated monitor. Do not remove or
  control an existing `omega` until its disposable status is established.
- No push, deployment, or PR was performed.

#### Retry after Docker-group activation (passed within approved scope)

- Plain `docker` worked outside the Codex sandbox after the operator joined the
  Docker group and rebooted. Docker Engine/client: `29.8.2`; active Docker group
  GID: `973`. **No sudo commands were used.** Initial inspection found no
  containers, images, custom networks, or volumes to overwrite.
- Built the unchanged current-checkout Dockerfile as `omega:monitor-test`.
  The first attempt timed out downloading the CPU PyTorch wheel; a cached retry
  **passed** without changing dependencies or the Dockerfile. Image ID:
  `sha256:ecdc0c47e95009485a8440c83347661f636300e9fd6951ac6aa95e9078d78eeb`
  (7,929,862,199 bytes).
- Host Python venv support remains absent. Built an isolated
  `oma-monitor:test-runner` image using Python 3.14 and
  `monitor/requirements-dev.txt`; tests and the monitor ran as UID/GID
  `1000:1000`, with supplementary group `973` only where Docker access was
  needed. No host Python/system packages were installed.
- Regression suite: **37 passed, 3 skipped in 0.41s**. The three opt-in tests
  were then run separately against disposable current-source Oma:
  **3 passed in 5.89s**, covering real Docker status/logs, Stop/Start/Restart,
  and combined authenticated acceptance with controlled Falco-format events.
- Created disposable `omega` and non-root `omega-mocks` on
  `oma-monitor-test-net`, with volume `omega-monitor-test-memory`. Oma used
  `provider=Test`, `commchannel=test`, local embeddings, and offline model
  loading; no Telegram/model-provider credentials were supplied. Logs confirmed
  connections to both mock ports (9765 and 9766), 51 `CHARS_SENT` records at
  evidence capture, zero `Network is unreachable` errors, and zero Python
  tracebacks. These are runtime/log checks, not an agent-health assertion.
- Falco 0.45.0 semantic validation: **passed**. With the operator's explicit
  approval, launched the temporary privileged `oma-falco-test` using
  `engine.kind=modern_ebpf`, the repository's actual rules, and container plugin
  `0.7.4` on the same native Ubuntu kernel as Oma. File output was written to
  `/tmp/oma-falco-native-20261007/oma-events.jsonl`.
- **Real syscall-to-monitor integration: passed for all three approved
  indicators.** Ran a shell, attempted a TCP connect to `127.0.0.1:9`
  (connection refused), and called `unshare(CLONE_NEWNS)` (denied, errno 1) as
  Oma's unprivileged UID/GID `65534:65534`. Each corresponding Falco rule
  produced a `source: syscall` record with the controlled marker
  `oma-native-20261007` and Oma's actual container ID. This validates detection
  of attempts; it does not claim successful namespace manipulation.
- The actual Waitress monitor on `127.0.0.1:8765` returned HTTP 401 without
  credentials and HTTP 200 with temporary test credentials. All three marked
  kernel events reached its authenticated HTTP security SSE endpoint, with the
  controlled `token=` value redacted. No fabricated JSON was used for this
  native verification. Browser rendering was not manually checked.
- **Docker-socket indicator: skipped at the operator's explicit request.** No
  root exec or socket-file creation was performed inside Oma; its real capture
  remains unverified. The production rule remains unchanged.
- Falco's graceful shutdown reported 122 detections: 38 outbound, 76
  namespace/mount, and 8 shell/network-tool signals. Drop monitoring reported
  zero occurrences and zero actions. Startup itself generated many prototype
  signals, reinforcing the need to profile and tune expected behavior. This
  short test is not a production event-loss or false-positive assessment.
- Saved redacted evidence:
  [`validation/native-linux-2026-10-07.json`](validation/native-linux-2026-10-07.json).
  Full local build, runtime, verification, and Falco logs remain under `/tmp`;
  those temporary files will not survive a reboot.
- All four test containers (`omega`, `omega-mocks`, `oma-monitor-native`, and
  `oma-falco-test`) were stopped after testing. Images, stopped containers,
  network, and memory volume were retained for reuse; no pre-existing resources
  were removed. Temporary monitor credentials are in the mode-0600 file
  `/tmp/oma-monitor-native.env` and were not printed or saved in the repository.
- Existing handoff edits were preserved. No push, deployment, or PR was
  performed.

### Live OpenRouter/Telegram preparation — 2026-10-07

- The operator requested a real OpenRouter/Telegram run and a chosen browser
  password. Added `monitor/scripts/live.sh` with hidden local credential prompts,
  separate channel/browser authentication, and `start`, `monitor`, `resume`,
  `signals`, and `stop` operations. Tagged the existing built image as
  `omega:monitor-live`; no image rebuild or application behavior change was made.
- The launcher preserves the mock target by renaming it only when its known
  test label matches, uses a separate live memory volume, and keeps Falco events
  under the Git-ignored `.oma-monitor-local/` directory. It uses plain Docker
  throughout and the previously approved temporary privileged Falco setup.
- Added a durable non-root indicator helper, replacing the reliance on a
  `/tmp` script for future live runs. `bash -n` passed; the helper was executed
  in a disposable UID/GID `65534:65534` container and produced the expected
  refused connect and denied namespace attempt. No Docker-socket indicator was
  added or run.
- **Live provider/channel verification is pending local credential entry.**
  No OpenRouter key, BotFather token, channel auth secret, or chosen browser
  password was supplied to the agent. The new live launcher has not been run;
  no real provider/channel traffic or browser visual test is claimed. The earlier
  native Falco results remain the evidence for capture and authenticated SSE.
- Local launch instructions are in `monitor/README.md`. No push, deployment, or
  PR was performed. Existing handoff edits and validation evidence were preserved.

### Final scope and live review — 2026-10-07

- Verified the actual remote branch tip using `git ls-remote`:
  `b4314ca88941dd2cbeafbc6b6649b1154360f9ad`, matching local HEAD. That checkpoint
  adds only `monitor/` files relative to base `2aaa207`.
- The operator's OpenRouter/Telegram-configured `omega`, `oma-falco-live`, and
  `oma-monitor-live` are running. A live sample contained 280 outbound Notices,
  including 257 attributed to nginx, consistent with Oma's proxy traffic. The
  prototype reports every connect attempt; no allowlist or breach verdict was
  introduced. Provider response correctness/agent health are not asserted.
- Replaced the machine-specific 190-line all-in-one setup with a 69-line
  independent monitor launcher and a separate 24-line optional Falco launcher.
  The original setup script is preserved locally under the Git-ignored
  `.oma-monitor-local/` directory for reference, not included in the PR.
- Added a standalone `monitor/Dockerfile` that builds using only the monitor
  folder. Other users run Oma normally, then start monitoring separately; the
  monitor needs no provider/channel credentials and never starts/recreates Oma.
  README/TESTING instructions now use portable paths and a dedicated disposable
  acceptance target, avoiding lifecycle tests against the live bot.
- Fixed review findings: UTF-8 authentication/CSRF comparisons now reject invalid
  non-ASCII input without HTTP 500; the Falco reader waits for complete JSON
  lines, reports read-permission failures, and recovers after file replacement.
  Added focused regression coverage. The browser explains that outbound Notices
  include ordinary provider/channel connections.
- Validation: standalone image build **passed**; **44 regression tests passed,
  3 opt-in tests skipped** (`0.46s`); the three opt-in real Docker/combined tests
  then **passed** on a temporary disposable Python target (`41.95s`). This
  validation did not stop/restart the live credential-based Oma container.
- Generated the three non-root indicators in live Oma with marker
  `oma-monitor-check-1791382803`. All three Falco records matched its actual ID
  and `source: syscall`, and reached authenticated HTTP SSE on both the running
  user monitor and the rebuilt standalone monitor tested on port 18765. The
  demonstration token was redacted. Docker-socket capture remains skipped as
  previously requested; no successful escape is claimed.
- Removed only the two temporary review containers. The operator's three live
  containers remain running; the updated image was not substituted into the
  user's monitor. To adopt the updated monitor while reusing its original sensor
  directory, set `OMA_MONITOR_EVENTS_DIR="$PWD/.oma-monitor-local/falco-events"`
  and run `bash monitor/scripts/live.sh monitor` from the repository root.
- The proposed PR can contain **only `monitor/`**. The one-line root `.gitignore`
  addition protects this machine's original live event directory and can remain
  a local unstaged change. No source outside monitor is needed for the feature.
- No commit, push, deployment, or PR was performed during this review. Push and
  PR creation await operator approval and confirmation of the destination repo
  and base branch. This is a prototype with explicit production-tuning limits.

### Contribution destination and onboarding clarification — 2026-10-07

- The operator confirmed OmegaPulse as the intended contribution destination,
  with collaboration work first going to `MilaBooot/mettaclaw`. This changes the
  earlier proposed PR destination, not the source branch's historical base.
- Expanded README with the three-component architecture, Docker prerequisites,
  ordered sensor/monitor startup, browser login, live indicator testing,
  sensor logs/stop/resume, and Docker-socket test scope. Clarified that browser
  lifecycle buttons control Oma while launcher stop/resume controls the monitor.
- A GitHub PR needs an existing target base branch and a suitable fork/history
  relationship. OmegaPulse's base/history remains unverified. If it is empty or
  unrelated, agree a base with its maintainer and transfer only `monitor/` to a
  branch of an OmegaPulse fork rather than importing Oma's entire history.
- These follow-up changes are documentation only; `git diff --check` passed.
  No live service was changed, no skipped socket test was executed, and no push
  or PR was performed. A local PR description is prepared for review.

### Final Falco test and publication authorization — 2026-10-07

- The operator authorized a final real Falco test followed by commit/push to
  the existing collaboration branch. PR creation remains separate, pending the
  OmegaPulse base/history workflow. The earlier socket-test skip was preserved.
- Reused running `oma-falco-live`; its startup reports the modern BPF probe and
  syscall event source. Inspected its privileged setting and actual mounts.
  No additional sensor or host-root command was used.
- Generated marker `oma-monitor-check-1791384930` as UID/GID `65534:65534` in
  live Oma. All three raw records have `source: syscall` and ID `57121bddabad`,
  matching the current container. Connection refusal and namespace denial
  (errno 1) were expected. No Oma lifecycle action was taken.
- Authenticated HTTP SSE on the existing monitor received all three marked
  rules with `token=[REDACTED]`; unauthenticated status returned 401 and
  authenticated Docker state was running. Regression rerun: **44 passed,
  3 opt-in tests skipped in 0.20s**. Shell syntax and diff whitespace passed.
- Added explicit README descriptions of all watched syscalls and host access:
  privileged eBPF sensor, read-only tracing/proc/etc/rules mounts, Docker socket
  for container lookup, writable event directory, and separation from Oma.
- Redacted final evidence is in
  [`validation/final-falco-2026-10-07.json`](validation/final-falco-2026-10-07.json).
  Manual browser rendering, successful escape, and production event-loss rates
  are not claimed. Publication result will be reported after remote verification.

## Next milestone

Review the lifecycle controls and tune the Falco prototype on a staging Linux
host. Establish Oma's expected provider/DNS destinations and processes, convert
the alert-all outbound rule into a reviewed allowlist, validate false-positive
volume and dropped-event metrics, and choose durable audit/security-event
retention. Automatic stop or network isolation on an alert must not be enabled
until false-positive and recovery procedures are approved.
