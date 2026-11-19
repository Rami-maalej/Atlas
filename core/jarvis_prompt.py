"""System-prompt loading & building."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agent.agent_manager import get_agent_manager
from core.conversation_style import CONVERSATION_STYLE
from memory.memory_manager import format_memory_for_prompt, load_memory
from memory.vector_memory import get_memory_count, get_relevant_context
from skills.skill_loader import get_active_skill_context

# Paths
BASE_DIR        = Path(__file__).resolve().parent.parent
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
_SYSTEM_PROMPT_CACHE: str | None = None

# ── Cached time-context: re-built at most once per minute ────────────
_time_ctx_cache:      str   = ""
_time_ctx_cache_min:  int   = -1

def _load_system_prompt() -> str:
    global _SYSTEM_PROMPT_CACHE
    if _SYSTEM_PROMPT_CACHE is not None:
        return _SYSTEM_PROMPT_CACHE
    try:
        from core.persona import load_persona
        _SYSTEM_PROMPT_CACHE = (
            PROMPT_PATH.read_text(encoding="utf-8")
            + "\n\n" + load_persona()
        )
    except Exception:
        _SYSTEM_PROMPT_CACHE = (
            "You are ATLANTIS — Rami's aide in the mould of Jarvis from Iron Man. "
            "Calm, precise, dry wit. Address him as 'sir' sparingly. Brief complete "
            "sentences; one or two lines for routine matters. No filler, no "
            "exclamation marks, no emoji. State results first. Never claim an action "
            "succeeded without a confirmed tool result. Always answer in the user's language."
        )
    return _SYSTEM_PROMPT_CACHE


# ---------------------------------------------------------------------------

def _build_system_prompt(self, user_text: str = "") -> str:
    # ── ORDER MATTERS for Ollama KV prefix caching ─────────────────────
    # Ollama caches the KV attention state of any stable prompt prefix.
    # By putting the STATIC JARVIS protocol text FIRST, Ollama reuses its
    # cached KV for all those tokens on every request.  Only the small
    # dynamic tail (memory + time, ~50-80 tokens) needs re-evaluation.
    # This turns a 17-second first-token into a sub-second one after warmup.
    #
    # Rule: static content first → semi-static memory middle → dynamic time LAST.
    sys_p   = _load_system_prompt()               # cached in-process after first call
    # ── User profile: static enough to sit right after the protocol ─────
    try:
        from core.jarvis_profile import profile_for_prompt  # noqa: E402
        _user_profile_ctx = profile_for_prompt()
    except Exception:
        _user_profile_ctx = ""
    memory  = load_memory()
    mem_str = format_memory_for_prompt(memory)    # semi-static
    now     = datetime.now()
    # ── Human-like recall: recent episodes + past conversations ────────
    # In addition to explicit facts, JARVIS now recalls:
    #   • what was discussed recently (working memory / episodes)
    #   • past conversations that match the current topic
    # This is the "remembers like a real person" layer.
    _episodic_ctx = ""
    try:
        from core.jarvis_memory import format_human_recall  # noqa: E402
        # include_facts/vectors=False → those blocks are injected once below
        # (mem_str / vec_context), instead of twice as before.
        _episodic_ctx = format_human_recall(
            user_text, include_facts=False, include_vectors=False
        )
    except Exception:
        pass

    # ── Time context: cached per-minute (avoids regenerating tokens) ───
    global _time_ctx_cache, _time_ctx_cache_min
    cur_min = now.hour * 60 + now.minute
    if cur_min != _time_ctx_cache_min:
        _time_ctx_cache = (
            f"[CRITICAL: CURRENT DATE & TIME — USE THESE VALUES, NEVER YOUR TRAINING DATA]\n"
            f"The current year is {now.year}. Today is: {now.strftime('%A, %B %d, %Y')}\n"
            f"Current time: {now.strftime('%I:%M %p')} (local)\n"
            f"For ANY question about today's date, the time, the year, or the day of the week, "
            f"answer using ONLY the values above — never a year from training data. "
            f"It is {now.year}. Any other year is wrong."
        )
        _time_ctx_cache_min = cur_min
    time_ctx = _time_ctx_cache

    # ── Vector memory + skills: use pre-fetched result if available ─────
    vec_context   = getattr(self, "_prefetched_vec",   None)
    skill_context = getattr(self, "_prefetched_skill", None)
    # Only trust a prefetch that was started for THIS user text.
    if vec_context and getattr(self, "_prefetched_for", None) != user_text:
        vec_context = None
    if skill_context and getattr(self, "_prefetched_for", None) != user_text:
        skill_context = None

    if vec_context is None and user_text:
        vec_context = get_relevant_context(user_text)
    if isinstance(vec_context, str) and vec_context:
        vec_count   = get_memory_count()
        vec_context = f"[SEMANTIC MEMORY — {vec_count} stored memories]\n{vec_context}"
    else:
        vec_context = ""

    if skill_context is None and user_text:
        skill_context = get_active_skill_context(user_text)
    if isinstance(skill_context, str) and skill_context:
        skill_context = f"[ACTIVE SKILL]\n{skill_context}"
    else:
        skill_context = ""

    # Background agents status
    agent_mgr  = get_agent_manager()
    running    = agent_mgr.get_running_count()
    agent_info = f"[BACKGROUND AGENTS: {running} running]" if running > 0 else ""

    parts = [CONVERSATION_STYLE, sys_p]
    if _user_profile_ctx:
        parts.append(_user_profile_ctx)
    if mem_str:
        parts.append(mem_str)
    if _episodic_ctx:
        parts.append(_episodic_ctx)
    if vec_context:
        parts.append(vec_context)
    if skill_context:
        parts.append(skill_context)
    # Obsidian vault = primary long-term memory (TTL-cached, non-fatal)
    try:
        from actions.obsidian_vault import build_memory_context
        vault_ctx = build_memory_context()
    except Exception:
        vault_ctx = ""
    if vault_ctx:
        parts.append(vault_ctx)
    # ── Vault RECALL: the actual contents of the most relevant notes ───
    # This is the "he remembers what I told him, in detail" layer.
    vault_recall = ""
    if user_text:
        try:
            from actions.obsidian_vault import recall_context
            vault_recall = recall_context(user_text)
        except Exception:
            vault_recall = ""
    if vault_recall:
        parts.append(
            "[VAULT RECALL — the notes most relevant to this message; "
            "weave the facts in naturally, do not recite them]\n" + vault_recall
        )
    elif user_text:
        # Always-on vault access: even when no note matches this message
        # directly, show what the vault contains and how to reach it.
        try:
            from actions.obsidian_vault import note_stem_index
            stems = note_stem_index()
        except Exception:
            stems = ""
        if stems:
            parts.append(
                "[VAULT — no note matched this message directly. That does NOT "
                "mean the fact is missing: use the obsidian tool (action "
                "\"search\" or \"read\" or \"list\") to look inside these notes "
                "before ever saying you cannot or don't know about anything "
                "personal to Rami]\n" + stems
            )
    if agent_info:
        parts.append(agent_info)
    parts.append(time_ctx)
    return "\n\n".join(parts)

