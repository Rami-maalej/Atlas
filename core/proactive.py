"""Autonomous proactive mind — Atlantis initiates instead of waiting.

Background daemon (started from JarvisLocal.run()) that:

* nudges about **due / overdue tasks** once per task per day,
* delivers a **morning briefing** (07:00–10:30, once/day),
* runs an **evening reflection** (20:00–23:00) that counters the day and
  writes a Journal note into the **Obsidian vault** (the primary memory),
* keeps dedupe state in ``memory/proactive_state.json``.

All messages surface as normal chat bubbles (``Atlantis: …`` prefix, which the
UI parser renders). Voice is used only for the briefing when not muted.
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from core.paths import memory_path

logger = logging.getLogger("proactive")

BASE_DIR = Path(__file__).resolve().parent.parent
TASKS_PATH = memory_path("tasks.json")
EPISODES_PATH = memory_path("episodes.json")
STATE_PATH = memory_path("proactive_state.json")

CHECK_SECONDS = 300          # 5-minute cadence
BRIEFING_WINDOW = (7, 30, 10, 30)    # 07:30 → 10:30
EVENING_WINDOW = (20, 0, 23, 0)      # 20:00 → 23:00

_state_lock = threading.Lock()
_started = False
_stop_event = threading.Event()


# ── small helpers ───────────────────────────────────────────────────────
def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_state() -> dict:
    st = _load_json(STATE_PATH, {})
    return st if isinstance(st, dict) else {}


def _save_state(st: dict) -> None:
    try:
        with _state_lock:
            STATE_PATH.write_text(
                json.dumps(st, indent=1, ensure_ascii=False), encoding="utf-8"
            )
    except Exception as e:
        logger.debug("state save failed: %s", e)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _in_window(window: tuple[int, int, int, int]) -> bool:
    now = datetime.now()
    h1, m1, h2, m2 = window
    start = now.replace(hour=h1, minute=m1, second=0, microsecond=0)
    end = now.replace(hour=h2, minute=m2, second=0, microsecond=0)
    return start <= now <= end


# ── data sources ────────────────────────────────────────────────────────
def due_tasks() -> list[dict]:
    """Open tasks whose due date is today or earlier (ISO strings compare fine)."""
    data = _load_json(TASKS_PATH, {})
    today = _today()
    out: list[dict] = []
    for t in (data.get("tasks") or []) if isinstance(data, dict) else []:
        if isinstance(t, dict) and not t.get("done"):
            due = str(t.get("due") or "").strip()
            if due and due[:10] <= today:
                out.append(t)
    out.sort(key=lambda t: str(t.get("due") or ""))
    return out


def _todays_episodes() -> list[dict]:
    eps = _load_json(EPISODES_PATH, [])
    if not isinstance(eps, list):
        return []
    today = _today()
    return [e for e in eps if isinstance(e, dict) and str(e.get("t", "")).startswith(today)]


# ── message builders ────────────────────────────────────────────────────
def briefing_text() -> str:
    tasks = due_tasks()
    now = datetime.now()
    parts = [f"Good morning, Rami — it's {now.strftime('%A, %B %d')}."]
    if tasks:
        titles = ", ".join(str(t.get("title") or "?") for t in tasks[:3])
        over = sum(1 for t in tasks if str(t.get("due"))[:10] < _today())
        lead = f"{len(tasks)} due task" + ("s" if len(tasks) != 1 else "")
        if over:
            lead += f" ({over} overdue)"
        parts.append(f"{lead}: {titles}.")
        high = [t for t in tasks if str(t.get("priority", "")).lower() == "high"]
        if high:
            parts.append("High priority: " + str(high[0].get("title")) + ".")
    else:
        parts.append("Nothing due today — you're clear.")
    return " ".join(parts)


def nudge_text(task: dict) -> str:
    title = str(task.get("title") or "a task")
    due = str(task.get("due") or "")[:10]
    today = _today()
    if due < today:
        return f"Reminder: '{title}' was due {due} — still open. Want me to push it to next week?"
    return f"'{title}' is due today. Want me to keep it on your radar tonight?"


def evening_text() -> tuple[str, bool]:
    """Returns (message, should_write_journal)."""
    episodes = _todays_episodes()
    tasks = due_tasks()
    data = _load_json(TASKS_PATH, {})
    all_tasks = [t for t in (data.get("tasks") or [])] if isinstance(data, dict) else []
    done = sum(1 for t in all_tasks if isinstance(t, dict) and t.get("done"))
    bits = []
    if episodes:
        bits.append(f"{len(episodes)} exchanges logged to your vault")
    else:
        bits.append("quiet day — no conversations recorded")
    bits.append(f"{len(all_tasks) - done} tasks still open")
    if tasks:
        bits.append(f"{len(tasks)} due")
    return "Day wrapped: " + ", ".join(bits) + ".", bool(episodes)


def write_vault_journal(episodes: list[dict]) -> bool:
    """Append today's conversations as a Journal note in the Obsidian vault."""
    try:
        from actions.obsidian_vault import save_note

        today = _today()
        lines = [f"# {today}", "", f"{len(episodes)} exchanges with Atlantis.", ""]
        for e in episodes[-40:]:
            u = str(e.get("u", "")).replace("\n", " ")[:200]
            a = str(e.get("a", "")).replace("\n", " ")[:350]
            lines.append(f"- **You:** {u}")
            lines.append(f"  **Atlantis:** {a}")
        save_note(title=f"Day {today}", content="\n".join(lines), folder="Journal")
        return True
    except Exception as e:
        logger.debug("vault journal failed: %s", e)
        return False


