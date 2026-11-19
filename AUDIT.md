# AUDIT — Ultron / ATLANTIS
## Summary
| Check | Result |
|---|---|
| Python files reviewed | 224 |
| Total source lines | 55135 |
| ruff | 1134 findings before auto-fix; 15 fixed; 1119 remaining (815 E501, 172 E701, 30 E702, 26 B904, 25 F841, 20 E402, 13 F401, 9 E741, 7 B007, 6 I001, 2 E731, 1 each UP035/UP022/UP017/F541/B905) |
| mypy | 258 errors in 53 of 162 checked files (mostly pre-existing missing annotations / implicit Optional) |
| bandit (core, actions, memory) | High 0, Medium 31, Low 753 (before fixes: High 4) |
| pip-audit | Pillow 12.3.0 resolves from requirements with 23 advisories; fix 13.0.0. Installed 13.0.0, but browser-use 1.0.6 pins ==12.3.0 — see *needs my review* |
| Tests | 624 collected: 605 passed, 5 pre-existing failures, 8 skipped, 6 xfailed (see TESTS.md) |

## Tool availability
- `ruff`, `mypy` from project `.venv`; `bandit`, `pip-audit`, `pytest-qt`, `pytest-asyncio`, `pytest-cov`, `pytest-json-report` installed via pip during this audit.
- The `claude-skills` MCP tools (`find_helpful_skills`, `list_skills`, `read_skill_document`) are **not exposed in this session** (MCP resource discovery returned empty). The built-in `skill` tool was used instead. No MCP calls were fabricated.

## Files reviewed (line by line via automated scan + targeted manual review)

