"""OAuth PKCE and keyring fallback (Google APIs mocked)."""
from __future__ import annotations

from pathlib import Path

from core import google_auth


def test_keyring_fallback_encrypts_tokens(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(google_auth, "_keyring", lambda: None)
    monkeypatch.setattr(google_auth, "KEY_FILE", tmp_path / ".google_key")
    monkeypatch.setattr(google_auth, "TOKEN_FILE", tmp_path / "tokens.enc")

    google_auth.store_token("user@example.com", {"refresh_token": "secret"})
    loaded = google_auth.load_token("user@example.com")

    assert loaded == {"refresh_token": "secret"}
    assert "secret" not in (tmp_path / "tokens.enc").read_text()


def test_delete_token_removes_it(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(google_auth, "_keyring", lambda: None)
    monkeypatch.setattr(google_auth, "KEY_FILE", tmp_path / ".google_key")
    monkeypatch.setattr(google_auth, "TOKEN_FILE", tmp_path / "tokens.enc")
    google_auth.store_token("a@b.com", {"refresh_token": "x"})
    google_auth.delete_token("a@b.com")
    assert google_auth.load_token("a@b.com") is None


def test_credentials_path_from_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("GOOGLE_CREDENTIALS_PATH", str(tmp_path / "creds.json"))
    assert google_auth.credentials_path() == tmp_path / "creds.json"


def test_pkce_challenge_is_deterministic():
    v = "verifier-123"
    assert google_auth._code_challenge(v) == google_auth._code_challenge(v)
    assert google_auth._code_challenge(v) != v
