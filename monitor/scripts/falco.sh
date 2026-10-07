#!/usr/bin/env bash
# Optional native-Linux sensor; run only with approved privileged kernel access.
set -euo pipefail
monitor_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
events_dir="${OMA_MONITOR_EVENTS_DIR:-$monitor_dir/.local/falco-events}"
container="${OMA_FALCO_CONTAINER:-oma-falco-live}"
if docker container inspect "$container" >/dev/null 2>&1; then
    printf 'Container %s already exists. Inspect it or use docker start %s.\n' "$container" "$container" >&2
    exit 1
fi
umask 077
mkdir -p "$events_dir"
events_dir="$(cd -- "$events_dir" && pwd)"
docker run -d --name "$container" --label oma.monitor.component=falco --privileged \
    --mount type=bind,src=/sys/kernel/tracing,dst=/sys/kernel/tracing,readonly \
    --mount type=bind,src=/var/run/docker.sock,dst=/host/var/run/docker.sock \
    --mount type=bind,src=/proc,dst=/host/proc,readonly \
    --mount type=bind,src=/etc,dst=/host/etc,readonly \
    --mount "type=bind,src=$monitor_dir/falco/oma_rules.yaml,dst=/rules/oma_rules.yaml,readonly" \
    --mount "type=bind,src=$events_dir,dst=/events" \
    falcosecurity/falco:0.45.0 falco -U -r /rules/oma_rules.yaml \
    -o engine.kind=modern_ebpf -o json_output=true -o stdout_output.enabled=false \
    -o file_output.enabled=true -o file_output.keep_alive=false \
    -o file_output.filename=/events/oma-events.jsonl
