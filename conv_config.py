"""Conversation-layer config. Kept separate from config/api_keys.json so the
LLM flag can be toggled without touching API keys. Never import as `config`
(the repo already has a config/ package)."""
from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
KEYS_FILE = BASE / "config" / "api_keys.json"
CONV_FILE = BASE / "config" / "conversation.json"

DEFAULT = {
    "LLM_ENABLED": True,
    "LLM_MODEL": "",            # empty = use configured model (prefer a small one)
    "LLM_CACHE": True,
    "LLM_LOG": True,
    "TTS_BACKEND": "auto",      # auto | pyttsx3 | edge | kokoro | elevenlabs
    "Wake word": "jarvis",
}


def load_conv_config() -> dict:
    cfg = dict(DEFAULT)
    try:
        if CONV_FILE.exists():
            cfg.update(json.loads(CONV_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return cfg


def save_conv_config(patch: dict) -> None:
    cfg = load_conv_config()
    cfg.update(patch)
    CONV_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONV_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def llm_enabled() -> bool:
    """LLM_ENABLED in conversation.json wins; environment variable overrides."""
    import os
    env = os.environ.get("LLM_ENABLED")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    return bool(load_conv_config().get("LLM_ENABLED", True))
