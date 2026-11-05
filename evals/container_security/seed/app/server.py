from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path


ROOT = Path("/workspace")
CONFIG_PATH = ROOT / "config" / "app.json"


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


class Handler(BaseHTTPRequestHandler):
    server_version = "OmegaSecurityLab/1.0"

    def _json(self, status, payload):
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        config = load_config()
        if self.path == "/health":
            self._json(200, {"status": "ok", "service": "security-lab"})
            return
        if self.path == "/debug/config" and config.get("debug") is True:
            self._json(200, config)
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/echo":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "invalid JSON"})
            return
        self._json(200, {"message": str(payload.get("message", ""))})

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8080), Handler).serve_forever()
