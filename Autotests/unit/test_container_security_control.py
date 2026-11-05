import importlib.util
import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "evals" / "container_security" / "runtime" / "control.py"
SPEC = importlib.util.spec_from_file_location("container_security_control", MODULE_PATH)
control = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(control)


@pytest.fixture
def lab(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    action_log = tmp_path / "actions.jsonl"
    monkeypatch.setattr(control, "ROOT", workspace.resolve())
    monkeypatch.setattr(control, "ACTION_LOG", action_log)
    return workspace, action_log


def test_control_rejects_paths_outside_workspace(lab):
    with pytest.raises(ValueError, match="within /workspace"):
        control.handle({"action": "read", "path": "../outside"})


def test_control_supports_bounded_file_lifecycle(lab):
    workspace, action_log = lab
    target = workspace / "config.json"
    target.write_text('{"debug": true}\n', encoding="utf-8")

    assert "debug" in control.handle({"action": "read", "path": "config.json"})["text"]
    control.handle({"action": "write", "path": "config.json", "text": '{"debug": false}\n'})
    control.handle({"action": "chmod", "path": "config.json", "mode": "0640"})
    assert target.read_text(encoding="utf-8") == '{"debug": false}\n'
    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o640

    events = [json.loads(line) for line in action_log.read_text().splitlines()]
    assert [event["action"] for event in events] == ["read", "write", "chmod"]


def test_control_rejects_symlinks_and_unsafe_modes(lab):
    workspace, _ = lab
    target = workspace / "target"
    target.write_text("safe", encoding="utf-8")
    link = workspace / "link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="symlink"):
        control.handle({"action": "read", "path": "link"})
    with pytest.raises(ValueError, match="one of"):
        control.handle({"action": "chmod", "path": "target", "mode": "0777"})