| File | Lines |
|---|---:|
| `actions/__init__.py` | 0 |
| `actions/_lazy_pya.py` | 60 |
| `actions/archive_tools.py` | 34 |
| `actions/books.py` | 95 |
| `actions/browser_control.py` | 1226 |
| `actions/browser_use_agent.py` | 164 |
| `actions/capability_registry.py` | 134 |
| `actions/clipboard_mgr.py` | 75 |
| `actions/code_helper.py` | 520 |
| `actions/comfyui.py` | 304 |
| `actions/computer_control.py` | 722 |
| `actions/computer_settings.py` | 1181 |
| `actions/context_bus.py` | 128 |
| `actions/dashboard.py` | 175 |
| `actions/desktop.py` | 421 |
| `actions/dev_agent.py` | 520 |
| `actions/device_scanner.py` | 320 |
| `actions/dictionary_tools.py` | 129 |
| `actions/doc_tools.py` | 162 |
| `actions/email_reader.py` | 141 |
| `actions/face_recognition.py` | 128 |
| `actions/fast_browser.py` | 48 |
| `actions/fcc_runner.py` | 328 |
| `actions/federation.py` | 191 |
| `actions/file_controller.py` | 883 |
| `actions/file_converter.py` | 479 |
| `actions/file_processor.py` | 836 |
| `actions/file_search.py` | 176 |
| `actions/finance_tracker.py` | 129 |
| `actions/flight_finder.py` | 349 |
| `actions/forensics.py` | 255 |
| `actions/game_updater.py` | 1051 |
| `actions/get_datetime.py` | 20 |
| `actions/get_location.py` | 380 |
| `actions/github_integration.py` | 414 |
| `actions/goal_engine.py` | 147 |
| `actions/google_workspace.py` | 349 |
| `actions/habit_actions.py` | 148 |
| `actions/habit_tracker/__init__.py` | 0 |
| `actions/habit_tracker/analytics.py` | 77 |
| `actions/habit_tracker/database.py` | 74 |
| `actions/habit_tracker/habit.py` | 14 |
| `actions/hash_tools.py` | 46 |
| `actions/hermes_agent.py` | 41 |
| `actions/image_edit.py` | 33 |
| `actions/install_tool.py` | 131 |
| `actions/intent_router.py` | 2363 |
| `actions/jobs.py` | 72 |
| `actions/maps.py` | 124 |
| `actions/math_solver.py` | 60 |
| `actions/media_downloader.py` | 38 |
| `actions/mega_router.py` | 124 |
| `actions/monitor_manager.py` | 101 |
| `actions/network_discovery.py` | 145 |
| `actions/network_tools.py` | 24 |
| `actions/news_pro.py` | 40 |
| `actions/news_reader.py` | 72 |
| `actions/notes_tools.py` | 73 |
| `actions/obsidian_vault.py` | 449 |
| `actions/open_app.py` | 708 |
| `actions/opencode_launcher.py` | 144 |
| `actions/package_manager.py` | 239 |
| `actions/particle_sphere.py` | 127 |
| `actions/pdf_reader.py` | 101 |
| `actions/process_mgr.py` | 44 |
| `actions/project_init.py` | 458 |
| `actions/project_scaffold.py` | 203 |
| `actions/projectinitializer.py` | 705 |
| `actions/public_apis.py` | 152 |
| `actions/qr_tools.py` | 79 |
| `actions/random_number.py` | 21 |
| `actions/random_tools.py` | 45 |
| `actions/read_email.py` | 112 |
| `actions/realtime_tutor/backend/main.py` | 249 |
| `actions/realtime_tutor.py` | 111 |
| `actions/relationship_graph.py` | 195 |
| `actions/reminder.py` | 338 |
| `actions/remote_control.py` | 184 |
| `actions/screen_explain.py` | 188 |
| `actions/screen_processor.py` | 478 |
| `actions/screen_reader.py` | 206 |
| `actions/screen_vision.py` | 17 |
| `actions/screenshot_ocr.py` | 85 |
| `actions/security_vault.py` | 109 |
| `actions/send_message.py` | 274 |
| `actions/set_language.py` | 81 |
| `actions/stock_market.py` | 84 |
| `actions/stock_prices.py` | 71 |
| `actions/sys_tool.py` | 157 |
| `actions/system_health.py` | 29 |
| `actions/system_info.py` | 55 |
| `actions/system_info_tools.py` | 79 |
| `actions/task_graph.py` | 134 |
| `actions/task_manager.py` | 223 |
| `actions/timer_scheduler.py` | 256 |
| `actions/todo_display.py` | 278 |
| `actions/translator.py` | 28 |
| `actions/unit_converter.py` | 199 |
| `actions/voice_calls.py` | 157 |
| `actions/wake_word.py` | 170 |
| `actions/weather_report.py` | 113 |
| `actions/web_search.py` | 119 |
| `actions/wiki_tools.py` | 25 |
| `actions/youtube_video.py` | 577 |
| `agent/agent_manager.py` | 206 |
| `agent/error_handler.py` | 149 |
| `agent/executor.py` | 395 |
| `agent/planner.py` | 213 |
| `agent/task_queue.py` | 222 |
| `config/__init__.py` | 19 |
| `conftest.py` | 5 |
| `conv_config.py` | 46 |
| `conversation.py` | 339 |
| `core/__init__.py` | 1 |
| `core/audio_consts.py` | 6 |
| `core/chat_history.py` | 122 |
| `core/companion_settings.py` | 92 |
| `core/conversation_state.py` | 151 |
| `core/conversation_style.py` | 12 |
| `core/decision_engine.py` | 372 |
| `core/events.py` | 28 |
| `core/fast_browser.py` | 310 |
| `core/gmail_store.py` | 300 |
| `core/google_auth.py` | 349 |
| `core/google_overlay.py` | 215 |
| `core/google_service.py` | 176 |
| `core/google_tools.py` | 103 |
| `core/hf_utils.py` | 51 |
| `core/initiative_engine.py` | 249 |
| `core/installer.py` | 138 |
| `core/jarvis_config.py` | 84 |
| `core/jarvis_core.py` | 528 |
| `core/jarvis_general.py` | 136 |
| `core/jarvis_llm.py` | 530 |
| `core/jarvis_memory.py` | 207 |
| `core/jarvis_profile.py` | 133 |
| `core/jarvis_prompt.py` | 177 |
| `core/jarvis_script_lang.py` | 45 |
| `core/jarvis_stt.py` | 161 |
| `core/jarvis_tts.py` | 115 |
| `core/jarvis_utils.py` | 194 |
| `core/jarvis_vision.py` | 81 |
| `core/lifecycle.py` | 258 |
| `core/llm_client.py` | 1085 |
| `core/llm_provider_detector.py` | 324 |
| `core/mail_client.py` | 759 |
| `core/mail_overlay.py` | 880 |
| `core/memory_overlay.py` | 108 |
| `core/memory_store.py` | 225 |
| `core/ollama_models.py` | 171 |
| `core/ollama_models_overlay.py` | 336 |
| `core/paths.py` | 58 |
| `core/persona.py` | 65 |
| `core/proactive.py` | 248 |
| `core/provider_overlay.py` | 641 |
| `core/remote_api.py` | 432 |
| `core/safe_math.py` | 54 |
| `core/scheduler.py` | 193 |
| `core/startup_progress.py` | 152 |
| `core/stt.py` | 115 |
| `core/tools/__init__.py` | 1 |
| `core/tools/declarations.py` | 1628 |
| `core/tools/executor.py` | 1859 |
| `core/tts.py` | 557 |
| `core/vad_buffer.py` | 61 |
| `core/voice_loop.py` | 208 |
| `core/workflows.py` | 147 |
| `gws_bridge.py` | 208 |
| `idea_bar.py` | 115 |
| `main.py` | 179 |
| `memory/__init__.py` | 1 |
| `memory/config_manager.py` | 40 |
| `memory/db_vector_store.py` | 180 |
| `memory/memory_manager.py` | 375 |
| `memory/vector_memory.py` | 330 |
| `pc_bridge.py` | 939 |
| `skills/__init__.py` | 1 |
| `skills/skill_loader.py` | 95 |
| `stt.py` | 48 |
| `test-yourself/app/__init__.py` | 0 |
| `test-yourself/app/config.py` | 12 |
| `test-yourself/app/crud.py` | 168 |
| `test-yourself/app/database.py` | 177 |
| `test-yourself/app/main.py` | 97 |
| `test-yourself/app/models.py` | 85 |
| `test-yourself/tests/__init__.py` | 0 |
| `test-yourself/tests/conftest.py` | 11 |
| `tests/conftest.py` | 42 |
| `tests/test_all.py` | 498 |
| `tests/test_browser_use_routing.py` | 60 |
| `tests/test_chat_copy.py` | 17 |
| `tests/test_conversation_memory.py` | 98 |
| `tests/test_conversation_state.py` | 67 |
| `tests/test_decision_engine.py` | 230 |
| `tests/test_deep.py` | 831 |
| `tests/test_fd_search.py` | 49 |
| `tests/test_features.py` | 801 |
| `tests/test_file_controller_safety.py` | 115 |
| `tests/test_final.py` | 18 |
| `tests/test_gmail_parsing.py` | 78 |
| `tests/test_google_service.py` | 114 |
| `tests/test_hard.py` | 288 |
| `tests/test_hard2.py` | 364 |
| `tests/test_hard3.py` | 192 |
| `tests/test_hard4.py` | 170 |
| `tests/test_headless_dispatch.py` | 74 |
| `tests/test_hf_offline_reset.py` | 32 |
| `tests/test_initiative_engine.py` | 75 |
| `tests/test_mail_client.py` | 370 |
| `tests/test_mail_overlay.py` | 117 |
| `tests/test_market_and_youtube_routing.py` | 151 |
| `tests/test_memory_store.py` | 62 |
| `tests/test_mute_latency.py` | 25 |
| `tests/test_new_features.py` | 99 |
| `tests/test_open_mail_intent.py` | 62 |
| `tests/test_persona.py` | 39 |
| `tests/test_provider_overlay.py` | 64 |
| `tests/test_remote_api.py` | 224 |
| `tests/test_tool_declarations.py` | 33 |
| `tests/test_vector_db.py` | 61 |
| `tests/test_voice_loop.py` | 39 |
| `tests/test_wake_and_idle.py` | 91 |
| `tts.py` | 72 |
| `ui.py` | 3797 |

