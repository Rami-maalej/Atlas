import json
import threading
from datetime import datetime

import numpy as np
import requests

from core.llm_client import resolve_llm_url
from core.paths import base_dir as get_base_dir
from core.paths import memory_path
from memory import db_vector_store as _db

_LOCAL_MODEL = None

_OLLAMA_URL = "http://localhost:11434"

BASE_DIR = get_base_dir()
VEC_PATH = memory_path("vector_store.json")
_lock = threading.Lock()

# ── In-process vector-store cache ───────────────────────────────────────────────
# _load_store() is called for every search AND every write.  Caching by file
# mtime means repeated reads within the same turn hit RAM instead of disk.
_store_cache: dict = {"memories": [], "conversations": []}
_store_mtime: float = 0.0

def _get_config():
    """Config read with a tiny mtime cache — _embed() calls this on every
    embedding request (2-3 per turn) and it used to hit disk every time."""
    global _cfg_cache, _cfg_mtime
    cfg_path = BASE_DIR / "config" / "api_keys.json"
    try:
        mtime = cfg_path.stat().st_mtime
    except OSError:
        mtime = 0.0
    if _cfg_cache is not None and mtime == _cfg_mtime:
        return dict(_cfg_cache)
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    if cfg.get("llm_url_local") or cfg.get("llm_url_remote"):
        cfg["llm_url"] = resolve_llm_url(cfg)
    _cfg_cache, _cfg_mtime = cfg, mtime
    return dict(cfg)

_cfg_cache: dict | None = None
_cfg_mtime: float = -1.0

def _get_embedding_url():
    cfg = _get_config()
    if cfg.get("embed_url"):
        return cfg["embed_url"].rstrip("/")
    # Always prefer local Ollama for embeddings — all-minilm:l6-v2 is tiny (45MB)
    # and works regardless of which LLM provider is configured.
    return f"{_OLLAMA_URL}/api/embeddings"

_EMBED_MODEL = "all-minilm:l6-v2"

_embed_cache: dict[str, list[float]] = {}
_embed_warned: set[str] = set()
_embeddings_disabled: bool = False
_embed_retry_after: float = 0.0
_embed_failures: dict[str, int] = {}
_embed_lock = threading.Lock()
_EMBED_MAX_RETRIES = 3
_EMBED_RETRY_WAIT = 5.0
_EMBED_DISABLE_AFTER = 5

def _embed(text: str) -> list[float]:
    global _embeddings_disabled, _embed_retry_after
    import time as _time

    key = text[:1000]
    if _embeddings_disabled and _time.monotonic() >= _embed_retry_after:
        _embeddings_disabled = False
        _embed_failures.clear()
    if _embeddings_disabled:
        return _local_embed(key)

    cached = _embed_cache.get(key)
    if cached:
        return cached

    cfg = _get_config()
    embed_url = _get_embedding_url()
    embed_model = cfg.get("embed_model") or _EMBED_MODEL
    payload = {"model": embed_model, "prompt": key}

    failure_key = f"ollama:{embed_url}"
    with _embed_lock:
        if _embed_failures.get(failure_key, 0) >= _EMBED_DISABLE_AFTER:
            if failure_key not in _embed_warned:
                print(f"[VectorMemory] Embedding disabled after {_EMBED_DISABLE_AFTER} failures.")
                _embed_warned.add(failure_key)
            _embeddings_disabled = True
            _embed_retry_after = _time.monotonic() + 60.0
            return _local_embed(key)

    try:
        resp = requests.post(embed_url, json=payload, timeout=3.0)
        resp.raise_for_status()
        data = resp.json()
        with _embed_lock:
            _embed_failures.pop(failure_key, None)
        emb = data.get("embedding", [])
        if emb:
            if len(_embed_cache) > 512:
                _embed_cache.clear()
            _embed_cache[key] = emb
        return emb
    except requests.exceptions.HTTPError as e:
        with _embed_lock:
            cnt = _embed_failures.get(failure_key, 0) + 1
            _embed_failures[failure_key] = cnt
        if failure_key not in _embed_warned:
            print(f"[VectorMemory] Embedding API error ({embed_url}): {e.response.status_code} (attempt {cnt}/{_EMBED_DISABLE_AFTER})")
            _embed_warned.add(failure_key)
        _embeddings_disabled = True
        _embed_retry_after = _time.monotonic() + 60.0
        return _local_embed(key)
    except Exception:
        with _embed_lock:
            cnt = _embed_failures.get(failure_key, 0) + 1
            _embed_failures[failure_key] = cnt
        if failure_key not in _embed_warned and cnt >= _EMBED_DISABLE_AFTER:
            # Only warn once, after all retries failed — no noisy startup errors.
            print("[VectorMemory] Embedding unavailable — running without semantic memory.")
            _embed_warned.add(failure_key)
        _embeddings_disabled = True
        _embed_retry_after = _time.monotonic() + 60.0
        return _local_embed(key)

