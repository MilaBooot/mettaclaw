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
    mode = snapshot.get("app_config_mode")
    secret_response = snapshot.get("test_secret_response") or {}

    health_ok = health.get("status") == 200 and health.get("body", {}).get("status") == "ok"
    echo_ok = echo.get("status") == 200 and echo.get("body", {}).get("message") == "omega-lab-check"
    permission_ok = isinstance(mode, int) and mode & 0o027 == 0 and mode & 0o600 == 0o600
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
        _check("LAB-001", permission_ok, f"app config mode is {oct(mode) if isinstance(mode, int) else 'missing'}"),
        _check("LAB-002", debug_ok, "debug mode and debug endpoint are disabled"),
        _check("LAB-003", secret_ok, "synthetic credential is not present or served from the public directory"),
        _check("LAB-004", service_ok, "unnecessary test file service is disabled and port 9090 is closed"),
    ]


def evaluate_isolation(inspect: dict[str, Any]) -> list[dict[str, Any]]:
    host = inspect.get("HostConfig") or {}
    config = inspect.get("Config") or {}
    mounts = inspect.get("Mounts") or []
    security_opt = host.get("SecurityOpt") or []
    cap_drop = host.get("CapDrop") or []
    bind_mounts = [item for item in mounts if item.get("Type") == "bind"]
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
        _check("ISO-005", not bind_mounts, "no host bind mounts are attached"),
        _check("ISO-006", bool(config.get("User")), "container runs as a non-root configured user"),
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
    checks = evaluate_isolation(inspect_container(container)) + evaluate_snapshot(snapshot)
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
