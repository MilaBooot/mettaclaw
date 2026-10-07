# Monitor validation

Keep three claims separate: Docker status/logs/controls, Falco JSON display, and
real kernel syscall capture. Mock JSON validates the reader/UI contract; only a
sensor on Oma's native Linux kernel validates capture. No test establishes that
a signal represents a successful breach or escape.

## Regression checks

From the repository root, in an isolated Python environment with
`monitor/requirements-dev.txt` installed:

```bash
python -m pytest monitor/tests -q
```

The real Docker and combined acceptance tests are skipped unless explicitly
configured. They stop/start/restart their target, so use a disposable container.
Do not point them at a live Telegram/provider bot.

## Current-source Oma with mock services

Build the current checkout. Check that the following dedicated test names are
unused before creating them; do not remove an existing container to make room.
No Telegram or model-provider credentials are supplied.

```bash
docker build -t omega:monitor-test .
docker network create oma-monitor-acceptance-net
docker run -d --name oma-monitor-mocks \
  --network oma-monitor-acceptance-net --user 65534:65534 \
  --entrypoint python3 \
  --mount "type=bind,src=$PWD,dst=/workspace,readonly" \
  -w /workspace omega:monitor-test monitor/tests/omega_mock_services.py
```

Wait for `Omega mock services ready: LLM=9765 channel=9766` in its logs. Then:

```bash
docker run -dit --name oma-monitor-acceptance \
  --network oma-monitor-acceptance-net \
  --security-opt no-new-privileges:true --init \
  --tmpfs /tmp:size=64m,mode=1777 --tmpfs /var/tmp:size=64m,mode=1777 \
  --tmpfs /run:size=16m,mode=755 \
  --volume oma-monitor-acceptance-memory:/PeTTa/repos/Omega/memory \
  -e TEST_SERVER_IP=oma-monitor-mocks -e IMPORT_KB_ON_START=0 \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  omega:monitor-test commchannel=test provider=Test embeddingprovider=Local \
  securityPolicyPath=/PeTTa/repos/Omega/profile/policy.yaml \
  memoryDirectory=/PeTTa/repos/Omega/memory TEST_SERVER_IP=oma-monitor-mocks
```

Wait for connections to both mock ports and a `CHARS_SENT` record. In the Python
test environment, run:

```bash
OMA_MONITOR_INTEGRATION_CONTAINER=oma-monitor-acceptance \
OMA_MONITOR_ACCEPTANCE_CONTAINER=oma-monitor-acceptance \
  python -m pytest monitor/tests/test_docker_integration.py \
    monitor/tests/test_acceptance_integration.py -q
```

Expected: three tests pass. The lifecycle test restores the initial state; the
combined test checks authentication, real status/logs, fixed-target rejection,
controls, and controlled Falco JSON filtering/redaction. This is not kernel capture.

For a browser check, point the independent monitor at this disposable target:

```bash
OMA_MONITOR_CONTAINER=oma-monitor-acceptance bash monitor/scripts/live.sh start
```

After stopping the monitor, remove only the resources you created for this test:

```bash
docker stop oma-monitor-acceptance oma-monitor-mocks
docker rm oma-monitor-acceptance oma-monitor-mocks
docker volume rm oma-monitor-acceptance-memory
docker network rm oma-monitor-acceptance-net
```

## Real native-Linux Falco test

Oma and Falco must share the native Linux kernel. The included rule macro selects
`omega`; for a differently named disposable target, edit a separate test rule
copy to match its name. Rules and event-file configuration must agree with the
monitor's configured target. Do not run multiple test sensors unnecessarily.

First validate the actual rules without kernel privileges:

```bash
docker run --rm \
  --mount "type=bind,src=$PWD/monitor/falco/oma_rules.yaml,dst=/rules/oma_rules.yaml,readonly" \
  falcosecurity/falco:0.45.0 falco -V /rules/oma_rules.yaml
```

Expected: `/rules/oma_rules.yaml: Ok`. After approval for privileged sensor access,
start the sensor and independent monitor as described in [README.md](README.md).
If they already run, reuse them. Check `docker logs oma-falco-live` for successful
modern BPF probe startup and check that the container remains running.

With the authenticated browser security panel open:

```bash
bash monitor/scripts/live.sh signals
```

The command runs a shell, attempts a localhost TCP connect, and calls
`unshare(CLONE_NEWNS)` as nobody. Expect connection refusal and namespace denial.
Find its unique printed marker in all three corresponding Falco rule events:

- `Unexpected shell or network utility in Oma`
- `Oma outbound connection attempt`
- `Oma namespace or mount manipulation`

Check raw JSON for `source: syscall`, the configured container name, and its ID;
compare the ID with `docker inspect --format '{{.Id}}' omega`. The same marked
events should appear through the authenticated monitor, with `token=[REDACTED]`.
The raw file contains the harmless demonstration token. This helper does not
execute the Docker-socket indicator; its native capture requires a separate,
explicitly approved check.

Normal provider/Telegram connections trigger outbound Notices too. High counts
are expected with the current alert-all prototype. Profile and review allowlists;
do not automate containment based on these rules. Keep production sensor tuning,
dropped-event metrics, and log retention separate from this short integration test.
