# Oma container monitor

An independent, authenticated monitor for one existing Oma Docker container.
It provides Start, Stop, and Restart, live Docker logs, and optional Falco runtime
signals. It does not change Oma's reasoning, providers, channels, or launch workflow.

## How it works

Three separate containers have different jobs:

| Component | Job |
| --- | --- |
| Oma (`omega`) | Runs the agent with its own provider/channel configuration |
| Falco (`oma-falco-live`) | Observes kernel syscalls and writes security events |
| Monitor (`oma-monitor-live`) | Provides browser authentication, Docker controls, logs, and the event display |

The monitor reads Docker status/logs through the Docker socket. Falco writes
JSON-lines events to a shared host directory; the monitor reads that directory
read-only and streams matching, redacted events to the browser. Falco runs
separately because its eBPF sensor needs privileged kernel access, while the web
application does not need to run as a privileged container. Each can be restarted
independently. Docker controls and logs work without Falco; real syscall signals
require a working Falco sensor.

### What Falco watches and what access it has

The executable rules are in [falco/oma_rules.yaml](falco/oma_rules.yaml). Every
rule selects the configured Oma container, initially `container.name = omega`:

| Rule | Watched operation | Priority |
| --- | --- | --- |
| Outbound connection | IPv4/IPv6 `connect` syscall attempts | Notice |
| Namespace/mount manipulation | `setns`, `unshare`, `mount`, `umount`, `umount2` | Warning |
| Shell/network utility | `execve`/`execveat` for the listed shells and network tools | Warning |
| Docker-socket access | `open`/`openat`/`openat2` of the two configured socket paths | Critical |

[scripts/falco.sh](scripts/falco.sh) is the complete sensor launch command. It
selects `engine.kind=modern_ebpf` and uses `--privileged`, which grants broad
host capabilities/device access to the sensor container. The read-only mounts
do not remove those privileges. Kernel observation happens at the host level;
the rules restrict which observed events are reported, not the sensor's access.

The tracing filesystem, host `/proc`, host `/etc`, and rule file are mounted
read-only. The host Docker socket is mounted for container identity lookup and
also grants Docker daemon control; it must be treated as privileged access.
The event directory is writable so Falco can emit JSON. Only the sensor gets
these kernel permissions; no such permission or socket is added to Oma by the
sensor launcher. The monitor itself has a separate Docker socket mount for its
authorized lifecycle controls.

These rules report attempts and metadata. They do not inspect packet contents,
classify every possible escape technique, or block syscalls. The monitor displays
the events; it does not automatically stop Oma in response to them.

## Quick start with real security signals

Prerequisites: native Linux, a running Docker Engine accessible through plain
`docker` commands, and an existing Oma container named `omega`. Both launchers
use the local `/var/run/docker.sock`; no `sudo` is used. The Falco launch uses
`--privileged` to observe this host's kernel and should be reviewed by its operator.

From the repository containing this `monitor/` folder, after starting Oma normally:

```bash
docker ps --filter name=omega
bash monitor/scripts/falco.sh
bash monitor/scripts/live.sh start
```

Choose the browser credentials when prompted, then open `http://127.0.0.1:8765/`.
Check container status, live logs, and the security panel. Start/Stop/Restart
buttons act on Oma; the shell launcher's stop/resume commands act on the monitor.
Generate three controlled security indicators with:

```bash
bash monitor/scripts/live.sh signals
```

Find the printed marker in the security panel. To inspect sensor startup or stop
only the sensor:

```bash
docker logs --tail 50 oma-falco-live
docker stop oma-falco-live
```

Resume an existing stopped sensor with `docker start oma-falco-live`; the Falco
launcher deliberately refuses to overwrite an existing container. If your target
has another name, set `OMA_MONITOR_CONTAINER` and update the target macro in
`falco/oma_rules.yaml` before launching the sensor.

## Start separately from Oma

Run Oma using its normal setup. The monitor needs Docker access and a browser
login; it does not need your OpenRouter key or Telegram token.

On native Linux, from the repository root:

```bash
bash monitor/scripts/live.sh start
```

This builds the small monitor image using only `monitor/`, prompts for the browser
username/password (at least 12 characters), and starts it at
`http://127.0.0.1:8765/`. It never starts, removes, renames, or recreates Oma.
The monitor container runs as your user with the Docker socket's group.

To change the browser login, rerun `start` or `monitor`. The old monitor is stopped
and preserved under a timestamped backup name. Stop/resume affect only the monitor:

```bash
bash monitor/scripts/live.sh stop
bash monitor/scripts/live.sh resume
```

The launcher assumes native Linux and a local `/var/run/docker.sock`. For a
Python process instead, create a venv, install `monitor/requirements.txt`, set
`OMA_MONITOR_USERNAME` and `OMA_MONITOR_PASSWORD`, then run `python -m monitor.app`
from the repository root. See `.env.example` for configuration placeholders.

