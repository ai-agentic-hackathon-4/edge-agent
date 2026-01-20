#!/usr/bin/env python3
import argparse
import json
import os
from collections import deque
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parents[1]
LOG_PATH = BASE_DIR / "scripts" / "logs" / "sensor_logger.log"
ENV_PATH = BASE_DIR / "agent" / ".env"
FIRESTORE_DATABASE = os.getenv("FIRESTORE_DATABASE", "ai-agentic-hackathon-4-db")
ALLOWED_KEYS = [
    "SENSOR_API_BASE",
    "GCS_BUCKET_NAME",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_REGION",
    "MCP_SERVER_PATH",
    "AGENT_INSTRUCTION",
]
MAX_LOG_LINES = 200
MAX_BODY_BYTES = 100_000


def tail_lines(path: Path, max_lines: int) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return list(deque(handle, max_lines))


def sanitize_value(value: str) -> str:
    return value.replace("\n", "").replace("\r", "")


def read_env_settings(path: Path) -> dict[str, str]:
    settings: dict[str, str] = {}
    if not path.exists():
        return settings
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if not key:
            continue
        key = key.strip()
        if key in ALLOWED_KEYS:
            settings[key] = value.strip()
    return settings


def update_env_settings(path: Path, updates: dict[str, str]) -> None:
    filtered_updates = {
        key: sanitize_value(str(value))
        for key, value in updates.items()
        if key in ALLOWED_KEYS
    }
    lines = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    remaining = dict(filtered_updates)
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key, _ = stripped.split("=", 1)
        if not key:
            new_lines.append(line)
            continue
        key = key.strip()
        if key in remaining:
            new_lines.append(f"{key}={remaining.pop(key)}")
        else:
            new_lines.append(line)
    for key, value in remaining.items():
        new_lines.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(new_lines)
    if content:
        content += "\n"
    path.write_text(content, encoding="utf-8")


def make_json_safe(value) -> object:
    """Convert Firestore payloads into JSON-serializable values."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: make_json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [make_json_safe(item) for item in value]
    return value


def fetch_firestore_logs(limit: int = 20) -> dict:
    try:
        from google.cloud import firestore  # type: ignore
    except ImportError as exc:
        return {"error": f"Firestore not available: {exc}"}
    try:
        client = firestore.Client(database=FIRESTORE_DATABASE)
        query = (
            client.collection("agent_execution_logs")
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        entries = []
        for doc in query.stream():
            entries.append(
                {
                    "id": doc.id,
                    "data": make_json_safe(doc.to_dict() or {}),
                }
            )
        return {"entries": entries}
    except Exception as exc:
        return {"error": str(exc)}


HTML_PAGE = """<!doctype html>
<html lang="ja">
  <head>
    <meta charset="utf-8" />
    <title>Edge Agent ログと設定</title>
    <style>
      body { font-family: Arial, sans-serif; margin: 20px; }
      pre { background: #f5f5f5; padding: 12px; white-space: pre-wrap; }
      label { display: block; margin-top: 8px; }
      input[type="text"] { width: 100%; padding: 6px; }
      button { margin-top: 10px; }
    </style>
  </head>
  <body>
    <h1>Edge Agent ログと設定</h1>
    <section>
      <h2>センサーロガーのログ</h2>
      <button onclick="loadLogs()">ログを更新</button>
      <pre id="sensor-logs">読み込み中...</pre>
    </section>
    <section>
      <h2>Firestore agent_execution_logs（任意）</h2>
      <button onclick="loadFirestore()">Firestoreログを更新</button>
      <pre id="firestore-logs">読み込み中...</pre>
    </section>
    <section>
      <h2>設定</h2>
      <div id="settings-form"></div>
      <button onclick="saveSettings()">設定を保存</button>
      <div id="settings-status"></div>
    </section>
    <script>
      const allowedKeys = __ALLOWED_KEYS__;

      function renderSettings(settings) {
        const container = document.getElementById("settings-form");
        container.innerHTML = "";
        allowedKeys.forEach((key) => {
          const label = document.createElement("label");
          label.textContent = key;
          const input = document.createElement("input");
          input.type = "text";
          input.value = settings[key] || "";
          input.id = `setting-${key}`;
          container.appendChild(label);
          container.appendChild(input);
        });
      }

      async function loadSettings() {
        const response = await fetch("/api/settings");
        const data = await response.json();
        renderSettings(data.settings || {});
      }

      async function saveSettings() {
        const payload = {};
        allowedKeys.forEach((key) => {
          payload[key] = document.getElementById(`setting-${key}`).value || "";
        });
        const response = await fetch("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await response.json();
        document.getElementById("settings-status").textContent =
          data.error ? `エラー: ${data.error}` : "保存しました";
      }

      async function loadLogs() {
        const response = await fetch("/api/logs");
        const data = await response.json();
        const target = document.getElementById("sensor-logs");
        if (data.error) {
          target.textContent = data.error;
        } else {
          target.textContent = (data.lines || []).join("");
        }
      }

      async function loadFirestore() {
        const response = await fetch("/api/firestore");
        const data = await response.json();
        const target = document.getElementById("firestore-logs");
        if (data.error) {
          target.textContent = data.error;
        } else {
          target.textContent = JSON.stringify(data.entries || [], null, 2);
        }
      }

      loadSettings();
      loadLogs();
      loadFirestore();
    </script>
  </body>
</html>
"""


class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html()
            return
        if parsed.path == "/api/logs":
            self._send_json(self._get_logs())
            return
        if parsed.path == "/api/firestore":
            self._send_json(fetch_firestore_logs())
            return
        if parsed.path == "/api/settings":
            self._send_json({"settings": read_env_settings(ENV_PATH)})
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/settings":
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"error": "Invalid Content-Length."}, status=HTTPStatus.BAD_REQUEST)
            return
        if length < 0 or length > MAX_BODY_BYTES:
            self._send_json({"error": "Request too large."}, status=HTTPStatus.BAD_REQUEST)
            return
        try:
            body = self.rfile.read(length).decode("utf-8") if length else ""
        except UnicodeDecodeError:
            self._send_json({"error": "Invalid request encoding."}, status=HTTPStatus.BAD_REQUEST)
            return
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        try:
            update_env_settings(ENV_PATH, payload)
        except OSError as exc:
            self.log_error("Failed to update settings: %s", exc)
            self._send_json({"error": "Failed to update settings."}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self._send_json({"status": "ok"})

    def _get_logs(self) -> dict:
        lines = tail_lines(LOG_PATH, MAX_LOG_LINES)
        if not lines:
            return {"error": f"Log file not found: {LOG_PATH}"}
        return {"lines": lines}

    def _send_html(self) -> None:
        content = HTML_PAGE.replace("__ALLOWED_KEYS__", json.dumps(ALLOWED_KEYS))
        encoded = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local web UI for logs/settings.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), RequestHandler)
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Refusing to bind to non-localhost address.")
    print(f"Serving on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
