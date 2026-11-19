"""Secrets in logs and command/path injection attempts."""
from __future__ import annotations

from pathlib import Path

from actions import install_tool, sys_tool
from core import google_auth


def test_install_rejects_unknown_tool(monkeypatch):
    monkeypatch.setattr(install_tool, "_is_installed", lambda _t: False)
    called = []
    monkeypatch.setattr(install_tool.subprocess, "run", lambda *a, **k: called.append(a))
    result = install_tool.install_tool({"tool": "vim; rm -rf ~"})
    assert "cannot" in result.lower()
    assert not called


def test_sys_tool_never_uses_shell():
    source = Path("actions/sys_tool.py").read_text()
    assert "shell=True" not in source
    assert isinstance(sys_tool.use_tool({"tool": "ping", "args": "x"}), str)


def test_token_never_logged(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(google_auth, "_keyring", lambda: None)
    monkeypatch.setattr(google_auth, "KEY_FILE", tmp_path / ".key")
    monkeypatch.setattr(google_auth, "TOKEN_FILE", tmp_path / "t.enc")
    google_auth.store_token("user@example.com", {"refresh_token": "TOPSECRET"})
    captured = capsys.readouterr()
    assert "TOPSECRET" not in captured.out + captured.err


def test_credentials_not_hardcoded():
    source = Path("core/google_auth.py").read_text()
    assert "client_secret" not in source.split("def run_oauth")[0]
