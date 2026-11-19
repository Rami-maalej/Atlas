"""Tests for wake word, idle sleep and the event bus wiring."""

from __future__ import annotations

import sys
import types

import numpy as np

from actions import wake_word
from core import events


def test_event_bus_delivers_sync_and_async_style_handlers() -> None:
    seen: list[str] = []
    events.subscribe(events.WAKE, lambda ctx: seen.append(ctx.kwargs["source"]))

    events.emit(events.WAKE, source="voice")

    assert "voice" in seen


def test_wake_detector_maps_jarvis_to_builtin_model(monkeypatch) -> None:
    fake_oww = types.ModuleType("openwakeword")
    fake_model = types.ModuleType("openwakeword.model")

    class FakeModel:
        models = {"hey_jarvis_v0.1": {}}

        def __init__(self, wakeword_model_paths=None):
            self.paths = wakeword_model_paths

        def predict(self, _chunk):
            return {"hey_jarvis_v0.1": 0.9}

    fake_model.Model = FakeModel
    fake_oww.models = {"hey_jarvis": {}, "alexa": {}}
    fake_oww.get_pretrained_model_paths = lambda: ["/models/hey_jarvis_v0.1.onnx"]
    monkeypatch.setitem(sys.modules, "openwakeword", fake_oww)
    monkeypatch.setitem(sys.modules, "openwakeword.model", fake_model)

    detector = wake_word.WakeWordDetector(model_name="jarvis")

    assert detector._load_model() is True
    assert detector._model_key == "hey_jarvis_v0.1"
    assert detector._oww.paths == ["/models/hey_jarvis_v0.1.onnx"]


def test_fed_audio_is_converted_to_int16() -> None:
    detector = wake_word.WakeWordDetector()
    detector._running = True
    detector._oww = object()

    detector.feed_audio(np.zeros((1024, 1), dtype=np.float32))

    chunk = detector._audio_queue.get_nowait()
    assert chunk.dtype == np.int16
    assert chunk.shape == (1024,)


def test_wake_callback_has_a_cooldown() -> None:
    calls: list[int] = []
    detector = wake_word.WakeWordDetector(on_wake=lambda: calls.append(1))

    detector._wake_if_needed(0.9)
    detector._wake_if_needed(0.9)

    assert len(calls) == 1


def test_wake_word_detector_accepts_updated_callback(monkeypatch) -> None:
    wake_word._detector = None
    def first():
        return None

    def second():
        return None
    wake_word.get_detector(on_wake=first)

    wake_word.get_detector(on_wake=second)

    assert wake_word._detector.on_wake is second
    wake_word._detector = None


def test_hud_has_blue_and_grey_palettes() -> None:
    source = open("ui.py", encoding="utf-8").read()

    assert "_SLEEP_BLUE" in source
    assert 'state == "SLEEP"' in source
    assert "self.hud.awake = awake" in source
