"""Tests for core.remote_api — localhost task bridge (in-process server)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

import pytest

from core import remote_api as ra


def _request(
    url: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    token: str | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-Token", token)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode()
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        status = exc.code
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw


@pytest.fixture
def server():
    calls: list[tuple[str, dict[str, Any]]] = []

    def runner(name: str, args: dict[str, Any]) -> str:
        if name == "boom":
            raise RuntimeError("exploded")
        calls.append((name, args))
        return f"ran {name} with {sorted(args)}"

    def command_runner(text: str) -> str:
        return f"echo: {text}"

    srv = ra.RemoteAPIServer(
        runner=runner,
        command_runner=command_runner,
        host="127.0.0.1",
        port=0,
        token="t" * 32,
    )
    srv.start_background()
    srv.base = f"http://127.0.0.1:{srv.port}"
    srv.calls = calls
    yield srv
    srv.shutdown()


def test_ping_requires_token(server) -> None:
    status, payload = _request(f"{server.base}/api/ping")
    assert status == 401
    assert payload["ok"] is False


def test_ping_with_token(server) -> None:
    status, payload = _request(f"{server.base}/api/ping", token=server.token)
    assert status == 200
    assert payload == {"ok": True, "app": "MARK XL"}


def test_ping_with_bearer_header(server) -> None:
    status, _ = _request(
        f"{server.base}/api/ping",
        headers={"Authorization": f"Bearer {server.token}"},
    )
    assert status == 200


def test_ping_with_query_token(server) -> None:
    status, _ = _request(f"{server.base}/api/ping?token={server.token}")
    assert status == 200


def test_wrong_token_rejected(server) -> None:
    status, payload = _request(f"{server.base}/api/ping", token="nope")
    assert status == 401
    assert "token" in payload["error"]


def test_control_page_served(server) -> None:
    status, html = _request(f"{server.base}/?token={server.token}")
    assert status == 200
    assert "MARK XL" in html
    assert "api/task" in html


def test_tasks_registry(server) -> None:
    status, payload = _request(f"{server.base}/api/tasks", token=server.token)
    assert status == 200
    names = [t["name"] for t in payload["tasks"]]
    assert "open_app" in names
    assert "read_emails" in names
    assert "open_mail_screen" in names


def test_run_task(server) -> None:
    status, payload = _request(
        f"{server.base}/api/task",
        method="POST",
        body={"name": "open_app", "args": {"name": "firefox"}},
        token=server.token,
    )
    assert status == 200
    assert payload["ok"] is True
    assert "open_app" in payload["result"]
    assert server.calls == [("open_app", {"name": "firefox"})]


def test_task_missing_name(server) -> None:
    status, payload = _request(
        f"{server.base}/api/task", method="POST", body={}, token=server.token
    )
    assert status == 400
    assert payload["ok"] is False


def test_task_bad_args_type(server) -> None:
    status, _ = _request(
        f"{server.base}/api/task",
        method="POST",
        body={"name": "x", "args": "not-a-dict"},
        token=server.token,
    )
    assert status == 400


def test_task_runner_error_reported(server) -> None:
    status, payload = _request(
        f"{server.base}/api/task",
        method="POST",
        body={"name": "boom", "args": {}},
        token=server.token,
    )
    assert status == 200
    assert payload["ok"] is False
    assert "exploded" in payload["error"]


def test_command_endpoint(server) -> None:
    status, payload = _request(
        f"{server.base}/api/command",
        method="POST",
        body={"text": "open firefox"},
        token=server.token,
    )
    assert status == 200
    assert payload["result"] == "echo: open firefox"


def test_command_missing_text(server) -> None:
    status, _ = _request(
        f"{server.base}/api/command", method="POST", body={}, token=server.token
    )
    assert status == 400


def test_unknown_route_404(server) -> None:
    status, _ = _request(f"{server.base}/api/nope", token=server.token)
    assert status == 404


def test_invalid_json_body(server) -> None:
    req = urllib.request.Request(
        f"{server.base}/api/task",
        data=b"not json",
        method="POST",
        headers={"Content-Type": "application/json", "X-Token": server.token},
    )
    try:
        urllib.request.urlopen(req, timeout=5)
        raise AssertionError("expected failure")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400


# ── Token helpers ───────────────────────────────────────────────────────────
def test_load_or_create_token_persists(tmp_path) -> None:
    path = tmp_path / "remote_token.txt"
    first = ra.load_or_create_token(path)
    assert len(first) >= 16
    second = ra.load_or_create_token(path)
    assert first == second
    assert oct(os.stat(path).st_mode)[-3:] == "600"


def test_load_or_create_token_regenerates_garbage(tmp_path) -> None:
    path = tmp_path / "remote_token.txt"
    path.write_text("short", encoding="utf-8")
    token = ra.load_or_create_token(path)
    assert len(token) >= 16


def test_check_token() -> None:
    assert ra.check_token("abc123", "abc123") is True
    assert ra.check_token("abc123", "wrong") is False
    assert ra.check_token("abc123", None) is False
    assert ra.check_token("", "") is False


def test_url_property(server) -> None:
    assert server.url.startswith("http://")
    assert f"token={server.token}" in server.url
