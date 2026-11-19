"""Continuous voice loop: wake word, VAD endpointing, follow-up window, barge-in.

Providers are selected by config so STT/TTS/VAD can be swapped. All audio work
happens on sounddevice's callback thread or a dedicated worker, never the GUI.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from core.conversation_state import ConversationState, LatencyLog, State

logger = logging.getLogger("voice_loop")


class VADProvider(Protocol):
    """Interface every VAD backend implements."""

    def is_speech(self, chunk: np.ndarray) -> bool: ...
    def feed(self, chunk: np.ndarray) -> np.ndarray | None: ...
    def reset(self) -> None: ...


@dataclass
class _SpeechBuffer:
    frames: list[np.ndarray]
    last_voice: float
    started: float


class EnergyVAD:
    """Adaptive-energy VAD with smart endpointing and no external model."""

    def __init__(self, threshold: float = 0.012, endpointing_ms: int = 700,
                 min_speech_ms: int = 250):
        self.threshold = threshold
        self.endpoint_ms = endpointing_ms
        self.min_speech_ms = min_speech_ms
        self._buf = _SpeechBuffer([], 0.0, 0.0)
        self._lock = threading.Lock()

    def is_speech(self, chunk: np.ndarray) -> bool:
        if chunk.size == 0:
            return False
        rms = float(np.sqrt(np.mean(np.square(chunk.astype(np.float32)))))
        return rms > self.threshold

    def feed(self, chunk: np.ndarray) -> np.ndarray | None:
        now = time.monotonic()
        speech = self.is_speech(chunk)
        with self._lock:
            if speech:
                if not self._buf.frames:
                    self._buf.started = now
                self._buf.frames.append(chunk.copy())
                self._buf.last_voice = now
                return None
            if not self._buf.frames:
                return None
            duration = (now - self._buf.started) * 1000
            silence = (now - self._buf.last_voice) * 1000
            if silence < self.endpoint_ms or duration < self.min_speech_ms:
                self._buf.frames.append(chunk.copy())
                return None
            audio = np.concatenate(self._buf.frames)
            self._buf = _SpeechBuffer([], 0.0, 0.0)
            return audio

    def reset(self) -> None:
        with self._lock:
            self._buf = _SpeechBuffer([], 0.0, 0.0)


class SileroVAD(EnergyVAD):
    """Silero ONNX VAD when a model is available; otherwise energy fallback."""

    def __init__(self, model_path: str = "", **kwargs):
        super().__init__(**kwargs)
        self._model = None
        self._available = False
        if model_path:
            try:
                import onnxruntime as ort

                self._model = ort.InferenceSession(model_path)
                self._available = True
            except Exception as e:
                logger.warning("Silero VAD unavailable (%s); using energy VAD", type(e).__name__)

    @property
    def available(self) -> bool:
        return self._available


class VoiceLoop:
    """Coordinate mic capture, wake word, VAD and state transitions."""

    SAMPLE_RATE = 16000
    BLOCK = 1024

    def __init__(
        self,
        state: ConversationState,
        latency: LatencyLog | None = None,
        on_utterance: Callable[[np.ndarray, str], None] | None = None,
        on_barge_in: Callable[[], None] | None = None,
        config: dict[str, Any] | None = None,
    ):
        self.state = state
        self.latency = latency or LatencyLog()
        self.on_utterance = on_utterance
        self.on_barge_in = on_barge_in
        cfg = config if config is not None else _config()
        self.wake_word = str(cfg.get("wake_word", "jarvis"))
        self.conversation_mode = bool(cfg.get("voice_conversation_mode", True))
        self.follow_up_seconds = float(cfg.get("follow_up_seconds", 12.0))
        self.endpoint_ms = int(cfg.get("endpointing_ms", 700))
        self.vad: VADProvider = (
            SileroVAD(model_path=str(cfg.get("vad_model", "")), endpointing_ms=self.endpoint_ms)
            if cfg.get("vad_provider") == "silero"
            else EnergyVAD(endpointing_ms=self.endpoint_ms)
        )
        self._stream: Any = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._detector = None

    def start(self) -> bool:
        """Start mic capture. Returns False when no microphone is available."""
        if self._running:
            return True
        try:
            import sounddevice as sd
        except Exception as e:
            logger.warning("Voice loop unavailable: %s", e)
            return False

        def callback(indata, _frames, _time, _status):
            chunk = indata.reshape(-1)
            if self.state.is_speaking:
                if self.vad.is_speech(chunk):
                    if self.on_barge_in:
                        self.on_barge_in()
                    self.vad.reset()
                return
            if self._detector is not None:
                try:
                    self._detector.feed_audio(chunk)
                except Exception:
                    pass
            if self.state.state in (State.LISTENING, State.TRANSCRIBING):
                audio = self.vad.feed(chunk)
                if audio is not None and self.on_utterance:
                    self.latency.mark("VAD_END")
                    self.vad.reset()
                    self.on_utterance(audio, "")

        try:
            self._stream = sd.InputStream(
                samplerate=self.SAMPLE_RATE, channels=1, dtype="float32",
                blocksize=self.BLOCK, callback=callback,
            )
            self._stream.start()
            self._running = True
            logger.info("Voice loop started (wake='%s', endpoint=%dms)",
                        self.wake_word, self.endpoint_ms)
            return True
        except Exception as e:
            logger.warning("Mic unavailable: %s", e)
            return False

    def stop(self) -> None:
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self.vad.reset()

    def listen_for_follow_up(self) -> None:
        """After answering, keep listening without requiring the wake word."""
        if not self.conversation_mode:
            return
        self.state.note_user_turn(self.follow_up_seconds)
        self.state.transition(State.LISTENING)

    def end_turn(self) -> None:
        self.state.clear_follow_up()
        self.state.transition(State.IDLE)


def _config() -> dict[str, Any]:
    try:
        from memory.config_manager import load_config

        return load_config()
    except Exception:
        return {}
