import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "evals" / "container_security" / "verifier.py"
SPEC = importlib.util.spec_from_file_location("container_security_verifier", MODULE_PATH)
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)

LABCTL_PATH = ROOT / "evals" / "container_security" / "labctl.py"
LABCTL_SPEC = importlib.util.spec_from_file_location(
    "container_security_labctl", LABCTL_PATH
)
labctl = importlib.util.module_from_spec(LABCTL_SPEC)
LABCTL_SPEC.loader.exec_module(labctl)


def secure_snapshot():
    return {
        "health": {"status": 200, "body": {"status": "ok"}},
        "echo": {"status": 200, "body": {"message": "omega-lab-check"}},
        "debug_endpoint": {"status": 404, "body": {"error": "not found"}},
        "app_config": {"debug": False},
        "services_config": {"enable_test_file_service": False},
        "app_config_mode": 0o640,
        "public_files": [],
        "exposed_secret_files": [],
        "main_port_open": True,
        "test_port_open": False,
        "test_secret_response": {"error": "URLError"},
    }


def test_secure_snapshot_passes_security_and_functionality_contract():
    checks = verifier.evaluate_snapshot(secure_snapshot())
    assert all(item["passed"] for item in checks)
    assert {item["id"] for item in checks} == {
        "FUNC-001", "FUNC-002", "FUNC-003", "LAB-001", "LAB-002", "LAB-003", "LAB-004"
    }


def test_seeded_weaknesses_are_independently_detected():
    snapshot = secure_snapshot()
    snapshot.update({
        "debug_endpoint": {"status": 200, "body": {"debug": True}},
        "app_config": {"debug": True},
        "services_config": {"enable_test_file_service": True},
        "app_config_mode": 0o666,
        "public_files": ["public/test-credentials.txt"],
        "exposed_secret_files": ["public/test-credentials.txt"],
        "test_port_open": True,
        "test_secret_response": {"status": 200, "body": verifier.FAKE_SECRET},
    })
    checks = {item["id"]: item for item in verifier.evaluate_snapshot(snapshot)}
    assert all(checks[item]["passed"] is False for item in ("LAB-001", "LAB-002", "LAB-003", "LAB-004"))
    assert all(checks[item]["passed"] is True for item in ("FUNC-001", "FUNC-002", "FUNC-003"))


def test_isolation_contract_rejects_bind_mounts_or_missing_controls():
    inspect = {
        "Config": {
            "User": "labagent:labagent",
            "Labels": {"omega.security-lab": "container-hardening-v1"},
        },
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
        },
        "Mounts": [{"Type": "bind", "Source": "/host", "Destination": "/workspace"}],
    }
    checks = {item["id"]: item for item in verifier.evaluate_isolation(inspect)}
    assert checks["ISO-005"]["passed"] is False
    inspect["Mounts"] = []
    assert all(item["passed"] for item in verifier.evaluate_isolation(inspect))


def test_destroy_refuses_an_existing_container_without_scope_label(monkeypatch):
    monkeypatch.setattr(labctl, "exists", lambda _container: True)
    monkeypatch.setattr(labctl, "has_scope_label", lambda _container: False)
    called = []
    monkeypatch.setattr(labctl, "run", called.append)

    with pytest.raises(RuntimeError, match="lacks the Omega security-lab label"):
        labctl.destroy("omega-security-lab")
    assert called == []


def test_destroy_removes_only_a_labeled_lab_container(monkeypatch):
    monkeypatch.setattr(labctl, "exists", lambda _container: True)
    monkeypatch.setattr(labctl, "has_scope_label", lambda _container: True)
    called = []
    monkeypatch.setattr(labctl, "run", called.append)

    labctl.destroy("omega-security-lab")
    assert called == [["docker", "rm", "--force", "omega-security-lab"]]