## Issues found and fixed

| File:line | Severity | Issue | Fix |
|---|---|---|---|
| actions/wake_word.py:69-73 | Critical | Mic gives 2-D (1024,1) chunks; openwakeword needs flat 1-D int16 >=400 samples. ONNX Conv_3 spam ~10x/s. | Flatten with reshape(-1), int16 conversion, skip chunks <400 samples. |
| actions/wake_word.py:55 | High | Model key mismatch: code read "hey_jarvis", actual key "hey_jarvis_v0.1" — wake word never fired. | Derive key from loaded model keys. |
| core/lifecycle.py:240-246 | High | Shutdown emitted ui._win._quit_sig on a MainWindow (no _win) then os._exit(0), leaking semaphores. | Resolve quit signal defensively, fall back to QApplication.quit(); no hard exit. |
| ui.py:2708 | High | closeEvent passed MainWindow instead of JarvisUI adapter to shutdown(). | Call shutdown(ui=None). |
| core/tools/executor.py:593 | High | calculate tool called safe_math(parameters=args) — TypeError for every call. | Use calculate(args.get("expression","")). |
| actions/browser_use_agent.py:136-138 | Medium | Event loop closed before browser.close() — Chromium leaked. | Close browser before loop.close(); clear event loop. |
| core/jarvis_memory.py:185 | Low | Conversation recall read key "timestamp" but store writes "created" — blank dates. | Use "created". |
| core/scheduler.py:34-35 | High | Unguarded Prefect import in start() could abort app startup. | try/except fallback to direct execution. |
| core/scheduler.py:137 | High | Malformed next_run killed the scheduler thread permanently. | Per-job try/except; disable invalid jobs. |
| core/scheduler.py:151 | Medium | One-shot schedules repeated forever. | Disable job after first run for once/one-time. |
| actions/intent_router.py:588-594 | Medium | browse/research patterns scored 1.0 and hijacked local file/YouTube requests. | Negative lookahead for local nouns. |
| actions/file_controller.py:371 | High | rename_file never validated new_name — path traversal. | Reject separators/..; validate new path. |
| actions/file_controller.py:666 | High | extract() created destination before safe-path check. | Validate before mkdir; tarfile filter="data". |
| actions/file_controller.py:689-712 | High | download() mkdir before validation; unsanitized URL/Content-Disposition filename; arbitrary schemes/SSRF. | Validate scheme/path; Path(name).name sanitization; http(s) only. |
| actions/install_tool.py:72,109 | High | Unknown tool name flowed into shell=True apt command — command injection. | Allowlist aliases; shlex.split + shell=False; separate apt update. |
| actions/sys_tool.py:143 | High | LLM args concatenated into shell=True command. | shlex.split + shell=False. |
| actions/device_scanner.py:48 | Low | shell=True on fixed literal commands (bandit B602). | Justified nosec with comment: no user input. |
| actions/file_controller.py:678 | Low | zipfile.extractall flagged by bandit B202. | Justified nosec with comment: zipfile sanitizes member paths. |
| core/decision_engine.py | High | Jev HTTP client with API key and no configured key. | Replaced entirely with local Laya decision model. |
| core/chat_history.py, lifecycle.py, main.py | Medium | Chat history not persisted/replayed. | JSON history, shutdown flush, startup replay. |
| core/vector_memory.py, db_vector_store.py | High | JSON-only vector store with permanent embedder disable. | sqlite-vec DB + local fastembed fallback + migration. |
| core/google_*.py | Medium | No Google/Gmail support. | Added OAuth PKCE, multi-account manager, Gmail cache/tools/GUI. |
| core/conversation_state.py, voice_loop.py, persona.py, memory_store.py, initiative_engine.py | Medium | No companion behaviour. | Added state machine, voice loop, persona, SQLite memory, initiative engine. |

