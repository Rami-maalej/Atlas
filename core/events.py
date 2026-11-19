"""Shared async event bus for wake word, idle and UI state events.

The assistant runs most of its work on plain threads, so ``emit()`` uses the
library's synchronous wrapper; handlers may still be async.
"""

from __future__ import annotations

from collections.abc import Callable

from async_event_bus import EventBus

bus = EventBus()

WAKE = "assistant.wake"
SLEEP = "assistant.sleep"
ACTIVITY = "assistant.activity"
STATE = "assistant.state"


def emit(event: str, **kwargs) -> None:
    """Emit an event from synchronous code (safe from worker threads)."""
    bus.emit_sync(event, **kwargs)


def subscribe(event: str, callback: Callable, *, weight: int = 1) -> None:
    """Register a sync or async handler for an event."""
    bus.subscribe(event, callback, weight=weight)
