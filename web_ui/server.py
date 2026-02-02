#!/usr/bin/env python3
import argparse
import json
import os
import threading
from collections import deque
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import requests

BASE_DIR = Path(__file__).resolve().parents[1]
LOG_PATH = BASE_DIR / "scripts" / "logs" / "sensor_logger.log"
ENV_PATH = BASE_DIR / "agent" / ".env"
DATA_DIR = BASE_DIR / "data"
SESSION_FILE_PATH = DATA_DIR / "current_session.json"
FIRESTORE_DATABASE = os.getenv("FIRESTORE_DATABASE", "ai-agentic-hackathon-4-db")
AGENT_API_URL = os.getenv("AGENT_API_URL", "http://agent:8080")
ALLOWED_KEYS = [
    "SENSOR_API_BASE",
    "GCS_BUCKET_NAME",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_REGION",
    "GOOGLE_GENAI_USE_VERTEXAI",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "MCP_SERVER_PATH",
    "AGENT_INSTRUCTION",
]
MAX_LOG_LINES = 200
MAX_BODY_BYTES = 100_000
ENV_LOCK = threading.Lock()
SESSION_LOCK = threading.Lock()


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
    with ENV_LOCK:
        lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines:
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
    with ENV_LOCK:
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


def get_current_session() -> dict:
    """Get the current session ID from the persistent file."""
    with SESSION_LOCK:
        try:
            if SESSION_FILE_PATH.exists():
                data = json.loads(SESSION_FILE_PATH.read_text(encoding="utf-8"))
                return {"session_id": data.get("session_id")}
        except Exception as exc:
            return {"error": str(exc)}
    return {"session_id": None}


def set_current_session(session_id: str) -> dict:
    """Set the current session ID in the persistent file."""
    with SESSION_LOCK:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            SESSION_FILE_PATH.write_text(
                json.dumps({"session_id": session_id}),
                encoding="utf-8"
            )
            return {"status": "ok", "session_id": session_id}
        except Exception as exc:
            return {"error": str(exc)}


def clear_current_session() -> dict:
    """Clear the current session ID from the persistent file."""
    with SESSION_LOCK:
        try:
            if SESSION_FILE_PATH.exists():
                SESSION_FILE_PATH.unlink()
            return {"status": "ok", "message": "Session cleared"}
        except Exception as exc:
            return {"error": str(exc)}


def create_new_session() -> dict:
    """Create a new session via the agent API."""
    try:
        session_url = f"{AGENT_API_URL}/apps/agent/users/default/sessions"
        resp = requests.post(session_url, json={}, timeout=30)
        if resp.status_code != 200:
            return {"error": f"Failed to create session at {session_url}: {resp.status_code} {resp.text}"}
        
        session_data = resp.json()
        session_id = session_data.get("id")
        if not session_id:
            session_id = session_data.get("name", "").split("/")[-1]
        
        if not session_id:
            return {"error": "Could not extract session_id from response"}
        
        # Save the new session as current
        set_current_session(session_id)
        return {"status": "ok", "session_id": session_id}
    except Exception as exc:
        return {"error": str(exc)}


