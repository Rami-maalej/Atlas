import json
import time as _time
from datetime import datetime
from threading import Lock
from pathlib import Path

from core.paths import base_dir as get_base_dir
from core.paths import memory_path


BASE_DIR         = get_base_dir()
MEMORY_PATH      = memory_path("long_term.json")
_lock            = Lock()
MAX_VALUE_LENGTH = 380

# The six canonical categories.  ``format_memory_for_prompt`` reads exactly
# these keys, so anything else is invisible to the assistant.
CATEGORIES = ("identity", "preferences", "projects", "relationships", "wishes", "notes")

# The LLM emits category names in every casing and synonym it likes
# ("Preferences", "Name", "prefs", "personal", ...).  Left unchecked those
# create new top-level keys that the prompt builder never reads, so the
# fact was saved but the assistant could never recall it.
_CATEGORY_ALIASES = {
    "identity": "identity",
    "name": "identity",
    "names": "identity",
    "personal": "identity",
    "profile": "identity",
    "about_me": "identity",
    "user": "identity",
    "me": "identity",
    "preferences": "preferences",
    "preference": "preferences",
    "prefs": "preferences",
    "likes": "preferences",
    "dislikes": "preferences",
    "favorites": "preferences",
    "favourite": "preferences",
    "habits": "preferences",
    "taste": "preferences",
    "projects": "projects",
    "project": "projects",
    "work": "projects",
    "goals": "projects",
    "relationships": "relationships",
    "relationship": "relationships",
    "people": "relationships",
    "contacts": "relationships",
    "family": "relationships",
    "wishes": "wishes",
    "wish": "wishes",
    "plans": "wishes",
    "notes": "notes",
    "note": "notes",
    "other": "notes",
    "general": "notes",
    "misc": "notes",
}


def normalize_category(category: str) -> str:
    """Map a free-form category name onto one of the canonical six.

    Unknown categories fall back to "notes" rather than being dropped, so
    nothing the user says is lost.
    """
    if not isinstance(category, str):
        return "notes"
    key = category.strip().lower().replace("-", "_").replace(" ", "_")
    if key in CATEGORIES:
        return key
    return _CATEGORY_ALIASES.get(key, "notes")

# 2200 chars evicted genuine facts (name, project, preference) after ~2 days
# because a single long note pushed past the cap. 3200 still keeps the
# injected block well under 800 tokens.
MEMORY_MAX_CHARS = 3200

# ── In-memory cache to avoid disk reads every turn ──────────────────────
_MEMORY_CACHE:     dict  = {}
_MEMORY_CACHE_AT:  float = 0.0
_MEMORY_CACHE_TTL: float = 2.0

def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":   {},
        "projects":      {},
        "relationships": {},
        "wishes":        {},
        "notes":         {},
    }

def load_memory() -> dict:
    global _MEMORY_CACHE_AT, _MEMORY_CACHE
    now = _time.monotonic()
    if now - _MEMORY_CACHE_AT < _MEMORY_CACHE_TTL and _MEMORY_CACHE:
        return _MEMORY_CACHE
    if not MEMORY_PATH.exists():
        return _empty_memory()
    with _lock:
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base = _empty_memory()
                for key in base:
                    if key not in data:
                        data[key] = {}
                # Fold legacy non-canonical categories ("Preferences", "Name")
                # into their canonical bucket so previously-saved facts become
                # visible to the prompt builder again.
                for key in list(data.keys()):
                    if key in base:
                        continue
                    entries = data[key]
                    if not isinstance(entries, dict):
                        continue
                    target = normalize_category(key)
                    if target == key:
                        continue
                    merged = data[target]
                    for sub_key, entry in entries.items():
                        merged.setdefault(sub_key, entry)
                    del data[key]
                _MEMORY_CACHE.clear()
                _MEMORY_CACHE.update(data)
                _MEMORY_CACHE_AT = now
                return data
            return _empty_memory()
        except Exception as e:
            print(f"[Memory] ⚠️ Load error: {e}")
            return _empty_memory()

def _all_entries(memory: dict) -> list[tuple]:
    entries = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if isinstance(entry, dict) and "value" in entry:
                entries.append((cat, key, entry))
    return entries


def _trim_to_limit(memory: dict) -> dict:
    if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
        return memory
    entries = _all_entries(memory)
    entries.sort(key=lambda t: t[2].get("updated", "0000-00-00"))
    for cat, key, _ in entries:
        if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
            break
        del memory[cat][key]
        print(f"[Memory] 🗑️  Trimmed {cat}/{key}")
    return memory

def save_memory(memory: dict) -> None:
    if not isinstance(memory, dict):
        return
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        memory = _trim_to_limit(memory)
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    global _MEMORY_CACHE_AT
    _MEMORY_CACHE_AT = 0.0


def _truncate_value(val: str) -> str:
    if isinstance(val, str) and len(val) > MAX_VALUE_LENGTH:
        return val[:MAX_VALUE_LENGTH].rstrip() + "…"
    return val


