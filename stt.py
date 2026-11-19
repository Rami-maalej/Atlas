"""Speech-to-text helpers: wake word 'Jarvis' + typed-input fallback.

The app already has local STT (faster-whisper/vosk) in core/stt.py and the
listeners in core/jarvis_stt.py. This module only adds:
  - has_wake_word(text): does the transcribed text start with the wake word?
  - strip_wake_word(text): remove it before routing.
  - transcribe_once(engine): one blocking capture using the configured engine.
  - typed_input(prompt): fallback when no mic is available.
"""
from __future__ import annotations

import re

WAKE = "jarvis"


def has_wake_word(text: str) -> bool:
    return bool(text) and re.match(r"^\s*(hey\s+|ok\s+)?jarvis\b", text.strip(), re.IGNORECASE) is not None


def strip_wake_word(text: str) -> str:
    if not text:
        return text
    return re.sub(r"^\s*(hey\s+|ok\s+)?jarvis[\s,:.!-]*", "", text.strip(), flags=re.IGNORECASE).strip()


def transcribe_once(engine=None) -> str:
    """One short listen using an existing STT engine object (optional)."""
    import sounddevice as sd

    from core.audio_consts import CHANNELS, SAMPLE_RATE_IN

    if engine is None:
        from core.stt import WhisperSTT
        engine = WhisperSTT(model_name="tiny")
    audio = sd.rec(int(1.5 * SAMPLE_RATE_IN), samplerate=SAMPLE_RATE_IN,
                   channels=CHANNELS, dtype="float32")
    sd.wait()
    if hasattr(engine, "transcribe"):
        return engine.transcribe(audio.flatten())
    return ""


def typed_input(prompt: str = "You: ") -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return ""
