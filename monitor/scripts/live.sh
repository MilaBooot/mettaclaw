#!/usr/bin/env bash
# Start the monitor separately from Oma; no provider or Telegram keys are needed.
set -euo pipefail
set +x
monitor_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
events_dir="${OMA_MONITOR_EVENTS_DIR:-$monitor_dir/.local/falco-events}"
container="${OMA_MONITOR_DOCKER_NAME:-oma-monitor-live}"
target="${OMA_MONITOR_CONTAINER:-omega}"
[[ "$container" != "$target" ]] || { printf 'Monitor and Oma container names must differ.\n' >&2; exit 1; }

is_monitor() {
    local metadata
    metadata="$(docker inspect --format '{{ index .Config.Labels "oma.monitor.component" }} {{ index .Config.Labels "oma.monitor.live" }} {{json .Config.Cmd}}' "$container")"
    [[ "$metadata" == monitor\ * || "$metadata" == *' local-test ["python","-m","monitor.app"]' ]]
}

case "${1:-start}" in
    signals)
        marker="oma-monitor-check-$(date +%s)"
        docker exec -i -u 65534:65534 "$target" sh -c \
            'python3 - "$1" token=demo-secret' sh "$marker" \
            < "$monitor_dir/tests/omega_runtime_indicators.py"
        printf 'Find %s in the browser security signals.\n' "$marker"
        exit 0 ;;
    stop|resume)
        is_monitor || { printf 'Existing container is not a managed monitor.\n' >&2; exit 1; }
        action=stop
        [[ "$1" == stop ]] || action=start
        docker "$action" "$container"
        exit 0 ;;
    start|monitor) ;;
    *) printf 'Usage: bash monitor/scripts/live.sh start|monitor|signals|stop|resume\n' >&2; exit 1 ;;
esac

docker info >/dev/null
umask 077
mkdir -p "$events_dir"
events_dir="$(cd -- "$events_dir" && pwd)"
docker build -t oma-monitor:local "$monitor_dir"
read -r -p 'Browser username [operator]: ' OMA_MONITOR_USERNAME
export OMA_MONITOR_USERNAME="${OMA_MONITOR_USERNAME:-operator}"
IFS= read -r -s -p 'Browser password (at least 12 characters): ' OMA_MONITOR_PASSWORD
printf '\n'
export OMA_MONITOR_PASSWORD
IFS= read -r -s -p 'Confirm browser password: ' confirmation
printf '\n'
[[ "$confirmation" == "$OMA_MONITOR_PASSWORD" ]] || { printf 'Passwords did not match.\n' >&2; exit 1; }
export OMA_MONITOR_CONTAINER="$target" OMA_MONITOR_HOST=127.0.0.1
export OMA_MONITOR_PORT="${OMA_MONITOR_PORT:-8765}"
export OMA_MONITOR_SECURITY_EVENTS_FILE=/events/oma-events.jsonl
docker run --rm -e OMA_MONITOR_USERNAME -e OMA_MONITOR_PASSWORD \
    -e OMA_MONITOR_CONTAINER -e OMA_MONITOR_HOST -e OMA_MONITOR_PORT -e OMA_MONITOR_SECURITY_EVENTS_FILE \
    --entrypoint python oma-monitor:local -c \
    'from monitor.config import MonitorConfig; MonitorConfig.from_env()'

if docker container inspect "$container" >/dev/null 2>&1; then
    is_monitor || { printf 'Existing container is not a managed monitor.\n' >&2; exit 1; }
    docker stop "$container" >/dev/null
    docker rename "$container" "$container-backup-$(date +%Y%m%d-%H%M%S)"
fi
docker run -d --name "$container" --label oma.monitor.component=monitor \
    --user "$(id -u):$(id -g)" --group-add "$(stat -c '%g' /var/run/docker.sock)" \
    --network host --init --security-opt no-new-privileges:true \
    -e OMA_MONITOR_USERNAME -e OMA_MONITOR_PASSWORD -e OMA_MONITOR_CONTAINER \
    -e OMA_MONITOR_HOST -e OMA_MONITOR_PORT -e OMA_MONITOR_SECURITY_EVENTS_FILE \
    --mount type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock \
    --mount "type=bind,src=$events_dir,dst=/events,readonly" oma-monitor:local
unset OMA_MONITOR_PASSWORD confirmation
printf 'Monitor: http://127.0.0.1:%s/\n' "$OMA_MONITOR_PORT"
