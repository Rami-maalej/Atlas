"""Human-like memory for JARVIS.

Adds a layered memory system on top of the existing long-term / vector
memory, so JARVIS remembers like a real person:

  1. Episodic  — every conversation turn is logged with context
                 ("what happened, when, with whom").
  2. Semantic  — facts, preferences, identity, projects (existing
                 long_term.json, now enriched with timestamps + recency).
  3. Reflective — at the end of a conversation JARVIS extracts durable
                 facts and preferences and consolidates them into long-term
                 storage (like a person reviewing their day).
  4. Recall    — on every new user message, the system automatically
                 retrieves the most relevant past context (vector +
                 recency + explicit memories) and injects it in the prompt.

This module is the recall side; storage is shared with
memory/memory_manager.py and memory/vector_memory.py (no duplicate state).
"""
from __future__ import annotations

import json
import logging
import time as _time
from datetime import datetime
from threading import RLock

logger = logging.getLogger("jarvis.memory")

from core.paths import memory_dir, memory_path

BASE_DIR    = memory_dir().parent
MEMORY_DIR  = memory_dir()
EPISODES_PATH = memory_path("episodes.json")
_lock       = RLock()  # module-level guard (reentrant)

# ── In-memory episode cache (avoid disk reads on every turn) ────────────
_EPISODES:        list[dict] = []
_EPISODES_LOADED: bool       = False


def _load_episodes() -> list[dict]:
    global _EPISODES, _EPISODES_LOADED
    if _EPISODES_LOADED:
        return _EPISODES
    with _lock:
        if EPISODES_PATH.exists():
            try:
                _EPISODES = json.loads(EPISODES_PATH.read_text(encoding="utf-8"))
                if not isinstance(_EPISODES, list):
                    _EPISODES = []
            except Exception:
                _EPISODES = []
        _EPISODES_LOADED = True
        return _EPISODES


def _save_episodes() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    EPISODES_PATH.write_text(
        json.dumps(_EPISODES[-1500:], ensure_ascii=False),   # rolling window
        encoding="utf-8",
    )


def flush_episodes() -> None:
    """Write the episodic buffer to disk.

    Called during shutdown so the next launch starts with the full history
    instead of only the turns that happened to be flushed along the way.
    """
    with _lock:
        if not _EPISODES_LOADED:
            _load_episodes()
        _save_episodes()


def record_episode(user_text: str, assistant_text: str,
                   mode: str = "conversation") -> None:
    """Log one conversation turn — JARVIS episodic memory."""
    episode = {
        "t":  datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ts": _time.time(),
        "u":  user_text[:500],
        "a":  assistant_text[:1200],
        "m":  mode,
    }
    with _lock:
        _load_episodes()
        _EPISODES.append(episode)
        _save_episodes()
    # The vault journal is the readable twin of the episodic buffer.
    try:
        from actions.obsidian_vault import append_journal
        append_journal(user_text, assistant_text)
    except Exception:
        pass


def recent_episodes(n: int = 5) -> list[dict]:
    return _load_episodes()[-n:]


def update_last_episode(assistant_text: str) -> None:
    """Fill in the assistant answer of the most recent recorded episode."""
    with _lock:
        eps = _load_episodes()
        if eps:
            eps[-1]["a"] = assistant_text[:1200]
            _save_episodes()


def format_episode_recall(query: str, top_k: int = 4) -> str:
    """Recency-based recall: the latest relevant episodes.

    Unlike semantic search (embeddings), this mimics "what happened
    recently" — human short-term memory.
    """
    eps = _load_episodes()
    if not eps:
        return ""
    q = query.lower()
    recent = eps[-min(3, top_k):] if top_k > 0 else []
    recent_ids = {id(ep) for ep in recent}
    # simple keyword overlap + recency weighting
    scored: list[tuple[float, dict]] = []
    for ep in eps[-300:]:
        if id(ep) in recent_ids:
            continue
        if not q:
            score = 0.1
        else:
            words = [w for w in q.split() if len(w) > 2]
            hit = sum(1 for w in words if w in ep["u"].lower() or w in ep["a"].lower())
            if hit == 0:
                continue
            score = hit / max(len(words), 1)
        scored.append((score, ep))
    scored.sort(key=lambda t: -t[0])
    picks = [(0.1, ep) for ep in recent]
    picks.extend(scored[:max(0, top_k - len(picks))])
    lines = []
    for _, ep in picks:
        lines.append(f"- [{ep['t']}] You: {ep['u']}\n  Me:  {ep['a'][:220]}")
    return "\n".join(lines)


def format_human_recall(query: str, top_k: int = 5,
                        include_facts: bool = True,
                        include_vectors: bool = True) -> str:
    """Combined human-style recall for the system prompt.

    Merges: explicit memories (long_term.json), semantic vectors,
    and recent episodes.

    `include_facts` / `include_vectors` let the caller skip the pieces it
    already injects on its own — without them the long-term memory block was
    emitted TWICE in the same system prompt (jarvis_prompt + here), wasting
    prompt budget on every single turn.
    """
    from memory.memory_manager import format_memory_for_prompt, load_memory
    from memory.vector_memory import get_relevant_context, recent_conversations, search_conversation

    parts: list[str] = []

    # 1. Explicit memory (facts / preferences / identity)
    if include_facts:
        mem = load_memory()
        mem_str = format_memory_for_prompt(mem)
        if mem_str:
            parts.append(mem_str)

    # 2. Semantic vectors (long-term associations)
    if query:
        if include_vectors:
            vec = get_relevant_context(query, top_k=top_k)
            if isinstance(vec, str) and vec.strip():
                parts.append(f"[SEMANTIC MEMORY]\n{vec}")
        # 3. Past conversations that match
        conv = search_conversation(query, top_k=2)
        if conv:
            lines = []
            for c in conv[:2]:
                lines.append(
                    f"- [{c.get('timestamp', '')[:16]}] "
                    f"You: {str(c.get('user', ''))[:140]}\n"
                    f"  Atlantis: {str(c.get('assistant', ''))[:200]}"
                )
            parts.append("[PAST CONVERSATIONS]\n" + "\n".join(lines))

    # Recent conversation recall does not depend on embeddings being available.
    recent = recent_conversations(limit=8)
    if recent:
        lines = []
        for item in recent:
            lines.append(
                f"- You: {str(item.get('user', ''))[:200]}\n"
                f"  Atlantis: {str(item.get('assistant', ''))[:240]}"
            )
        parts.append("[RECENT CONVERSATIONS]\n" + "\n".join(lines))

    # 4. Recent episodes (short-term / working memory)
    rec = format_episode_recall(query, top_k=4)
    if rec:
        parts.append(f"[RECENT EPISODES]\n{rec}")

    return "\n\n".join(parts)
