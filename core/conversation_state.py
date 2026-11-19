"""Conversation state machine and per-stage latency logging.

States: IDLE -> LISTENING -> TRANSCRIBING -> THINKING -> SPEAKING -> IDLE.
Barge-in moves SPEAKING back to LISTENING. SLEEP is an extension of IDLE used
by the existing wake-word/idle system.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from core.paths import memory_path

logger = logging.getLogger("conversation_state")


class State(StrEnum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    SLEEP = "SLEEP"


ALLOWED: dict[State, set[State]] = {
    State.IDLE: {State.LISTENING, State.SLEEP},
    State.SLEEP: {State.LISTENING, State.IDLE},
    State.LISTENING: {State.TRANSCRIBING, State.IDLE, State.SLEEP},
    State.TRANSCRIBING: {State.THINKING, State.LISTENING, State.IDLE},
    State.THINKING: {State.SPEAKING, State.LISTENING, State.IDLE},
    State.SPEAKING: {State.LISTENING, State.THINKING, State.IDLE},
}


class InvalidTransition(ValueError):
    """Raised when a requested state transition is not allowed."""


class ConversationState:
    """Thread-safe state holder with validated transitions."""

    def __init__(self, on_change: Callable[[State, State], None] | None = None):
        self._state = State.IDLE
        self._lock = threading.RLock()
        self._on_change = on_change
        self._follow_up_until = 0.0
        self._last_user_turn = 0.0

    @property
    def state(self) -> State:
        with self._lock:
            return self._state

    def transition(self, target: State, *, force: bool = False) -> State:
        with self._lock:
            old = self._state
            if old is target:
                return old
            if not force and target not in ALLOWED.get(old, set()):
                raise InvalidTransition(f"{old.value} -> {target.value}")
            self._state = target
        if self._on_change:
            try:
                self._on_change(old, target)
            except Exception as e:
                logger.debug("state callback failed: %s", e)
        return target

    def reset(self) -> None:
        """Any state may collapse to IDLE on error/cancel."""
        self.transition(State.IDLE, force=True)

    def barge_in(self) -> bool:
        """User started talking while the assistant was speaking."""
        with self._lock:
            if self._state is State.SPEAKING:
                self._state = State.LISTENING
                target = True
            else:
                target = False
        if target and self._on_change:
            self._on_change(State.SPEAKING, State.LISTENING)
        return target

    @property
    def is_speaking(self) -> bool:
        return self.state is State.SPEAKING

    def note_user_turn(self, follow_up_seconds: float = 12.0) -> None:
        """Open the follow-up window after answering a user turn."""
        with self._lock:
            self._last_user_turn = time.monotonic()
            self._follow_up_until = self._last_user_turn + follow_up_seconds

    def in_follow_up_window(self) -> bool:
        with self._lock:
            return time.monotonic() <= self._follow_up_until

    def clear_follow_up(self) -> None:
        with self._lock:
            self._follow_up_until = 0.0


STAGES = ("VAD_END", "STT_DONE", "FIRST_LLM_TOKEN", "FIRST_TTS_AUDIO", "RESPONSE_END")


class LatencyLog:
    """Append-only per-turn stage timings to a local debug log."""

    def __init__(self, path: Path | None = None, enabled: bool = True):
        self.path = path or memory_path("latency.log")
        self.enabled = enabled
        self._start = 0.0
        self._marks: dict[str, float] = {}
        self._lock = threading.RLock()

    def begin_turn(self) -> None:
        with self._lock:
            self._start = time.monotonic()
            self._marks = {}

    def mark(self, stage: str) -> None:
        if stage not in STAGES:
            return
        with self._lock:
            if not self._start:
                self.begin_turn()
            self._marks[stage] = time.monotonic() - self._start

    def finish(self) -> dict[str, float]:
        with self._lock:
            marks = dict(self._marks)
            if not self.enabled or not marks:
                self._start = 0.0
                return marks
            line = "  ".join(f"{k}={v*1000:.0f}ms" for k, v in marks.items())
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {line}\n")
            except Exception as e:
                logger.debug("latency log failed: %s", e)
            self._start = 0.0
            self._marks = {}
            return marks
