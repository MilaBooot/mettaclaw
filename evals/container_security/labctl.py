#!/usr/bin/env python3
"""Build, reset, inspect, and verify the disposable security lab."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent
DEFAULT_IMAGE = "omega-security-lab:local"
DEFAULT_CONTAINER = "omega-security-lab"
SCOPE_LABEL = "omega.security-lab=container-hardening-v1"


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, text=True)


def exists(container: str) -> bool:
    result = subprocess.run(
        ["docker", "container", "inspect", container],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def has_scope_label(container: str) -> bool:
    result = subprocess.run(
        [
            "docker", "container", "inspect",
            "--format={{ index .Config.Labels \"omega.security-lab\" }}",
            container,
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "container-hardening-v1"


def build(image: str) -> None:
    run(["docker", "build", "--tag", image, str(ROOT)])


def destroy(container: str) -> None:
    if exists(container):
        if not has_scope_label(container):
            raise RuntimeError(
                f"refusing to remove {container}: target lacks the Omega security-lab label"
            )
        run(["docker", "rm", "--force", container])


def reset(image: str, container: str) -> None:
    destroy(container)
    run(
        [
            "docker",
            "run",
            "--detach",
            "--name",
            container,
            "--label",
            SCOPE_LABEL,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "128",
            "--memory",
            "256m",
            "--cpus",
            "1.0",
            "--tmpfs",
            "/run:rw,noexec,nosuid,size=16m,uid=10001,gid=10001,mode=0750",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=16m,uid=10001,gid=10001,mode=0750",
            "--tmpfs",
            "/workspace:rw,noexec,nosuid,size=32m,uid=10001,gid=10001,mode=0750",
            image,
        ]
    )
    wait_ready(container)
    print(f"Reset {container} from {image}")


def wait_ready(container: str, timeout_seconds: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "exec", container, "python", "/opt/security-lab/bin/collector.py"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            try:
                snapshot = json.loads(result.stdout)
            except ValueError:
                snapshot = {}
            if snapshot.get("health", {}).get("status") == 200:
                return
        time.sleep(0.25)
    raise RuntimeError(f"{container} did not become healthy within {timeout_seconds:g}s")


def verify(container: str, extra: list[str]) -> int:
    return subprocess.run(
        [sys.executable, str(ROOT / "verifier.py"), "--container", container, *extra]
    ).returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build")
    commands.add_parser("reset")
    commands.add_parser("destroy")
    commands.add_parser("status")
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.command == "build":
        build(args.image)
    elif args.command == "reset":
        reset(args.image, args.container)
    elif args.command == "destroy":
        destroy(args.container)
    elif args.command == "status":
        run(["docker", "ps", "--filter", f"name=^{args.container}$"])
    elif args.command == "verify":
        return verify(args.container, ["--json"] if args.json else [])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