# ── one full check cycle ────────────────────────────────────────────────
def _notify(ui, speak_fn, text: str, voice: bool = False) -> None:
    try:
        if ui is not None:
            ui.write_log(f"Atlantis: {text}")
        if voice and speak_fn is not None and not getattr(ui, "muted", False):
            speak_fn(text)
    except Exception as e:
        logger.debug("notify failed: %s", e)


def run_check(ui=None, speak_fn: Callable[[str], None] | None = None) -> list[str]:
    """Run every autonomous check once. Returns the messages it surfaced."""
    st = _load_state()
    today = _today()
    surfaced: list[str] = []

    # 1. Due-task nudges (once per task per day)
    nudged = st.setdefault("nudged", {})
    for t in due_tasks():
        tid = str(t.get("id") or t.get("title") or "")
        if tid and nudged.get(tid) != today:
            msg = nudge_text(t)
            _notify(ui, speak_fn, msg)
            surfaced.append(msg)
            nudged[tid] = today

    # 2. Morning briefing (window, once/day)
    if _in_window(BRIEFING_WINDOW) and st.get("briefing") != today:
        msg = briefing_text()
        _notify(ui, speak_fn, msg, voice=True)
        surfaced.append(msg)
        st["briefing"] = today

    # 3. Evening reflection + vault journal (window, once/day)
    if _in_window(EVENING_WINDOW) and st.get("evening") != today:
        msg, journal = evening_text()
        wrote = write_vault_journal(_todays_episodes()) if journal else False
        if wrote:
            msg += " Journal note written."
        _notify(ui, speak_fn, msg)
        surfaced.append(msg)
        st["evening"] = today

    # keep nudge map from growing forever
    if len(nudged) > 200:
        st["nudged"] = dict(list(nudged.items())[-100:])

    _save_state(st)
    return surfaced


# ── daemon lifecycle ────────────────────────────────────────────────────
def _loop(ui, speak_fn) -> None:
    # first cycle after a short grace period (let startup settle)
    if _stop_event.wait(45):
        return
    while not _stop_event.is_set():
        try:
            run_check(ui, speak_fn)
        except Exception as e:
            logger.debug("proactive cycle failed: %s", e)
        if _stop_event.wait(CHECK_SECONDS):
            return


def start_proactive(ui, speak_fn: Callable[[str], None] | None = None) -> bool:
    """Start the daemon once. Returns True if a new thread was started."""
    global _started
    if _started:
        return False
    _started = True
    _stop_event.clear()
    threading.Thread(target=_loop, args=(ui, speak_fn), daemon=True).start()
    print("[Proactive] Autonomous mind started")
    return True


def stop_proactive() -> None:
    """Ask the autonomous mind to stop its next cycle."""
    global _started
    _stop_event.set()
    _started = False
