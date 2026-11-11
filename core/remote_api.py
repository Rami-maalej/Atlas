"""MARK XL — localhost HTTP task bridge for the phone.

Serves a token-protected JSON API plus a phone-friendly control page so the
Android app (or any mobile browser) can run tasks on the PC over a simple
``http://<pc-ip>:8767/?token=…`` link.

Endpoints
---------
``GET  /``             Mobile control page (task buttons + command box)
``GET  /api/ping``     Liveness probe: ``{"ok": true, "app": "MARK XL"}``
``GET  /api/tasks``    Registry of runnable tasks
``POST /api/task``     ``{"name": "open_app", "args": {...}}`` → run a task
``POST /api/command``  ``{"text": "open firefox"}`` → natural-language command

Authentication
--------------
Every request must carry the token via ``Authorization: Bearer <token>``,
``X-Token: <token>``, or ``?token=<token>``. The token is generated on first
run and stored in ``config/remote_token.txt`` (0600, gitignored).

Example:
    >>> server = RemoteAPIServer(runner=lambda n, a: "ok")
    >>> server.start_background()          # thread + port from constructor
    >>> server.url                          # 'http://0.0.0.0:8767/?token=…'
"""

from __future__ import annotations

import json
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
TOKEN_FILE = CONFIG_DIR / "remote_token.txt"

TaskRunner = Callable[[str, dict[str, Any]], str]
CommandRunner = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """One task advertised to the phone UI."""

    name: str
    label: str
    description: str = ""


#: Default task registry shown as buttons on the control page.
DEFAULT_TASKS: tuple[TaskSpec, ...] = (
    TaskSpec("open_app", "Open app", "Launch a program: args {\"name\": \"firefox\"}"),
    TaskSpec("system_info", "System info", "CPU / RAM / disk summary"),
    TaskSpec("battery_status", "Battery", "Battery level and state"),
    TaskSpec("weather_report", "Weather", "Local weather report"),
    TaskSpec("screenshot", "Screenshot", "Capture the screen"),
    TaskSpec("clipboard_read", "Clipboard", "Read the clipboard"),
    TaskSpec("quick_note_list", "Notes", "List quick notes"),
    TaskSpec("web_search", "Web search", "Search the web: args {\"query\": \"…\"}"),
    TaskSpec("read_emails", "Read emails", "Latest emails from the inbox"),
    TaskSpec("open_mail_screen", "Mail screen", "Open the desktop mail screen"),
)


class RemoteAPIError(Exception):
    """Raised for client-visible API failures (bad token, bad payload)."""


def load_or_create_token(path: Path | None = None) -> str:
    """Load the API token, creating a 32-byte one on first run.

    Args:
        path: Token file location (defaults to ``config/remote_token.txt``).

    Returns:
        The hex token string.
    """
    token_path = path or TOKEN_FILE
    try:
        existing = token_path.read_text(encoding="utf-8").strip()
        if len(existing) >= 16:
            return existing
    except OSError:
        pass
    token = secrets.token_hex(16)
    try:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(token, encoding="utf-8")
        try:
            token_path.chmod(0o600)
        except OSError:
            pass
    except OSError as exc:
        raise RemoteAPIError(f"Cannot write token file {token_path}: {exc}") from exc
    return token


def check_token(expected: str, request_token: str | None) -> bool:
    """Constant-time token comparison.

    Args:
        expected: Server token.
        request_token: Token supplied by the client (may be ``None``).

    Returns:
        ``True`` when they match.
    """
    if not expected or not request_token:
        return False
    return secrets.compare_digest(expected, request_token)


def extract_token(handler: BaseHTTPRequestHandler) -> str | None:
    """Pull the token from a request (header, bearer, or query string).

    Args:
        handler: Request handler carrying headers/path.

    Returns:
        The token if present, else ``None``.
    """
    header = (
        handler.headers.get("X-Token")
        or handler.headers.get("Authorization")
        or ""
    ).strip()
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    if header:
        return header
    query = parse_qs(urlparse(handler.path).query)
    values = query.get("token")
    return values[0] if values else None


