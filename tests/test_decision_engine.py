"""Tests for core.decision_engine — Laya decision model (offline, fake agent)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from core import decision_engine as de


class FakeAgent:
    """Records predict() calls and returns a canned Laya-shaped response."""

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def predict(self, state: str, questions: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((state, questions))
        return self.payload


def engine_with(payload: dict[str, Any]) -> tuple[de.DecisionEngine, FakeAgent]:
    agent = FakeAgent(payload)
    return de.DecisionEngine(model="test-model", agent=agent), agent


# ── Question builders ───────────────────────────────────────────────────────
def test_noul_question_shape() -> None:
    q = de.noul_question("Is it urgent?", {"true": "time-sensitive", "false": "no rush"})
    assert q["type"] == "noul"
    assert q["instructions"] == "Is it urgent?"
    assert q["criteria"]["true"] == "time-sensitive"


def test_noul_question_without_criteria() -> None:
    assert "criteria" not in de.noul_question("Yes or no?")


def test_choice_question_shape() -> None:
    q = de.choice_question("Route it", {"a": "Alpha", "b": "Beta"})
    assert q["type"] == "choice"
    assert q["criteria"] == {"a": "Alpha", "b": "Beta"}


def test_choice_question_needs_two_options() -> None:
    with pytest.raises(ValueError):
        de.choice_question("Route it", {"only": "one"})


def test_score_question_levels_bounds() -> None:
    assert de.score_question("Rate", ["Low", "High"])["type"] == "score"
    with pytest.raises(ValueError):
        de.score_question("Rate", ["only-one"])
    with pytest.raises(ValueError):
        de.score_question("Rate", [str(i) for i in range(11)])


# ── Model resolution ───────────────────────────────────────────────────────
def test_resolve_model_explicit(monkeypatch) -> None:
    monkeypatch.delenv(de.MODEL_ENV, raising=False)
    assert de.resolve_model("  my/model  ") == "my/model"


def test_resolve_model_env(monkeypatch) -> None:
    monkeypatch.setenv(de.MODEL_ENV, "env/model")
    assert de.resolve_model(None) == "env/model"


def test_resolve_model_config(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(de.MODEL_ENV, raising=False)
    cfg = tmp_path / "api_keys.json"
    cfg.write_text(json.dumps({"laya_model": "cfg/model"}), encoding="utf-8")
    monkeypatch.setattr(de, "CONFIG_DIR", tmp_path)
    assert de.resolve_model(None) == "cfg/model"


def test_resolve_model_default(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(de.MODEL_ENV, raising=False)
    monkeypatch.setattr(de, "CONFIG_DIR", tmp_path)
    assert de.resolve_model(None) == de.DEFAULT_MODEL


# ── Response parsing ───────────────────────────────────────────────────────
FULL_RESPONSE: dict[str, Any] = {
    "answers": {
        "urgent": {"noul": 0.95},
        "route": {
            "choice": "email",
            "probabilities": {"email": 0.8, "web": 0.15, "other": 0.05},
            "answer_confidence": 0.72,
        },
        "severity": {
            "score": 1.05,
            "levels": ["Calm", "Frustrated", "Very angry"],
            "probabilities": {"0": 0.0, "1": 0.95, "2": 0.05},
            "answer_confidence": 0.92,
        },
    },
}


def test_evaluate_parses_all_answer_types() -> None:
    engine, agent = engine_with(FULL_RESPONSE)
    result = engine.evaluate(
        "Help! My payouts failed 3 days ago.",
        {
            "urgent": de.noul_question("Urgent?"),
            "route": de.choice_question("Route", {"email": "e", "web": "w", "other": "o"}),
            "severity": de.score_question("Severity", ["Calm", "Frustrated", "Very angry"]),
        },
    )
    assert result.model == "test-model"
    assert result.noul["urgent"].probability == 0.95
    assert result.noul["urgent"].yes is True
    assert result.choice["route"].choice == "email"
    assert result.choice["route"].runner_up == "web"
    assert result.choice["route"].confidence == 0.72
    assert result.score["severity"].level == "Frustrated"
    assert result.noul_value("urgent") == 0.95
    assert result.choice_value("route") == "email"
    assert result.noul_value("missing") == -1.0
    assert result.choice_value("missing", "fallback") == "fallback"
    assert agent.calls[0][0] == "Help! My payouts failed 3 days ago."
    assert agent.calls[0][1]["urgent"]["type"] == "noul"


def test_evaluate_requires_questions() -> None:
    engine, _ = engine_with(FULL_RESPONSE)
    with pytest.raises(de.DecisionError):
        engine.evaluate("state", {})


def test_evaluate_agent_errors_bubble() -> None:
    class Broken:
        def predict(self, *_args, **_kwargs):
            raise de.DecisionError("boom")

    engine = de.DecisionEngine(agent=Broken())
    with pytest.raises(de.DecisionError):
        engine.evaluate("state", {"q": de.noul_question("ok?")})


# ── Helpers ─────────────────────────────────────────────────────────────────
def test_route_intent_returns_choice() -> None:
    payload = {
        "answers": {
            "intent": {
                "choice": "email",
                "probabilities": {"email": 0.8, "web": 0.2},
                "answer_confidence": 0.72,
            }
        }
    }
    engine, agent = engine_with(payload)
    answer = engine.route_intent("send an email to bob", {"email": "mail", "web": "web"})
    assert answer is not None
    assert answer.choice == "email"
    assert "send an email to bob" in agent.calls[0][0]
    assert agent.calls[0][1]["intent"]["type"] == "choice"


def test_route_intent_invalid_options_returns_none() -> None:
    engine, _ = engine_with(FULL_RESPONSE)
    assert engine.route_intent("x", {"only": "1"}) is None


def test_is_harmful_threshold() -> None:
    engine, _ = engine_with({"answers": {"harmful": {"noul": 0.9}}})
    assert engine.is_harmful("delete everything") is True

    engine2, _ = engine_with({"answers": {"harmful": {"noul": 0.1}}})
    assert engine2.is_harmful("hello") is False


def test_score_urgency() -> None:
    engine, _ = engine_with({
        "answers": {
            "urgency": {
                "score": 2.4,
                "levels": ["Calm", "Soon", "Urgent", "Critical"],
                "probabilities": {"0": 0.0, "1": 0.1, "2": 0.8, "3": 0.1},
                "answer_confidence": 0.7,
            }
        }
    })
    answer = engine.score_urgency("server on fire!")
    assert answer is not None
    assert answer.level == "Urgent"
    assert answer.confidence == 0.7


# ── Tool wrapper ────────────────────────────────────────────────────────────
def test_decide_via_tool_choice(monkeypatch) -> None:
    payload = {
        "answers": {
            "intent": {
                "choice": "email",
                "probabilities": {"email": 0.8, "web": 0.15, "other": 0.05},
                "answer_confidence": 0.72,
            }
        }
    }
    engine, agent = engine_with(payload)
    monkeypatch.setattr(de, "get_engine", lambda refresh=False: engine)
    out = de.decide_via_tool(
        {"question": "Route this", "options": ["email", "web", "other"],
         "state": "please reply to the client"}
    )
    assert "Decision: email" in out
    assert "Confidence: 0.72" in out
    assert "please reply to the client" in agent.calls[0][0]


def test_decide_via_tool_yes_no(monkeypatch) -> None:
    engine, _ = engine_with({"answers": {"answer": {"noul": 0.82}}})
    monkeypatch.setattr(de, "get_engine", lambda refresh=False: engine)
    out = de.decide_via_tool({"question": "Should I retry?"})
    assert "Answer: YES" in out
    assert "0.82" in out


def test_decide_via_tool_missing_question() -> None:
    assert "required" in de.decide_via_tool({})


def test_get_engine_singleton() -> None:
    assert de.get_engine(refresh=True) is de.get_engine()
