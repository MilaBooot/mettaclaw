"""Narrow mutation boundary used by the evaluation-only OpenClaw tools."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys


ROOT = Path("/workspace").resolve()
ACTION_LOG = Path("/run/security-lab/actions.jsonl")
MAX_TEXT_BYTES = 16_384
ALLOWED_MODES = {0o600, 0o640, 0o644}


def target_path(value):
    raw = Path(str(value))
    if not raw.is_absolute():
        raw = ROOT / raw
    if raw.is_symlink():
        raise ValueError("symlink targets are not allowed")
    resolved = raw.resolve(strict=False)
    try:
        resolved.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError("path must stay within /workspace") from exc
    if resolved == ROOT:
        raise ValueError("operation requires a file below /workspace")
    return resolved


def require_regular_file(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("target must be an existing regular file")


def record(action, path=None):
    ACTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "path": str(path) if path else None,
    }
    with ACTION_LOG.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def list_files():
    entries = []
    for path in sorted(ROOT.rglob("*")):
        if path.is_symlink():
            kind = "symlink"
        elif path.is_dir():
            kind = "directory"
        elif path.is_file():
            kind = "file"
        else:
            kind = "other"
        entries.append({
            "path": str(path),
            "kind": kind,
            "mode": oct(path.lstat().st_mode & 0o777),
            "size": path.stat().st_size if path.is_file() else 0,
        })
        if len(entries) >= 200:
            break
    return {"entries": entries}


def handle(payload):
    action = str(payload.get("action", ""))
    if action == "list":
        record(action)
        return list_files()
    if action == "actions":
        text = ACTION_LOG.read_text(encoding="utf-8") if ACTION_LOG.exists() else ""
        return {"events": [json.loads(line) for line in text.splitlines()[-100:]]}

    path = target_path(payload.get("path", ""))
    if action == "read":
        require_regular_file(path)
        data = path.read_bytes()
        if len(data) > MAX_TEXT_BYTES:
            raise ValueError(f"file exceeds {MAX_TEXT_BYTES} byte read limit")
        record(action, path)
        return {"path": str(path), "text": data.decode("utf-8", errors="replace")}
    if action == "write":
        require_regular_file(path)
        text = str(payload.get("text", ""))
        encoded = text.encode("utf-8")
        if len(encoded) > MAX_TEXT_BYTES:
            raise ValueError(f"content exceeds {MAX_TEXT_BYTES} byte write limit")
        path.write_bytes(encoded)
        record(action, path)
        return {"path": str(path), "bytes": len(encoded)}
    if action == "chmod":
        require_regular_file(path)
        mode_text = str(payload.get("mode", ""))
        try:
            mode = int(mode_text, 8)
        except ValueError as exc:
            raise ValueError("mode must be an octal string") from exc
        if mode not in ALLOWED_MODES:
            raise ValueError("mode must be one of 0600, 0640, or 0644")
        os.chmod(path, mode)
        record(action, path)
        return {"path": str(path), "mode": oct(mode)}
    if action == "remove":
        require_regular_file(path)
        path.unlink()
        record(action, path)
        return {"path": str(path), "removed": True}
    raise ValueError("unsupported action")


def main():
    try:
        payload = json.load(sys.stdin)
        result = {"ok": True, "result": handle(payload)}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
