from __future__ import annotations

import hmac
import json
import logging
import secrets
from functools import wraps
from typing import Any, Callable

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from .config import MonitorConfig
from .docker_backend import DockerActionError, DockerBackend
from .security_backend import SecurityEventReader


logger = logging.getLogger("oma_monitor.audit")


def create_app(
    config: MonitorConfig | None = None,
    backend: DockerBackend | None = None,
    security_backend: SecurityEventReader | None = None,
) -> Flask:
    settings = config or MonitorConfig.from_env()
    docker_backend = backend or DockerBackend(
        settings.container_name, settings.reconnect_seconds
    )
    csrf_token = secrets.token_urlsafe(32)
    event_reader = security_backend or SecurityEventReader(
        settings.security_events_file, settings.container_name
    )
    app = Flask(__name__)
    app.config.update(
        MONITOR_CONFIG=settings,
        DOCKER_BACKEND=docker_backend,
        SECURITY_BACKEND=event_reader,
        SEND_FILE_MAX_AGE_DEFAULT=0,
    )

    def authenticated(function: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            auth = request.authorization
            valid = bool(
                auth
                and (auth.type or "").lower() == "basic"
                and hmac.compare_digest((auth.username or "").encode(), settings.username.encode())
                and hmac.compare_digest((auth.password or "").encode(), settings.password.encode())
            )
            if not valid:
                return Response(
                    "Authentication required.\n",
                    401,
                    {"WWW-Authenticate": 'Basic realm="Oma monitor", charset="UTF-8"'},
                    content_type="text/plain; charset=utf-8",
                )
            return function(*args, **kwargs)

        return wrapped

    @app.after_request
    def security_headers(response: Response) -> Response:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'none'"
        )
        return response

    @app.get("/")
    @authenticated
    def index() -> str:
        return render_template(
            "index.html",
            container_name=settings.container_name,
            browser_log_limit=settings.browser_log_limit,
            csrf_token=csrf_token,
        )

    @app.get("/api/status")
    @authenticated
    def status() -> Response:
        if request.args:
            return jsonify({"error": "query parameters are not accepted"}), 400
        return jsonify(docker_backend.status())

    @app.get("/api/logs")
    @authenticated
    def logs() -> Response:
        if request.args:
            return jsonify({"error": "query parameters are not accepted"}), 400

        @stream_with_context
        def stream() -> Any:
            yield "retry: 3000\n\n"
            for event in docker_backend.log_events():
                event_type = "log" if event.get("type") == "log" else "system"
                yield f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

        return Response(
            stream(),
            content_type="text/event-stream; charset=utf-8",
            headers={"X-Accel-Buffering": "no"},
        )

    @app.post("/api/actions/<action>")
    @authenticated
    def action(action: str) -> Response:
        if request.args or action not in {"start", "stop", "restart"}:
            return jsonify({"error": "unsupported-action"}), 400
        if not request.is_json:
            return jsonify({"error": "application/json is required"}), 415
        candidate = request.headers.get("X-CSRF-Token", "")
        if not candidate or not hmac.compare_digest(candidate.encode(), csrf_token.encode()):
            return jsonify({"error": "invalid-csrf-token"}), 403
        if request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            return jsonify({"error": "cross-site-request-denied"}), 403

        try:
            result = docker_backend.perform_action(action)
        except DockerActionError as exc:
            logger.warning(
                "operator_action user=%s action=%s target=%s result=%s",
                settings.username,
                action,
                settings.container_name,
                exc.code,
            )
            return jsonify({"error": exc.code}), exc.http_status

        logger.info(
            "operator_action user=%s action=%s target=%s result=accepted",
            settings.username,
            action,
            settings.container_name,
        )
        return jsonify(result)

    @app.get("/api/security/status")
    @authenticated
    def security_status() -> Response:
        if request.args:
            return jsonify({"error": "query parameters are not accepted"}), 400
        return jsonify(event_reader.status())

    @app.get("/api/security/events")
    @authenticated
    def security_events() -> Response:
        if request.args:
            return jsonify({"error": "query parameters are not accepted"}), 400

        @stream_with_context
        def stream() -> Any:
            yield "retry: 3000\n\n"
            for event in event_reader.events():
                event_type = "security" if event.get("type") == "security" else "system"
                yield f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

        return Response(
            stream(),
            content_type="text/event-stream; charset=utf-8",
            headers={"X-Accel-Buffering": "no"},
        )

    return app


def main() -> None:
    from waitress import serve

    settings = MonitorConfig.from_env()
    app = create_app(settings)
    serve(app, host=settings.host, port=settings.port, threads=8)


if __name__ == "__main__":
    main()
