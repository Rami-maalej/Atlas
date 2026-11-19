"""Tests for the fd-backed fast file search."""

from __future__ import annotations

from types import SimpleNamespace

from actions import file_search


def test_fd_search_parses_results(monkeypatch, tmp_path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("hello", encoding="utf-8")
    monkeypatch.setattr(file_search, "_fd_binary", lambda: "/fake/fd")
    monkeypatch.setattr(
        file_search.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=f"{target}\n", stderr=""),
    )

    results = file_search._search_fd("notes", str(tmp_path), 10)

    assert len(results) == 1
    assert results[0]["name"] == "notes.txt"
    assert results[0]["path"] == str(target.resolve())


def test_fd_search_falls_back_when_fd_missing(monkeypatch) -> None:
    monkeypatch.setattr(file_search, "_fd_binary", lambda: None)

    assert file_search._search_fd("anything", "/tmp", 10) == []


def test_linux_search_prefers_fd(monkeypatch, tmp_path) -> None:
    target = tmp_path / "report.md"
    target.write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        file_search,
        "_search_fd",
        lambda q, r, n: [{"name": "report.md", "path": str(target)}],
    )
    monkeypatch.setattr(
        file_search,
        "_search_everything",
        lambda q, n: [],
    )

    results = file_search.search_files("report", root=str(tmp_path))

    assert results[0]["name"] == "report.md"
