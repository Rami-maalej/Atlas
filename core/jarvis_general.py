"""Ultra-fast general-knowledge answers.

For everyday factual questions ("Who won the Nobel Prize?",
"What is the capital of Tunisia?", ...) JARVIS skips the full
tool-calling pipeline and answers directly with the configured
AI model, WITHOUT tool definitions (no function schema = much
faster) and with a tiny temperature-0 prompt.

How it works:
  1. A cheap rule-based classifier decides if the message is a
     general-knowledge question (no tools needed).
  2. `ask_general()` streams a direct answer and returns the
     full text as soon as the first complete sentence arrives.
  3. If the fast path fails for any reason, the caller falls
     back to the normal tool-calling pipeline.

Local Ollama answers arrive sub-second once the model is warm;
cloud providers (Groq, NIM…) answer in a few hundred ms.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("jarvis.general")

# Question starters that almost never need tools
_GENERAL_PREFIXES = (
    "who ", "what ", "when ", "where ", "why ", "how ", "which ",
    "is ", "are ", "was ", "were ", "did ", "does ", "do ",
    "name ", "define ", "explain ", "tell me ", "what's ", "who's ",
)

# Explicit task intents that are NOT general knowledge
_TASK_WORDS = (
    "open", "launch", "start", "run", "send", "text", "whatsapp",
    "telegram", "remind", "timer", "schedule", "shutdown", "restart",
    "set ", "mute", "volume", "brightness", "play", "stop", "download",
    "search ", "find", "weather",
)

_FAST_SYSTEM = (
    "You are Atlantis, Rami Maalej's assistant. Answer the general-knowledge "
    "question directly and accurately in 1-3 short, natural sentences — like a "
    "well-informed friend, not an encyclopedia entry. You may end with ONE "
    "useful follow-up question or offer to search for more. No preamble, no "
    "meta-commentary about being an AI."
)

# Pronoun patterns that make a question personal — answered from memory/vault.
_PERSONAL_WORDS = (
    " my ", " mine ", " i ", " i'", " me ", " my'",
    " am i", " do i", " did i", " am ", "j'ai", "mon ", "ma ", "mes ", "je ",
)


def _is_personal_question(t: str) -> bool:
    tspace = f" {t} "
    return any(w in tspace for w in _PERSONAL_WORDS)


def is_general_question(text: str) -> bool:
    """Cheap classifier: general-knowledge question vs. action intent."""
    t = text.strip().lower()
    if not t or len(t) > 220:          # long texts usually contain tasks
        return False
    # Questions about Rami himself ("what are my skills", "where do I work")
    # are PERSONAL knowledge — they need the vault/memory layers, never the
    # context-free fast path (which used to make him say "I cannot do that").
    if _is_personal_question(t):
        return False
    # Social chatter needs the FULL system prompt (persona + memory), not the
    # context-free fast answer — otherwise "how are you?" gets a canned reply.
    try:
        from core.jarvis_utils import _is_smalltalk
        if _is_smalltalk(t):
            return False
    except Exception:
        pass
    tspace = f" {t} "
    if any(t.startswith(w) or w in tspace for w in _TASK_WORDS):
        return False
    for w in _GENERAL_PREFIXES:
        if t.startswith(w):
            return True
    if t.endswith("?"):
        return True
    return False


def ask_general(question: str) -> str | None:
    """Get a fast direct answer from the configured AI provider.

    Returns the full answer text, or None if the fast path failed.
    Uses the configured provider/model WITHOUT tool definitions
    (fastest possible path through the existing LLM client).
    """
    try:
        from core.llm_client import call_llm  # noqa: E402

        messages = [
            {"role": "system", "content": _FAST_SYSTEM},
            {"role": "user",   "content": question},
        ]
        result = call_llm(messages, tools=None, timeout=30)
        answer = ""
        if isinstance(result, dict):
            answer = result.get("content", "") or ""
        elif isinstance(result, str):
            answer = result
        answer = answer.strip()
        # Keep it snappy — cut at a sentence boundary rather than mid-word.
        if len(answer) > 500:
            answer = answer[:500].rsplit(".", 1)[0] + "."
        return answer or None
    except Exception as e:
        logger.warning("Fast general answer failed: %s", e)
        return None
