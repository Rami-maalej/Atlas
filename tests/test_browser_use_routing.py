"""Tests for routing heavy browser work through browser-use."""

from __future__ import annotations

from actions import browser_use_agent
from actions.intent_router import IntentRouter
from core.tools import executor


class FakeUI:
    def __init__(self):
        self.states: list[str] = []

    def set_state(self, state: str) -> None:
        self.states.append(state)

    def show_error_state(self, _message: str) -> None:
        pass


def test_heavy_browser_intent_routes_to_browser_use() -> None:
    result = IntentRouter().route("browse the web and find the cheapest i7 mini pc")

    assert result.matched is True
    assert result.intent_name == "browser_use"
    assert result.handler_name == "browser_use"
    assert result.requires_ai is False
    assert "cheapest i7" in result.handler_params["task"]


def test_simple_navigation_still_uses_fast_browser() -> None:
    result = IntentRouter().route("go to https://example.com")

    assert result.handler_name == "fast_browser"


def test_executor_delegates_to_browser_use(monkeypatch) -> None:
    seen: dict = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return "done"

    monkeypatch.setattr(browser_use_agent, "run_browser_use_task", fake_run)

    out = executor.execute_tool(
        FakeUI(), "browser_use",
        {"task": "fill the form", "headless": False, "max_steps": 5, "timeout": 30},
    )

    assert out == "done"
    assert seen["task"] == "fill the form"
    assert seen["headless"] is False
    assert seen["max_steps"] == 5


def test_local_browse_does_not_launch_browser_agent() -> None:
    result = IntentRouter().route("browse files on desktop")

    assert result.intent_name != "browser_use"