def list_sessions() -> dict:
    """List available sessions from the agent API."""
    try:
        sessions_url = f"{AGENT_API_URL}/apps/agent/users/default/sessions"
        resp = requests.get(sessions_url, timeout=30)
        if resp.status_code != 200:
            return {"error": f"Failed to list sessions from {sessions_url}: {resp.status_code} {resp.text}"}
        
        sessions_data = resp.json()
        # The response format may vary; extract session list
        sessions = []
        if isinstance(sessions_data, list):
            for session in sessions_data:
                session_id = session.get("id") or session.get("name", "").split("/")[-1]
                if session_id:
                    sessions.append({
                        "id": session_id,
                        "created_at": session.get("created_at") or session.get("createTime"),
                        "updated_at": session.get("updated_at") or session.get("updateTime"),
                    })
        elif isinstance(sessions_data, dict) and "sessions" in sessions_data:
            for session in sessions_data["sessions"]:
                session_id = session.get("id") or session.get("name", "").split("/")[-1]
                if session_id:
                    sessions.append({
                        "id": session_id,
                        "created_at": session.get("created_at") or session.get("createTime"),
                        "updated_at": session.get("updated_at") or session.get("updateTime"),
                    })
        
        return {"sessions": sessions}
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
      button { margin-top: 10px; margin-right: 5px; }
      .session-item { padding: 8px; margin: 4px 0; border: 1px solid #ddd; border-radius: 4px; }
      .session-item.active { background-color: #e3f2fd; border-color: #2196F3; }
      .session-item button { margin: 0 5px 0 0; }
      .status-message { padding: 8px; margin-top: 8px; }
      .status-message.success { background-color: #d4edda; color: #155724; }
      .status-message.error { background-color: #f8d7da; color: #721c24; }
      .btn-danger { background-color: #dc3545; color: white; border: none; padding: 8px 16px; cursor: pointer; }
      .btn-danger:hover { background-color: #c82333; }
    </style>
  </head>
  <body>
    <h1>Edge Agent ログと設定</h1>
    
    <section>
      <h2>セッション管理</h2>
      <p>現在のセッションID: <strong id="current-session">読み込み中...</strong></p>
      <button onclick="createNewSession()">新規セッション作成</button>
      <button onclick="loadSessions()">セッション一覧を更新</button>
      <button class="btn-danger" onclick="clearSession()">セッション初期化</button>
      <div id="session-status"></div>
      <h3>利用可能なセッション</h3>
      <div id="sessions-list">読み込み中...</div>
    </section>
    
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
      let currentSessionId = null;

      function showSessionStatus(message, isError = false) {
        const status = document.getElementById("session-status");
        status.textContent = message;
        status.className = "status-message " + (isError ? "error" : "success");
        setTimeout(() => { status.textContent = ""; status.className = ""; }, 5000);
      }

      async function loadCurrentSession() {
        try {
          const response = await fetch("/api/session");
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const data = await response.json();
          currentSessionId = data.session_id;
          document.getElementById("current-session").textContent = currentSessionId || "(未設定)";
          return currentSessionId;
        } catch (error) {
          document.getElementById("current-session").textContent = `エラー: ${error}`;
          return null;
        }
      }

      async function loadSessions() {
        const container = document.getElementById("sessions-list");
        try {
          const response = await fetch("/api/sessions");
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const data = await response.json();
          if (data.error) {
            container.textContent = data.error;
            return;
          }
          const sessions = data.sessions || [];
          if (sessions.length === 0) {
            container.textContent = "セッションがありません";
            return;
          }
          container.innerHTML = "";
          sessions.forEach((session) => {
            const div = document.createElement("div");
            div.className = "session-item" + (session.id === currentSessionId ? " active" : "");
            
            const idSpan = document.createElement("span");
            idSpan.textContent = session.id;
            
            const selectBtn = document.createElement("button");
            selectBtn.textContent = "選択";
            selectBtn.onclick = () => selectSession(session.id);
            if (session.id === currentSessionId) {
              selectBtn.disabled = true;
            }
            
            div.appendChild(selectBtn);
            div.appendChild(idSpan);
            if (session.updated_at) {
              const timeSpan = document.createElement("span");
              timeSpan.style.marginLeft = "10px";
              timeSpan.style.color = "#666";
              timeSpan.textContent = ` (更新: ${session.updated_at})`;
              div.appendChild(timeSpan);
            }
            container.appendChild(div);
          });
        } catch (error) {
          container.textContent = `取得エラー: ${error}`;
        }
      }

      async function selectSession(sessionId) {
        try {
          const response = await fetch("/api/session", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessionId }),
          });
          const data = await response.json();
          if (!response.ok || data.error) {
            throw new Error(data.error || `HTTP ${response.status}`);
          }
          currentSessionId = sessionId;
          document.getElementById("current-session").textContent = sessionId;
          showSessionStatus(`セッション ${sessionId} を選択しました`);
          loadSessions();
        } catch (error) {
          showSessionStatus(`エラー: ${error}`, true);
        }
      }

      async function createNewSession() {
        try {
          const response = await fetch("/api/session/new", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
          });
          const data = await response.json();
          if (!response.ok || data.error) {
            throw new Error(data.error || `HTTP ${response.status}`);
          }
          currentSessionId = data.session_id;
          document.getElementById("current-session").textContent = data.session_id;
          showSessionStatus(`新規セッション ${data.session_id} を作成しました`);
          loadSessions();
        } catch (error) {
          showSessionStatus(`エラー: ${error}`, true);
        }
      }

      async function clearSession() {
        if (!confirm("現在のセッションを初期化しますか？次回のスケジューラー実行時に新しいセッションが作成されます。")) {
          return;
        }
        try {
          const response = await fetch("/api/session/clear", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
          });
          const data = await response.json();
          if (!response.ok || data.error) {
            throw new Error(data.error || `HTTP ${response.status}`);
          }
          currentSessionId = null;
          document.getElementById("current-session").textContent = "(未設定)";
          showSessionStatus("セッションを初期化しました。次回実行時に新しいセッションが作成されます。");
          loadSessions();
        } catch (error) {
          showSessionStatus(`エラー: ${error}`, true);
        }
      }

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
        const status = document.getElementById("settings-status");
        status.textContent = "";
        try {
          const response = await fetch("/api/settings");
          if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
          }
          const data = await response.json();
          renderSettings(data.settings || {});
        } catch (error) {
          status.textContent = `エラー: ${error}`;
        }
      }

      async function saveSettings() {
        const payload = {};
        const status = document.getElementById("settings-status");
        status.textContent = "";
        allowedKeys.forEach((key) => {
          payload[key] = document.getElementById(`setting-${key}`).value || "";
        });
        try {
          const response = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          const data = await response.json();
          if (!response.ok || data.error) {
            throw new Error(data.error || `HTTP ${response.status}`);
          }
          status.textContent = "保存しました";
        } catch (error) {
          status.textContent = `エラー: ${error}`;
        }
      }

      async function loadLogs() {
        const target = document.getElementById("sensor-logs");
        try {
          const response = await fetch("/api/logs");
          if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
          }
          const data = await response.json();
          if (data.error) {
            target.textContent = data.error;
          } else {
            target.textContent = (data.lines || []).join("");
          }
        } catch (error) {
          target.textContent = `取得エラー: ${error}`;
        }
      }

      async function loadFirestore() {
        const target = document.getElementById("firestore-logs");
        try {
          const response = await fetch("/api/firestore");
          if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
          }
          const data = await response.json();
          if (data.error) {
            target.textContent = data.error;
          } else {
            target.textContent = JSON.stringify(data.entries || [], null, 2);
          }
        } catch (error) {
          target.textContent = `取得エラー: ${error}`;
        }
      }

      // Initialize
      loadCurrentSession().then(() => {
        loadSessions();
      });
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
        if parsed.path == "/api/session":
            self._send_json(get_current_session())
            return
        if parsed.path == "/api/sessions":
            self._send_json(list_sessions())
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def _read_json_body(self) -> dict | None:
        """Read and parse JSON body from request. Returns None on error (response already sent)."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"error": "Invalid Content-Length."}, status=HTTPStatus.BAD_REQUEST)
            return None
        if length < 0 or length > MAX_BODY_BYTES:
            self._send_json({"error": "Request too large."}, status=HTTPStatus.BAD_REQUEST)
            return None
        try:
            body = self.rfile.read(length).decode("utf-8") if length else ""
        except UnicodeDecodeError:
            self._send_json({"error": "Invalid request encoding."}, status=HTTPStatus.BAD_REQUEST)
            return None
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return None
        if not isinstance(payload, dict):
            self._send_json({"error": "リクエスト本文はJSONオブジェクトである必要があります。"}, status=HTTPStatus.BAD_REQUEST)
            return None
        return payload

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        
        # Session management endpoints
        if parsed.path == "/api/session":
            payload = self._read_json_body()
            if payload is None:
                return
            session_id = payload.get("session_id")
            if not session_id:
                self._send_json({"error": "session_id is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(set_current_session(session_id))
            return
        
        if parsed.path == "/api/session/new":
            self._send_json(create_new_session())
            return
        
        if parsed.path == "/api/session/clear":
            self._send_json(clear_current_session())
            return
        
        if parsed.path == "/api/settings":
            payload = self._read_json_body()
            if payload is None:
                return
            try:
                update_env_settings(ENV_PATH, payload)
            except OSError as exc:
                self.log_error("Failed to update settings: %s", exc)
                self._send_json({"error": "Failed to update settings."}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._send_json({"status": "ok"})
            return
        
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

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

    def _is_local_origin(self) -> bool:
        origin = self.headers.get("Origin") or self.headers.get("Referer")
        if not origin:
            return True
        parsed = urlparse(origin)
        host = parsed.hostname
        return host in {"localhost", "127.0.0.1"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Local web UI for logs/settings.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    # if args.host not in {"127.0.0.1", "localhost"}:
    #     raise SystemExit("Refusing to bind to non-localhost address.")
    server = ThreadingHTTPServer((args.host, args.port), RequestHandler)
    print(f"Serving on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        # Allow clean shutdown on Ctrl+C without printing a traceback.
        pass


if __name__ == "__main__":
    main()
