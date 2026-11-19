"""SQLite schema, concurrency and edge cases."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core import gmail_store, memory_store


def test_memory_fact_search_after_update(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(memory_store, "DB_PATH", tmp_path / "m.db")
    s = memory_store.MemoryStore()
    s.add_fact("preferences", "colour", "blue")
    s.add_fact("preferences", "colour", "green")
    hits = s.search_facts("green")
    assert hits and hits[0]["value"] == "green"
    assert not s.search_facts("blue")


def test_concurrent_fact_writes(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(memory_store, "DB_PATH", tmp_path / "m.db")
    s = memory_store.MemoryStore()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: s.add_fact("notes", f"k{i}", f"v{i}"), range(40)))
    assert len(s.list_facts(limit=100)) == 40


def test_empty_query_search(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(gmail_store, "DB_PATH", tmp_path / "g.db")
    gmail_store.upsert_message("a@b.com", {"message_id": "m1", "subject": "x"})
    assert isinstance(gmail_store.search("", account="a@b.com"), list)


def test_forget_missing_subject(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(memory_store, "DB_PATH", tmp_path / "m.db")
    s = memory_store.MemoryStore()
    assert "Nothing stored" in s.forget("unknown-topic")
