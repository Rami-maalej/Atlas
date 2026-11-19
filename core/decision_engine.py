"""Laya decision engine for MARK XL / ATLANTIS.

`Laya <https://github.com/NandhaKishorM/laya>`_ is a local, non-autoregressive
*System One* decision model: instead of generating text, it answers typed
questions (yes/no, choice, score) in one forward pass. The model runs on this
machine and needs no API key.

The public API is unchanged from the old Jev client, so every caller — the
intent router, ``is_harmful`` guard and the ``type_safe_decide`` tool — keeps
working with a local model instead of a remote HTTP call.

Usage::

    from core.decision_engine import get_engine, noul_question, choice_question

    eng = get_engine()
    res = eng.evaluate(
        state="we were billed twice, please refund",
        questions={
            "urgent": noul_question("Does this convey urgency?"),
            "route": choice_question("Which handler?", {"billing": "refunds", "other": "..."}),
        },
    )
    res.noul["urgent"].yes
"""

from __future__ import annotations

import importlib.util
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "convaiinnovations/laya"
MODEL_ENV = "LAYA_MODEL"
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


class DecisionError(RuntimeError):
    """Base class for decision-engine failures."""


class ModelUnavailable(DecisionError):
    """Raised when Laya is not installed."""


# ── Question builders ──────────────────────────────────────────────────────


