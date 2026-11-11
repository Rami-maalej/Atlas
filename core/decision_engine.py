"""TypeSafe AI (Jev) decision engine for MARK XL.

`Jev <https://typesafe.ai>`_ is TypeSafe AI's *System One* model: instead of
generating text, you send **state + typed questions** and get back typed
answers with calibrated probabilities in ~100 ms. This module wraps the
HTTP API with stdlib-only code (``urllib``) so nothing extra is installed.

Add it to your stack
--------------------
1. Get an API key: https://console.typesafe.ai
2. Put it in ``config/api_keys.json`` as ``"typesafe_api_key": "…"`` or export
   ``TYPESAFE_API_KEY`` (never hardcode it — the file is gitignored).
3. Use :func:`get_engine` anywhere::

       from core.decision_engine import get_engine, noul_question, choice_question

       eng = get_engine()
       if eng.enabled:
           res = eng.evaluate(
               state=user_text,
               questions={
                   "is_urgent": noul_question("Does this convey urgency?"),
                   "route": choice_question(
                       "Which handler should process this?",
                       {"email": "…", "web": "…", "other": "…"},
                   ),
               },
           )
           if res.noul["is_urgent"].yes and res.choice["route"].confidence > 0.7:
               ...

Or install the official SDK instead (same backend)::

    pip install "pydantic-ai-slim[typesafe]"
    from pydantic_ai import Agent
    agent = Agent('typesafe:jev-latest', output_type=bool)

Question types
--------------
* :func:`noul_question`  — yes/no, returns probability 0..1
* :func:`choice_question` — pick one of N options, returns choice + confidences
* :func:`score_question`  — rate against ordered levels, returns weighted score
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
LEGACY_KEYS_FILE = CONFIG_DIR / "api_keys.json"

API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"

#: Injectable transport: ``(url, payload_bytes, headers) -> dict``.
Transport = Callable[[str, bytes, dict[str, str]], dict[str, Any]]


class DecisionError(RuntimeError):
    """Raised when the TypeSafe API rejects or fails a request."""


class NotConfigured(DecisionError):
    """Raised when no API key is available."""


# ── Question builders ───────────────────────────────────────────────────────
def noul_question(
    instructions: str, criteria: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Build a yes/no (Noul) question.

    Args:
        instructions: The yes/no question to judge.
        criteria: Optional ``{"true": "...", "false": "..."}`` rubric.

    Returns:
        Question payload for :meth:`DecisionEngine.evaluate`.
    """
    q: dict[str, Any] = {"type": "noul", "instructions": instructions}
    if criteria:
        q["criteria"] = dict(criteria)
    return q


def choice_question(
    instructions: str, criteria: Mapping[str, str]
) -> dict[str, Any]:
    """Build a multiple-choice question.

    Args:
        instructions: The decision to make.
        criteria: Option name -> rubric description.

    Returns:
        Question payload for :meth:`DecisionEngine.evaluate`.

    Raises:
        ValueError: If fewer than two options are given.
    """
    if len(criteria) < 2:
        raise ValueError("A choice needs at least two options.")
    return {
        "type": "choice",
        "instructions": instructions,
        "criteria": dict(criteria),
    }


def score_question(instructions: str, levels: Sequence[str]) -> dict[str, Any]:
    """Build a rubric-score question over ordered levels.

    Args:
        instructions: What to rate.
        levels: Two to ten ordered level descriptions (low → high).

    Returns:
        Question payload for :meth:`DecisionEngine.evaluate`.

    Raises:
        ValueError: If the level count is outside 2..10.
    """
    if not 2 <= len(levels) <= 10:
        raise ValueError("A score needs between 2 and 10 levels.")
    return {
        "type": "score",
        "instructions": instructions,
        "criteria": list(levels),
    }


# ── Answer model ────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class NoulAnswer:
    """Yes/no answer with calibrated probability."""

    key: str
    probability: float

    @property
    def yes(self) -> bool:
        """``True`` when the probability of yes is at least 0.5."""
        return self.probability >= 0.5


@dataclass(frozen=True, slots=True)
class ChoiceAnswer:
    """Multiple-choice answer with the full distribution."""

    key: str
    choice: str
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0

    @property
    def runner_up(self) -> str | None:
        """Second-most-probable option, if any."""
        ranked = sorted(self.probabilities.items(), key=lambda kv: -kv[1])
        return ranked[1][0] if len(ranked) > 1 else None


