# End-to-end testing

This guide separates three claims that must not be confused:

1. the monitor can authenticate, show real Oma Docker logs, and control Oma;
2. Falco rules can parse and the monitor can display Falco JSON;
3. Falco actually observes kernel syscalls from Oma.

The automated suite covers the first two with mocks. A real Docker integration
covers status, logs, Start, Stop, and Restart. Claim 3 requires Falco and Oma to
run on the same native Linux kernel.

## A. Current-source Oma without external credentials

Use three WSL terminals. Do not supply Telegram or model-provider secrets. A
private Docker network gives the mock services stable DNS and avoids
`host.docker.internal`/WSL routing differences.

Terminal 1 - build the exact checkout, create the private network, and run the
repository's deterministic mock LLM/channel services:

```bash
cd /mnt/d/HyperClaw/Omega
docker build -t omega:monitor-test .
docker network create oma-monitor-test-net
docker run --rm --name omega-mocks \
  --network oma-monitor-test-net \
  --entrypoint python3 \
  -v /mnt/d/HyperClaw/Omega:/workspace:ro \
  -w /workspace \
  omega:monitor-test monitor/tests/omega_mock_services.py
```

Wait for `Omega mock services ready: LLM=9765 channel=9766`.

Terminal 2 - create the disposable local Oma instance. This command removes
only an existing container named exactly `omega`; confirm it is disposable
first. It does not use `scripts/omega start`, which also recreates the target.

```bash
cd /mnt/d/HyperClaw/Omega
docker ps -a --filter 'name=^/omega$'
docker rm -f omega 2>/dev/null || true
docker run -dit --name omega \
  --network oma-monitor-test-net \
  --security-opt no-new-privileges:true \
  --init \
  --tmpfs /tmp:size=64m,mode=1777 \
  --tmpfs /var/tmp:size=64m,mode=1777 \
  --tmpfs /run:size=16m,mode=755 \
  --volume omega-monitor-test-memory:/PeTTa/repos/Omega/memory \
  -e TEST_SERVER_IP=omega-mocks \
  -e IMPORT_KB_ON_START=0 \
  omega:monitor-test \
  commchannel=test \
  provider=Test \
  embeddingprovider=Local \
  securityPolicyPath=/PeTTa/repos/Omega/profile/policy.yaml \
  memoryDirectory=/PeTTa/repos/Omega/memory \
  TEST_SERVER_IP=omega-mocks
docker ps -a --filter 'name=^/omega$'
docker logs --tail 100 -f omega
```

Wait for `Connected to: ('omega-mocks', 9766)`, `Connected to:
('omega-mocks', 9765)`, and a runtime `CHARS_SENT: <number>` record. Do not
substitute a real model or Telegram token merely to make the smoke test pass.

Terminal 3 - run the monitor:

```bash
cd /mnt/d/HyperClaw/Omega
source ~/.venvs/oma-monitor/bin/activate
export OMA_MONITOR_USERNAME=operator
read -rsp 'Monitor password: ' OMA_MONITOR_PASSWORD; echo
export OMA_MONITOR_PASSWORD
export OMA_MONITOR_CONTAINER=omega
python -m monitor.app
```

Open `http://127.0.0.1:8765/`. Verify authentication, real logs, Stop, Start,
and Restart. The monitor's Start operation only starts the existing container;
it never invokes `scripts/omega start` or recreates a missing container.

Run the opt-in integration while `omega` is disposable:

```bash
OMA_MONITOR_INTEGRATION_CONTAINER=omega \
  python -m unittest monitor.tests.test_docker_integration -v
```

Expected: two tests pass, covering real status/log retrieval and real
Stop/Start/Restart.

Cleanup after stopping the monitor and the foreground mock-service command:

```bash
docker rm -f omega
docker volume rm omega-monitor-test-memory
docker network rm oma-monitor-test-net
```

If an older cached `singularitynet/omegaclaw:latest` image is used instead, its
repository root may be `/PeTTa/repos/OmegaClaw-Core`; adjust the mounted and
argument paths consistently. That validates the monitor integration but is not
a substitute for building and testing the current checkout.

## B. Combined WSL acceptance test (mock Falco events)

