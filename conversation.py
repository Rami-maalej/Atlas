"""Conversational layer for Jarvis — 4 layers, cheapest first.

Every layer is zero-AI except the last one. All input (typed + voice) funnels
through handle(); automation is left untouched — we only RETURN True when the
turn was fully handled conversationally, otherwise the existing router runs.

Every incoming message and every reply is printed to the terminal live.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import time
from datetime import datetime
from pathlib import Path

from conv_config import llm_enabled, load_conv_config
from stt import strip_wake_word

BASE = Path(__file__).resolve().parent
RESPONSES = json.loads((BASE / "responses.json").read_text(encoding="utf-8"))
MEM_FILE = BASE / "memory.json"
CACHE_FILE = BASE / "conversation_cache.json"
LOG_FILE = BASE / "logs" / "llm_calls.log"

_last_reply = {"text": ""}
_pending = {"action": None, "payload": None}


# ---------------------------------------------------------------- helpers
def _memory() -> dict:
    try:
        return json.loads(MEM_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"name": "Rami", "preferences": {}, "last_action": "", "last_target": "", "facts": []}


def _save_memory(mem: dict) -> None:
    MEM_FILE.write_text(json.dumps(mem, indent=2), encoding="utf-8")


def _pick(key: str, **kw) -> str:
    variants = RESPONSES.get(key, [])
    if not variants:
        return ""
    choices = [v for v in variants if v != _last_reply["text"]] or variants
    out = random.choice(choices)
    try:
        out = out.format(**kw)
    except Exception:
        pass
    _last_reply["text"] = out
    return out


def _say(assistant, text: str, layer: str) -> None:
    """Print + speak + show one reply (speak() already syncs bubble & voice)."""
    if not text:
        return
    print(f"[{layer}] Atlantis: {text}", flush=True)
    try:
        assistant.speak(text)
    except Exception as e:
        print(f"[conversation] speak failed: {e}", flush=True)


def _greeting_key() -> str:
    h = datetime.now().hour
    if h < 12:
        return "morning"
    if h < 18:
        return "afternoon"
    return "evening"


def _note_action(name: str, target: str = "") -> None:
    mem = _memory()
    mem["last_action"] = name
    mem["last_target"] = target
    _save_memory(mem)


# ------------------------------------------------------- layer 1: rules
SMALL_TALK = {
    "hello": r"^(hi|hey|hello|yo|good\s+(morning|afternoon|evening)|bonjour|salut)\b[\s!.]*$",
    "how_are_you": r"^(how\s+(are\s+you|r\s+u)|how's\s+it\s+going|what'?s\s+up|comment\s+\?a\s+va)\b[\s?.!]*$",
    "thanks": r"^(thanks|thank\s+you|merci|thx)\b[\s!.]*$",
    "goodbye": r"^(bye|goodbye|see\s+you|later|au\s+revoir|c\+\+)\b[\s!.]*$",
    "joke": r"^(tell\s+(me\s+)?a\s+joke|raconte\s+(moi\s+)?une\s+blague|make\s+me\s+laugh)\b[\s?.!]*$",
    "interrupt": r"^(stop|cancel|shut\s+up|never\s+mind|arrête|arrete)\b[\s!.]*$",
    "confirm_yes": r"^(yes|yeah|yep|sure|go\s+ahead|do\s+it|oui)\b[\s!.]*$",
    "confirm_no": r"^(no|nope|cancel\s+that|don'?t|non)\b[\s!.]*$",
    "remember_name": r"^(my\s+name\s+is|call\s+me|je\s+m'appelle)\s+([\w-]+)",
    "memory_query": r"^(what\s+(is\s+)?my\s+name|who\s+am\s+i|do\s+you\s+remember\s+me|"
                    r"what\s+do\s+(you\s+)?remember\s+about\s+me)\b[\s?.!]*$",
    "save_fact": r"^(?:i\s+(?:love|like|prefer|hate|enjoy)|my\s+favou?rite\s+\w+\s+is|"
                 r"remember\s+that\s+i|i\s+like\s+to)\b",
}

# Common create/delete phrasings for fuzzy matching (rapidfuzz) — these map
# to EXISTING intents; we only correct typos, never reimplement the action.
ACTION_PHRASES = {
    "open chrome": "open_app",
    "open the terminal": "open_app",
    "create a folder": "create_folder",
    "create a file": "create_file",
    "make a folder": "create_folder",
    "write a note": "notes_tools",
    "check my email": "read_emails",
    "play a song on youtube": "youtube_video",
    "show my tasks": "todo_display",
    "what time is it": "get_datetime",
    "what is the weather": "weather_report",
}


_COMMAND_RE = re.compile(
    r"^(?:jarvis[,\s]+)?(?:open|launch|start|play|close|quit|kill|stop|create|make|new|"
    r"write|save|delete|remove|move|copy|search|find|google|look\s+up|check|show|list|"
    r"set|turn|switch|go|run|execute|send|reply|call|text|translate|convert|calculate|"
    r"what|where|when|who|how\s+many|how\s+much|which|tell\s+me|give\s+me|get\s+me|"
    r"read|remember|add|remind|take|buy|connect|disconnect|download|upload|install|"
    r"ouvre|lance|démarr|démarre|cherche|trouve|affiche|crée|créer|supprime|envoie|"
    r"traduis|calcule)\b",
    re.IGNORECASE,
)


def _looks_like_command(text: str) -> bool:
    """True if the text starts with a verb/noun that the existing intent
    router handles — these must NEVER fall through to the LLM fallback."""
    return bool(_COMMAND_RE.match(text.strip()))


def _fuzzy_action(text: str) -> str | None:
    """Return a canonical phrase for a typo'd command, or None."""
    try:
        from rapidfuzz import fuzz, process
    except Exception:
        return None
    best = process.extractOne(text, ACTION_PHRASES.keys(), scorer=fuzz.token_sort_ratio)
    if best and best[1] >= 78:
        return best[0]
    return None


