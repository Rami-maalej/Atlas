"""Tests for VAD endpointing and the voice loop."""

from __future__ import annotations

import numpy as np

from core.conversation_state import ConversationState, State
from core.voice_loop import EnergyVAD, VoiceLoop


def test_energy_vad_ends_after_silence() -> None:
    vad = EnergyVAD(threshold=0.01, endpointing_ms=30, min_speech_ms=10)
    loud = np.ones(1024, dtype=np.float32) * 0.5
    quiet = np.zeros(1024, dtype=np.float32)
    assert vad.feed(loud) is None
    import time

    time.sleep(0.05)
    result = vad.feed(quiet)
    assert result is not None and result.size == 1024


def test_energy_vad_ignores_pure_silence() -> None:
    vad = EnergyVAD()
    assert vad.feed(np.zeros(1024, dtype=np.float32)) is None


def test_voice_loop_follow_up_keeps_listening() -> None:
    sm = ConversationState()
    sm.transition(State.LISTENING)
    sm.transition(State.TRANSCRIBING)
    sm.transition(State.THINKING)
    sm.transition(State.SPEAKING)
    loop = VoiceLoop(sm, config={"voice_conversation_mode": True})

    loop.listen_for_follow_up()

    assert sm.state is State.LISTENING
    assert sm.in_follow_up_window() is True
