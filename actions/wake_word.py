import logging
import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

logger = logging.getLogger("wake_word")

DEFAULT_MODEL = "jarvis"  # aliased to openwakeword's built-in "hey_jarvis"
_MODEL_ALIASES = {
    "jarvis": "hey_jarvis",
    "hey jarvis": "hey_jarvis",
    "hey_jarvis": "hey_jarvis",
    "alexa": "alexa",
    "computer": "hey_jarvis",
}
_WAKE_COOLDOWN = 2.0


class WakeWordDetector:
    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        sensitivity: float = 0.5,
        on_wake: Callable[[], None] | None = None,
    ):
        self.model_name = model_name
        self.sensitivity = sensitivity
        self.on_wake = on_wake
        self._running = False
        self._thread: threading.Thread | None = None
        self._audio_queue: queue.Queue = queue.Queue()
        self._oww = None
        self._model_key = _MODEL_ALIASES.get(model_name.lower(), model_name)
        self._last_wake = 0.0

    def _load_model(self):
        try:
            import openwakeword
            from openwakeword.model import Model
        except ImportError:
            logger.error(
                "OpenWakeWord not installed. Run: pip install openwakeword"
            )
            return False

        try:
            if self._model_key not in openwakeword.models:
                logger.warning(
                    "Unknown wake word '%s' — using 'hey_jarvis'", self.model_name
                )
                self._model_key = "hey_jarvis"
            paths = [
                p for p in openwakeword.get_pretrained_model_paths()
                if Path(p).name.startswith(f"{self._model_key}_v")
            ]
            self._oww = Model(wakeword_model_paths=paths) if paths else Model()
            self._model_key = next(iter(self._oww.models), self._model_key)
            return True
        except Exception as e:
            logger.warning("OpenWakeWord model load failed: %s", e)
            return False

    def start(self):
        if self._running:
            return
        if not self._load_model():
            logger.error("Failed to load wake word model")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Wake word detector started: '%s'", self.model_name)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        logger.info("Wake word detector stopped")

    def feed_audio(self, audio_chunk: np.ndarray):
        if not (self._running and self._oww is not None):
            return
        chunk = np.asarray(audio_chunk).reshape(-1)
        if chunk.dtype != np.int16:
            chunk = (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16)
        if chunk.size < 400:
            return
        self._audio_queue.put(chunk)

    def _run(self):
        while self._running:
            try:
                chunk = self._audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                prediction = self._oww.predict(chunk)
                self._wake_if_needed(prediction.get(self._model_key, 0.0))
            except Exception as e:
                logger.debug("Wake word inference error: %s", e)

    def _wake_if_needed(self, score: float) -> None:
        now = time.monotonic()
        if score <= self.sensitivity or now - self._last_wake <= _WAKE_COOLDOWN:
            return
        self._last_wake = now
        logger.info("Wake word detected! (score=%.3f)", score)
        if self.on_wake:
            self.on_wake()

    def is_running(self) -> bool:
        return self._running


# ── Global singleton ──────────────────────────────────────────────────────

_detector: WakeWordDetector | None = None


def get_detector(
    model_name: str = DEFAULT_MODEL,
    sensitivity: float = 0.5,
    on_wake: Callable[[], None] | None = None,
) -> WakeWordDetector:
    global _detector
    if _detector is None:
        _detector = WakeWordDetector(
            model_name=model_name,
            sensitivity=sensitivity,
            on_wake=on_wake,
        )
    elif on_wake is not None:
        _detector.on_wake = on_wake
    return _detector


def start_wake_word(
    model_name: str = DEFAULT_MODEL,
    sensitivity: float = 0.5,
    on_wake: Callable[[], None] | None = None,
) -> str:
    detector = get_detector(
        model_name=model_name,
        sensitivity=sensitivity,
        on_wake=on_wake,
    )
    detector.start()
    if detector._oww is None:
        return "Wake word unavailable — OpenWakeWord model not loaded."
    return f"Wake word '{model_name}' active (sensitivity={sensitivity})."


def stop_wake_word() -> str:
    global _detector
    if _detector:
        _detector.stop()
        _detector = None
        return "Wake word detector stopped."
    return "No wake word detector running."


def feed_audio_chunk(chunk: np.ndarray):
    if _detector and _detector.is_running():
        _detector.feed_audio(chunk)