def _rule_layer(text: str) -> tuple[str, str] | None:
    """Return (kind, matched_text) for small talk, else None."""
    t = text.strip().lower()
    for kind, pattern in SMALL_TALK.items():
        m = re.match(pattern, t)
        if m:
            return kind, (m.group(2) if kind == "remember_name" and m.lastindex else "")
    return None


# ------------------------------------------------------ layer 4: LLM
SYSTEM = (
    "You are Jarvis, a friendly human-like assistant. Reply in 1-2 short "
    "sentences, casual tone, no lists, no emojis. At most 80 tokens."
)


def _llm_answer(assistant, history: list[dict], text: str) -> str | None:
    if not llm_enabled():
        return None
    cfg = load_conv_config()
    key = hashlib.sha256(re.sub(r"[^a-z0-9 ]", "", text.lower()).encode()).hexdigest()[:16]
    if cfg.get("LLM_CACHE", True):
        try:
            cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if key in cached:
                print("[llm] cache hit", flush=True)
                return cached[key]
        except Exception:
            pass
    try:
        from core.llm_client import call_llm_text
        recent = history[-3:] if history else []
        prompt = "\n".join(f"{m.get('role','user')}: {m.get('content','')}" for m in recent)
        prompt += f"\nuser: {text}\nassistant:"
        t0 = time.time()
        answer = call_llm_text(prompt, system=SYSTEM, model=cfg.get("LLM_MODEL") or None, timeout=25)
        ms = int((time.time() - t0) * 1000)
        print(f"[llm] call ({ms}ms)", flush=True)
        if cfg.get("LLM_CACHE", True):
            try:
                cache = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}
                cache[key] = answer
                CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
        if cfg.get("LLM_LOG", True):
            try:
                LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
                with LOG_FILE.open("a", encoding="utf-8") as f:
                    f.write(f"{datetime.now().isoformat()} {ms}ms q={text[:80]!r}\n")
            except Exception:
                pass
        return answer.strip() or None
    except Exception as e:
        print(f"[llm] unavailable: {e}", flush=True)
        return None


