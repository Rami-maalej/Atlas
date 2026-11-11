"""Tests for core.decision_engine — TypeSafe AI (Jev) integration (offline)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from core import decision_engine as de


# ── Question builders ───────────────────────────────────────────────────────
def test_noul_question_shape() -> None:
    q = de.noul_question("Is it urgent?", {"true": "time-sensitive", "false": "no rush"})
    assert q["type"] == "noul"
    assert q["instructions"] == "Is it urgent?"
    assert q["criteria"]["true"] == "time-sensitive"


def test_noul_question_without_criteria() -> None:
    q = de.noul_question("Yes or no?")
    assert "criteria" not in q


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


# ── API key resolution ──────────────────────────────────────────────────────
def test_resolve_api_key_explicit(monkeypatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert de.resolve_api_key("  key-1  ") == "key-1"


def test_resolve_api_key_env(monkeypatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "env-key")
    assert de.resolve_api_key(None) == "env-key"


def test_resolve_api_key_config_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    cfg = tmp_path / "api_keys.json"
    cfg.write_text(json.dumps({"typesafe_api_key": "cfg-key"}), encoding="utf-8")
    monkeypatch.setattr(de, "LEGACY_KEYS_FILE", cfg)
    assert de.resolve_api_key(None) == "cfg-key"


def test_resolve_api_key_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(de, "LEGACY_KEYS_FILE", tmp_path / "nope.json")
    assert de.resolve_api_key(None) == ""


# ── Response parsing ────────────────────────────────────────────────────────
FULL_RESPONSE: dict[str, Any] = {
    "model": "jev-1.13.0",
    "answers": {
        "urgent": {"type": "noul", "noul": 0.95},
        "route": {
            "type": "choice",
            "choice": "email",
            "probabilities": {"email": 0.8, "web": 0.15, "other": 0.05},
            "confidence": 0.72,
        },
        "severity": {
            "type": "score",
            "score": 1.05,
            "legend": {"0": "Calm", "1": "Frustrated", "2": "Very angry"},
            "probabilities": {"0": 0.0, "1": 0.95, "2": 0.05},
            "confidence": 0.92,
        },
    },
    "usage": {"input_tokens": 296, "output_tokens": 20},
}


def _engine_with(payload: dict[str, Any], api_key: str = "k") -> tuple[de.DecisionEngine, dict]:
    seen: dict[str, Any] = {}

    def transport(url: str, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
        seen["url"] = url
        seen["body"] = json.loads(body.decode())
        seen["headers"] = headers
        return payload

    return de.DecisionEngine(api_key=api_key, transport=transport), seen


def test_evaluate_parses_all_answer_types() -> None:
    engine, seen = _engine_with(FULL_RESPONSE)
    result = engine.evaluate(
        "Help! My payouts failed 3 days ago.",
        {
            "urgent": de.noul_question("Urgent?"),
            "route": de.choice_question("Route", {"email": "e", "web": "w", "other": "o"}),
            "severity": de.score_question("Severity", ["Calm", "Frustrated", "Very angry"]),
        },
    )
    assert seen["url"] == de.API_URL
    assert seen["headers"]["Authorization"] == "Bearer k"
    assert seen["body"]["model"] == "jev-latest"
    assert result.model == "jev-1.13.0"
    assert result.noul["urgent"].probability == 0.95
    assert result.noul["urgent"].yes is True
    assert result.choice["route"].choice == "email"
    assert result.choice["route"].runner_up == "web"
    assert result.choice["route"].confidence == 0.72
    assert result.score["severity"].level == "Frustrated"
    assert result.input_tokens == 296
    assert result.output_tokens == 20
    assert result.noul_value("urgent") == 0.95
    assert result.choice_value("route") == "email"
    assert result.noul_value("missing") == -1.0
    assert result.choice_value("missing", "fallback") == "fallback"


def test_evaluate_requires_key() -> None:
    engine = de.DecisionEngine(api_key="", transport=lambda u, b, h: {})
    with pytest.raises(de.NotConfigured):
        engine.evaluate("state", {"q": de.noul_question("ok?")})
    assert engine.enabled is False


def test_evaluate_requires_questions() -> None:
    engine, _ = _engine_with(FULL_RESPONSE)
    with pytest.raises(de.DecisionError):
        engine.evaluate("state", {})


def test_evaluate_transport_errors_bubble() -> None:
    def transport(url: str, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
        raise de.DecisionError("boom")

    engine = de.DecisionEngine(api_key="k", transport=transport)
    with pytest.raises(de.DecisionError):
        engine.evaluate("state", {"q": de.noul_question("ok?")})


# ── Helpers ─────────────────────────────────────────────────────────────────
def test_route_intent_returns_choice() -> None:
    payload = {
        "model": "jev-1.13.0",
        "answers": {
            "intent": {
                "type": "choice",
                "choice": "email",
                "probabilities": {"email": 0.8, "web": 0.2},
                "confidence": 0.72,
            }
        },
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    engine, seen = _engine_with(payload)
    answer = engine.route_intent("send an email to bob", {"email": "mail", "web": "web"})
    assert answer is not None
    assert answer.choice == "email"
    # state passed through to the request
    assert "send an email to bob" in seen["body"]["state"]
    assert seen["body"]["questions"]["intent"]["type"] == "choice"


def test_route_intent_disabled_returns_none() -> None:
    engine = de.DecisionEngine(api_key="", transport=lambda u, b, h: {})
    assert engine.route_intent("x", {"a": "1", "b": "2"}) is None
    assert engine.route_intent("x", {"only": "1"}) is None


def test_is_harmful_threshold() -> None:
    engine, _ = _engine_with({"answers": {"harmful": {"type": "noul", "noul": 0.9}}})
    assert engine.is_harmful("delete everything") is True

    engine2, _ = _engine_with({"answers": {"harmful": {"type": "noul", "noul": 0.1}}})
    assert engine2.is_harmful("hello") is False


def test_is_harmful_disabled() -> None:
    engine = de.DecisionEngine(api_key="", transport=lambda u, b, h: {})
    assert engine.is_harmful("anything") is None


def test_score_urgency() -> None:
    engine, _ = _engine_with(
        {"answers": {"urgency": {"type": "score", "score": 2.4,
                                 "legend": {"0": "Calm", "1": "Soon",
                                            "2": "Urgent", "3": "Critical"},
                                 "probabilities": {"0": 0.0, "1": 0.1, "2": 0.8, "3": 0.1},
                                 "confidence": 0.7}}}
    )
    answer = engine.score_urgency("server on fire!")
    assert answer is not None
    assert answer.level == "Urgent"
    assert answer.confidence == 0.7


def test_score_urgency_disabled() -> None:
    engine = de.DecisionEngine(api_key="", transport=lambda u, b, h: {})
    assert engine.score_urgency("x") is None


# ── Tool wrapper ────────────────────────────────────────────────────────────
def test_decide_via_tool_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(de, "get_engine", lambda refresh=False: de.DecisionEngine(api_key=""))
    out = de.decide_via_tool({"question": "Is it urgent?"})
    assert "not configured" in out


def test_decide_via_tool_choice(monkeypatch) -> None:
    payload = {
        "model": "jev-1.13.0",
        "answers": {
            "intent": {
                "type": "choice",
                "choice": "email",
                "probabilities": {"email": 0.8, "web": 0.15, "other": 0.05},
                "confidence": 0.72,
            }
        },
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    engine, seen = _engine_with(payload)
    monkeypatch.setattr(de, "get_engine", lambda refresh=False: engine)
    out = de.decide_via_tool(
        {"question": "Route this", "options": ["email", "web", "other"],
         "state": "please reply to the client"}
    )
    assert "Decision: email" in out
    assert "Confidence: 0.72" in out
    assert "please reply to the client" in seen["body"]["state"]


def test_decide_via_tool_yes_no(monkeypatch) -> None:
    engine, _ = _engine_with({"answers": {"answer": {"type": "noul", "noul": 0.82}}})
    monkeypatch.setattr(de, "get_engine", lambda refresh=False: engine)
    out = de.decide_via_tool({"question": "Should I retry?"})
    assert "Answer: YES" in out
    assert "0.82" in out


def test_decide_via_tool_missing_question() -> None:
    out = de.decide_via_tool({})
    assert "required" in out


def test_get_engine_singleton() -> None:
    first = de.get_engine(refresh=True)
    second = de.get_engine()
    assert first is second
