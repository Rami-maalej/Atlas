"""Local Gmail cache: SQLite + FTS5, message parsing and incremental sync."""

from __future__ import annotations

import base64
import html
import logging
import re
import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from core.paths import memory_path

logger = logging.getLogger("gmail_store")

DB_PATH = memory_path("gmail.db")
_lock = threading.RLock()


class GmailStoreError(RuntimeError):
    """Raised on cache or sync failures."""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=15000")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account TEXT NOT NULL,
            message_id TEXT NOT NULL,
            thread_id TEXT NOT NULL DEFAULT '',
            sender TEXT NOT NULL DEFAULT '',
            recipient TEXT NOT NULL DEFAULT '',
            subject TEXT NOT NULL DEFAULT '',
            date TEXT NOT NULL DEFAULT '',
            snippet TEXT NOT NULL DEFAULT '',
            body_text TEXT NOT NULL DEFAULT '',
            labels TEXT NOT NULL DEFAULT '[]',
            UNIQUE(account, message_id)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
            subject, sender, body_text, email_id UNINDEXED
        );
        CREATE TABLE IF NOT EXISTS sync_state (
            account TEXT PRIMARY KEY,
            history_id TEXT NOT NULL DEFAULT '',
            last_sync TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_emails_account_date ON emails(account, date DESC);
        """
    )
    return con


def _fts_escape(query: str) -> str:
    tokens = re.findall(r"[\w\-']+", query)
    return " ".join(f'"{t}"' for t in tokens) if tokens else ""


def parse_message(payload: dict[str, Any]) -> dict[str, Any]:
    """Turn a Gmail API message payload into the cache row shape."""
    root = payload.get("payload") or {}
    headers = {
        str(h.get("name", "")).lower(): str(h.get("value", ""))
        for h in root.get("headers", [])
        if isinstance(h, dict)
    }
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[dict[str, Any]] = []

    def walk(part: dict[str, Any]) -> None:
        mime = str(part.get("mimeType", ""))
        body = part.get("body") or {}
        data = body.get("data")
        if part.get("filename") and body.get("attachmentId"):
            attachments.append({
                "filename": part["filename"],
                "mimeType": mime,
                "size": int(body.get("size", 0) or 0),
                "attachmentId": body["attachmentId"],
            })
        if data and mime not in ("multipart/alternative", "multipart/mixed"):
            try:
                decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
                    "utf-8", errors="replace"
                )
            except Exception:
                decoded = ""
            if mime == "text/html":
                html_parts.append(decoded)
            elif mime == "text/plain":
                plain_parts.append(decoded)
        for child in part.get("parts", []) or []:
            walk(child)

    walk(root)
    if not plain_parts and html_parts:
        text = re.sub(r"<[^>]+>", " ", " ".join(html_parts))
        plain_parts.append(html.unescape(re.sub(r"\s+", " ", text)).strip())

    raw_date = headers.get("date", "")
    try:
        dt = parsedate_to_datetime(raw_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        iso_date = dt.astimezone(UTC).isoformat()
    except Exception:
        iso_date = ""

    return {
        "message_id": str(payload.get("id", "")),
        "thread_id": str(payload.get("threadId", "")),
        "sender": headers.get("from", ""),
        "recipient": headers.get("to", ""),
        "subject": headers.get("subject", ""),
        "date": iso_date,
        "snippet": str(payload.get("snippet", ""))[:400],
        "body_text": "\n".join(plain_parts)[:20000],
        "labels": list(payload.get("labelIds", []) or []),
        "attachments": attachments,
        "history_id": str(payload.get("historyId", "")),
    }


def upsert_message(account: str, message: dict[str, Any]) -> None:
    with _lock:
        con = _connect()
        try:
            cur = con.execute(
                """INSERT INTO emails
                   (account,message_id,thread_id,sender,recipient,subject,date,snippet,body_text,labels)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(account,message_id) DO UPDATE SET
                     thread_id=excluded.thread_id, sender=excluded.sender,
                     recipient=excluded.recipient, subject=excluded.subject,
                     date=excluded.date, snippet=excluded.snippet,
                     body_text=excluded.body_text, labels=excluded.labels""",
                (
                    account.lower(), message["message_id"], message.get("thread_id", ""),
                    message.get("sender", ""), message.get("recipient", ""),
                    message.get("subject", ""), message.get("date", ""),
                    message.get("snippet", ""), message.get("body_text", ""),
                    __import__("json").dumps(message.get("labels", [])),
                ),
            )
            existing = con.execute(
                "SELECT id FROM emails WHERE account=? AND message_id=?",
                (account.lower(), message["message_id"]),
            ).fetchone()
            email_id = int(existing["id"]) if existing else int(cur.lastrowid or 0)
            con.execute("DELETE FROM emails_fts WHERE email_id=?", (str(email_id),))
            con.execute(
                "INSERT INTO emails_fts(subject,sender,body_text,email_id) VALUES (?,?,?,?)",
                (message.get("subject", ""), message.get("sender", ""),
                 message.get("body_text", ""), str(email_id)),
            )
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()


def get_message(account: str, message_id: str) -> dict[str, Any] | None:
    with _lock:
        con = _connect()
        try:
            row = con.execute(
                "SELECT * FROM emails WHERE account=? AND message_id=?",
                (account.lower(), message_id),
            ).fetchone()
            return _row_to_dict(row) if row else None
        finally:
            con.close()


def delete_message(account: str, message_id: str) -> None:
    """Remove one cached message (history 'messageDeleted')."""
    with _lock:
        con = _connect()
        try:
            row = con.execute(
                "SELECT id FROM emails WHERE account=? AND message_id=?",
                (account.lower(), message_id),
            ).fetchone()
            if row:
                con.execute("DELETE FROM emails_fts WHERE email_id=?", (str(row["id"]),))
                con.execute("DELETE FROM emails WHERE id=?", (row["id"],))
                con.commit()
        finally:
            con.close()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    try:
        import json

        data["labels"] = json.loads(data.get("labels") or "[]")
    except Exception:
        data["labels"] = []
    data.pop("id", None)
    return data


def search(query: str = "", account: str | None = None,
           limit: int = 20) -> list[dict[str, Any]]:
    with _lock:
        con = _connect()
        try:
            where: list[str] = []
            args: list[Any] = []
            where_fts: list[str] = []
            if account:
                where_fts.append("e.account=?")
                where.append("account=?")
                args.append(account.lower())
            fts = _fts_escape(query)
            if fts:
                sql = (
                    "SELECT e.* FROM emails e JOIN emails_fts f "
                    "ON CAST(f.email_id AS INTEGER)=e.id WHERE emails_fts MATCH ?"
                )
                params: list[Any] = [fts]
                if where_fts:
                    sql += " AND " + " AND ".join(where_fts)
                    params += args
                sql += " ORDER BY e.date DESC LIMIT ?"
                params.append(limit)
                try:
                    return [_row_to_dict(r) for r in con.execute(sql, params)]
                except sqlite3.OperationalError:
                    pass
            sql = "SELECT * FROM emails"
            if where or query:
                sql += " WHERE " + " AND ".join(
                    where + ["(subject LIKE ? OR body_text LIKE ? OR sender LIKE ?)"]
                )
                args += [f"%{query}%"] * 3
            sql += " ORDER BY date DESC LIMIT ?"
            args.append(limit)
            return [_row_to_dict(r) for r in con.execute(sql, args)]
        finally:
            con.close()


def list_recent(account: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    with _lock:
        con = _connect()
        try:
            if account:
                rows = con.execute(
                    "SELECT * FROM emails WHERE account=? ORDER BY date DESC LIMIT ?",
                    (account.lower(), limit),
                )
            else:
                rows = con.execute("SELECT * FROM emails ORDER BY date DESC LIMIT ?", (limit,))
            return [_row_to_dict(r) for r in rows]
        finally:
            con.close()


def get_sync_state(account: str) -> tuple[str, str]:
    with _lock:
        con = _connect()
        try:
            row = con.execute(
                "SELECT history_id,last_sync FROM sync_state WHERE account=?",
                (account.lower(),),
            ).fetchone()
            return (str(row["history_id"]), str(row["last_sync"])) if row else ("", "")
        finally:
            con.close()


def set_sync_state(account: str, history_id: str, last_sync: str | None = None) -> None:
    with _lock:
        con = _connect()
        try:
            last_sync = last_sync or datetime.now(UTC).isoformat()
            con.execute(
                """INSERT INTO sync_state(account,history_id,last_sync) VALUES (?,?,?)
                   ON CONFLICT(account) DO UPDATE SET
                     history_id=excluded.history_id, last_sync=excluded.last_sync""",
                (account.lower(), history_id, last_sync),
            )
            con.commit()
        finally:
            con.close()


def with_backoff[T](fn: Callable[[], T], attempts: int = 5) -> T:
    """Retry transient Google API failures with exponential backoff."""
    delay = 0.5
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as e:
            status = getattr(getattr(e, "resp", None), "status", None)
            transient = status in (429, 500, 502, 503, 504) or status is None
            if not transient or attempt == attempts - 1:
                raise
            resp = getattr(e, "resp", None)
            wait = float((resp.getheader("Retry-After") if resp else None) or delay)
            logger.debug("Transient Gmail error; retrying in %.1fs", wait)
            time.sleep(wait)
            delay = min(delay * 2, 30.0)
    raise GmailStoreError("unreachable")