This is the final repeatable test before native-Linux Falco validation. It uses
an existing disposable `omega` container, its real Docker logs and lifecycle,
the authenticated Flask surface, and controlled Falco-format JSON. It stops,
starts, and restarts the target, then restores its initial running/stopped
state. It never creates or removes the container.

```bash
cd /mnt/d/HyperClaw/Omega
source ~/.venvs/oma-monitor/bin/activate
OMA_MONITOR_ACCEPTANCE_CONTAINER=omega \
  python -m pytest monitor/tests/test_acceptance_integration.py -q -s
```

Expected: `1 passed`. This covers authentication, the fixed target, real
status/logs, Stop/Start/Restart, security status/SSE, filtering out events for
other containers, and secret redaction.

Validate the actual Falco rule file semantically without attaching to the
kernel:

```bash
docker run --rm \
  -v "$PWD/monitor/falco/oma_rules.yaml:/rules/oma_rules.yaml:ro" \
  falcosecurity/falco:0.45.0 \
  falco -V /rules/oma_rules.yaml
```

Expected: `/rules/oma_rules.yaml: Ok`.

For a visual browser check, restart the monitor with a persistent fixture:

```bash
mkdir -p /tmp/oma-monitor
: > /tmp/oma-monitor/falco-events.jsonl
export OMA_MONITOR_SECURITY_EVENTS_FILE=/tmp/oma-monitor/falco-events.jsonl
python -m monitor.app
```

In a second WSL terminal, append a controlled outbound signal:

```bash
printf '%s\n' \
  '{"time":"2026-10-06T12:00:00Z","priority":"Warning","rule":"Oma outbound connection attempt","output":"Test outbound token=secret","output_fields":{"container.name":"omega"}}' \
  >> /tmp/oma-monitor/falco-events.jsonl
```

The authenticated page at `http://127.0.0.1:8765/` must show the outbound rule
and `token=[REDACTED]`. This proves the browser integration, not kernel capture.

## C. Real Falco syscall test

Falco's official Docker quickstart says it does not work on Windows/macOS
Docker Desktop. A valid end-to-end test therefore uses a native Linux VM/server
where Oma and Falco share a kernel. The commands below grant Falco privileged
kernel access and must be approved for a dedicated test host.

On that Linux host, after starting the disposable `omega` from section A:

```bash
mkdir -p /tmp/oma-falco-events
docker run --rm -d --name oma-falco-test \
  --privileged \
  -v /sys/kernel/tracing:/sys/kernel/tracing:ro \
  -v /var/run/docker.sock:/host/var/run/docker.sock \
  -v /proc:/host/proc:ro \
  -v /etc:/host/etc:ro \
  -v "$PWD/monitor/falco/oma_rules.yaml:/rules/oma_rules.yaml:ro" \
  -v /tmp/oma-falco-events:/events \
  falcosecurity/falco:0.45.0 falco -U \
  -r /rules/oma_rules.yaml \
  -o engine.kind=modern_ebpf \
  -o json_output=true \
  -o stdout_output.enabled=false \
  -o file_output.enabled=true \
  -o file_output.keep_alive=false \
  -o file_output.filename=/events/oma-events.jsonl
```

Configure the monitor before starting it:

```bash
export OMA_MONITOR_SECURITY_EVENTS_FILE=/tmp/oma-falco-events/oma-events.jsonl
```

Generate controlled indicators in the disposable Oma container:

```bash
docker exec omega sh -c 'wget -qO- https://example.com >/dev/null || true'
docker exec omega sh -c 'unshare -m true || true'
docker exec -u 0 omega sh -c 'mkdir -p /var/run; : > /var/run/docker.sock'
```

Verify that Falco, not a hand-written fixture, appended JSON records:

```bash
tail -f /tmp/oma-falco-events/oma-events.jsonl
```

The authenticated monitor should display the same events. Expected rule names
include `Oma outbound connection attempt`, `Oma namespace or mount
manipulation`, `Unexpected shell or network utility in Oma`, and `Oma attempts
Docker socket access`.

These events are indicators, not proof of compromise. The outbound rule is
deliberately noisy until expected provider/DNS destinations are profiled and
allowlisted. Do not automate Stop based on these prototype rules.
