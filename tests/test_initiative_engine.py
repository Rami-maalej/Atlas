"""Tests for anti-annoyance rules and initiative candidates."""

from __future__ import annotations

from datetime import datetime

from core.conversation_state import ConversationState, State
from core.initiative_engine import (
    AntiAnnoyance,
    AntiAnnoyanceGate,
    Candidate,
    InitiativeEngine,
    _urgent,
)


def test_quiet_hours_block(monkeypatch) -> None:
    rules = AntiAnnoyance(quiet_start=22, quiet_end=8)
    gate = AntiAnnoyanceGate(rules)
    ok, reason = gate.allow(
        Candidate("x", "hi", 0.9),
        now=datetime(2026, 1, 1, 23, 0),
    )
    assert not ok and reason == "quiet hours"


def test_dnd_and_threshold() -> None:
    gate = AntiAnnoyanceGate(AntiAnnoyance(dnd=True))
    assert gate.allow(Candidate("x", "hi", 0.9))[1] == "do not disturb"
    gate2 = AntiAnnoyanceGate(AntiAnnoyance(urgency_threshold=0.8))
    assert gate2.allow(Candidate("x", "hi", 0.4))[0] is False


def test_in_conversation_blocks() -> None:
    sm = ConversationState()
    sm.transition(State.LISTENING)
    gate = AntiAnnoyanceGate()
    ok, reason = gate.allow(Candidate("x", "hi", 0.9), state=sm)
    assert not ok and reason == "in conversation"


def test_on_call_blocks() -> None:
    gate = AntiAnnoyanceGate()
    assert gate.allow(Candidate("x", "hi", 0.9), on_call=True)[1] == "on a call"


def test_rate_limit_and_cooldown() -> None:
    gate = AntiAnnoyanceGate(AntiAnnoyance(max_per_hour=2, cooldown_seconds=60))
    cand = Candidate("topic", "hi", 0.9)
    assert gate.allow(cand)[0] is True
    gate.record_spoken()
    gate.dismiss("other")
    assert gate.allow(Candidate("other", "hi", 0.9))[1] == "dismissed recently"
    gate.record_spoken()
    assert gate.allow(cand)[1] == "rate limit"


def test_low_urgency_notify_only() -> None:
    assert Candidate("x", "hi", 0.5).should_notify_only is True
    assert Candidate("x", "hi", 0.85).should_notify_only is False


def test_urgency_keywords() -> None:
    assert _urgent("URGENT: server down")
    assert not _urgent("weekly newsletter")


def test_followup_candidate_from_episodes(monkeypatch, tmp_path) -> None:
    from core import memory_store

    monkeypatch.setattr(memory_store, "DB_PATH", tmp_path / "memory.db")
    memory_store.MemoryStore().add_episode("my exam is Friday", "noted")
    engine = InitiativeEngine()
    candidates = engine.followup_candidates()
    assert candidates and "exam" in candidates[0].message
