"""Tests for SQLite memory, fact extraction and forgetting."""

from __future__ import annotations

from pathlib import Path

from core import memory_store


def setup_store(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(memory_store, "DB_PATH", tmp_path / "memory.db")


def test_add_and_search_fact(monkeypatch, tmp_path) -> None:
    setup_store(monkeypatch, tmp_path)
    store = memory_store.MemoryStore()

    store.add_fact("preferences", "colour", "teal")
    hits = store.search_facts("teal")

    assert hits and hits[0]["value"] == "teal"


def test_fact_update_dedupes(monkeypatch, tmp_path) -> None:
    setup_store(monkeypatch, tmp_path)
    store = memory_store.MemoryStore()
    store.add_fact("identity", "name", "Rami")
    store.add_fact("identity", "name", "Rami M")

    facts = [f for f in store.list_facts() if f["key"] == "name"]

    assert len(facts) == 1 and facts[0]["value"] == "Rami M"


def test_extract_facts_patterns() -> None:
    store = memory_store.MemoryStore()
    found = store.extract_facts("My name is Sam. I really like mint tea.")

    assert ("identity", "name", "Sam") in found
    assert any(key == "likes" for _, key, _ in found)


def test_ingest_and_forget(monkeypatch, tmp_path) -> None:
    setup_store(monkeypatch, tmp_path)
    store = memory_store.MemoryStore()
    store.ingest("Remember that my exam is Friday.")

    assert store.search_facts("exam")
    out = store.forget("exam")
    assert "Forgot 1" in out
    assert not store.search_facts("exam")


def test_short_term_and_episodes(monkeypatch, tmp_path) -> None:
    setup_store(monkeypatch, tmp_path)
    store = memory_store.MemoryStore()
    store.add_turn("user", "hello")
    store.add_turn("assistant", "hi")
    store.add_episode("hello", "hi", "greeting")

    assert [t["role"] for t in store.recent_turns()] == ["user", "assistant"]
    assert store.recent_episodes()[0]["summary"] == "greeting"


def test_forget_rejects_empty_subject(monkeypatch, tmp_path) -> None:
    setup_store(monkeypatch, tmp_path)
    store = memory_store.MemoryStore()
    store.add_fact("identity", "name", "Rami")
    assert "specify" in store.forget("   ")
    assert len(store.list_facts()) == 1


def test_forget_matches_words_not_arbitrary_substrings(monkeypatch, tmp_path) -> None:
    setup_store(monkeypatch, tmp_path)
    store = memory_store.MemoryStore()
    store.add_fact("notes", "task", "buy milk")
    assert "Nothing stored" in store.forget("ilk")
    assert "Forgot 1" in store.forget("milk")
