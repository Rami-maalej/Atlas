# TESTS — Ultron / ATLANTIS

## Real coverage (measured, not estimated)

`python3 -m pytest --cov=core --cov=actions --cov=memory --cov=ui --cov=main --cov=pc_bridge`:

- Statements: 26861
- Covered: 8546
- Missing: 18315
- **Line coverage: 31.8%** (target 85% — **not met**)
- Result: 605 passed, 5 pre-existing failures, 8 skipped, 6 xfailed.

The gap is concentrated in legacy UI/OS-integration code (see below). Adding tests for those requires hardware mocks and a large surface; no coverage number was fabricated.

## Test matrix

| Feature | Test files | Status |
|---|---|---|
| Google OAuth / accounts | tests/test_google_service.py, tests/core/test_google_oauth_more.py | covered (mocked) |
| Gmail client & parsing | tests/test_gmail_parsing.py, tests/core/test_gmail_client.py | covered (mocked) |
| SQLite layers | tests/test_vector_db.py, tests/memory/test_sqlite_layers.py, tests/test_memory_store.py | covered |
| Voice pipeline | tests/test_conversation_state.py, tests/test_voice_loop.py, tests/test_wake_and_idle.py | covered (mocked) |
| LLM / tools | tests/core/test_llm_pipeline.py, tests/test_decision_engine.py, tests/test_tool_declarations.py | partially covered |
| Persona / style | tests/test_persona.py, tests/gui/test_widgets.py | covered |
| Memory & forget | tests/test_memory_store.py, tests/test_conversation_memory.py | covered |
| Initiative engine | tests/test_initiative_engine.py | covered |
| PyQt6 GUI | tests/gui/test_widgets.py, tests/test_chat_copy.py | partially covered |
| Security | tests/security/test_logs_and_injection.py, tests/test_file_controller_safety.py, tests/test_remote_api.py | partially covered |
| Config / fallbacks | tests/integration/test_fallbacks.py, tests/test_provider_overlay.py | partially covered |
| Browser automation | tests/test_browser_use_routing.py | partially covered |

## Untested code and reasons

- `ui.py`: 19.5% covered, 2022 lines missing — PyQt6 rendering/state handlers; needs qtbot snapshots and a real display for full coverage.
- `core/tools/executor.py`: 25.3% covered, 1025 lines missing — ~100 tool branches, most require OS/network side effects; only dispatched branches tested.
- `actions/browser_control.py`: 12.6% covered, 693 lines missing — Live Playwright browser; requires browser binary and network.
- `actions/game_updater.py`: 7.0% covered, 681 lines missing — External game launcher/Steam integration.
- `actions/computer_settings.py`: 12.6% covered, 673 lines missing — OS-specific settings (Windows/macOS paths unreachable on Linux).
- `actions/file_processor.py`: 3.9% covered, 597 lines missing — Third-party converters and optional binaries.
- `core/llm_client.py`: 22.0% covered, 495 lines missing — Many cloud provider adapters; mocked transport tested, provider-specific paths not.
- `actions/file_controller.py`: 30.1% covered, 431 lines missing — OS file operations beyond the safety-critical paths.
- `actions/projectinitializer.py`: 13.8% covered, 392 lines missing — Code-generation scaffolds (string templates).
- `core/jarvis_core.py`: 0.0% covered, 374 lines missing — Full assistant orchestration needs mic/TTS/LLM; state machine tested separately.
- `actions/computer_control.py`: 20.2% covered, 367 lines missing — GUI automation (pyautogui) and shell paths.
- `actions/youtube_video.py`: 14.3% covered, 323 lines missing — External YouTube URL launching.

## Markers and commands

```bash
# everything (offline, mocked)
python3 -m pytest -q
# only fast unit tests
python3 -m pytest -q -m "not slow and not network and not hardware and not integration"
# GUI widgets only (offscreen)
python3 -m pytest -q -m gui
# coverage + machine-readable results
python3 run_tests.py
```

Markers configured in `pyproject.toml`: `qt`, `network`, `slow`, `hardware`, `integration`, `gui`.
Five known pre-existing failures: 3 file-converter tests (img2pdf missing), 1 face-cascade test (no cascade file), 1 cached-identity test.