## Optional real Falco signals

Falco must run on the same native Linux kernel as Oma. After approving privileged
sensor access on a local/staging host, start it separately:

```bash
bash monitor/scripts/falco.sh
```

The sensor and monitor launchers share `monitor/.local/falco-events/` by default.
This directory is Git-ignored. Both accept `OMA_MONITOR_EVENTS_DIR` to select an
existing event directory. For example, to keep using our original live sensor:

```bash
export OMA_MONITOR_EVENTS_DIR="$PWD/.oma-monitor-local/falco-events"
bash monitor/scripts/live.sh monitor
```

With the browser's security panel open, generate controlled indicators:

```bash
bash monitor/scripts/live.sh signals
```

Find the printed marker in three new events: shell execution, outbound connect,
and namespace/mount manipulation. The helper runs as nobody inside the configured
Oma container. Connection refusal and namespace permission denial are expected;
the rules detect attempts. It does not access or create a Docker socket file.
The raw file retains the demonstration token; the browser redacts it.

Frequent outbound Notices are expected: the prototype reports every IPv4/IPv6
connect attempt, including ordinary provider and Telegram requests. Signals are
not breach verdicts. Profile expected destinations/processes before introducing
reviewed allowlists. No automatic Stop or containment is enabled.
See [falco/README.md](falco/README.md) for the sensor integration contract.

The Docker-socket rule detects Oma opening `/var/run/docker.sock` or
`/run/docker.sock`. Access to a real Docker daemon socket can allow control of
other containers and the host, so this is a critical indicator. The native test
for this rule was skipped by operator choice; the rule remains enabled but its
real capture is unverified. The proposed test would open an empty regular file
at that path inside the test container, without mounting the real host socket.
It would test the pathname-based rule, not prove a successful escape. Never mount
the host Docker socket into Oma just to generate this indicator.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `OMA_MONITOR_USERNAME` | required | Browser operator username |
| `OMA_MONITOR_PASSWORD` | required | Browser password, at least 12 characters |
| `OMA_MONITOR_CONTAINER` | `omega` | Fixed target container |
| `OMA_MONITOR_HOST` | `127.0.0.1` | Python server bind address |
| `OMA_MONITOR_PORT` | `8765` | Server port |
| `OMA_MONITOR_SECURITY_EVENTS_FILE` | disabled | Falco JSON-lines file for Python setup |

The Docker launcher fixes the server to localhost and maps its shared event file
to `/events/oma-events.jsonl`. `OMA_MONITOR_DOCKER_NAME` selects its own container
name; `OMA_FALCO_CONTAINER` selects the sensor container name. If Oma's name
changes, also update `oma_target_container` in `falco/oma_rules.yaml`.

## Authorization and limits

All page/API routes require independent HTTP Basic authentication. Lifecycle
requests also require POST JSON, a CSRF header, browser confirmation, and serialized
Docker operations. Start only starts an existing container; it never recreates one.
Logs/events are rendered as text, redacted on a best-effort basis, and bounded to
1,000 log records and 500 security records in the browser. Falco JSON is filtered
to the configured container. Streams recover after stops, Docker failures, and
container/event-file replacement.

Docker socket access gives the monitor privileged host control. Restrict its
operator account and keep it on localhost, through SSH, or behind HTTPS. There is
one operator role; production identity controls and durable audit retention are
deferred. Credentials are stored in container environment configuration by Docker,
not in the repository or browser storage. Do not use `bash -x` when entering secrets.

“Running” reports Docker process state, not agent health. A readable event file
also does not prove the sensor is currently capturing. Falco output requires host
rotation/retention configuration; the monitor does not rotate or archive it.

## Validation

Install `monitor/requirements-dev.txt` in a test environment and run:

```bash
python -m pytest monitor/tests -q
```

Real Docker lifecycle tests are opt-in and must target a disposable container.
See [TESTING.md](TESTING.md) for mock services, combined acceptance, and native
Falco capture checks; [HANDOFF.md](HANDOFF.md) records executed results and limits.

## Contribution scope

The feature can be shared as just this `monitor/` directory, including its image
definition, launchers, rules, tests, and documentation. It does not require changes
to Oma's source or dependencies. Current collaboration work is on
`MilaBooot/mettaclaw`, branch `feat/oma-monitor-phase1`; the intended destination
is `iCog-Labs-Dev/OmegaPulse`.

A cross-repository pull request requires a suitable target base branch and shared
Git history/fork relationship. If OmegaPulse is empty or has unrelated history,
its maintainer must first establish a base branch and contribution workflow.
Then use a fork of OmegaPulse and copy only `monitor/` onto a branch based on that
repository. Do not propose the whole Oma repository history merely to transfer
the monitor folder. Confirm that workflow before publishing a PR.
