"""sqlite-vec backed storage for semantic memory.

One embedded SQLite file under ``memory_path("vector_store.db")``. WAL mode and
a busy timeout make it safe for the desktop process and the phone bridge to
read/write the same store. The public helpers mirror the old JSON store so
``memory.vector_memory`` keeps its API.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

import numpy as np
import sqlite_vec

from core.paths import memory_path

DB_PATH = memory_path("vector_store.db")
JSON_PATH = memory_path("vector_store.json")
DIM = 384
_lock = threading.RLock()
_initialized = False


def _connect() -> sqlite3.Connection:
    global _initialized
    con = sqlite3.connect(str(DB_PATH), timeout=15)
    con.enable_load_extension(True)
    sqlite_vec.load(con)
    con.enable_load_extension(False)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=15000")
    if not _initialized:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY, row_num INTEGER, text TEXT, category TEXT,
                source TEXT, created TEXT, embedding BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY, row_num INTEGER, user TEXT, assistant TEXT,
                created TEXT, embedding BLOB NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_memories
                USING vec0(embedding float[384] distance_metric=cosine);
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_conversations
                USING vec0(embedding float[384] distance_metric=cosine);
            """
        )
        _initialized = True
    return con


def _blob(embedding: list[float] | np.ndarray) -> bytes:
    vector: np.ndarray = np.asarray(embedding, dtype=np.float32)
    if vector.size != DIM:
        vector = np.resize(vector, DIM)
    return vector.tobytes()


def _vector(blob: bytes) -> list[float]:
    return np.frombuffer(blob, dtype=np.float32).tolist()


def load_all() -> dict[str, list[dict[str, Any]]]:
    """Return the whole store in the legacy JSON shape."""
    with _lock:
        try:
            con = _connect()
            try:
                memories = [
                    {
                        "id": row[0], "text": row[1], "category": row[2],
                        "source": row[3], "created": row[4],
                        "embedding": _vector(row[5]),
                    }
                    for row in con.execute(
                        "SELECT id,text,category,source,created,embedding FROM memories"
                    )
                ]
                conversations = [
                    {
                        "id": row[0], "user": row[1], "assistant": row[2],
                        "created": row[3], "embedding": _vector(row[4]),
                    }
                    for row in con.execute(
                        "SELECT id,user,assistant,created,embedding FROM conversations"
                    )
                ]
                return {"memories": memories, "conversations": conversations}
            finally:
                con.close()
        except Exception:
            return {"memories": [], "conversations": []}


def replace_all(store: dict[str, list[dict[str, Any]]]) -> None:
    """Atomically replace the store (transaction across all four tables)."""
    with _lock:
        con = _connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute("DELETE FROM memories")
            con.execute("DELETE FROM conversations")
            con.execute("DELETE FROM vec_memories")
            con.execute("DELETE FROM vec_conversations")
            for idx, m in enumerate(store.get("memories", []), 1):
                rid = str(m.get("id", ""))
                emb = m.get("embedding") or []
                stored = _blob(emb) if emb else np.zeros(DIM, dtype=np.float32).tobytes()
                con.execute(
                    "INSERT INTO memories VALUES (?,?,?,?,?,?,?)",
                    (rid, idx, m.get("text", ""), m.get("category", "general"),
                     m.get("source", "conversation"), m.get("created", ""), stored),
                )
                if emb:
                    con.execute("INSERT INTO vec_memories(rowid, embedding) VALUES (?,?)",
                                (idx, _blob(emb)))
            for idx, c in enumerate(store.get("conversations", []), 1):
                rid = str(c.get("id", ""))
                emb = c.get("embedding") or []
                stored = _blob(emb) if emb else np.zeros(DIM, dtype=np.float32).tobytes()
                con.execute(
                    "INSERT INTO conversations VALUES (?,?,?,?,?,?)",
                    (rid, idx, c.get("user", ""), c.get("assistant", ""),
                     c.get("created", ""), stored),
                )
                if emb:
                    con.execute("INSERT INTO vec_conversations(rowid, embedding) VALUES (?,?)",
                                (idx, _blob(emb)))
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()


def knn(table: str, embedding: list[float], k: int) -> list[tuple[str, float]]:
    """Return ``(rowid, cosine_similarity)`` pairs, highest first."""
    if table not in ("memories", "conversations"):
        return []
    try:
        with _lock:
            con = _connect()
            try:
                rows = con.execute(
                    f"SELECT t.id, 1.0 - v.distance FROM vec_{table} v "
                    f"JOIN {table} t ON t.row_num = v.rowid "
                    "WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance",
                    (_blob(embedding), k),
                ).fetchall()
                return [(str(r[0]), float(r[1])) for r in rows]
            finally:
                con.close()
    except Exception:
        return []


def import_legacy_json() -> bool:
    """Import the old vector_store.json once; keep the JSON as a backup."""
    try:
        payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    except Exception:
        return False
    store = load_all()
    if store["memories"] or store["conversations"]:
        return False
    if not payload.get("memories") and not payload.get("conversations"):
        return False
    replace_all(payload)
    return True


def checkpoint() -> None:
    """WAL is autocommitted; nothing special is required on shutdown."""
    return None
