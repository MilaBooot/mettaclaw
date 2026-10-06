# Optional Falco runtime sensor

Falco is the proposed rule-based sensor for Linux production hosts. The monitor
does not install or control Falco. It only reads Falco's newline-delimited JSON
file when `OMA_MONITOR_SECURITY_EVENTS_FILE` is configured.

The included rules flag four kinds of signals for the container named `omega`:

- any outbound IPv4/IPv6 connection attempt;
- namespace or mount manipulation;
- execution of shells and common network utilities;
- attempts to open a Docker daemon socket.

These are indicators, not proof that a breach or escape occurred. In particular,
Oma normally makes outbound model/provider requests, so the outbound rule is
intentionally noisy. Profile expected destinations and processes in staging,
then add explicit allowlists before production alerting. Keep the upstream Falco
default rules enabled as another layer.

## Integration contract

1. Install Falco separately on the Linux host using the official instructions.
2. Load `oma_rules.yaml` after Falco's default rules.
3. Merge `falco-output.fragment.yaml` into `falco.yaml` and run Falco unbuffered.
4. Give the monitor read-only filesystem permission to the resulting JSON-lines
   file. Do not expose Falco's control surface through the monitor.
5. Set, for example:

   ```bash
   export OMA_MONITOR_SECURITY_EVENTS_FILE=/var/log/falco/oma-events.jsonl
   ```

Falco's file output does not rotate itself. Configure host log rotation and
retention, and keep permissions narrow because events can include commands,
usernames, addresses, and other sensitive metadata.

## Deployment warning

Falco consumes Linux kernel events and requires elevated host capabilities and
host mounts. Do not copy a privileged `docker run` command into production
without infrastructure/security review. Docker Desktop/WSL is useful for the
monitor integration test but is not a faithful production Falco environment.
Validate the Falco version, driver, rules syntax, event volume, and dropped-event
metrics on the actual Linux deployment target.

References:

- <https://falco.org/docs/setup/container/>
- <https://falco.org/docs/reference/rules/examples/>
- <https://falco.org/docs/concepts/outputs/channels/>
