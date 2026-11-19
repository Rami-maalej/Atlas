"""Tests for Gmail message parsing and local cache (Google API mocked)."""

from __future__ import annotations

import base64
from pathlib import Path

from core import gmail_store


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def test_parse_message_multipart_and_attachment() -> None:
    payload = {
        "id": "m1", "threadId": "t1", "snippet": "short",
        "historyId": "99", "labelIds": ["INBOX", "UNREAD"],
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "Alice <alice@example.com>"},
                {"name": "To", "value": "me@example.com"},
                {"name": "Subject", "value": "Report"},
                {"name": "Date", "value": "Tue, 18 Nov 2026 10:00:00 +0000"},
            ],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64("hello world")}},
                {"mimeType": "text/html", "body": {"data": _b64("<p>ignored</p>")}},
                {"mimeType": "application/pdf", "filename": "r.pdf",
                 "body": {"attachmentId": "att1", "size": 42}},
            ],
        },
    }

    result = gmail_store.parse_message(payload)

    assert result["message_id"] == "m1"
    assert result["sender"] == "Alice <alice@example.com>"
    assert result["subject"] == "Report"
    assert result["body_text"] == "hello world"
    assert result["labels"] == ["INBOX", "UNREAD"]
    assert result["attachments"][0]["filename"] == "r.pdf"
    assert result["date"].startswith("2026-11-18T10:00")


def test_parse_message_html_only_strips_tags() -> None:
    payload = {
        "id": "m2",
        "payload": {
            "mimeType": "text/html",
            "headers": [],
            "body": {"data": _b64("<div>Hi &amp; bye</div>")},
        },
    }

    result = gmail_store.parse_message(payload)

    assert "Hi & bye" in result["body_text"]
    assert "<div>" not in result["body_text"]


def test_cache_search_and_upsert(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(gmail_store, "DB_PATH", tmp_path / "gmail.db")
    message = {
        "message_id": "m3", "thread_id": "t3", "sender": "bob@example.com",
        "recipient": "me@example.com", "subject": "Invoice August",
        "date": "2026-11-01T09:00:00+00:00", "snippet": "invoice attached",
        "body_text": "Please find the invoice attached.", "labels": ["INBOX"],
    }

    gmail_store.upsert_message("me@example.com", message)

    assert gmail_store.get_message("me@example.com", "m3")["subject"] == "Invoice August"
    hits = gmail_store.search("invoice", account="me@example.com")
    assert len(hits) == 1 and hits[0]["message_id"] == "m3"
    gmail_store.upsert_message("me@example.com", {**message, "subject": "Invoice September"})
    assert len(gmail_store.search("invoice", account="me@example.com")) == 1
