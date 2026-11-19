"""Tests for the multi-account manager with Google APIs mocked."""

from __future__ import annotations

from datetime import datetime

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core import google_auth, google_service
from core.google_service import GmailClient, GoogleAccountManager


@pytest.fixture
def fake_auth(monkeypatch, tmp_path: Path) -> dict[str, str]:
    tokens: dict[str, dict[str, Any]] = {}

    def fake_oauth(_credentials=None):
        return {
            "userinfo": {
                "email": "user@example.com",
                "name": "Example User",
                "avatar_url": "https://example.com/a.png",
            },
            "token": {"token": "access", "refresh_token": "refresh",
                     "expiry": "2020-01-01T00:00:00+00:00",
                     "token_uri": "https://oauth2.googleapis.com/token"},
        }

    monkeypatch.setattr(google_auth, "run_oauth", fake_oauth)
    monkeypatch.setattr(google_auth, "store_token", lambda e, t: tokens.__setitem__(e, t))
    monkeypatch.setattr(google_auth, "load_token", lambda e: tokens.get(e))
    monkeypatch.setattr(google_auth, "delete_token", lambda e: tokens.pop(e, None))
    monkeypatch.setattr(google_auth, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    return tokens


def test_add_and_remove_account(fake_auth) -> None:
    manager = GoogleAccountManager()

    account = manager.add_account()

    assert account.email == "user@example.com"
    assert [a.email for a in manager.list_accounts()] == ["user@example.com"]
    assert "user@example.com" in fake_auth

    manager.remove_account("user@example.com")
    assert manager.list_accounts() == []
    assert fake_auth == {}


def test_second_account_is_added_independently(fake_auth, monkeypatch) -> None:
    manager = GoogleAccountManager()

    manager.add_account()
    monkeypatch.setattr(
        google_auth, "run_oauth",
        lambda _c=None: {
            "userinfo": {"email": "second@example.com", "name": "Second"},
            "token": {"token": "a2"},
        },
    )
    manager.add_account()

    assert {a.email for a in manager.list_accounts()} == {
        "user@example.com", "second@example.com"
    }


def test_get_credentials_marks_needs_reauth_on_failure(fake_auth, monkeypatch) -> None:
    class BrokenCreds:
        def __init__(self, **_kwargs):
            self.expired = True
            self.refresh_token = "refresh"

        def refresh(self, _request):
            raise RuntimeError("token revoked")

    monkeypatch.setattr("google.oauth2.credentials.Credentials", BrokenCreds)
    manager = GoogleAccountManager()
    manager.add_account()
    marked: list[str] = []
    monkeypatch.setattr(google_auth, "mark_needs_reauth", marked.append)

    with pytest.raises(google_service.GoogleServiceError):
        manager.get_credentials("user@example.com")

    assert marked == ["user@example.com"]


def test_gmail_client_search_uses_cache(monkeypatch) -> None:
    monkeypatch.setattr(
        __import__("core.gmail_store", fromlist=["search"]),
        "search",
        lambda q, account=None, limit=20: [{"message_id": "m1", "subject": q}],
    )
    client = GmailClient("user@example.com", manager=SimpleNamespace())

    result = client.search("invoice")

    assert result[0]["subject"] == "invoice"


def test_pkce_challenge_is_s256() -> None:
    import base64
    import hashlib

    verifier = "a" * 64
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")

    assert google_auth._code_challenge(verifier) == expected


def test_credentials_include_expiry_and_persist_rotated_token(fake_auth, monkeypatch) -> None:
    captured = {}

    class FakeCreds:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.expired = True
            self.refresh_token = "new-refresh"
            self.token = "new-access"
            self.expiry = datetime(2030, 1, 1)

        def refresh(self, _request):
            return None

    monkeypatch.setattr("google.oauth2.credentials.Credentials", FakeCreds)
    fake_auth["user@example.com"] = {
        "token": "old", "refresh_token": "old-refresh",
        "expiry": "2020-01-01T00:00:00+00:00",
    }
    manager = GoogleAccountManager()
    manager.get_credentials("user@example.com")

    assert captured["expiry"].year == 2020
    assert fake_auth["user@example.com"]["refresh_token"] == "new-refresh"