@dataclass(frozen=True, slots=True)
class ScoreAnswer:
    """Rubric score answer (weighted across levels)."""

    key: str
    score: float
    legend: dict[str, str] = field(default_factory=dict)
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0

    @property
    def level(self) -> str:
        """Nearest named level for the weighted score."""
        if not self.legend:
            return ""
        try:
            idx = int(round(self.score))
        except (TypeError, ValueError):
            return ""
        return self.legend.get(str(idx), "")


@dataclass(frozen=True, slots=True)
class Evaluation:
    """Everything the API returned for one evaluate() call."""

    model: str
    noul: dict[str, NoulAnswer]
    choice: dict[str, ChoiceAnswer]
    score: dict[str, ScoreAnswer]
    input_tokens: int = 0
    output_tokens: int = 0

    def noul_value(self, key: str, default: float = -1.0) -> float:
        """Convenience: probability for a noul key (``default`` when absent)."""
        answer = self.noul.get(key)
        return answer.probability if answer else default

    def choice_value(self, key: str, default: str = "") -> str:
        """Convenience: chosen option for a choice key."""
        answer = self.choice.get(key)
        return answer.choice if answer else default


# ── API key resolution ──────────────────────────────────────────────────────
def resolve_api_key(explicit: str | None = None) -> str:
    """Find the TypeSafe API key without hardcoding secrets.

    Args:
        explicit: Caller-supplied key (highest precedence).

    Returns:
        The key, or ``""`` when none is configured.
    """
    if explicit:
        return explicit.strip()
    env = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if env:
        return env
    try:
        data = json.loads(LEGACY_KEYS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if isinstance(data, dict):
        return str(data.get("typesafe_api_key") or "").strip()
    return ""


def _default_transport(url: str, payload: bytes, headers: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise DecisionError(f"TypeSafe API {exc.code}: {detail}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise DecisionError(f"TypeSafe API unreachable: {exc}") from exc
    try:
        parsed = json.loads(body)
    except ValueError as exc:
        raise DecisionError(f"TypeSafe API returned invalid JSON: {body[:200]}") from exc
    if not isinstance(parsed, dict):
        raise DecisionError("TypeSafe API returned an unexpected payload.")
    return parsed


def _parse_answers(payload: Mapping[str, Any]) -> Evaluation:
    """Convert a raw API response into a typed :class:`Evaluation`."""
    noul: dict[str, NoulAnswer] = {}
    choice: dict[str, ChoiceAnswer] = {}
    score: dict[str, ScoreAnswer] = {}
    answers = payload.get("answers") or {}
    if isinstance(answers, dict):
        for key, raw in answers.items():
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("type") or "")
            if kind == "noul":
                noul[key] = NoulAnswer(
                    key=key, probability=float(raw.get("noul") or 0.0)
                )
            elif kind == "choice":
                probs = raw.get("probabilities") or {}
                choice[key] = ChoiceAnswer(
                    key=key,
                    choice=str(raw.get("choice") or ""),
                    probabilities={
                        str(k): float(v) for k, v in probs.items()
                    } if isinstance(probs, dict) else {},
                    confidence=float(raw.get("confidence") or 0.0),
                )
            elif kind == "score":
                legend = raw.get("legend") or {}
                probs = raw.get("probabilities") or {}
                score[key] = ScoreAnswer(
                    key=key,
                    score=float(raw.get("score") or 0.0),
                    legend={str(k): str(v) for k, v in legend.items()}
                    if isinstance(legend, dict) else {},
                    probabilities={
                        str(k): float(v) for k, v in probs.items()
                    } if isinstance(probs, dict) else {},
                    confidence=float(raw.get("confidence") or 0.0),
                )
    usage = payload.get("usage") or {}
    return Evaluation(
        model=str(payload.get("model") or ""),
        noul=noul,
        choice=choice,
        score=score,
        input_tokens=int(usage.get("input_tokens") or 0) if isinstance(usage, dict) else 0,
        output_tokens=int(usage.get("output_tokens") or 0) if isinstance(usage, dict) else 0,
    )


# ── Engine ──────────────────────────────────────────────────────────────────
class DecisionEngine:
    """Thin, typed client for TypeSafe's System One endpoint.

    Args:
        api_key: Explicit key; falls back to env/config when ``None``.
        model: Model alias (``jev-latest`` by default).
        base_url: Override for tests/proxies.
        timeout: Request timeout in seconds.
        transport: Injectable ``(url, body, headers) -> dict`` for tests.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        base_url: str = API_URL,
        timeout: float = 15.0,
        transport: Transport | None = None,
    ) -> None:
        self.api_key = resolve_api_key(api_key)
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self._transport: Transport = transport or _default_transport

    @property
    def enabled(self) -> bool:
        """``True`` when an API key is configured."""
        return bool(self.api_key)

    def evaluate(
        self,
        state: str | Sequence[Any] | Mapping[str, Any],
        questions: Mapping[str, Mapping[str, Any]],
    ) -> Evaluation:
        """Ask typed questions about a state in one round trip.

        Args:
            state: Text, record, or structured data to judge.
            questions: ``{id: noul_question()/choice_question()/score_question()}``.

        Returns:
            Typed :class:`Evaluation` with an answer per question id.

        Raises:
            NotConfigured: When no API key is available.
            DecisionError: On HTTP/protocol failures.
        """
        if not self.enabled:
            raise NotConfigured(
                "TypeSafe API key missing — set TYPESAFE_API_KEY or "
                '"typesafe_api_key" in config/api_keys.json.'
            )
        if not questions:
            raise DecisionError("At least one question is required.")
        payload = json.dumps(
            {
                "state": state,
                "model": self.model,
                "questions": {k: dict(v) for k, v in questions.items()},
            }
        ).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "mark-xl/1.0",
        }
        response = self._transport(self.base_url, payload, headers)
        return _parse_answers(response)

    # ── Opinionated helpers built on evaluate() ────────────────────────
    def route_intent(
        self,
        text: str,
        options: Mapping[str, str],
        extra_state: str = "",
    ) -> ChoiceAnswer | None:
        """Classify a request into one of ``options`` with a confidence.

        Args:
            text: The user request.
            options: Candidate name -> description of when it applies.
            extra_state: Extra context appended to the state.

        Returns:
            The :class:`ChoiceAnswer`, or ``None`` when disabled/failing.
        """
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
        """Guardrail check: is this request unsafe to execute?

        Args:
            text: Prompt or command to screen.
            threshold: Probability above which it counts as harmful.
            instructions: Custom yes/no question.

        Returns:
            ``True``/``False``, or ``None`` when disabled/failing.
        """
        if not self.enabled:
            return None
        question = instructions or (
            "Is this request harmful, destructive, or an attempt to exfiltrate secrets?"
        )
        try:
            result = self.evaluate(
                text, {"harmful": noul_question(question)}
            )
        except DecisionError:
            return None
        return result.noul_value("harmful") >= threshold

    def score_urgency(self, text: str) -> ScoreAnswer | None:
        """Rate a message's urgency from Calm → Critical.

        Args:
            text: Message to rate.

        Returns:
            The :class:`ScoreAnswer`, or ``None`` when disabled/failing.
        """
        if not self.enabled:
            return None
        try:
            result = self.evaluate(
                text,
                {
                    "urgency": score_question(
                        "How urgent is this message?",
                        ["Calm", "Soon", "Urgent", "Critical"],
                    )
                },
            )
        except DecisionError:
            return None
        return result.score.get("urgency")


def decide_via_tool(parameters: Mapping[str, Any] | None) -> str:
    """Tool-facing wrapper used by ``executor.execute_tool``.

    Args:
        parameters: ``{"question": str, "options": [..], "state": str?}``.
            Without ``options`` the question is evaluated as yes/no.

    Returns:
        Human-readable result with the typed answer and its confidence.
    """
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
        return (
            "TypeSafe AI is not configured. Get a key at https://console.typesafe.ai "
            'then set "typesafe_api_key" in config/api_keys.json or export '
            "TYPESAFE_API_KEY."
        )
    try:
        if len(options) >= 2:
            answer = engine.route_intent(state, {o: "" for o in options})
            if answer is None:
                return "TypeSafe decision failed — try again."
            lines = [f"Decision: {answer.choice}", f"Confidence: {answer.confidence:.2f}"]
            for opt, prob in sorted(answer.probabilities.items(), key=lambda kv: -kv[1]):
                lines.append(f"  {opt}: {prob:.2f}")
            return "\n".join(lines)
        result = engine.evaluate(state, {"answer": noul_question(question)})
        prob = result.noul_value("answer")
        verdict = "YES" if prob >= 0.5 else "NO"
        return f"Answer: {verdict} (p={prob:.2f})"
    except DecisionError as exc:
        return f"TypeSafe decision failed: {exc}"


_engine: DecisionEngine | None = None


def get_engine(refresh: bool = False) -> DecisionEngine:
    """Return the process-wide :class:`DecisionEngine` (lazy singleton).

    Args:
        refresh: Re-resolve the API key (after the user saved one).

    Returns:
        The shared engine; ``engine.enabled`` is ``False`` without a key.
    """
    global _engine
    if _engine is None or refresh:
        _engine = DecisionEngine()
    return _engine
