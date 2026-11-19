"""Persona loading and spoken/display output shaping."""

from __future__ import annotations

import re
from pathlib import Path

from core.paths import config_path

PERSONA_FILE = Path(__file__).resolve().parent.parent / "persona.md"

_FILLERS = {
    "search_emails": "hold on, checking your mail…",
    "get_email": "one sec, opening that…",
    "list_recent_emails": "let me look…",
    "summarize_unread": "checking what's new…",
    "browser_use": "give me a moment to look around…",
    "web_search": "let me check…",
    "run_command": "working on it…",
}

_NONSPEAK = re.compile(r"As an AI[^.]*\.|I'm just (a|an) [^.]*\.", re.IGNORECASE)


def load_persona() -> str:
    """Load the editable persona file, allowing a config-dir override."""
    for path in (config_path("persona.md"), PERSONA_FILE):
        try:
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
        except Exception:
            continue
    return "You are Jarvis, a warm and concise voice companion."


def detect_language(text: str) -> str:
    """Cheap language hint for tone matching (en/fr/ar)."""
    if re.search(r"[\u0600-\u06ff]", text):
        return "ar"
    french = re.findall(
        r"\b(bonjour|merci|oui|non|je|tu|nous|vous|est|s'il vous plaît)\b",
        text.lower(),
    )
    return "fr" if len(french) >= 2 else "en"


def spoken_text(text: str, max_sentences: int = 3) -> str:
    """Strip formatting and keep a short speakable summary."""
    cleaned = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"^\s*[-*#>`]+\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"[*_`]", "", cleaned)
    cleaned = _NONSPEAK.sub("", cleaned)
    sentences = re.split(r"(?<=[.!?])\s+", cleaned.strip())
    return " ".join(s for s in sentences if s)[:600]


def display_text(text: str) -> str:
    """Full content for the GUI (no truncation)."""
    return text.strip()


def backchannel(tool_name: str) -> str:
    """Short filler while a tool runs — used sparingly."""
    return _FILLERS.get(tool_name, "")
