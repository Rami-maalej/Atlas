"""Regression tests for the phone bridge's headless tool dispatch."""

from __future__ import annotations

import signal

import pc_bridge
from core.tools import executor


class TestHeadlessDispatch:
    def test_unknown_tool_keeps_phone_contract(self) -> None:
        result = pc_bridge.HeadlessJarvis()._execute_tool("no_such_tool", {})

        assert result == "Unknown tool: no_such_tool"

    def test_save_memory_is_silent_without_values(self) -> None:
        result = pc_bridge.HeadlessJarvis()._execute_tool("save_memory", {})

        assert result == "__SILENT__"

    def test_calculate_temperature_conversion(self) -> None:
        result = pc_bridge.HeadlessJarvis()._execute_tool(
            "calculate", {"expression": "25 C to F"}
        )

        assert result == "25 C to F = 77.0°F"

    def test_calculate_percentage(self) -> None:
        result = pc_bridge.HeadlessJarvis()._execute_tool(
            "calculate", {"expression": "10% of 200"}
        )

        assert result == "10.0% of 200.0 = 20.0"

    def test_shutdown_uses_sigterm(self, monkeypatch) -> None:
        killed: list[tuple[int, int]] = []
        monkeypatch.setattr(
            executor.os, "kill", lambda pid, sig: killed.append((pid, sig))
        )

        result = pc_bridge.HeadlessJarvis()._execute_tool("shutdown_jarvis", {})

        assert result == "Shutting down."
        assert killed and killed[0][1] == signal.SIGTERM

    def test_manage_agents_start_is_unknown_on_phone(self, monkeypatch) -> None:
        class FakeManager:
            def get_agent(self, _agent_id):
                return None

        monkeypatch.setattr(
            executor, "get_agent_manager", lambda: FakeManager()
        )

        result = pc_bridge.HeadlessJarvis()._execute_tool(
            "manage_agents", {"action": "start"}
        )

        assert result == "Unknown action: start"

    def test_desktop_tool_is_reachable_from_phone(self) -> None:
        result = pc_bridge.HeadlessJarvis()._execute_tool("get_datetime", {})

        assert isinstance(result, str) and result

    def test_adapter_exposes_no_ui_capability_probes(self) -> None:
        adapter = pc_bridge._HeadlessUIAdapter(lambda _msg: None)

        assert adapter.muted is True
        assert adapter.current_file is None
        assert not hasattr(adapter, "_win")
        assert not hasattr(adapter, "request_api_key")
        assert not hasattr(adapter, "open_todo_panel")
