"""Gmail pagination, backoff and incremental sync (mocked service)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core import gmail_store
from core.google_service import GmailClient


class FakeMessages:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(execute=lambda: self.pages[len(self.calls) - 1])


class FakeService:
    def __init__(self, pages):
        self._messages = FakeMessages(pages)

    def users(self):
        return self

    def messages(self):
        return self._messages


def test_list_messages_pagination(monkeypatch):
    pages = [{"messages": [{"id": "1"}], "nextPageToken": "p2"}, {"messages": [{"id": "2"}]}]
    svc = FakeService(pages)
    client = GmailClient("a@b.com", manager=SimpleNamespace(get_credentials=lambda e: object()))
    monkeypatch.setattr(client, "_service", lambda: svc)

    first = client.list_messages("in:anywhere", 1)
    second = client.list_messages("in:anywhere", 1, "p2")

    assert first["nextPageToken"] == "p2"
    assert second["messages"][0]["id"] == "2"
    assert svc._messages.calls[0]["q"] == "in:anywhere"


def test_backoff_retries_429(monkeypatch):
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 2:
            resp = SimpleNamespace(status=429, getheader=lambda _k: "0")
            err = RuntimeError("rate limited")
            err.resp = resp
            raise err
        return "ok"

    monkeypatch.setattr(gmail_store.time, "sleep", lambda _x: None)
    assert gmail_store.with_backoff(flaky) == "ok"
    assert len(attempts) == 2


def test_get_message_uses_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(gmail_store, "DB_PATH", tmp_path / "g.db")
    gmail_store.upsert_message("a@b.com", {
        "message_id": "m1", "subject": "Hi", "body_text": "hello",
    })
    client = GmailClient("a@b.com", manager=SimpleNamespace())
    assert client.get_message("m1")["subject"] == "Hi"


def test_search_uses_fts(monkeypatch, tmp_path):
    monkeypatch.setattr(gmail_store, "DB_PATH", tmp_path / "g.db")
    gmail_store.upsert_message("a@b.com", {
        "message_id": "m2", "subject": "Invoice", "body_text": "paid",
    })
    client = GmailClient("a@b.com", manager=SimpleNamespace())
    assert any(r["message_id"] == "m2" for r in client.search("invoice"))


class FakeHistory:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        idx = len(self.calls) - 1
        result = self.pages[idx]
        if isinstance(result, Exception):
            err = result
            err.resp = SimpleNamespace(status=getattr(err, "status", 500), getheader=lambda _k: "0")
            raise err
        return SimpleNamespace(execute=lambda: result)


class FakeProfile:
    def execute(self):
        return {"historyId": "seed-123"}


class FakeUsers:
    def __init__(self, history):
        self._history = history

    def history(self):
        return self._history

    def getProfile(self, **_kwargs):
        return FakeProfile()

    def messages(self):
        return self._messages

    def set_messages(self, messages):
        self._messages = messages


def test_initial_sync_seeds_history_id(monkeypatch):
    from core import google_service

    pages = [{"messages": [{"id": "m1"}]}]
    users = FakeUsers(FakeHistory(pages))
    users.set_messages(FakeMessages(pages))
    svc = SimpleNamespace(users=lambda: users)
    client = GmailClient("a@b.com", manager=SimpleNamespace(get_credentials=lambda e: object()))
    monkeypatch.setattr(client, "_service", lambda: svc)
    monkeypatch.setattr(client, "get_message", lambda mid: None)
    monkeypatch.setattr(google_service.gmail_store, "set_sync_state", lambda email, hid: setattr(client, "_stored", hid))
    monkeypatch.setattr(google_service.google_auth, "set_last_sync", lambda *a: None)

    client.sync(incremental=False)

    assert client._stored == "seed-123"


def test_history_sync_paginates(monkeypatch):
    from core import google_service

    pages = [
        {"history": [{"messagesAdded": [{"message": {"id": "m1"}}]}], "historyId": "h1", "nextPageToken": "p2"},
        {"history": [{"messagesAdded": [{"message": {"id": "m2"}}]}], "historyId": "h2"},
    ]
    history = FakeHistory(pages)
    client = GmailClient("a@b.com", manager=SimpleNamespace(get_credentials=lambda e: object()))
    monkeypatch.setattr(client, "_service", lambda: SimpleNamespace(users=lambda: FakeUsers(history)))
    seen = []
    monkeypatch.setattr(client, "get_message", lambda mid: seen.append(mid))
    monkeypatch.setattr(google_service.gmail_store, "set_sync_state", lambda e, h: seen.append(h))
    monkeypatch.setattr(google_service.google_auth, "set_last_sync", lambda *a: None)

    count = client._sync_history("start")

    assert count == 2 and history.calls[1].get("pageToken") == "p2"
    assert seen[-1] == "h2"
