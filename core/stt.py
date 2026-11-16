"""
Speech-to-Text engines for MARK XL.

Whisper  – offline transcription via faster-whisper (VAD-buffered)
Vosk     – offline streaming transcription (lighter)
"""
import json

import numpy as np

from core.hf_utils import remove_broken_hf_snapshot, reset_hf_offline_flags


class WhisperSTT:
    """Offline transcription using faster-whisper."""

    def __init__(self, model_name: str = "base", language: str | None = None):
        import os

        from faster_whisper import WhisperModel
        print(f"[STT] Loading Whisper '{model_name}'…")
        try:
            import ctranslate2
            device  = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            compute = "float16" if device == "cuda" else "int8"
        except Exception:
            device, compute = "cpu", "int8"

        # ctranslate2 scales poorly past a handful of threads for int8 CPU
        # inference — measurements on an 8-core box showed 4 threads beating
        # 8 by ~25% (0.75s vs 1.08s for an 8.6s utterance), because the extra
        # threads spend their time synchronising rather than decoding.
        # Capping at 4 also leaves the machine responsive for the UI and TTS.
        _threads = max(1, min(4, os.cpu_count() or 4))
        if device == "cuda":
            # The GPU does the decoding; extra CPU threads only help the
            # audio pre-processing.
            _threads = max(1, os.cpu_count() or 4)

        try:
            self._model = WhisperModel(
                model_name, device=device, compute_type=compute, cpu_threads=_threads,
            )
        except Exception as _first_err:
            # Offline flag set but model not cached yet → download once, then offline forever
            _e = str(_first_err).lower()
            if any(k in _e for k in ("offline", "not found", "cache", "localentry", "does not exist", "unable to open file", "model.bin")):
                print(f"[STT] '{model_name}' cache is incomplete or offline — refreshing the model download…")
                reset_hf_offline_flags()
                removed = remove_broken_hf_snapshot(model_name)
                if removed:
                    print(f"[STT] Removed broken cache snapshot(s): {', '.join(removed)}")
                self._model = WhisperModel(
                    model_name, device=device, compute_type=compute, cpu_threads=_threads,
                )
            else:
                raise

        self._language = None if (not language or language.strip().lower() == "auto") else language.strip().lower()
        # Language auto-detection costs ~100-200 ms per utterance; cache the
        # detected language and reuse it as a hint on the next turn.
        self._detected_language: str | None = None
        print(f"[STT] Whisper '{model_name}' ready ({device}, {_threads} threads)")

        # Warm the graph up so the FIRST real utterance is not slower than
        # the rest — ctranslate2 builds its decoder kernels lazily, which
        # otherwise costs a few hundred ms on the first transcription.
        try:
            self.transcribe(np.zeros(16000, dtype=np.float32))
        except Exception:
            pass

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe a float32 mono 16 kHz numpy array. Returns transcript string."""
        try:
            # vad_filter=False: the outer energy VAD (core/vad_buffer.py) has
            # already trimmed leading/trailing silence — running Silero's VAD
            # again on the trimmed buffer is redundant CPU work per turn.
            segments, info = self._model.transcribe(
                audio,
                language=self._language or self._detected_language,
                beam_size=1,                       # greedy — 2-3x faster
                best_of=1,
                condition_on_previous_text=False,  # no hallucinations, faster
                without_timestamps=True,           # skip timestamp decoding
            )
            if self._language is None and info is not None and getattr(info, "language", None):
                self._detected_language = info.language
            return " ".join(s.text for s in segments).strip()
        except Exception as e:
            print(f"[STT] Transcription error: {e}")
            raise


class VoskSTT:
    """Streaming transcription using Vosk."""

    def __init__(self, model_path: str | None = None, language: str = "en-us"):
        from vosk import KaldiRecognizer, Model
        print("[STT] Loading Vosk model…")
        if model_path:
            model = Model(model_path)
        else:
            lang  = language.strip().lower() if language and language.strip().lower() != "auto" else "en-us"
            model = Model(lang=lang)
        self._rec = KaldiRecognizer(model, 16000)
        print("[STT] Vosk ready.")

    def process_chunk(self, audio_bytes: bytes) -> tuple[str, bool]:
        """Feed raw int16 LE PCM bytes. Returns (text, is_final)."""
        if self._rec.AcceptWaveform(audio_bytes):
            result = json.loads(self._rec.Result())
            return result.get("text", ""), True
        partial = json.loads(self._rec.PartialResult())
        return partial.get("partial", ""), False
