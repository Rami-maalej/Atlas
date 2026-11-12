from core.tools.declarations import OLLAMA_TOOLS


def test_ollama_tool_schema_preserves_parameter_descriptions():
    tools = {item["function"]["name"]: item["function"] for item in OLLAMA_TOOLS}
    file_name = tools["file_controller"]["parameters"]["properties"]["file_name"]
    context = tools["context"]["description"]
    maps = tools["maps"]["parameters"]

    assert "filename alias" in file_name["description"]
    assert "not the user's profile" in context
    assert maps["required"] == ["action"]


def test_empty_context_bus_does_not_sound_like_missing_user_memory():
    from actions.context_bus import ContextBus

    result = ContextBus().get_summary()

    assert "live system context" in result.lower()
    assert "no context data" not in result.lower()


def test_use_tool_is_dispatched(monkeypatch):
    from actions import sys_tool
    from core.tools.executor import execute_tool

    class UI:
        def set_state(self, _state):
            pass

    monkeypatch.setattr(sys_tool, "use_tool", lambda parameters, player=None: "tool dispatched")
    assert execute_tool(UI(), "use_tool", {"tool": "ping"}) == "tool dispatched"