## Remaining tool findings (not silently ignored)

- **ruff 1119**: 815 E501 (line length), 172 E701, 30 E702, 26 B904, 25 F841, 20 E402, 13 F401, 9 E741, 7 B007, 6 I001, 2 E731, and 5 single-rule findings. These are pre-existing style/import-order findings across 53 legacy files. Reformatting all of them would produce unrelated churn and is listed under *needs my review*. No blanket `# noqa` was added.
- **mypy 258**: mostly missing annotations/implicit Optional in legacy modules. All newly added modules are mypy-clean (verified individually).
- **bandit Medium 31 / Low 753**: mostly B404/B603 subprocess wrappers and assert/try-except patterns in legacy code; high-severity findings are all fixed.
- **pip-audit**: see needs-my-review.

## Needs my review

1. **Pillow / browser-use conflict** — Pillow 13.0.0 fixes 23 CVEs but `browser-use 1.0.6` and `browser-harness 0.1.13` pin `pillow==12.3.0`. Installed 13.0.0; `pip-audit -r requirements.txt` still resolves 12.3.0. Options: drop browser-use (and heavy browser tasks) or accept the CVEs. No silent pin was changed.
2. **Legacy style findings** — 1119 ruff / 258 mypy findings above. Bulk auto-format is available but touches ~50 unrelated files.
3. **Unauthenticated WebSocket bridge** — `pc_bridge.py` binds 0.0.0.0:8765 with no auth; token-based auth would require changing the Android app. Not changed silently.
4. **Arbitrary code tools** — `run_command`/`run_python`/`opencode_run` remain executable by the LLM with no confirmation gate. Adding a gate changes user-visible behaviour.
5. **Real personal data in git** — `config/user_profile.json`, `memory/long_term.json`, `memory/vector_store.json` contain real data and are tracked. History scrub needs user decision.

## Verification commands

```bash
.venv/bin/ruff check .
.venv/bin/mypy --explicit-package-bases core actions memory --follow-imports=skip
bandit -r core actions memory -x tests,.venv
pip-audit -r requirements.txt
python3 -m pytest -q
```