def _recursive_update(target: dict, updates: dict) -> bool:
    changed = False
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, dict) and "value" not in value:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
                changed = True
            if _recursive_update(target[key], value):
                changed = True
        else:
            new_val  = _truncate_value(str(value["value"] if isinstance(value, dict) else value))
            entry    = {"value": new_val, "updated": datetime.now().strftime("%Y-%m-%d")}
            existing = target.get(key, {})
            if not isinstance(existing, dict) or existing.get("value") != new_val:
                target[key] = entry
                changed = True
    return changed


def update_memory(memory_update: dict) -> dict:
    global _MEMORY_CACHE_AT, _MEMORY_CACHE
    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()
    # Normalize the category keys before writing so a fact can never land
    # in a non-canonical bucket that the prompt builder cannot see.
    memory_update = {
        normalize_category(category): entries
        for category, entries in memory_update.items()
        if isinstance(entries, dict)
    }
    if not memory_update:
        return load_memory()
    with _lock:
        try:
            memory = json.loads(MEMORY_PATH.read_text(encoding="utf-8")) if MEMORY_PATH.exists() else _empty_memory()
        except Exception as e:
            print(f"[Memory] ⚠️ Load error during update: {e}")
            memory = _empty_memory()
        changed = _recursive_update(memory, memory_update)
        if changed:
            _trim_to_limit(memory)
            # The memory directory may not exist yet on a fresh install.
            MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            MEMORY_PATH.write_text(json.dumps(memory, indent=2, ensure_ascii=False), encoding="utf-8")
            _MEMORY_CACHE.clear()
            _MEMORY_CACHE.update(memory)
            _MEMORY_CACHE_AT = 0.0
            _mirror_to_vault(memory)
    if changed:
        print(f"[Memory] 💾 Saved: {list(memory_update.keys())}")
    return memory


def _mirror_to_vault(memory: dict) -> None:
    """Mirror the fact tables into the Obsidian vault.

    The vault is the assistant's long-term home: facts are readable and
    editable there.  The JSON file stays as a fast cache and a fallback
    when no vault is configured.
    """
    try:
        from actions.obsidian_vault import load_facts, store_facts
    except Exception:
        return
    for category in CATEGORIES:
        entries = memory.get(category) or {}
        if not isinstance(entries, dict) or not entries:
            continue
        facts = {
            key: str(entry.get("value") if isinstance(entry, dict) else entry)
            for key, entry in entries.items()
        }
        store_facts(category, facts)


def import_vault_facts() -> int:
    """Pull facts out of the Obsidian vault into the JSON memory.

    This runs at startup so facts edited by hand inside Obsidian are
    picked up, and so a fresh install can restore memory from the vault
    alone.  Returns the number of facts imported.
    """
    try:
        from actions.obsidian_vault import load_facts
    except Exception:
        return 0
    vault = load_facts()
    if not vault:
        return 0
    imported = 0
    for category, facts in vault.items():
        if not facts:
            continue
        for key, value in facts.items():
            if not str(value).strip():
                continue
            update_memory({category: {key: {"value": value}}})
            imported += 1
    if imported:
        print(f"[Memory] 📥 Imported {imported} fact(s) from the Obsidian vault")
    return imported

def format_memory_for_prompt(memory: dict | None) -> str:
    if not memory:
        return ""

    lines = []

    identity  = memory.get("identity", {})
    id_fields = ["name", "age", "birthday", "city", "job", "language", "school", "nationality"]
    for field in id_fields:
        entry = identity.get(field)
        if entry:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"{field.title()}: {val}")
    for key, entry in identity.items():
        if key in id_fields:
            continue
        val = entry.get("value") if isinstance(entry, dict) else entry
        if val:
            lines.append(f"{key.replace('_', ' ').title()}: {val}")

    prefs = memory.get("preferences", {})
    if prefs:
        lines.append("")
        lines.append("Preferences:")
        for key, entry in list(prefs.items())[:15]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    projects = memory.get("projects", {})
    if projects:
        lines.append("")
        lines.append("Active Projects / Goals:")
        for key, entry in list(projects.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    rels = memory.get("relationships", {})
    if rels:
        lines.append("")
        lines.append("People in their life:")
        for key, entry in list(rels.items())[:10]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    wishes = memory.get("wishes", {})
    if wishes:
        lines.append("")
        lines.append("Wishes / Plans / Wants:")
        for key, entry in list(wishes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    notes = memory.get("notes", {})
    if notes:
        lines.append("")
        lines.append("Other notes:")
        for key, entry in list(notes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key}: {val}")

    if not lines:
        return ""

    header = "[WHAT YOU KNOW ABOUT THIS PERSON — use naturally, never recite like a list]\n"
    result = header + "\n".join(lines)
    if len(result) > 2600:
        result = result[:2597] + "…"

    return result + "\n"

def remember(key: str, value: str, category: str = "notes") -> str:
    category = normalize_category(category)
    update_memory({category: {key: {"value": value}}})
    return f"Remembered: {category}/{key} = {value}"


def forget(key: str, category: str = "notes") -> str:
    memory = load_memory()
    cat    = memory.get(category, {})
    if key in cat:
        del cat[key]
        memory[category] = cat
        save_memory(memory)
        return f"Forgotten: {category}/{key}"
    return f"Not found: {category}/{key}"


forget_memory = forget