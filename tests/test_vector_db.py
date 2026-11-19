"""Tests for the sqlite-vec memory store."""

from __future__ import annotations

import json
from pathlib import Path

from memory import db_vector_store as db


def _entry(i: int, vec: list[float]) -> dict:
    return {
        "id": str(1700000000.0 + i),
        "user": f"question {i}",
        "assistant": f"answer {i}",
        "created": f"2026-01-01T00:00:{i:02d}",
        "embedding": vec,
    }


def test_replace_all_and_knn(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "store.db")
    monkeypatch.setattr(db, "_initialized", False)
    vec = [0.1] * db.DIM
    store = {"memories": [], "conversations": [_entry(1, vec),
        _entry(2, [0.9] * 192 + [-0.9] * 192),]}

    db.replace_all(store)

    assert len(db.load_all()["conversations"]) == 2
    hits = db.knn("conversations", vec, 2)
    assert len(hits) == 2
    assert hits[0][0] == store["conversations"][0]["id"]
    assert hits[0][1] > hits[1][1]


def test_import_legacy_json(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "store.db")
    monkeypatch.setattr(db, "JSON_PATH", tmp_path / "store.json")
    monkeypatch.setattr(db, "_initialized", False)
    vec = [0.2] * db.DIM
    (tmp_path / "store.json").write_text(
        json.dumps({"memories": [], "conversations": [_entry(1, vec)]}),
        encoding="utf-8",
    )

    assert db.import_legacy_json() is True
    assert len(db.load_all()["conversations"]) == 1
    assert db.import_legacy_json() is False


def test_empty_embeddings_are_kept_but_not_searchable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "store.db")
    monkeypatch.setattr(db, "_initialized", False)
    entry = _entry(1, [0.1] * db.DIM)
    entry["embedding"] = []

    db.replace_all({"memories": [], "conversations": [entry]})

    assert len(db.load_all()["conversations"]) == 1
    assert db.knn("conversations", [0.1] * db.DIM, 2) == []