def _local_embed(text: str) -> list[float]:
    """Fallback embedder that runs on CPU with no external service."""
    global _LOCAL_MODEL
    try:
        from fastembed import TextEmbedding
        if _LOCAL_MODEL is None:
            _LOCAL_MODEL = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")
        vector = list(next(iter(_LOCAL_MODEL.embed([text]))))
        if vector and len(_embed_cache) > 512:
            _embed_cache.clear()
        if vector:
            _embed_cache[text[:1000]] = vector
        return vector
    except Exception as e:
        print(f"[VectorMemory] Local embedder failed: {e}")
        return []

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    a = np.array(a, dtype=np.float64)
    b = np.array(b, dtype=np.float64)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0:
        return 0.0
    return float(np.dot(a, b) / norm)

_migrated = False

def _load_store() -> dict:
    global _store_cache, _migrated
    if not _migrated:
        _db.import_legacy_json()
        _migrated = True
    data = _db.load_all()
    _store_cache = data
    return _store_cache

def _save_store(store: dict) -> None:
    global _store_cache
    _db.replace_all(store)
    _store_cache = store

def store_memory(text: str, category: str = "general", source: str = "conversation") -> bool:
    emb = _embed(text)
    if not emb:
        return False
    with _lock:
        store = _load_store()
        entry = {
            "id": datetime.now().timestamp(),
            "text": text[:2000],
            "category": category,
            "source": source,
            "embedding": emb,
            "created": datetime.now().isoformat(),
        }
        store["memories"].append(entry)
        _save_store(store)
        print(f"[VectorMemory] Stored ({category}): {text[:60]}...")
        return True

def search_memory(query: str, top_k: int = 5, threshold: float = 0.3) -> list[dict]:
    query_emb = _embed(query)
    if not query_emb:
        return []
    with _lock:
        store = _load_store()
        candidates = store.get("memories", [])
        scored = []
        for m in candidates:
            if not m.get("embedding"):
                continue
            sim = _cosine_similarity(query_emb, m["embedding"])
            if sim >= threshold:
                scored.append((sim, m))
        scored.sort(reverse=True, key=lambda x: x[0])
        results = [{"score": s, **{k: v for k, v in m.items() if k != "embedding"}} for s, m in scored[:top_k]]
        return results

def store_conversation(user_text: str, assistant_text: str) -> None:
    full = f"User: {user_text}\nAssistant: {assistant_text}"
    emb = _embed(full)
    with _lock:
        store = _load_store()
        entry = {
            "id": datetime.now().timestamp(),
            "user": user_text[:500],
            "assistant": assistant_text[:2000],
            "embedding": emb,
            "created": datetime.now().isoformat(),
        }
        store["conversations"].append(entry)
        # Keep max 200 conversations to bound size
        if len(store["conversations"]) > 200:
            store["conversations"] = store["conversations"][-200:]
        _save_store(store)

