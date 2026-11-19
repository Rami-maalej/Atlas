"""SQLite memory: short-term turns, long-term facts, episodic summaries.

All state is local. FTS5 makes recall fast without an embedding service.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any

from core.paths import memory_path

logger = logging.getLogger("memory_store")

DB_PATH = memory_path("memory.db")
_lock = threading.RLock()

_FACT_PATTERNS = (
    (r"\bmy name is\s+([^.!?]+)", "identity", "name"),
    (r"\b(?:call me|i am called)\s+([^.!?]+)", "identity", "name"),
    (r"\bi (?:really )?(?:like|love|enjoy)\s+([^.!?]+)", "preferences", "likes"),
    (r"\bi (?:hate|dislike)\s+([^.!?]+)", "preferences", "dislikes"),
    (r"\bi(?:'m| am) working on\s+(.+?)[.!?]?$", "projects", "current"),
    (r"\bremember that\s+([^.!?]+)", "notes", "remembered"),
    (
        r"\bmy (?:wife|husband|partner|friend|dog|cat|son|daughter)\s+([^.!?]+)",
        "relationships", "people",
    ),
)


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=15000")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS short_term (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session TEXT NOT NULL DEFAULT 'default',
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            ts TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            updated TEXT NOT NULL,
            UNIQUE(category, key)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
            value, category, fact_id UNINDEXED
        );
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            user TEXT NOT NULL,
            assistant TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT ''
        );
        """
    )
    return con


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class MemoryStore:
    """Public API for short-term, fact and episodic memory."""

    def add_turn(self, role: str, content: str, session: str = "default") -> None:
        with _lock:
            con = _connect()
            try:
                con.execute(
                    "INSERT INTO short_term(session,role,content,ts) VALUES (?,?,?,?)",
                    (session, role, content[:4000], _now()),
                )
                con.commit()
            finally:
                con.close()

    def recent_turns(self, limit: int = 10, session: str = "default") -> list[dict[str, Any]]:
        with _lock:
            con = _connect()
            try:
                rows = con.execute(
                    "SELECT role,content,ts FROM short_term WHERE session=? "
                    "ORDER BY id DESC LIMIT ?", (session, limit),
                ).fetchall()
                return [dict(r) for r in reversed(rows)]
            finally:
                con.close()

    def add_fact(self, category: str, key: str, value: str) -> str:
        """Insert or update one fact, keeping FTS in sync."""
        with _lock:
            con = _connect()
            try:
                cur = con.execute(
                    """INSERT INTO facts(category,key,value,updated) VALUES (?,?,?,?)
                       ON CONFLICT(category,key) DO UPDATE SET
                         value=excluded.value, updated=excluded.updated""",
                    (category, key, value[:1000], _now()),
                )
                row = con.execute(
                    "SELECT id FROM facts WHERE category=? AND key=?", (category, key)
                ).fetchone()
                fact_id = int(row["id"]) if row else int(cur.lastrowid or 0)
                con.execute("DELETE FROM facts_fts WHERE fact_id=?", (str(fact_id),))
                con.execute(
                    "INSERT INTO facts_fts(value,category,fact_id) VALUES (?,?,?)",
                    (value[:1000], category, str(fact_id)),
                )
                con.commit()
                return f"Remembered: {key} = {value}"
            finally:
                con.close()

    def list_facts(self, limit: int = 100) -> list[dict[str, Any]]:
        with _lock:
            con = _connect()
            try:
                rows = con.execute(
                    "SELECT id,category,key,value,updated FROM facts ORDER BY updated DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                con.close()

    def search_facts(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        with _lock:
            con = _connect()
            try:
                tokens = " ".join(f'"{t}"' for t in re.findall(r"[\w']+", query))
                if tokens:
                    try:
                        rows = con.execute(
                            "SELECT f.category,f.key,f.value FROM facts f "
                            "JOIN facts_fts x ON CAST(x.fact_id AS INTEGER)=f.id "
                            "WHERE facts_fts MATCH ? LIMIT ?", (tokens, limit),
                        ).fetchall()
                        return [dict(r) for r in rows]
                    except sqlite3.OperationalError:
                        pass
                rows = con.execute(
                    "SELECT category,key,value FROM facts WHERE value LIKE ? LIMIT ?",
                    (f"%{query}%", limit),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                con.close()

    def forget(self, subject: str) -> str:
        """Delete facts matching a key or value. Never deletes with no subject."""
        needle = str(subject or "").lower().strip()
        for prefix in ("my ", "the ", "about ", "that "):
            if needle.startswith(prefix):
                needle = needle[len(prefix):].strip()
        if not needle:
            return "Please specify what to forget."
        with _lock:
            con = _connect()
            try:
                rows = con.execute("SELECT id,key,value FROM facts").fetchall()
                ids = [
                    int(r["id"]) for r in rows
                    if needle == r["key"].lower()
                    or needle == r["value"].lower()
                    or needle in re.split(r"\W+", r["key"].lower())
                    or needle in re.split(r"\W+", r["value"].lower())
                ]
                for fid in ids:
                    con.execute("DELETE FROM facts_fts WHERE fact_id=?", (str(fid),))
                    con.execute("DELETE FROM facts WHERE id=?", (fid,))
                con.commit()
                if ids:
                    return f"Forgot {len(ids)} fact(s) about {subject}."
                return f"Nothing stored about {subject}."
            finally:
                con.close()

    def delete_fact(self, fact_id: int) -> bool:
        """Delete exactly one fact by id (used by the GUI)."""
        with _lock:
            con = _connect()
            try:
                row = con.execute(
                    "SELECT id FROM facts WHERE id=?", (int(fact_id),)
                ).fetchone()
                if not row:
                    return False
                con.execute("DELETE FROM facts_fts WHERE fact_id=?", (str(fact_id),))
                con.execute("DELETE FROM facts WHERE id=?", (int(fact_id),))
                con.commit()
                return True
            finally:
                con.close()

    def add_episode(self, user: str, assistant: str, summary: str = "") -> None:
        with _lock:
            con = _connect()
            try:
                con.execute(
                    "INSERT INTO episodes(ts,user,assistant,summary) VALUES (?,?,?,?)",
                    (_now(), user[:1000], assistant[:2000], summary[:1000]),
                )
                con.commit()
            finally:
                con.close()

    def recent_episodes(self, limit: int = 5) -> list[dict[str, Any]]:
        with _lock:
            con = _connect()
            try:
                rows = con.execute(
                    "SELECT ts,user,assistant,summary FROM episodes ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                con.close()

    def extract_facts(self, text: str) -> list[tuple[str, str, str]]:
        """Extract new facts from a user turn (deterministic, dedupe-friendly)."""
        found: list[tuple[str, str, str]] = []
        for pattern, category, key in _FACT_PATTERNS:
            m = re.search(pattern, text.strip(), re.IGNORECASE)
            if m:
                value = m.group(1).strip(" '\"")
                if value:
                    found.append((category, key, value[:200]))
        return found

    def ingest(self, user_text: str) -> list[str]:
        """Extract + store facts; returns confirmation strings."""
        messages = []
        for category, key, value in self.extract_facts(user_text):
            messages.append(self.add_fact(category, key, value))
        return messages