# -------------------------------------------------------------- public
def handle(assistant, user_text: str) -> bool:
    """Return True if the turn was fully handled here (no automation/LLM path)."""
    text = strip_wake_word(user_text or "").strip()
    if not text:
        return True
    print(f"[you] {text}", flush=True)

    # Layer 1/2 — rules + templates
    rule = _rule_layer(text)
    if rule:
        kind, arg = rule
        name = _memory().get("name", "Rami")
        if kind == "interrupt":
            try:
                import tts as local_tts
                local_tts.stop()
            except Exception:
                pass
            try:
                assistant._tts.stop()
            except Exception:
                pass
            _say(assistant, _pick("interrupt"), "rule")
            return True
        if kind == "confirm_yes" and _pending["action"]:
            action, payload = _pending["action"], _pending["payload"]
            _pending.update(action=None, payload=None)
            _say(assistant, _pick("confirm_yes"), "memory")
            try:
                from core.tools.executor import execute_tool
                result = execute_tool(assistant.ui, action, payload or {}, speak=lambda x: None)
                _say(assistant, _pick("success", target=payload.get("name", "that")), "template")
                _note_action(action)
            except Exception:
                _say(assistant, _pick("error"), "template")
            return True
        if kind == "confirm_no" and _pending["action"]:
            _pending.update(action=None, payload=None)
            _say(assistant, _pick("confirm_no"), "memory")
            return True
        if kind == "hello":
            gkey = _greeting_key()
            if "morning" in text.lower():
                gkey = "morning"
            elif "evening" in text.lower():
                gkey = "evening"
            elif "afternoon" in text.lower():
                gkey = "afternoon"
            hello_variants = RESPONSES["greeting"][gkey]
            hello = random.choice(hello_variants).format(name=name)
            _last_reply["text"] = hello
            _say(assistant, hello, "template")
            return True
        if kind == "how_are_you":
            _say(assistant, _pick("how_are_you", name=name), "template")
            return True
        if kind == "thanks":
            _say(assistant, _pick("thanks", name=name), "template")
            return True
        if kind == "goodbye":
            _say(assistant, _pick("goodbye", name=name), "template")
            return True
        if kind == "joke":
            _say(assistant, _pick("joke"), "template")
            return True
        if kind == "remember_name":
            mem = _memory()
            mname = re.search(r"(?:my\s+name\s+is|call\s+me|je\s+m'appelle)\s+([\w-]+)", user_text, re.IGNORECASE)
            arg = mname.group(1) if mname else arg
            mem["name"] = arg
            _save_memory(mem)
            _say(assistant, _pick("remember_name", name=arg), "memory")
            return True
        if kind == "memory_query":
            mem = _memory()
            last = mem.get("last_action")
            reply = f"You're {mem.get('name','Rami')}." + (f" Last thing I did: {last}." if last else "")
            _say(assistant, reply, "memory")
            return True

    # Layer 1 — fuzzy action correction: rewrite to canonical phrase so the
    # EXISTING intent router handles it (typos tolerated), no new automation.
    canonical = _fuzzy_action(text)
    if canonical:
        if canonical.lower() != text.lower():
            print(f"[rule] fuzzy: {text!r} -> {canonical!r}", flush=True)
            _note_action("fuzzy_correction", canonical)
            _say(assistant, _pick("start", action=canonical), "template")
        # Exact or corrected action → let the EXISTING router execute it.
        return False

    # GUARD — any action-like command must go to the EXISTING router,
    # never to the LLM (which refuses and says "I can't launch apps").
    if _looks_like_command(text):
        print("[rule] command detected -> existing router", flush=True)
        return False

    # Layer 3 — memory-based follow-ups: "same folder as last time?"
    if re.search(r"\b(same\s+(folder|place|as\s+last)|again|last\s+time)\b", text, re.IGNORECASE):
        mem = _memory()
        if mem.get("last_target"):
            _say(assistant, f"Same as last time — {mem['last_target']}.", "memory")
            return True

    # Layer 4 — LLM fallback (rare, logged + cached)
    history = list(getattr(assistant, "_conversation", []) or [])
    answer = _llm_answer(assistant, history, text)
    if answer:
        _say(assistant, answer, "llm")
        return True

    _say(assistant, _pick("unknown"), "template")
    return True


def handle_action(assistant, text: str) -> bool:
    """Wrap an existing action with templated narration + risk confirmation.
    Called from the direct-intent branch; returns True if handled here."""
    from actions.intent_router import route
    r = route(text)
    if not r.matched:
        return False
    target = r.handler_params.get("name") or r.handler_params.get("app_name") or ""
    risky = r.intent_name in {"delete_file", "task_delete", "delete_task"} or bool(
        re.search(r"\b(delete|remove|overwrite|format)\b", text, re.IGNORECASE)
    )
    if risky:
        _pending.update(action=r.handler_name, payload=dict(r.handler_params))
        _say(assistant, _pick("confirm_risky", action=f"{r.intent_name} {target}".strip()), "template")
        return True
    return False
