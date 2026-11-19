"""Proactive initiative engine with strict anti-annoyance rules.

All triggers are read-only. Candidates are short, contextual and dismissible.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.conversation_state import ConversationState, State
from core.paths import memory_path
from memory.config_manager import load_config

logger = logging.getLogger("initiative")

REMINDERS_PATH = memory_path("reminders.json")
DISMISSED_PATH = memory_path("proactive_dismissed.json")


@dataclass
class AntiAnnoyance:
    """All limits are configurable from config/api_keys.json."""

    enabled: bool = True
    dnd: bool = False
    quiet_start: int = 22
    quiet_end: int = 8
    max_per_hour: int = 3
    cooldown_seconds: int = 600
    urgency_threshold: float = 0.55

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None = None) -> AntiAnnoyance:
        cfg = cfg if cfg is not None else load_config()
        return cls(
            enabled=bool(cfg.get("proactive_enabled", True)),
            dnd=bool(cfg.get("do_not_disturb", False)),
            quiet_start=int(cfg.get("quiet_hours_start", 22)),
            quiet_end=int(cfg.get("quiet_hours_end", 8)),
            max_per_hour=int(cfg.get("max_proactive_per_hour", 3)),
            cooldown_seconds=int(cfg.get("proactive_cooldown", 600)),
            urgency_threshold=float(cfg.get("urgency_threshold", 0.55)),
        )


@dataclass
class Candidate:
    """A possible proactive message."""

    topic: str
    message: str
    urgency: float
    kind: str = "speak"

    @property
    def should_notify_only(self) -> bool:
        return self.urgency < 0.7


class AntiAnnoyanceGate:
    """Decide whether a candidate is allowed to interrupt right now."""

    def __init__(self, rules: AntiAnnoyance | None = None):
        self.rules = rules or AntiAnnoyance.from_config()
        self._spoken: list[float] = []
        self._dismissed: dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(DISMISSED_PATH.read_text(encoding="utf-8"))
            self._dismissed = {str(k): float(v) for k, v in data.items()}
        except Exception:
            self._dismissed = {}

    def _save(self) -> None:
        try:
            DISMISSED_PATH.parent.mkdir(parents=True, exist_ok=True)
            DISMISSED_PATH.write_text(
                json.dumps(self._dismissed), encoding="utf-8"
            )
        except Exception:
            pass

    def dismiss(self, topic: str) -> None:
        """Silence one topic for the cooldown period."""
        self._dismissed[topic.lower()] = time.time()
        self._save()

    def allow(
        self,
        candidate: Candidate,
        state: ConversationState | None = None,
        on_call: bool = False,
        now: datetime | None = None,
    ) -> tuple[bool, str]:
        r = self.rules
        now = now or datetime.now()
        if not r.enabled:
            return False, "disabled"
        if r.dnd:
            return False, "do not disturb"
        if r.quiet_start > r.quiet_end:
            if now.hour >= r.quiet_start or now.hour < r.quiet_end:
                return False, "quiet hours"
        elif r.quiet_start <= now.hour < r.quiet_end:
            return False, "quiet hours"
        if state is not None and state.state in (
            State.LISTENING, State.TRANSCRIBING, State.THINKING, State.SPEAKING
        ):
            return False, "in conversation"
        if on_call:
            return False, "on a call"
        if candidate.urgency < r.urgency_threshold:
            return False, "below threshold"
        cutoff = time.time() - 3600
        self._spoken = [t for t in self._spoken if t > cutoff]
        if len(self._spoken) >= r.max_per_hour:
            return False, "rate limit"
        until = self._dismissed.get(candidate.topic.lower(), 0)
        if time.time() - until < r.cooldown_seconds:
            return False, "dismissed recently"
        return True, "ok"

    def record_spoken(self) -> None:
        self._spoken.append(time.time())


class InitiativeEngine:
    """Collect candidates from read-only triggers."""

    def __init__(self, gate: AntiAnnoyanceGate | None = None):
        self.gate = gate or AntiAnnoyanceGate()
        self._lock = threading.Lock()

    def email_candidates(self) -> list[Candidate]:
        """Check unread mail; urgency from simple keyword heuristics."""
        try:
            from core.google_service import GmailClient, GoogleAccountManager

            manager = GoogleAccountManager()
            out: list[Candidate] = []
            for account in manager.list_accounts():
                if account.needs_reauth:
                    continue
                client = GmailClient(account.email, manager)
                rows = client.search("is:unread", limit=5)
                if not rows:
                    continue
                urgent = [r for r in rows if _urgent(r.get("subject", ""))]
                if urgent:
                    out.append(Candidate(
                        topic=f"email:{account.email}",
                        message=f"You've got {len(urgent)} urgent email(s) — want me to read them?",
                        urgency=0.85 if len(urgent) > 1 else 0.72,
                    ))
                elif rows:
                    out.append(Candidate(
                        topic=f"email:{account.email}",
                        message=f"{len(rows)} new emails came in.",
                        urgency=0.45,
                        kind="notify",
                    ))
            return out
        except Exception as e:
            logger.debug("email trigger failed: %s", e)
            return []

    def reminder_candidates(self) -> list[Candidate]:
        """Due reminders from the local store."""
        try:
            reminders = json.loads(REMINDERS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
        now = datetime.now()
        out = []
        for item in reminders if isinstance(reminders, list) else []:
            try:
                when = datetime.fromisoformat(str(item.get("when", "")))
            except Exception:
                continue
            if when <= now and not item.get("done"):
                out.append(Candidate(
                    topic=f"reminder:{item.get('text', '')}",
                    message=f"Reminder: {item.get('text', '')}",
                    urgency=0.8,
                ))
        return out

    def routine_candidates(self) -> list[Candidate]:
        """Time-based routines (once per day, tracked by dismissed topics)."""
        now = datetime.now()
        out: list[Candidate] = []
        if 7 <= now.hour < 9:
            out.append(Candidate(
                topic="routine:morning",
                message="Morning — want a quick briefing?",
                urgency=0.6,
            ))
        if 17 <= now.hour < 19:
            out.append(Candidate(
                topic="routine:eod",
                message="Wrapping up for the day? I can summarize what's left.",
                urgency=0.5,
                kind="notify",
            ))
        return out

    def followup_candidates(self) -> list[Candidate]:
        """Follow up on things the user said earlier."""
        try:
            from core.memory_store import MemoryStore

            episodes = MemoryStore().recent_episodes(limit=10)
        except Exception:
            return []
        out = []
        for ep in episodes:
            text = str(ep.get("user", ""))
            if "exam" in text.lower():
                out.append(Candidate(
                    topic=f"followup:{text[:40]}",
                    message="You mentioned an exam — how did it go?",
                    urgency=0.6,
                ))
                break
        return out

    def collect(self) -> list[Candidate]:
        return (
            self.email_candidates()
            + self.reminder_candidates()
            + self.routine_candidates()
            + self.followup_candidates()
        )


_URGENT_WORDS = ("urgent", "asap", "now", "deadline", " today", "invoice", "failed")


def _urgent(subject: str) -> bool:
    low = subject.lower()
    return any(word in low for word in _URGENT_WORDS)
