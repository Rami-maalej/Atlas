"""Startup progress tracking.

The startup sequence runs several subsystems in parallel, so a single
"loading" bar told the user nothing about where the time went.  This
module keeps a weighted, thread-safe view of the boot process so the
loading screen can show *real* progress:

* every stage declares a weight (how much of the total it is worth)
* stages report 0 → 1 as they advance
* the overall percentage is the weighted sum

The UI polls :func:`snapshot` on a timer, so worker threads never touch
Qt directly.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Stage:
    """One boot step."""

    key: str
    label: str
    weight: float = 1.0
    detail: str = ""
    progress: float = 0.0        # 0.0 → 1.0
    state: str = "pending"       # pending | running | done | error
    started_at: float = 0.0
    ended_at: float = 0.0

    @property
    def elapsed(self) -> float:
        if not self.started_at:
            return 0.0
        end = self.ended_at or time.monotonic()
        return max(0.0, end - self.started_at)


class StartupProgress:
    """Thread-safe registry of boot stages."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stages: dict[str, Stage] = {}
        self._order: list[str] = []
        self._started = time.monotonic()
        self._finished = False

    # ── Registration ─────────────────────────────────────────────────────
    def add(self, key: str, label: str, weight: float = 1.0) -> None:
        """Register a stage.  Safe to call before the stage starts."""
        with self._lock:
            if key in self._stages:
                return
            self._stages[key] = Stage(key=key, label=label, weight=weight)
            self._order.append(key)

    def add_many(self, stages: list[tuple[str, str, float]]) -> None:
        for key, label, weight in stages:
            self.add(key, label, weight)

    # ── Progress reporting ───────────────────────────────────────────────
    def start(self, key: str, detail: str = "") -> None:
        with self._lock:
            stage = self._stages.get(key)
            if stage is None:
                self.add(key, key.title())
                stage = self._stages[key]
            stage.state = "running"
            stage.started_at = time.monotonic()
            stage.progress = 0.0
            if detail:
                stage.detail = detail

    def update(self, key: str, progress: float, detail: str = "") -> None:
        """Report fractional progress for a running stage."""
        with self._lock:
            stage = self._stages.get(key)
            if stage is None:
                return
            stage.progress = max(0.0, min(1.0, progress))
            if detail:
                stage.detail = detail
            if stage.state == "pending":
                stage.state = "running"
                stage.started_at = time.monotonic()

    def finish(self, key: str, error: bool = False, detail: str = "") -> None:
        with self._lock:
            stage = self._stages.get(key)
            if stage is None:
                return
            stage.state = "error" if error else "done"
            stage.progress = 1.0
            stage.ended_at = time.monotonic()
            if detail:
                stage.detail = detail

    def complete(self) -> None:
        """Mark the whole boot as finished."""
        with self._lock:
            for stage in self._stages.values():
                if stage.state in ("pending", "running"):
                    stage.state = "done"
                    stage.progress = 1.0
                    stage.ended_at = time.monotonic()
            self._finished = True

    # ── Reading ──────────────────────────────────────────────────────────
    def snapshot(self) -> dict[str, Any]:
        """Return the current state — read by the UI on a timer."""
        with self._lock:
            stages = [
                {
                    "key": s.key,
                    "label": s.label,
                    "detail": s.detail,
                    "progress": s.progress,
                    "state": s.state,
                    "elapsed": s.elapsed,
                    "weight": s.weight,
                }
                for s in (self._stages[k] for k in self._order)
            ]
            total_weight = sum(s["weight"] for s in stages) or 1.0
            done_weight = sum(
                s["weight"] * (1.0 if s["state"] in ("done", "error") else s["progress"])
                for s in stages
            )
            overall = max(0.0, min(1.0, done_weight / total_weight))
            # A stage that errors still counts as attempted work.
            return {
                "stages": stages,
                "overall": overall,
                "percent": int(round(overall * 100)),
                "elapsed": time.monotonic() - self._started,
                "finished": self._finished,
                "active": next(
                    (s["label"] for s in stages if s["state"] == "running"),
                    "",
                ),
            }


#: The shared instance used by the boot sequence.
PROGRESS = StartupProgress()