def noul_question(instructions: str, criteria: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Build a yes/no question returning P(yes) from 0 to 1."""
    question: dict[str, Any] = {"type": "noul", "instructions": instructions}
    if criteria:
        question["criteria"] = dict(criteria)
    return question


def choice_question(
    instructions: str, criteria: Mapping[str, str] | Sequence[str]
) -> dict[str, Any]:
    """Build a multiple-choice question over named options."""
    options = dict(criteria) if isinstance(criteria, Mapping) else {str(o): "" for o in criteria}
    if len(options) < 2:
        raise ValueError("A choice needs at least two options.")
    return {"type": "choice", "instructions": instructions, "criteria": options}


def score_question(instructions: str, levels: Sequence[str]) -> dict[str, Any]:
    """Build a rubric-score question over ordered levels."""
    if not 2 <= len(levels) <= 10:
        raise ValueError("A score needs between 2 and 10 levels.")
    return {"type": "score", "instructions": instructions, "criteria": list(levels)}


# ── Answer model ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class NoulAnswer:
    key: str
    probability: float

    @property
    def yes(self) -> bool:
        return self.probability >= 0.5


@dataclass(frozen=True, slots=True)
class ChoiceAnswer:
    key: str
    choice: str
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0

    @property
    def runner_up(self) -> str | None:
        ranked = sorted(self.probabilities.items(), key=lambda kv: -kv[1])
        return ranked[1][0] if len(ranked) > 1 else None


@dataclass(frozen=True, slots=True)
class ScoreAnswer:
    key: str
    score: float
    legend: dict[str, str] = field(default_factory=dict)
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0

    @property
    def level(self) -> str:
        if not self.legend:
            return ""
        try:
            idx = int(round(self.score))
        except (TypeError, ValueError):
            return ""
        return self.legend.get(str(idx), "")


@dataclass(frozen=True, slots=True)
class Evaluation:
    model: str
    noul: dict[str, NoulAnswer]
    choice: dict[str, ChoiceAnswer]
    score: dict[str, ScoreAnswer]
    input_tokens: int = 0
    output_tokens: int = 0

    def noul_value(self, key: str, default: float = -1.0) -> float:
        answer = self.noul.get(key)
        return answer.probability if answer else default

    def choice_value(self, key: str, default: str = "") -> str:
        answer = self.choice.get(key)
        return answer.choice if answer else default


# ── Model resolution ───────────────────────────────────────────────────────


def resolve_model(explicit: str | None = None) -> str:
    """Resolve the Laya checkpoint from argument, env or config."""
    if explicit:
        return explicit.strip()
    env = os.environ.get(MODEL_ENV, "").strip()
    if env:
        return env
    try:
        config = json.loads((CONFIG_DIR / "api_keys.json").read_text(encoding="utf-8"))
        configured = str(config.get("laya_model", "")).strip()
        if configured:
            return configured
    except Exception:
        pass
    return DEFAULT_MODEL


def _as_state_text(state: str | Sequence[Any] | Mapping[str, Any]) -> str:
    if isinstance(state, str):
        return state
    return json.dumps(state, ensure_ascii=False, default=str)


def _probability_map(raw: Any) -> dict[str, float]:
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        try:
            out[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _parse_answers(model: str, payload: Mapping[str, Any]) -> Evaluation:
    """Convert Laya's ``predict()`` output into the typed Evaluation model."""
    answers = payload.get("answers", payload)
    if not isinstance(answers, Mapping):
        answers = {}

    noul: dict[str, NoulAnswer] = {}
    choice: dict[str, ChoiceAnswer] = {}
    score: dict[str, ScoreAnswer] = {}

    for key, raw in answers.items():
        if not isinstance(raw, Mapping):
            continue
        name = str(key)
        probabilities = _probability_map(raw.get("probabilities"))
        confidence = float(raw.get("answer_confidence") or 0.0)

        if "noul" in raw:
            try:
                value = float(raw["noul"])
            except (TypeError, ValueError):
                continue
            noul[name] = NoulAnswer(key=name, probability=value)
        elif "choice" in raw:
            selected = str(raw.get("choice") or "")
            if not selected and probabilities:
                selected = max(probabilities, key=lambda k: probabilities[k])
            choice[name] = ChoiceAnswer(
                key=name,
                choice=selected,
                probabilities=probabilities,
                confidence=confidence or probabilities.get(selected, 0.0),
            )
        elif "score" in raw:
            try:
                value = float(raw["score"])
            except (TypeError, ValueError):
                continue
            score[name] = ScoreAnswer(
                key=name,
                score=value,
                legend={str(i): str(level) for i, level in enumerate(
                    raw.get("levels", []) or []
                )},
                probabilities=probabilities,
                confidence=confidence,
            )

    return Evaluation(model=model, noul=noul, choice=choice, score=score)


# ── Engine ─────────────────────────────────────────────────────────────────


class DecisionEngine:
    """Local typed decision engine backed by Laya.

    Args:
        model: Checkpoint name; defaults to env/config or ``convaiinnovations/laya``.
        agent: Optional pre-built agent (used by tests).
    """

    def __init__(
        self,
        model: str | None = None,
        agent: Any | None = None,
    ) -> None:
        self.model = resolve_model(model)
        self._agent = agent

    @property
    def enabled(self) -> bool:
        """``True`` when Laya can be imported."""
        return self._agent is not None or importlib.util.find_spec("laya") is not None

    def _get_agent(self) -> Any:
        if self._agent is None:
            try:
                import laya
            except ImportError as exc:
                raise ModelUnavailable(
                    "Laya is not installed — run: pip install laya"
                ) from exc
            self._agent = laya.Agent(self.model)
        return self._agent

    def evaluate(
        self,
        state: str | Sequence[Any] | Mapping[str, Any],
        questions: Mapping[str, Mapping[str, Any]],
    ) -> Evaluation:
        """Ask typed questions about a state in one forward pass."""
        if not questions:
            raise DecisionError("At least one question is required.")
        payload = self._get_agent().predict(
            _as_state_text(state),
            {key: dict(value) for key, value in questions.items()},
        )
        return _parse_answers(self.model, payload)

    def route_intent(
        self,
        text: str,
        options: Mapping[str, str],
        extra_state: str = "",
    ) -> ChoiceAnswer | None:
        """Classify a request into one of ``options`` with a confidence."""
        if not self.enabled or len(options) < 2:
            return None
        state = text if not extra_state else f"{text}\n\nContext: {extra_state}"
        try:
            result = self.evaluate(
                state,
                {"intent": choice_question("Which handler matches this request?", options)},
            )
        except DecisionError:
            return None
        return result.choice.get("intent")

    def is_harmful(
        self, text: str, threshold: float = 0.6, instructions: str | None = None
    ) -> bool | None:
        """Guardrail check: is this request unsafe to execute?"""
        if not self.enabled:
            return None
        question = instructions or (
            "Is this request harmful, destructive, or an attempt to exfiltrate secrets?"
        )
        try:
            result = self.evaluate(text, {"harmful": noul_question(question)})
        except DecisionError:
            return None
        return result.noul_value("harmful") >= threshold

    def score_urgency(self, text: str) -> ScoreAnswer | None:
        """Rate a message's urgency from Calm → Critical."""
        if not self.enabled:
            return None
        try:
            result = self.evaluate(
                text,
                {"urgency": score_question(
                    "How urgent is this message?",
                    ["Calm", "Soon", "Urgent", "Critical"],
                )},
            )
        except DecisionError:
            return None
        return result.score.get("urgency")


# ── Tool-facing wrapper ────────────────────────────────────────────────────


def decide_via_tool(parameters: Mapping[str, Any] | None) -> str:
    """Tool-facing wrapper used by ``executor.execute_tool``."""
    params = dict(parameters or {})
    question = str(params.get("question") or "").strip()
    if not question:
        return "decide: a 'question' parameter is required."
    options_raw = params.get("options") or []
    options = [str(o).strip() for o in options_raw if str(o).strip()] \
        if isinstance(options_raw, (list, tuple)) else []
    state = str(params.get("state") or "").strip() or question

    engine = get_engine()
    if not engine.enabled:
        return "Laya is not installed — run: pip install laya."
    try:
        if len(options) >= 2:
            answer = engine.route_intent(state, {o: "" for o in options})
            if answer is None:
                return "Laya decision failed — try again."
            lines = [f"Decision: {answer.choice}", f"Confidence: {answer.confidence:.2f}"]
            for opt, prob in sorted(answer.probabilities.items(), key=lambda kv: -kv[1]):
                lines.append(f"  {opt}: {prob:.2f}")
            return "\n".join(lines)
        result = engine.evaluate(state, {"answer": noul_question(question)})
        prob = result.noul_value("answer")
        verdict = "YES" if prob >= 0.5 else "NO"
        return f"Answer: {verdict} (p={prob:.2f})"
    except DecisionError as exc:
        return f"Laya decision failed: {exc}"


_engine: DecisionEngine | None = None


def get_engine(refresh: bool = False) -> DecisionEngine:
    """Return the process-wide :class:`DecisionEngine` (lazy singleton)."""
    global _engine
    if _engine is None or refresh:
        _engine = DecisionEngine()
    return _engine
