# Oma operations monitor

This is a small, standalone web service for Oma's maintainers. It shows the
Docker state of one server-configured container, streams its Docker logs, and
provides authorized Start, Stop, and Restart actions. It runs outside Oma, so
the page remains available when the agent stops.

An optional adapter displays rule-based Falco runtime signals. There is no AI/ML
in monitoring or detection. Grafana, Prometheus, Loki, Alloy, and Axiom are not
required or currently integrated.

## What it does

- Reports `running`, `stopped`, `restarting`, `missing`, and
  `docker-unavailable` states. Running means only that Docker reports a running
  process; agent health is explicitly unknown.
- Requests the newest 200 timestamped Docker log lines and follows new output.
  It reconnects when a stream ends, Docker returns, or the container is
  recreated.
- Provides pause/resume and case-insensitive text filtering in the browser.
- Keeps at most 1,000 records in the browser. The server does not retain a
  shared log history and bounds an individual partial line to 16 KiB chunks.
- Applies best-effort credential redaction before a record leaves the backend.
  Redaction cannot guarantee removal of every secret; sensitive values should
  never intentionally be logged.
- Protects the page, status endpoint, and stream with one independent HTTP
  Basic operator account. Missing or invalid startup credentials fail closed.
- Provides confirmed Start, Stop, and Restart operations. Mutations require
  authentication, POST JSON, a CSRF token/custom header, and a same-origin
  browser context; actions are serialized and audit logged.
- Optionally reads the latest 100 Falco JSON events and streams new ones. Events
  are filtered to the configured container, redacted, rendered as text, and
  bounded to 500 records in the browser.

The browser cannot select a container. `OMA_MONITOR_CONTAINER` is read once by
the server (default `omega`), and API query parameters are rejected. Docker is
accessed only by the backend; this is not a general Docker API proxy.

## Local setup (Windows PowerShell)

From the repository root (`D:\HyperClaw\Omega`):

```powershell
py -3 -m venv monitor\.venv
monitor\.venv\Scripts\python -m pip install -r monitor\requirements.txt
$env:OMA_MONITOR_USERNAME = "operator"
$env:OMA_MONITOR_PASSWORD = "generate-a-long-random-password"
$env:OMA_MONITOR_CONTAINER = "omega"
monitor\.venv\Scripts\python -m monitor.app
```

Open `http://127.0.0.1:8765/` and enter the operator credentials when prompted.
Docker Desktop must be running and the current Windows user must be allowed to
access its Docker Engine.

For bash on Linux/macOS, create a venv, install the same requirements, export
the variables shown in [`monitor/.env.example`](.env.example), and run:

```bash
python -m monitor.app
```

The default bind address is `127.0.0.1`. HTTP Basic credentials are not safe on
an untrusted network without TLS. For remote use, keep the localhost bind and
use an SSH tunnel, or place the service behind an authenticated HTTPS reverse
proxy. Do not expose the development service directly.

## Configuration

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `OMA_MONITOR_USERNAME` | yes | — | Operator username |
| `OMA_MONITOR_PASSWORD` | yes | — | Operator password, at least 12 characters |
| `OMA_MONITOR_CONTAINER` | no | `omega` | Only container the backend can inspect |
| `OMA_MONITOR_HOST` | no | `127.0.0.1` | Listen address |
| `OMA_MONITOR_PORT` | no | `8765` | Listen port |
| `OMA_MONITOR_SECURITY_EVENTS_FILE` | no | disabled | Falco JSON-lines event file |

Credentials belong in the process environment or a proper secret manager, not
source control. The example file contains placeholders only. The UI uses no
local/session storage, and credentials are never placed in URLs or application
logs.

## Docker access and limitations

Access to the Docker socket grants highly privileged control over the host.
Even a read-only socket mount does not turn the Docker API into a read-only API;
the socket still accepts privileged requests. Run this small service as a
dedicated, patched process and restrict who can reach it. Application code calls
only ping, container inspect/logs, and the explicit start/stop/restart methods.
It has no remove, create, exec, image, volume, network, or arbitrary Docker proxy
operation. Start only starts an existing container; a missing target remains
missing. It never invokes the destructive `scripts/omega start` workflow.

Other limitations:

- HTTP Basic auth has one operator and no logout/session management or rate
  limiting. Use HTTPS or an SSH tunnel outside a trusted local machine.
- Status is Docker process state, not an application readiness or health check.
- Pause stops browser rendering, not backend collection. The bounded buffer
  continues to discard its oldest records.
- There is deliberately no Docker Pause button. Freezing a possibly compromised
  process is not reliable containment: existing sockets and host exposure remain.
  Stop is the safer phase-2 incident action; host/network isolation needs a
  separately designed response procedure.
- A server restart clears displayed history; Docker supplies the newest 200
  lines when the browser reconnects.
- Best-effort regex redaction may miss novel, split, encoded, or unusual secret
  formats.
- Controls use one operator role and local audit logs; production still needs
  durable centralized audit retention, rate limiting, and an HTTPS identity
  boundary.
- Security signals require an independently deployed Falco sensor. They are
  indicators, not proof of compromise. Review [`falco/README.md`](falco/README.md)
  before considering deployment.

## Tests and troubleshooting

For current-source Oma, real lifecycle/log validation, and native-Linux Falco
testing, follow [`TESTING.md`](TESTING.md).

```powershell
monitor\.venv\Scripts\python -m pip install -r monitor\requirements-dev.txt
monitor\.venv\Scripts\python -m pytest monitor\tests
```

An opt-in real lifecycle test requires an already-created disposable container;
the test never creates or removes it:

```bash
OMA_MONITOR_INTEGRATION_CONTAINER=your-disposable-name \
  python -m unittest monitor.tests.test_docker_integration -v
```

- **Monitor refuses to start:** set both credential variables and use a password
  of at least 12 characters.
- **Docker unavailable:** start Docker Desktop/Engine and verify `docker info`
  works for the same user running the monitor.
- **Container missing:** verify `docker ps -a --filter name=omega`; if the
  intended name differs, set `OMA_MONITOR_CONTAINER` before starting.
- **Logs disconnect:** the browser and backend retry automatically. Persistent
  failure usually means Docker is unavailable or an intermediary is buffering
  server-sent events.
- **Oma reports ports 9765/9766 unreachable:** those are the repository's Test
  provider/channel endpoints, not monitor ports or a breach alert. Start the
  deterministic mock services and private Docker network from `TESTING.md`, or
  configure Oma with its intended real provider/channel credentials. Never put
  those credentials into the monitor.
- **Detector not configured:** this is expected unless
  `OMA_MONITOR_SECURITY_EVENTS_FILE` points to readable Falco JSON output.
