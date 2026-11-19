from memory import db_vector_store, vector_memory


def test_store_conversation_without_embedding(monkeypatch, tmp_path):
    monkeypatch.setattr(db_vector_store, "DB_PATH", tmp_path / "vector_store.db")
    monkeypatch.setattr(db_vector_store, "_initialized", False)
    monkeypatch.setattr(vector_memory, "_migrated", True)
    monkeypatch.setattr(vector_memory, "_store_cache", {"memories": [], "conversations": []})
    monkeypatch.setattr(vector_memory, "_store_mtime", 0.0)
    monkeypatch.setattr(vector_memory, "_embed", lambda _text: [])

    vector_memory.store_conversation("I started a new project", "Nice. What is it about?")

    saved = vector_memory._load_store()["conversations"]
    assert len(saved) == 1
    assert saved[0]["user"] == "I started a new project"
    assert saved[0]["assistant"] == "Nice. What is it about?"


def test_recent_conversations_are_chronological_without_embeddings(monkeypatch, tmp_path):
    monkeypatch.setattr(db_vector_store, "DB_PATH", tmp_path / "vector_store.db")
    monkeypatch.setattr(db_vector_store, "_initialized", False)
    monkeypatch.setattr(vector_memory, "_migrated", True)
    monkeypatch.setattr(vector_memory, "_store_cache", {"memories": [], "conversations": []})
    monkeypatch.setattr(vector_memory, "_store_mtime", 0.0)
    monkeypatch.setattr(vector_memory, "_embed", lambda _text: [])

    vector_memory.store_conversation("First", "First reply")
    vector_memory.store_conversation("Second", "Second reply")

    recent = vector_memory.recent_conversations(limit=2)
    assert [turn["user"] for turn in recent] == ["First", "Second"]
    assert all("embedding" not in turn for turn in recent)


def test_recent_conversations_enter_memory_context_without_embeddings(monkeypatch):
    from core import jarvis_memory

    monkeypatch.setattr(
        vector_memory,
        "recent_conversations",
        lambda limit: [{
            "user": "My favorite color is blue",
            "assistant": "Got it, your favorite color is blue.",
        }],
    )
    monkeypatch.setattr(vector_memory, "get_relevant_context", lambda *args, **kwargs: "")
    monkeypatch.setattr(vector_memory, "search_conversation", lambda *args, **kwargs: [])
    monkeypatch.setattr(jarvis_memory, "format_episode_recall", lambda *args, **kwargs: "")

    context = jarvis_memory.format_human_recall(
        "What do you know about me?", include_facts=False, include_vectors=False
    )

    assert "[RECENT CONVERSATIONS]" in context
    assert "My favorite color is blue" in context


def test_conversation_trim_preserves_complete_tool_turns():
    from core.jarvis_llm import _trim_conversation

    history = [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "new question"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call-1"}]},
        {"role": "tool", "tool_call_id": "call-1", "content": "tool result"},
        {"role": "assistant", "content": "final answer"},
    ]

    trimmed = _trim_conversation(history, max_turns=1)

    assert [message["role"] for message in trimmed] == ["user", "assistant", "tool", "assistant"]
    assert trimmed[0]["content"] == "new question"


def test_fast_general_uses_shared_style_and_recent_history(monkeypatch):
    from core import jarvis_general, llm_client

    captured = {}

    def fake_call_llm(messages, tools=None, timeout=None):
        captured["messages"] = messages
        captured["tools"] = tools
        return "A concise answer."

    monkeypatch.setattr(llm_client, "call_llm", fake_call_llm)
    history = [
        {"role": "user", "content": "Who is Hannibal?"},
        {"role": "assistant", "content": "A Carthaginian general."},
    ]

    answer = jarvis_general.ask_general("Where was he from?", history=history)

    assert answer == "A concise answer."
    assert captured["messages"][0]["content"].startswith(jarvis_general.CONVERSATION_STYLE)
    assert captured["messages"][1:3] == history
    assert captured["tools"] is None