def recent_conversations(limit: int = 5) -> list[dict]:
    """Return the latest stored turns in chronological order."""
    if limit <= 0:
        return []
    with _lock:
        entries = _load_store().get("conversations", [])
        ordered = sorted(
            entries,
            key=lambda item: (item.get("created", ""), float(item.get("id", 0))),
        )
        return [
            {key: value for key, value in item.items() if key != "embedding"}
            for item in ordered[-limit:]
        ]

def search_conversation(query: str, top_k: int = 3, threshold: float = 0.25) -> list[dict]:
    query_emb = _embed(query)
    if not query_emb:
        return []
    with _lock:
        store = _load_store()
        candidates = store.get("conversations", [])
        scored = []
        for c in candidates:
            if not c.get("embedding"):
                continue
            sim = _cosine_similarity(query_emb, c["embedding"])
            if sim >= threshold:
                scored.append((sim, c))
        scored.sort(reverse=True, key=lambda x: x[0])
        results = [{"score": s, **{k: v for k, v in c.items() if k != "embedding"}} for s, c in scored[:top_k]]
        return results

def _search_memory_with_emb(query_emb: list[float], top_k: int = 5, threshold: float = 0.3) -> list[dict]:
    if not query_emb:
        return []
    with _lock:
        store = _load_store()
        hits = _db.knn("memories", query_emb, top_k)
        if hits:
            by_id = {str(m.get("id")): m for m in store.get("memories", [])}
            return [
                {"score": sim,
                 **{k: v for k, v in by_id[i].items() if k != "embedding"}}
                for i, sim in hits if i in by_id and sim >= threshold
            ]
        scored = []
        for m in store.get("memories", []):
            if not m.get("embedding"):
                continue
            sim = _cosine_similarity(query_emb, m["embedding"])
            if sim >= threshold:
                scored.append((sim, m))
        scored.sort(reverse=True, key=lambda x: x[0])
        return [{"score": s, **{k: v for k, v in m.items() if k != "embedding"}} for s, m in scored[:top_k]]


def _search_conversation_with_emb(query_emb: list[float], top_k: int = 3, threshold: float = 0.25) -> list[dict]:
    if not query_emb:
        return []
    with _lock:
        store = _load_store()
        hits = _db.knn("conversations", query_emb, top_k)
        if hits:
            by_id = {str(c.get("id")): c for c in store.get("conversations", [])}
            return [
                {"score": sim,
                 **{k: v for k, v in by_id[i].items() if k != "embedding"}}
                for i, sim in hits if i in by_id and sim >= threshold
            ]
        scored = []
        for c in store.get("conversations", []):
            if not c.get("embedding"):
                continue
            sim = _cosine_similarity(query_emb, c["embedding"])
            if sim >= threshold:
                scored.append((sim, c))
        scored.sort(reverse=True, key=lambda x: x[0])
        return [{"score": s, **{k: v for k, v in c.items() if k != "embedding"}} for s, c in scored[:top_k]]


def get_relevant_context(query: str, top_k: int = 5) -> str:
    query_emb = _embed(query)
    mems = _search_memory_with_emb(query_emb, top_k=top_k, threshold=0.3)
    convs = _search_conversation_with_emb(query_emb, top_k=3, threshold=0.25)
    parts = []
    if mems:
        parts.append("[Relevant Memories]")
        for m in mems:
            parts.append(f"  [{m['category']}] {m['text'][:200]}")
    if convs:
        parts.append("[Related Past Conversations]")
        for c in convs:
            parts.append(f"  User: {c['user'][:100]}")
            parts.append(f"  Jarvis: {c['assistant'][:200]}")
    return "\n".join(parts) if parts else ""

def get_memory_count() -> int:
    with _lock:
        store = _load_store()
        return len(store.get("memories", [])) + len(store.get("conversations", []))
