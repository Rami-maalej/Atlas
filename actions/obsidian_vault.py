import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("obsidian")


def _resolve_vault_dir() -> Path:
    """Vault path priority: config/api_keys.json "obsidian_vault" > OBSIDIAN_VAULT
    env var > ~/Obsidian. Config wins so the assistant and the grok_obsidian_memory
    project can share one vault."""
    try:
        from core.paths import config_path
        cfg_path = config_path("api_keys.json")
        if cfg_path.exists():
            configured = (json.loads(cfg_path.read_text(encoding="utf-8")).get("obsidian_vault") or "").strip()
            if configured and Path(configured).expanduser().exists():
                return Path(configured).expanduser()
    except Exception:
        pass
    env = os.environ.get("OBSIDIAN_VAULT", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / "Obsidian"


VAULT_DIR = _resolve_vault_dir()
NOTES_DIR = VAULT_DIR  # the whole vault is the assistant's memory (was: JARVIS/)

# Map memory categories from save_memory onto the vault's domain folders.
_FOLDER_ALIASES = {
    "notes": "Memories", "preferences": "Values", "facts": "Facts",
    "goals": "Goals", "health": "Health", "finance": "Finance",
    "journal": "Journal", "learning": "Learning", "people": "People",
    "projects": "Projects", "ideas": "Ideas", "skills": "Skills",
    "routine": "Routine", "travel": "Travel", "media": "Media",
    "quotes": "Quotes", "tastes": "Tastes", "career": "Career",
    "sources": "Sources", "values": "Values", "setup": "Setup",
    "memories": "Memories",
}


def _target_folder(folder: str) -> str:
    """Resolve a save folder against the vault: real folder > alias > Memories."""
    if not folder:
        return ""
    if (VAULT_DIR / folder).is_dir():
        return folder
    return _FOLDER_ALIASES.get(folder.strip().lower(), "Memories")


def set_vault_path(path: str) -> str:
    global VAULT_DIR, NOTES_DIR
    VAULT_DIR = Path(path)
    NOTES_DIR = VAULT_DIR
    if not VAULT_DIR.exists():
        return f"Vault path does not exist: {path}"
    return f"Vault set to: {path}"


def _ensure_notes_dir():
    NOTES_DIR.mkdir(parents=True, exist_ok=True)


def save_note(title: str, content: str, folder: str = "") -> dict[str, Any]:
    _ensure_notes_dir()
    target = NOTES_DIR
    folder = _target_folder(folder)
    if folder:
        target = NOTES_DIR / folder
        target.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(c for c in title if c.isalnum() or c in " _-").strip()
    if not safe_name:
        safe_name = f"note-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    path = target / f"{safe_name}.md"
    # Never overwrite an existing note — ideas with the same title get -2, -3…
    if path.exists():
        stem = path.stem
        n = 2
        while path.exists():
            path = target / f"{stem} {n}.md"
            n += 1
    header = f"---\ntitle: {title}\ncreated: {datetime.now().isoformat()}\ntags: []\n---\n\n"
    path.write_text(header + content + "\n", encoding="utf-8")
    logger.info("Note saved: %s", path)
    return {"path": str(path), "title": title, "size": len(content)}


def search_notes(query: str, max_results: int = 10) -> list[dict[str, Any]]:
    _ensure_notes_dir()
    results = []
    for f in sorted(NOTES_DIR.rglob("*.md")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            if query.lower() in text.lower():
                results.append({
                    "path": str(f),
                    "title": f.stem,
                    "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                    "snippet": text[:200].replace("---\n", "").strip(),
                })
                if len(results) >= max_results:
                    break
        except Exception:
            continue
    return results


def read_note(note_title: str) -> str:
    """Read one note's content by title (fuzzy: exact stem first, then substring)."""
    _ensure_notes_dir()
    q = (note_title or "").strip().strip(".md").lower()
    if not q:
        return "No note title given."
    candidates = sorted(NOTES_DIR.rglob("*.md"))
    for f in candidates:  # exact filename match first
        if f.stem.lower() == q or f.stem.lower() == q.replace(" ", "-"):
            return f.read_text(encoding="utf-8", errors="replace")
    for f in candidates:  # then substring match
        if q in f.stem.lower():
            return f.read_text(encoding="utf-8", errors="replace")
    return f"No note matching '{note_title}'."


# ── Vault as the primary fact store ───────────────────────────────────────
# Long-term facts live in the vault so they are readable, editable and
# versionable in Obsidian — not locked inside a JSON blob.  Each category
# gets one note whose body is a "key: value" table, so a fact saved by the
# assistant is visible and editable in the app the user already lives in.
_FACT_NOTES = {
    "identity":      ("Facts/Identity.md",      "Identity"),
    "preferences":   ("Facts/Preferences.md",   "Preferences"),
    "projects":      ("Facts/Projects.md",      "Projects"),
    "relationships": ("Facts/People.md",        "People"),
    "wishes":        ("Facts/Wishes.md",        "Wishes"),
    "notes":         ("Facts/Notes.md",         "Notes"),
}


def _fact_note_path(category: str) -> Path:
    rel, _label = _FACT_NOTES.get(category, _FACT_NOTES["notes"])
    return VAULT_DIR / rel


def _parse_fact_body(body: str) -> dict[str, str]:
    """Parse a "key: value" fact table back into a dict."""
    facts: dict[str, str] = {}
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("---"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lstrip("-").strip()
        value = value.strip()
        if key:
            facts[key] = value
    return facts


def store_facts(category: str, facts: dict[str, str]) -> str:
    """Write a category's facts into the vault, replacing the note body.

    Returns the note path, or an empty string when the vault is unavailable.
    """
    if not facts:
        return ""
    try:
        path = _fact_note_path(category)
        path.parent.mkdir(parents=True, exist_ok=True)
        _rel, label = _FACT_NOTES.get(category, _FACT_NOTES["notes"])
        body = "\n".join(f"{k}: {v}" for k, v in sorted(facts.items()))
        header = (
            "---\n"
            f"title: {label}\n"
            f"updated: {datetime.now().isoformat()}\n"
            "tags: [atlantis, memory]\n"
            "---\n\n"
            f"# {label}\n\n"
        )
        path.write_text(header + body + "\n", encoding="utf-8")
        logger.info("Facts stored in vault: %s (%d)", path, len(facts))
        return str(path)
    except Exception as e:
        logger.debug("store_facts failed: %s", e)
        return ""


def load_facts() -> dict[str, dict[str, str]]:
    """Read every category's facts back out of the vault."""
    out: dict[str, dict[str, str]] = {}
    try:
        if not VAULT_DIR.exists():
            return out
        for category, (rel, _label) in _FACT_NOTES.items():
            path = VAULT_DIR / rel
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            # Drop the YAML front-matter and the heading line.
            if text.startswith("---"):
                parts = text.split("---", 2)
                text = parts[-1] if len(parts) > 2 else text
            facts = _parse_fact_body(text)
            if facts:
                out[category] = facts
    except Exception as e:
        logger.debug("load_facts failed: %s", e)
    return out


# ── Daily journal: the conversation log inside the vault ──────────────────
_JOURNAL_DIR = "Journal"


def append_journal(user_text: str, assistant_text: str) -> str:
    """Append one conversation turn to today's journal note.

    The journal is what makes "he still remembers everything" true in a way
    the user can read: every day is one note in the vault, and the notes
    are searchable by the vault recall.
    """
    if not user_text and not assistant_text:
        return ""
    try:
        folder = VAULT_DIR / _JOURNAL_DIR
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{datetime.now().strftime('%Y-%m-%d')}.md"
        if not path.exists():
            header = (
                "---\n"
                f"title: {datetime.now().strftime('%Y-%m-%d')}\n"
                f"created: {datetime.now().isoformat()}\n"
                "tags: [atlantis, journal]\n"
                "---\n\n"
                f"# {datetime.now().strftime('%Y-%m-%d')}\n\n"
            )
            path.write_text(header, encoding="utf-8")
        stamp = datetime.now().strftime("%H:%M")
        line = f"- **{stamp}** — You: {user_text.strip()[:500]}\n"
        if assistant_text.strip():
            line += f"  - Atlantis: {assistant_text.strip()[:1000]}\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
        return str(path)
    except Exception as e:
        logger.debug("append_journal failed: %s", e)
        return ""


# ── Vault recall: TF-IDF over note contents, per user message ──────────
_RECALL_CACHE = {"key": "", "t": 0.0, "text": ""}
_RECALL_TTL = 30.0


def _is_index_note(path: Path) -> bool:
    stem = path.stem.lower()
    return stem == "home" or stem.endswith("-index")


def recall_context(query: str, top_k: int = 6, max_chars: int = 4500) -> str:
    """Most relevant NOTE CONTENTS for this message (TF-IDF, offline).
    This is what makes the assistant actually *remember* the vault at
    conversation depth: it sees the substance of the best-matching notes,
    not just their titles."""
    import time as _time

    if not query or not VAULT_DIR.exists():
        return ""
    key = " ".join(query.lower().split())
    now = _time.time()
    cached = _RECALL_CACHE
    if cached["text"] and cached["key"] == key and (now - cached["t"]) < _RECALL_TTL:
        return cached["text"]

    notes = [p for p in VAULT_DIR.rglob("*.md") if not _is_index_note(p)]
    if not notes:
        return ""
    docs: list[str] = []
    for p in notes:
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
            # strip YAML frontmatter
            docs.append(raw.split("---", 2)[-1] if raw.startswith("---") else raw)
        except Exception:
            docs.append("")
    recall = ""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        vec = TfidfVectorizer(stop_words="english")
        matrix = vec.fit_transform(docs + [query])
        sims = cosine_similarity(matrix[-1], matrix[:-1]).flatten()
        top = sorted(enumerate(sims), key=lambda x: x[1], reverse=True)[:top_k]
        blocks: list[str] = []
        for idx, score in top:
            if score <= 0:
                continue
            p = notes[idx]
            folder = p.parent.name if p.parent != VAULT_DIR else "Vault"
            body = docs[idx].strip().replace("\n", " ")
            blocks.append(f"[{folder} / {p.stem}] (relevance {score:.2f})\n{body[:900]}")
        if blocks:
            recall = "\n\n".join(blocks)[:max_chars]
            _RECALL_CACHE.update(key=key, t=now, text=recall)
    except Exception as e:
        logger.debug("recall_context failed: %s", e)
    return recall


_STEM_INDEX_CACHE = {"t": 0.0, "text": ""}


def note_stem_index(max_notes: int = 80, ttl: float = 60.0) -> str:
    """Compact 'folder → note titles' index for the current vault.

    Used when per-message recall finds no matching note, so the assistant
    still knows what exists and can read the right one via the obsidian tool.
    Cached for `ttl` seconds — vault edits appear within a minute.
    """
    import time as _time
    if not VAULT_DIR.exists():
        return ""
    now = _time.time()
    if _STEM_INDEX_CACHE["text"] and (now - _STEM_INDEX_CACHE["t"]) < ttl:
        return _STEM_INDEX_CACHE["text"]
    groups: dict[str, list[str]] = {}
    for p in sorted(VAULT_DIR.rglob("*.md")):
        rel_parent = p.parent.name if p.parent != VAULT_DIR else "(root)"
        groups.setdefault(rel_parent, [])
        if len(groups[rel_parent]) < max_notes:
            groups[rel_parent].append(p.stem)
    lines: list[str] = []
    for folder, stems in groups.items():
        lines.append(f"{folder}: {', '.join(stems)}")
    text = "\n".join(lines)[:3000]
    _STEM_INDEX_CACHE.update(t=now, text=text)
    return text


def list_notes(folder: str = "", max_results: int = 50) -> list[dict[str, Any]]:
    _ensure_notes_dir()
    target = NOTES_DIR
    if folder:
        target = target / folder

    notes = []
    for f in sorted(target.rglob("*.md")):
        try:
            notes.append({
                "path": str(f),
                "title": f.stem,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                "size": f.stat().st_size,
            })
        except Exception:
            continue
    return notes[:max_results]


def get_all_tags() -> list[str]:
    _ensure_notes_dir()
    tags = set()
    for f in NOTES_DIR.rglob("*.md"):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            import re
            tags.update(re.findall(r"#\w+", text))
        except Exception:
            continue
    return sorted(tags)


def create_knowledge_graph() -> dict[str, Any]:
    _ensure_notes_dir()
    notes = list_notes()
    links = []
    import re
    for note in notes:
        try:
            text = Path(note["path"]).read_text(encoding="utf-8")
            wiki_links = re.findall(r"\[\[([^\]]+)\]\]", text)
            for link in wiki_links:
                links.append({"source": note["title"], "target": link.strip()})
        except Exception:
            continue

    return {
        "nodes": [{"id": n["title"], "path": n["path"]} for n in notes],
        "edges": links,
        "node_count": len(notes),
        "edge_count": len(links),
    }


# ── Vault → prompt memory (TTL-cached) ─────────────────────────────────
_CTX_CACHE = {"t": 0.0, "text": ""}
_CTX_TTL = 60.0


def build_memory_context(max_chars: int = 6000) -> str:
    """Summarize the whole vault for the system prompt: Home hub + domain
    folders + note titles. Cached for 60s so every prompt build is cheap."""
    import time as _time

    now = _time.time()
    if _CTX_CACHE["text"] and (now - _CTX_CACHE["t"]) < _CTX_TTL:
        return _CTX_CACHE["text"]
    try:
        if not VAULT_DIR.exists():
            return ""
        lines: list[str] = []
        n_notes = 0
        home = VAULT_DIR / "Home.md"
        if home.exists():
            hub = home.read_text(encoding="utf-8", errors="replace")
            hub = hub.split("---", 2)[-1].strip()
            lines.append(f"HOME HUB:\n{hub[:1200]}")
        for d in sorted(p for p in VAULT_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")):
            notes = sorted(d.glob("*.md"))
            if not notes:
                continue
            n_notes += len(notes)
            titles = [x.stem for x in notes][:15]
            lines.append(f"{d.name} ({len(notes)}): " + ", ".join(titles))
        loose = [p.stem for p in sorted(VAULT_DIR.glob("*.md")) if p.name != "Home.md"]
        if loose:
            n_notes += len(loose)
            lines.append("Root: " + ", ".join(loose[:10]))
        if not n_notes:
            return ""
        text = (
            f"[OBSIDIAN VAULT — PRIMARY LONG-TERM MEMORY, {n_notes} notes @ {VAULT_DIR}]\n"
            "This vault is your second brain: reference it naturally in conversation, "
            "read folder notes with the obsidian tool, and write important new facts back.\n"
            + "\n".join(lines)
        )[:max_chars]
        _CTX_CACHE.update(t=now, text=text)
        return text
    except Exception as e:
        logger.debug("build_memory_context failed: %s", e)
        return ""
