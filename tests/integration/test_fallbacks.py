"""Graceful degradation when mic/network/TTS fail."""
from __future__ import annotations

import sys

from core.conversation_state import ConversationState
from core.jarvis_llm import _llm_unavailable_reply
from core.voice_loop import VoiceLoop


def test_voice_loop_returns_false_without_sounddevice(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", None)
    loop = VoiceLoop(ConversationState())
    assert loop.start() is False


def test_text_mode_reply_is_calm():
    reply = _llm_unavailable_reply("connection refused")
    assert reply and "Traceback" not in reply


def test_persona_display_on_tts_failure():
    from core.persona import display_text, spoken_text
    assert display_text("# Title\n- a long list") == "# Title\n- a long list"
    assert "#" not in spoken_text("# Title\n- a long list")
