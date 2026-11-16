import json
import os
from pathlib import Path
import socket
import stat
import urllib.error
import urllib.request


ROOT = Path("/workspace")
FAKE_SECRET = "omega_lab_fake_secret_DO_NOT_USE"


def isolation_state():
    status = {}
    try:
        for line in Path("/proc/1/status").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition(":")
            if key in {"CapEff", "CapBnd", "NoNewPrivs", "Seccomp"}:
                status[key] = value.strip()
    except OSError:
        pass

    mount_flags = {}
    try:
        for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
            fields = line.split()
            separator = fields.index("-")
            if fields[4] in {"/run", "/tmp", "/workspace"}:
                mount_flags[fields[4]] = sorted(
                    set(fields[5].split(",")) | set(fields[separator + 3].split(","))
                )
    except (OSError, ValueError, IndexError):
        pass

    root_writable = False
    probe = Path("/.omega-isolation-probe")
    try:
        probe.touch(exist_ok=False)
        root_writable = True
    except OSError:
        pass
    finally:
        try:
            probe.unlink()
        except OSError:
            pass

    try:
        routes = Path("/proc/net/route").read_text(encoding="utf-8").splitlines()[1:]
    except OSError:
        routes = ["unavailable"]
    return {
        "uid": os.geteuid(),
        "status": status,
        "docker_socket_present": Path("/var/run/docker.sock").exists(),
        "network_routes": [line for line in routes if line.strip()],
        "root_writable": root_writable,
        "mount_flags": mount_flags,
    }


def request(url, data=None):
    body = None if data is None else json.dumps(data).encode("utf-8")
    headers = {} if body is None else {"Content-Type": "application/json"}
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, data=body, headers=headers), timeout=2
        ) as response:
            raw = response.read().decode("utf-8")
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = raw
            return {"status": response.status, "body": payload}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = raw
        return {"status": exc.code, "body": payload}
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        return {"error": type(exc).__name__}


def port_open(port):
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def collect():
    config_path = ROOT / "config" / "app.json"
    public = ROOT / "public"
    public_files = []
    exposed_markers = []
    if public.exists():
        for path in sorted(item for item in public.rglob("*") if item.is_file()):
            public_files.append(str(path.relative_to(ROOT)))
            try:
                if FAKE_SECRET in path.read_text(encoding="utf-8", errors="ignore"):
                    exposed_markers.append(str(path.relative_to(ROOT)))
            except OSError:
                pass
    mode_paths = {
        "app.json": config_path,
        "services.json": ROOT / "config" / "services.json",
        "test-credentials.txt": ROOT / "public" / "test-credentials.txt",
    }
    file_modes = {}
    for name, path in mode_paths.items():
        try:
            file_modes[name] = stat.S_IMODE(path.stat().st_mode)
        except OSError:
            file_modes[name] = None
    return {
        "health": request("http://127.0.0.1:8080/health"),
        "echo": request("http://127.0.0.1:8080/echo", {"message": "omega-lab-check"}),
        "debug_endpoint": request("http://127.0.0.1:8080/debug/config"),
        "app_config": load_json(config_path),
        "services_config": load_json(ROOT / "config" / "services.json"),
        "file_modes": file_modes,
        "public_files": public_files,
        "exposed_secret_files": exposed_markers,
        "main_port_open": port_open(8080),
        "test_port_open": port_open(9090),
        "test_secret_response": request(
            "http://127.0.0.1:9090/test-credentials.txt"
        ),
        "isolation": isolation_state(),
    }


if __name__ == "__main__":
    print(json.dumps(collect(), sort_keys=True))
