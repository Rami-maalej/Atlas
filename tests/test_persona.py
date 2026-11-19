"""Tests for persona loading and spoken/display shaping."""

from __future__ import annotations

from core import persona


def test_persona_file_loads() -> None:
    text = persona.load_persona()
    assert "warm" in text.lower()
    assert "short" in text.lower()


def test_persona_override(tmp_path, monkeypatch) -> None:
    (tmp_path / "persona.md").write_text("Custom persona here.", encoding="utf-8")
    monkeypatch.setattr(persona, "config_path", lambda _name: tmp_path / "persona.md")
    assert persona.load_persona() == "Custom persona here."


def test_spoken_text_strips_markdown() -> None:
    raw = "- **Here's** the list.\\n- Item one.\\n```code```\\nDone."
    spoken = persona.spoken_text(raw)
    assert "**" not in spoken and "```" not in spoken
    assert "Here's the list." in spoken


def test_spoken_text_drops_ai_disclaimer() -> None:
    assert "As an AI" not in persona.spoken_text("As an AI, I can't. But I can help.")


def test_language_detection() -> None:
    assert persona.detect_language("bonjour, merci beaucoup") == "fr"
    assert persona.detect_language("مرحبا كيف حالك") == "ar"
    assert persona.detect_language("hello there") == "en"


def test_backchannel() -> None:
    assert "mail" in persona.backchannel("search_emails")
    assert persona.backchannel("unknown_tool") == ""
