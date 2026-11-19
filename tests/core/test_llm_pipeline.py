"""LLM tool schemas, prompt persona, and malformed-output handling."""
from __future__ import annotations

import pytest

from core import jarvis_prompt
from core.tools import declarations as decl


def test_every_declaration_has_name_description_parameters():
    for tool in decl.TOOL_DECLARATIONS:
        assert isinstance(tool.get("name"), str) and tool["name"]
        assert isinstance(tool.get("description"), str) and tool["description"]
        assert tool.get("parameters", {}).get("type") == "OBJECT"


def test_no_duplicate_tool_names():
    names = [t["name"] for t in decl.TOOL_DECLARATIONS]
    assert len(names) == len(set(names))


def test_openai_conversion_keeps_required_and_types():
    names = {t["function"]["name"]: t for t in decl.OLLAMA_TOOLS}
    tool = names["search_emails"]
    assert tool["type"] == "function"
    assert "query" in tool["function"]["parameters"]["required"]


def test_system_prompt_includes_persona():
    text = jarvis_prompt._load_system_prompt()
    assert "short" in text.lower() and "person" in text.lower()


def test_trim_conversation_keeps_tool_turns():
    from core.jarvis_llm import _trim_conversation
    history = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "result", "tool_call_id": "1"},
        {"role": "user", "content": "new"},
        {"role": "assistant", "content": "ok"},
    ]
    out = _trim_conversation(history, max_turns=1)
    assert out[0]["content"] == "new"
    assert len(out) == 2


def test_unavailable_reply_hides_tracebacks():
    from core.jarvis_llm import _llm_unavailable_reply
    reply = _llm_unavailable_reply("Traceback (most recent call last): boom")
    assert "Traceback" not in reply
    assert reply.strip()
