"""Tests for the conversation state machine and latency log."""

from __future__ import annotations

import pytest

from core.conversation_state import (
    ConversationState,
    InvalidTransition,
    LatencyLog,
    State,
)


def test_happy_path_transitions() -> None:
    sm = ConversationState()
    assert sm.state is State.IDLE
    sm.transition(State.LISTENING)
    sm.transition(State.TRANSCRIBING)
    sm.transition(State.THINKING)
    sm.transition(State.SPEAKING)
    sm.transition(State.IDLE)
    assert sm.state is State.IDLE


def test_invalid_transition_rejected() -> None:
    sm = ConversationState()
    with pytest.raises(InvalidTransition):
        sm.transition(State.SPEAKING)


def test_barge_in_only_from_speaking() -> None:
    sm = ConversationState()
    sm.transition(State.LISTENING)
    assert sm.barge_in() is False
    sm.transition(State.TRANSCRIBING)
    sm.transition(State.THINKING)
    sm.transition(State.SPEAKING)
    assert sm.barge_in() is True
    assert sm.state is State.LISTENING


def test_follow_up_window(tmp_path) -> None:
    sm = ConversationState()
    sm.note_user_turn(follow_up_seconds=0.05)
    assert sm.in_follow_up_window() is True
    import time

    time.sleep(0.08)
    assert sm.in_follow_up_window() is False


def test_latency_log_records_stages(tmp_path) -> None:
    log = LatencyLog(path=tmp_path / "latency.log")
    log.begin_turn()
    log.mark("VAD_END")
    log.mark("STT_DONE")
    marks = log.finish()
    assert "VAD_END" in marks and "STT_DONE" in marks
    assert "VAD_END" in (tmp_path / "latency.log").read_text()


def test_reset_allows_any_state() -> None:
    sm = ConversationState()
    sm.transition(State.LISTENING)
    sm.reset()
    assert sm.state is State.IDLE


def test_latency_mark_does_not_deadlock(tmp_path) -> None:
    import threading

    log = LatencyLog(path=tmp_path / "latency.log")
    thread = threading.Thread(target=lambda: log.mark("VAD_END"), daemon=True)
    thread.start()
    thread.join(2)
    assert not thread.is_alive()
