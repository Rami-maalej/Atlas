"""Jarvis user profile — everything Jarvis knows about its user.

Reads config/user_profile.json and exposes helpers used by the LLM
system prompt and by intents like "what do you know about me".
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger("jarvis_profile")

_DEFAULT_PROFILE = {
    "name": "Rami Maalej",
    "location": "Sfax, Tunisia",
    "email": "rami.maalej.2002@gmail.com",
    "phone": "+216 54 903 705",
    "languages": ["Arabic (native)", "French (B2)", "English (B2)"],
    "education": {"degree": "B.Sc. in Computer Science", "school": "ISIMS Sfax", "year": "2026"},
    "projects": {"Atlantis": "Desktop AI assistant — Python, PyQt6, Ollama/Groq/Gemini, Whisper STT, TTS, screen OCR, browser automation"},
    "timezone": "Africa/Tunis",
    # Learned from conversation (see core/jarvis_learn.py) — never asked twice.
    "interests": [],
    "_auto_populated": True,
}

_cache: dict | None = None

# Newest first, capped so the prompt block can't grow without bound.
MAX_INTERESTS = 14


def _profile_path() -> Path:
    base = Path(__file__).resolve().parent.parent
    return base / "config" / "user_profile.json"


def load_profile() -> dict:
    """Load the user profile, creating a default one if missing."""
    global _cache
    if _cache is not None:
        return _cache
    path = _profile_path()
    if not path.exists():
        logger.info("user_profile.json missing — creating default")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_DEFAULT_PROFILE, indent=2, ensure_ascii=False), encoding="utf-8")
        _cache = dict(_DEFAULT_PROFILE)
        return _cache
    try:
        _cache = json.loads(path.read_text(encoding="utf-8"))
        return _cache
    except Exception as exc:  # noqa: BLE001
        logger.warning("profile parse error: %s", exc)
        _cache = dict(_DEFAULT_PROFILE)
        return _cache


def update_profile(patch: dict) -> dict:
    """Merge new keys into the profile and persist.

    List fields (interests, skills, work, languages) are MERGED, not
    replaced — losing the existing interests because one new one arrived
    would be a silent memory wipe.
    """
    profile = load_profile()
    for key, value in patch.items():
        if isinstance(value, list) and isinstance(profile.get(key), list):
            existing = profile[key]
            fresh = [i for i in value if i and i not in existing]
            if key == "interests":
                # Newest interest first — the prompt block shows the head.
                profile[key] = (fresh + existing)[:MAX_INTERESTS]
            else:
                existing.extend(fresh)
        else:
            profile[key] = value
    try:
        _profile_path().parent.mkdir(parents=True, exist_ok=True)
        _profile_path().write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("profile write error: %s", exc)
    global _cache
    _cache = profile
    return profile


def profile_for_prompt(max_chars: int = 1600) -> str:
    """Compact prose snippet injected into the system prompt so the LLM
    always knows everything about the user without asking.

    Deliberately not raw JSON: `json.dumps(indent=2)` burned ~3x the tokens
    on braces and key names and got cut off mid-object by max_chars.
    """
    p = load_profile()

    def flat(v, sep=", "):
        if isinstance(v, list):
            return sep.join(str(x) for x in v)
        if isinstance(v, dict):
            return sep.join(f"{k}: {vv}" for k, vv in v.items())
        return str(v)

    lines = ["USER PROFILE — everything you know about your user (never ask for facts already here):"]
    if p.get("name"):
        lines.append(f"Name: {p['name']}")
    loc = p.get("location", "")
    tz = p.get("timezone", "")
    if loc or tz:
        lines.append(f"Location: {loc or '—'} (timezone: {tz or '—'})")
    if p.get("languages"):
        lines.append(f"Languages: {flat(p['languages'])}")
    edu = p.get("education") or {}
    if edu:
        lines.append("Education: " + " — ".join(
            str(edu.get(k, "")) for k in ("degree", "school", "year") if edu.get(k)))
    if p.get("work"):
        lines.append("Experience: " + " | ".join(str(w)[:180] for w in p["work"][:3]))
    if p.get("skills"):
        lines.append(f"Skills: {flat(p['skills'][:20])}")
    if isinstance(p.get("projects"), dict) and p["projects"]:
        lines.append("Projects: " + " | ".join(
            f"{k} — {str(v)[:90]}" for k, v in list(p["projects"].items())[:8]))
    if p.get("interests"):
        lines.append("Interests (learned from you): " + flat(p["interests"]))
    if p.get("notes"):
        lines.append(f"Notes: {flat(p['notes'])}")
    if p.get("email") or p.get("phone"):
        lines.append(f"Contact: {p.get('email', '')} / {p.get('phone', '')}")

    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars]
    return out
