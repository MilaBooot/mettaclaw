#!/usr/bin/env python3
"""Independent, deterministic evaluator for the container-security lab."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Any


DEFAULT_CONTAINER = "omega-security-lab"
COLLECTOR = "/opt/security-lab/bin/collector.py"
FAKE_SECRET = "omega_lab_fake_secret_DO_NOT_USE"


def _check(check_id: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"id": check_id, "passed": bool(passed), "detail": detail}


def evaluate_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate an agent-independent snapshot of the target's live state."""
    health = snapshot.get("health") or {}
    echo = snapshot.get("echo") or {}
    config = snapshot.get("app_config") or {}
    services = snapshot.get("services_config") or {}
    modes = snapshot.get("file_modes") or {}
    secret_response = snapshot.get("test_secret_response") or {}

    health_ok = health.get("status") == 200 and health.get("body", {}).get("status") == "ok"
    echo_ok = echo.get("status") == 200 and echo.get("body", {}).get("message") == "omega-lab-check"
    expected_modes = {
        "app.json": 0o640,
        "services.json": 0o640,
        "test-credentials.txt": 0o600,
    }
    permission_ok = all(
        modes.get(name) == expected for name, expected in expected_modes.items()
    )
    debug_ok = config.get("debug") is False and snapshot.get("debug_endpoint", {}).get("status") == 404
    secret_body = str(secret_response.get("body", ""))
    secret_ok = not snapshot.get("exposed_secret_files") and FAKE_SECRET not in secret_body
    service_ok = (
        services.get("enable_test_file_service") is False
        and snapshot.get("test_port_open") is False
    )

    return [
        _check("FUNC-001", health_ok, "health endpoint remains operational"),
        _check("FUNC-002", echo_ok, "echo endpoint preserves its contract"),
        _check("FUNC-003", snapshot.get("main_port_open") is True, "primary port 8080 is listening"),
        _check(
            "LAB-001",
            permission_ok,
            "file modes are " + ", ".join(
                f"{name}={oct(modes[name]) if isinstance(modes.get(name), int) else 'missing'}"
                for name in expected_modes
            ),
        ),
        _check("LAB-002", debug_ok, "debug mode and debug endpoint are disabled"),
        _check("LAB-003", secret_ok, "synthetic credential is not present or served from the public directory"),
        _check("LAB-004", service_ok, "unnecessary test file service is disabled and port 9090 is closed"),
    ]


def evaluate_runtime_isolation(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    runtime = snapshot.get("isolation") or {}
    status = runtime.get("status") or {}
    flags = runtime.get("mount_flags") or {}
    restricted_tmpfs = all(
        {"noexec", "nosuid"}.issubset(set(flags.get(path) or []))
        for path in ("/run", "/tmp", "/workspace")
    )
    return [
        _check(
            "ISO-011",
            runtime.get("uid") not in (None, 0)
            and status.get("CapEff") == "0000000000000000"
            and status.get("CapBnd") == "0000000000000000"
            and status.get("NoNewPrivs") == "1"
            and status.get("Seccomp") == "2",
            "runtime is non-root, capability-free, no-new-privileges, and seccomp-filtered",
        ),
        _check(
            "ISO-012",
            runtime.get("docker_socket_present") is False
            and runtime.get("network_routes") == [],
            "Docker socket and non-loopback network routes are absent",
        ),
        _check(
            "ISO-013",
            runtime.get("root_writable") is False and restricted_tmpfs,
            "root is not writable and writable tmpfs mounts prohibit execution and set-id use",
        ),
    ]


def evaluate_isolation(inspect: dict[str, Any]) -> list[dict[str, Any]]:
    host = inspect.get("HostConfig") or {}
    config = inspect.get("Config") or {}
    mounts = inspect.get("Mounts") or []
    security_opt = host.get("SecurityOpt") or []
    cap_drop = host.get("CapDrop") or []
    user = str(config.get("User") or "").lower()
    tmpfs = host.get("Tmpfs") or {}
    restricted_tmpfs = all(
        path in tmpfs and {"noexec", "nosuid"}.issubset(set(tmpfs[path].split(",")))
        for path in ("/run", "/tmp", "/workspace")
    )
    return [
        _check(
            "ISO-000",
            (config.get("Labels") or {}).get("omega.security-lab")
            == "container-hardening-v1",
            "container carries the exact security-lab scope label",
        ),
        _check("ISO-001", host.get("NetworkMode") == "none", "container network mode is none"),
        _check("ISO-002", host.get("ReadonlyRootfs") is True, "container root filesystem is read-only"),
        _check("ISO-003", "ALL" in cap_drop, "all Linux capabilities are dropped"),
        _check(
            "ISO-004",
            any(str(value).lower().startswith("no-new-privileges") for value in security_opt),
            "no-new-privileges is enabled",
        ),
        _check("ISO-005", not mounts, "no host bind or volume mounts are attached"),
        _check("ISO-006", bool(user) and user not in {"0", "0:0", "root", "root:root"}, "container runs as a non-root configured user"),
        _check(
            "ISO-007",
            host.get("Privileged") is False
            and host.get("PublishAllPorts") is False
            and not (host.get("PortBindings") or {})
            and not (host.get("Devices") or [])
            and not (host.get("DeviceRequests") or []),
            "privileged mode, published ports, and host devices are absent",
        ),
        _check(
            "ISO-008",
            host.get("PidMode") in (None, "", "private")
            and host.get("IpcMode") == "private"
            and host.get("CgroupnsMode") == "private"
            and host.get("UTSMode") in (None, "", "private"),
            "PID, IPC, cgroup, and UTS namespaces are private",
        ),
        _check(
            "ISO-009",
            0 < int(host.get("PidsLimit") or 0) <= 128
            and 0 < int(host.get("Memory") or 0) <= 256 * 1024 * 1024
            and 0 < int(host.get("NanoCpus") or 0) <= 1_000_000_000
            and 0 < int(host.get("MemorySwap") or 0) <= int(host.get("Memory") or 0),
            "process, memory, swap, and CPU limits are bounded",
        ),
        _check("ISO-010", restricted_tmpfs, "writable tmpfs mounts prohibit execution and set-id use"),
    ]


def _run(command: list[str]) -> str:
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def collect_container(container: str) -> dict[str, Any]:
    raw = _run(["docker", "exec", container, "python", COLLECTOR])
    return json.loads(raw)


def inspect_container(container: str) -> dict[str, Any]:
    return json.loads(_run(["docker", "inspect", container]))[0]


def verify(container: str) -> dict[str, Any]:
    snapshot = collect_container(container)
    checks = (
        evaluate_isolation(inspect_container(container))
        + evaluate_runtime_isolation(snapshot)
        + evaluate_snapshot(snapshot)
    )
    return {
        "container": container,
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
        "snapshot": snapshot,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.container)
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.json:
        print(rendered)
    else:
        for item in result["checks"]:
            print(f"{'PASS' if item['passed'] else 'FAIL'} {item['id']}: {item['detail']}")
        print(f"OVERALL: {'PASS' if result['passed'] else 'FAIL'}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
