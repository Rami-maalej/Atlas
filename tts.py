"""Local, free text-to-speech wrapper for the conversation layer.

Backend order: pyttsx3 (offline, espeak-ng) → existing core/tts.py engine
(edge/kokoro/elevenlabs). Importing this module never starts a voice; call
speak() explicitly. Safe to import from anywhere: the repo's real engines
live in core.tts, so this root module cannot shadow them.
"""
from __future__ import annotations

import re
import threading

_engine = None
_engine_lock = threading.Lock()
_last = {"text": ""}


def _get_engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            try:
                import pyttsx3
                _engine = pyttsx3.init()
                try:
                    _engine.setProperty("rate", 185)
                except Exception:
                    pass
            except Exception:
                _engine = False
        return _engine


def _natural_chunks(text: str):
    """Short sentences with a tiny natural pause between them."""
    parts = [p for p in re.split(r"(?<=[.!?])\s+|\n+", text.strip()) if p.strip()]
    return parts or [text.strip()]


def speak(text: str) -> None:
    """Speak text, splitting into short sentences with brief pauses."""
    if not text or not text.strip():
        return
    _last["text"] = text
    engine = _get_engine()
    if engine:
        for part in _natural_chunks(text):
            engine.say(part)
        engine.runAndWait()
        return
    try:
        from core.tts import create_tts_player
        from memory.config_manager import load_config
        player = create_tts_player(load_config())
        player.speak(text)
    except Exception:
        pass


def stop() -> None:
    """Stop speech immediately (used when the user interrupts)."""
    engine = _engine
    if engine:
        try:
            engine.stop()
        except Exception:
            pass
    try:
        import sounddevice as sd
        sd.stop()
    except Exception:
        pass
