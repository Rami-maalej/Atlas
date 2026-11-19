# Voice / companion setup

Everything runs locally by default. No audio is sent to the cloud before the
wake word fires, and raw audio is never stored unless you enable it.

## 1. Microphone

- Fedora: `sudo dnf install portaudio-devel libsndfile-devel`, then
  `pip install sounddevice` (already in `requirements.txt`).
- Test the mic: `python -c "import sounddevice as sd; print(sd.query_devices())"`.
- Set the correct input device in your system sound settings. If Jarvis hears
  himself, keep the "Voice" → continuous listening toggle off and use push-to-
  talk, or lower speaker volume. The mic is gated while he speaks (barge-in
  still works: start talking and he stops).

## 2. Models to download

- **STT**: faster-whisper downloads its model on first use. `tiny` / `base` are
  fastest on CPU and support English, French and Arabic with auto-detection.
  Set `whisper_model` in `config/api_keys.json` (default handled by `core/stt.py`).
- **TTS**: EdgeTTS is streaming and needs no local model (internet required).
- **Wake word**: openwakeword's bundled `hey_jarvis` ONNX model is installed
  with the package — nothing to download. Change `wake_word` in config if you
  want a different alias.
- **VAD (optional)**: the built-in energy VAD needs no model. For Silero VAD,
  download `silero_vad.onnx` and set `vad_provider: "silero"` and
  `vad_model: "/path/to/silero_vad.onnx"` in `config/api_keys.json`.

## 3. Tuning

All settings live under **Voice** in the GUI and in `config/api_keys.json`:

| Key | Meaning | Default |
|---|---|---|
| `continuous_listening` | Keep mic open with wake word | false |
| `voice_conversation_mode` | Keep listening ~12 s after answering | true |
| `follow_up_seconds` | Length of that follow-up window | 12 |
| `endpointing_ms` | Silence before treating speech as finished | 700 |
| `wake_word` | Wake word alias | jarvis |
| `vad_provider` | `energy` or `silero` | energy |
| `max_proactive_per_hour` | Anti-annoyance cap | 3 |
| `quiet_hours_start` / `_end` | No proactive speech window | 22 / 8 |
| `do_not_disturb` | Silence all proactive messages | false |
| `store_raw_audio` | Save audio (off by default) | false |

If he cuts you off mid-sentence, raise `endpointing_ms` to 900–1200. If he
waits too long after you stop, lower it to 400–500. "uh" / "hmm" and trailing
pauses are handled by the follow-up window rather than a hard cut.

## 4. Latency tuning

Per-turn stage timings are written to `memory/latency.log`:
`VAD_END`, `STT_DONE`, `FIRST_LLM_TOKEN`, `FIRST_TTS_AUDIO`, `RESPONSE_END`.
Target under ~1.5 s from VAD_END to FIRST_TTS_AUDIO. A large STT gap means a
smaller Whisper model; a large LLM gap means a smaller/faster LLM.

## 5. Privacy & safety

- Set `allow_cloud_before_wake` to false (default) — cloud STT is never used
  before the wake word.
- The mic-active indicator is the HUD orb: blue = listening, grey = sleeping.
- Proactive messages are read-only. Nothing sends, deletes or buys anything
  without explicit confirmation.
- To forget something: say "forget that exam", or use the **Memory** panel.
- Persona text is editable in `persona.md` (or `config/persona.md` to override).