def _page_html(token: str) -> str:
    """Render the mobile control page (single file, no external assets)."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MARK XL — Remote</title>
<style>
  :root {{ --acc:#007AFF; --line:#333; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:#000; color:#fff; font-family:system-ui,sans-serif; }}
  header {{ padding:14px 16px; border-bottom:1px solid var(--line);
            display:flex; justify-content:space-between; align-items:center; }}
  h1 {{ font-size:16px; margin:0; letter-spacing:2px; }}
  #state {{ font-size:11px; color:#888; }}
  .wrap {{ padding:14px; }}
  .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }}
  button {{ background:#000; color:#fff; border:1px solid var(--line);
            border-radius:0; padding:14px 8px; font-size:13px; }}
  button:active {{ background:var(--acc); border-color:var(--acc); }}
  input,textarea {{ width:100%; background:#111; color:#fff; border:1px solid var(--line);
            padding:12px; font-size:14px; border-radius:0; }}
  #cmd {{ display:flex; gap:8px; margin-top:14px; }}
  #cmd button {{ flex:0 0 84px; background:var(--acc); border-color:var(--acc); }}
  #out {{ margin-top:14px; white-space:pre-wrap; font-size:12px; color:#9ad;
          border:1px solid var(--line); padding:10px; min-height:60px; display:none; }}
  .hint {{ font-size:11px; color:#666; margin:10px 0 4px; }}
</style>
</head>
<body>
<header><h1>MARK XL</h1><span id="state">connecting…</span></header>
<div class="wrap">
  <div class="hint">TASKS — tap to run on your PC</div>
  <div class="grid" id="tasks"></div>
  <div class="hint">COMMAND — type anything for Jarvis</div>
  <div id="cmd">
    <input id="text" placeholder="open firefox, what time is it…" />
    <button onclick="sendCmd()">RUN</button>
  </div>
  <div id="out"></div>
</div>
<script>
const TOKEN = {json.dumps(token)};
const api = (path, opts) => {{
  const sep = path.includes("?") ? "&" : "?";
  return fetch(path + sep + "token=" + encodeURIComponent(TOKEN), opts);
}};
const out = (t) => {{ const el = document.getElementById("out");
  el.style.display = "block"; el.textContent = t; }};
async function ping() {{
  try {{
    const r = await api("/api/ping");
    const j = await r.json();
    document.getElementById("state").textContent = j.ok ? "● PC online" : "● error";
  }} catch (e) {{ document.getElementById("state").textContent = "● offline"; }}
}}
async function loadTasks() {{
  try {{
    const r = await api("/api/tasks");
    const j = await r.json();
    const grid = document.getElementById("tasks");
    grid.innerHTML = "";
    (j.tasks || []).forEach(t => {{
      const b = document.createElement("button");
      b.textContent = t.label;
      b.title = t.description || t.name;
      b.onclick = () => runTask(t.name);
      grid.appendChild(b);
    }});
  }} catch (e) {{ out("Cannot load tasks: " + e); }}
}}
async function runTask(name) {{
  out("Running " + name + "…");
  try {{
    const r = await api("/api/task", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ name: name, args: {{}} }})
    }});
    const j = await r.json();
    out(name + " →\\n" + (j.ok ? j.result : ("ERROR: " + j.error)));
  }} catch (e) {{ out("Request failed: " + e); }}
}}
async function sendCmd() {{
  const text = document.getElementById("text").value.trim();
  if (!text) return;
  out("…");
  try {{
    const r = await api("/api/command", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ text: text }})
    }});
    const j = await r.json();
    out(text + " →\\n" + (j.ok ? j.result : ("ERROR: " + j.error)));
  }} catch (e) {{ out("Request failed: " + e); }}
}}
document.getElementById("text").addEventListener("keydown", e => {{
  if (e.key === "Enter") sendCmd();
}});
ping(); loadTasks(); setInterval(ping, 15000);
</script>
</body>
</html>"""


