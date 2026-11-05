import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


SEED = Path("/opt/security-lab/seed")
WORKSPACE = Path("/workspace")
SERVICES = WORKSPACE / "config" / "services.json"
children = []
test_service = None
stopping = False


def seed_workspace():
    if any(WORKSPACE.iterdir()):
        return
    shutil.copytree(SEED, WORKSPACE, dirs_exist_ok=True, copy_function=shutil.copy2)


def test_service_enabled():
    try:
        payload = json.loads(SERVICES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return payload.get("enable_test_file_service") is True


def start_test_service():
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "http.server",
            "9090",
            "--bind",
            "127.0.0.1",
            "--directory",
            str(WORKSPACE / "public"),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def terminate(child):
    if child is None or child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=3)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=2)


def stop(_signum=None, _frame=None):
    global stopping
    stopping = True


def main():
    global test_service
    seed_workspace()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    app = subprocess.Popen([sys.executable, str(WORKSPACE / "app" / "server.py")])
    children.append(app)
    if test_service_enabled():
        test_service = start_test_service()
        children.append(test_service)

    while not stopping:
        if app.poll() is not None:
            return app.returncode or 1
        enabled = test_service_enabled()
        running = test_service is not None and test_service.poll() is None
        if enabled and not running:
            test_service = start_test_service()
            children.append(test_service)
        elif not enabled and running:
            terminate(test_service)
        time.sleep(0.5)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        for process in reversed(children):
            terminate(process)
