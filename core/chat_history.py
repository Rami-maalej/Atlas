"""Persistent chat history.

The live conversation used to exist only in memory (plus text pairs in the
vector store).  This module keeps the actual message list — roles, tool calls
and tool results — on disk so a restarted assistant continues the same
conversation instead of starting from an empty chat.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from core.paths import memory_path

_DESKTOP_FILE = "chat_history.json"
_PHONE_FILE = "chat_history_phone.json"
_MAX_TURNS = 5
_MAX_CONTENT = 4000
_ALLOWED_ROLES = ("user", "assistant", "tool")

_PROVIDERS: list[Callable[[], list[dict]]] = []


def _path(phone: bool) -> Path:
    return memory_path(_PHONE_FILE if phone else _DESKTOP_FILE)


def _sanitize(messages: Any, max_turns: int = _MAX_TURNS) -> list[dict]:
    """Keep valid chat messages only, then retain the last N whole turns."""
    cleaned: list[dict] = []
    pending_tool_ids: set[str] = set()

    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in _ALLOWED_ROLES:
            continue
        content = message.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        entry: dict[str, Any] = {"role": role, "content": content[:_MAX_CONTENT]}

        calls = message.get("tool_calls")
        if role == "assistant" and isinstance(calls, list) and calls:
            entry["tool_calls"] = calls
            for call in calls:
                if isinstance(call, dict) and call.get("id"):
                    pending_tool_ids.add(str(call["id"]))

        tool_id = message.get("tool_call_id")
        if role == "tool":
            if not tool_id or str(tool_id) not in pending_tool_ids:
                continue
            entry["tool_call_id"] = str(tool_id)
            pending_tool_ids.discard(str(tool_id))

        cleaned.append(entry)

    turns: list[list[dict]] = []
    current: list[dict] = []
    for message in cleaned:
        if message["role"] == "user":
            if current:
                turns.append(current)
            current = [message]
        elif current:
            current.append(message)
    if current:
        turns.append(current)
    return [m for turn in turns[-max_turns:] for m in turn]


def load_chat_history(phone: bool = False) -> list[dict]:
    """Return the saved conversation, or an empty list if none is usable."""
    try:
        payload = json.loads(_path(phone).read_text(encoding="utf-8"))
        return _sanitize(payload.get("messages", []))
    except Exception:
        return []


def save_chat_history(messages: Any, phone: bool = False) -> None:
    """Atomically persist the conversation, dropping invalid messages."""
    payload = {
        "version": 1,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "messages": _sanitize(messages),
    }
    path = _path(phone)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def register_history_provider(provider: Callable[[], list[dict]]) -> None:
    """Register a callable returning the live message list for final flush."""
    if provider not in _PROVIDERS:
        _PROVIDERS.append(provider)


def flush_chat_history() -> None:
    """Persist every registered live conversation (used on shutdown)."""
    for provider in list(_PROVIDERS):
        try:
            save_chat_history(provider())
        except Exception:
            pass