class _Handler(BaseHTTPRequestHandler):
    """Single HTTP handler for every route."""

    server_version = "MarkXLRemote/1.0"
    # injected by RemoteAPIServer before serving (staticmethods: a plain
    # function attribute would bind `self` and break the call signature)
    token: str = ""
    runner: TaskRunner = staticmethod(lambda name, args: "not configured")
    command_runner: CommandRunner = staticmethod(lambda text: "not configured")
    tasks: tuple[TaskSpec, ...] = DEFAULT_TASKS

    # Silence request logging on stdout (keeps the bridge output clean).
    def log_message(self, fmt: str, *args: Any) -> None:
        return

    # ── helpers ───────────────────────────────────────────────────────
    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Token, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, status: int = 200) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _require_auth(self) -> bool:
        if check_token(self.token, extract_token(self)):
            return True
        self._send_json({"ok": False, "error": "missing or invalid token"}, status=401)
        return False

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 1_000_000:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    # ── verbs ─────────────────────────────────────────────────────────
    def do_OPTIONS(self) -> None:
        self._send_json({"ok": True})

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if not self._require_auth():
            return
        if path == "/":
            self._send_html(_page_html(self.token))
        elif path == "/api/ping":
            self._send_json({"ok": True, "app": "MARK XL"})
        elif path == "/api/tasks":
            self._send_json(
                {
                    "ok": True,
                    "tasks": [
                        {"name": t.name, "label": t.label, "description": t.description}
                        for t in self.tasks
                    ],
                }
            )
        else:
            self._send_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if not self._require_auth():
            return
        if path == "/api/task":
            payload = self._read_body()
            name = str(payload.get("name") or "").strip()
            args = payload.get("args") or {}
            if not name:
                self._send_json({"ok": False, "error": "missing task name"}, status=400)
                return
            if not isinstance(args, dict):
                self._send_json({"ok": False, "error": "args must be an object"}, status=400)
                return
            try:
                result = self.runner(name, args)
            except Exception as exc:  # noqa: BLE001 — report to the phone
                self._send_json({"ok": False, "error": str(exc)})
                return
            self._send_json({"ok": True, "result": str(result)})
        elif path == "/api/command":
            payload = self._read_body()
            text = str(payload.get("text") or "").strip()
            if not text:
                self._send_json({"ok": False, "error": "missing text"}, status=400)
                return
            try:
                result = self.command_runner(text)
            except Exception as exc:  # noqa: BLE001 — report to the phone
                self._send_json({"ok": False, "error": str(exc)})
                return
            self._send_json({"ok": True, "result": str(result)})
        else:
            self._send_json({"ok": False, "error": "not found"}, status=404)


class RemoteAPIServer:
    """Threaded HTTP server exposing the phone control API.

    Args:
        runner: ``fn(task_name, args) -> str`` dispatcher.
        command_runner: ``fn(text) -> str`` natural-language handler.
        host: Bind address (``0.0.0.0`` to reach the phone on LAN).
        port: TCP port (``0`` picks a free port — used by tests).
        token: Auth token; generated/stored when omitted.
        tasks: Registry advertised to the UI.
    """

    def __init__(
        self,
        runner: TaskRunner | None = None,
        command_runner: CommandRunner | None = None,
        host: str = "0.0.0.0",
        port: int = 8767,
        token: str | None = None,
        tasks: tuple[TaskSpec, ...] = DEFAULT_TASKS,
    ) -> None:
        self.token = token if token is not None else load_or_create_token()
        self.host = host
        self.tasks = tasks
        handler = type(
            "BoundHandler",
            (_Handler,),
            {
                "token": self.token,
                "runner": staticmethod(
                    runner or (lambda _n, _a: "no task runner configured")
                ),
                "command_runner": staticmethod(
                    command_runner or (lambda _t: "no command runner configured")
                ),
                "tasks": tasks,
            },
        )
        self._httpd = ThreadingHTTPServer((host, port), handler)
        self._httpd.daemon_threads = True
        self.port = int(self._httpd.server_address[1])
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        """Control-page URL including the token (safe to QR-share)."""
        host = self.host if self.host != "0.0.0.0" else "127.0.0.1"
        return f"http://{host}:{self.port}/?token={self.token}"

    def start_background(self) -> None:
        """Serve forever on a daemon thread (non-blocking)."""
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="remote-api", daemon=True
        )
        self._thread.start()

    def serve_forever(self) -> None:
        """Block until the server stops."""
        self._httpd.serve_forever()

    def shutdown(self) -> None:
        """Stop the server and release the port."""
        self._httpd.shutdown()
        self._httpd.server_close()


def make_default_runners(
    execute_tool: Callable[..., str],
    ui: Any,
) -> tuple[TaskRunner, CommandRunner]:
    """Build runners wired to Jarvis' tool executor.

    Args:
        execute_tool: ``core.tools.executor.execute_tool``.
        ui: The UI/player object tools log to.

    Returns:
        ``(task_runner, command_runner)`` pair for :class:`RemoteAPIServer`.
    """

    def task_runner(name: str, args: dict[str, Any]) -> str:
        return execute_tool(ui, name, args, speak=lambda _x: None)

    def command_runner(text: str) -> str:
        # Route free text through the intent/LLM pipeline when the caller
        # exposes it; otherwise fall back to a plain tool execution error.
        process = getattr(ui, "process_remote_text", None)
        if callable(process):
            return str(process(text))
        return "Natural-language commands need pc_bridge running."

    return task_runner, command_runner
