from pathlib import Path
import re

from monitor.app import create_app
from monitor.config import MonitorConfig


class FakeBackend:
    def __init__(self):
        self.status_calls = 0
        self.actions = []

    def status(self):
        self.status_calls += 1
        return {
            "state": "running",
            "container": "omega",
            "container_id": "abc123",
            "docker_status": "running",
            "agent_healthy": None,
            "checked_at": "2026-01-01T00:00:00Z",
        }

    def log_events(self):
        yield {"type": "log", "text": "<img src=x onerror=alert(1)>"}

    def perform_action(self, action):
        self.actions.append(action)
        result = self.status()
        result["action"] = action
        return result


def make_client():
    config = MonitorConfig(username="operator", password="long-test-password")
    backend = FakeBackend()
    app = create_app(config, backend)
    app.testing = True
    return app.test_client(), backend


def auth():
    return {"Authorization": "Basic b3BlcmF0b3I6bG9uZy10ZXN0LXBhc3N3b3Jk"}


def test_page_status_stream_controls_and_security_require_authentication():
    client, _ = make_client()
    for path in (
        "/",
        "/api/status",
        "/api/logs",
        "/api/security/status",
        "/api/security/events",
    ):
        response = client.get(path)
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"].startswith("Basic ")
        assert response.headers["Cache-Control"] == "no-store"
    assert client.post("/api/actions/stop", json={}).status_code == 401


def test_invalid_credentials_are_denied():
    client, _ = make_client()
    response = client.get(
        "/api/status", headers={"Authorization": "Basic b3BlcmF0b3I6d3Jvbmc="}
    )
    assert response.status_code == 401


def test_authenticated_status_uses_only_configured_backend():
    client, backend = make_client()
    response = client.get("/api/status", headers=auth())
    assert response.status_code == 200
    assert response.json["container"] == "omega"
    assert response.json["agent_healthy"] is None
    assert backend.status_calls == 1


def test_query_parameters_cannot_select_a_container():
    client, backend = make_client()
    response = client.get("/api/status?container=other", headers=auth())
    assert response.status_code == 400
    assert backend.status_calls == 0
    response = client.get("/api/logs?container=other", headers=auth())
    assert response.status_code == 400


def test_lifecycle_action_requires_csrf_and_json():
    client, backend = make_client()
    assert client.post("/api/actions/stop", headers=auth()).status_code == 415
    assert client.post("/api/actions/stop", headers=auth(), json={}).status_code == 403
    assert backend.actions == []


def test_lifecycle_action_uses_fixed_backend_target():
    client, backend = make_client()
    page = client.get("/", headers=auth()).get_data(as_text=True)
    token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
    headers = {**auth(), "X-CSRF-Token": token}
    response = client.post("/api/actions/restart", headers=headers, json={})
    assert response.status_code == 200
    assert response.json["action"] == "restart"
    assert backend.actions == ["restart"]
    assert client.post(
        "/api/actions/start?container=other", headers=headers, json={}
    ).status_code == 400
    assert backend.actions == ["restart"]


def test_cross_site_lifecycle_action_is_denied():
    client, backend = make_client()
    page = client.get("/", headers=auth()).get_data(as_text=True)
    token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
    response = client.post(
        "/api/actions/stop",
        headers={**auth(), "X-CSRF-Token": token, "Sec-Fetch-Site": "cross-site"},
        json={},
    )
    assert response.status_code == 403
    assert backend.actions == []


def test_log_stream_serializes_untrusted_text_as_data():
    client, _ = make_client()
    response = client.get("/api/logs", headers=auth())
    body = response.get_data(as_text=True)
    assert response.content_type == "text/event-stream; charset=utf-8"
    assert '"text": "<img src=x onerror=alert(1)>"' in body


def test_browser_renders_logs_with_text_content_only():
    script = (Path(__file__).parents[1] / "static" / "monitor.js").read_text(
        encoding="utf-8"
    )
    assert "logView.textContent" in script
    assert "innerHTML" not in script
