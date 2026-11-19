# REVIEW — skeptical self-review of this session's work

**Verdict: NOT READY**

1. Two blockers make the advertised voice features non-functional in the live path (deadlocking latency logger, state machine never driven), and Google token refresh never triggers.
2. Multi-account GUI buttons delete/sync the *wrong* account, and `forget("")` wipes the whole fact store — data-destructive bugs.
3. Docs and dashboard contain stale numbers/keys and the runner masks failures; 5 tests still fail.

Review date: 2026-11-19. No fixes were applied during this review.

## Tooling note

`ocr` was installed (`npm i -g @alibaba-group/open-code-review`, binary at `~/.local/node-v24.../bin/ocr`) but could not run:

```
Error: resolve LLM endpoint: no valid LLM endpoint configured; one of
OCR_LLM_URL/OCR_LLM_TOKEN/OCR_LLM_MODEL, ~/.opencodereview/config.json, or
ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN/ANTHROPIC_MODEL must be set
```

So the "independent" OCR pass did not happen. All findings below were produced by direct commands and file reads in this session, with the command/output quoted as evidence.

## 1. Requirements checklist

| Requested | Status | Evidence / location |
|---|---|---|
| Google OAuth installed-app flow, loopback, PKCE | done | `core/google_auth.py:22` (SCOPES), `:217` (`run_oauth`), `:236-248` |
| Multi-account add/remove/list | done with bug | `core/google_service.py:35-56`; bug CR-4 in `core/google_overlay.py:167,172` |
| Refresh token in keyring, encrypted fallback | implemented, refresh broken | `core/google_auth.py:store_token/load_token`; CR-3 |
| fetch userinfo email/name | done | `core/google_auth.py:fetch_userinfo` |
| Gmail read-only scope | done | `core/google_auth.py:26` `gmail.readonly` |
| Gmail list/get/search, pagination, historyId, backoff | partial | `core/google_service.py:100-175`; HI-1, HI-2 |
| FTS5 local cache | done | `core/gmail_store.py`; FTS MATCH verified working by reviewer agent |
| Accounts GUI with signals/workers | done with bug | `core/google_overlay.py`; CR-4 |
| Four LLM email tools | done | `core/google_tools.py`, `core/tools/declarations.py`, `executor.py:436+` |
| Continuous listening + wake word + follow-up | partial/broken | `core/voice_loop.py`; CR-2, HI-5 |
| VAD endpointing | implemented | `core/voice_loop.py:38` (energy), Silero optional; tested |
| Streaming STT/TTS, sentence split, barge-in | pre-existing streaming; barge-in broken | `core/jarvis_tts.py:95-115`, CR-2 |
| Persona file + spoken/display split | done | `persona.md`, `core/persona.py`, `jarvis_llm.py:_speak_and_show` |
| SQLite memory: short/long/episodic + extraction | done with bug | `core/memory_store.py`; HI-4 |
| GUI Memory tab + "forget that" | done with bug | `core/memory_overlay.py`, `executor.py:436-438`, HI-4 |
| Initiative engine + anti-annoyance | implemented, disconnected from live state | `core/initiative_engine.py:66-117`; CR-2 |
| State machine module + tests | module + tests exist, not wired | `core/conversation_state.py`, tests; CR-1, CR-2 |
| Pluggable STT/TTS/VAD/LLM behind config | partial (VAD only) | `core/voice_loop.py:116-121`; STT/TTS still hardwired |
| Latency logging per stage | broken | CR-1, HI-6 |
| Graceful degradation | tested with mocks | `tests/integration/test_fallbacks.py`; real mic/network UNVERIFIED |
| Privacy: no cloud before wake, no raw audio | code-level done, runtime UNVERIFIED | `allow_cloud_before_wake` default false; mic hardware test needed |
| Full audit + AUDIT.md | done, numbers stale | `AUDIT.md:7-9`; MD-5 |
| Test suite + TESTS.md | done, coverage 31.8% | `TESTS.md`; real number confirmed |
| index.html dashboard + run_tests.py | works, with bugs | MD-1, MD-2, MD-7 |

No `TODO`, `FIXME` or `NotImplementedError` found in the new modules (grep returned empty).

## 2. Findings

| ID | Severity | File:line | What is wrong | Evidence (command / output) | Proposed fix | Effort |
|---|---|---|---|---|---|---|
| CR-1 | critical | `core/conversation_state.py:121,128-133` | `LatencyLog._lock` is `threading.Lock()` and `mark()` calls `begin_turn()` while holding it → self-deadlock on first mark | probe: `t=Thread(target=lambda: log.mark('VAD_END')); t.join(1); print(t.is_alive())` → `True`; `begin_turn()`/`finish()` never called in production (grep) | use `RLock` or inline init; call begin/finish in live path | trivial |
| CR-2 | critical | `core/jarvis_core.py:60,181,218-227`; `core/voice_loop.py:147,158,190-199` | `ConversationState` is never transitioned by the live pipeline: stays `IDLE`; barge-in always returns False; continuous loop never feeds VAD; initiative "in conversation" guard bypassed | grep: only `barge_in()` call in prod; no `.transition(` in jarvis_core/llm/tts/stt | drive state from real pipeline and mirror `_speaking`/`ui.state` | medium |
| CR-3 | critical | `core/google_service.py:67-76` | `Credentials(...)` built without `expiry=` → `expired` always False → refresh branch dead | probe: `Credentials(token='OLD', refresh_token='R', ...)` → `expiry=None expired=False` | pass parsed `expiry` from stored token; handle 401 with refresh+retry | small |
| CR-4 | critical | `core/google_overlay.py:167,172` | Late-binding lambdas: every Sync/Remove button acts on the last account | code: `lambda: self._sync(account.email)` inside `for account in …`; probe of same pattern → all calls return last value | `lambda acc=account: self._sync(acc.email)`; add 2-account UI test | trivial |
| HI-1 | high | `core/google_service.py:144-154` | Initial sync stores `history_id=""` → incremental sync never activates | `set_sync_state(self.email, "")` at end of initial sync; `if incremental and history_id:` never true | fetch `users().getProfile()` and store its `historyId` | small |
| HI-2 | high | `core/google_service.py:159-175` | history().list ignores `nextPageToken`, stores cursor after page 1; no 404→full-sync fallback; only `messageAdded` → deletes/labels never update | code read; bundled discovery says 404 requires full sync | paginate, advance cursor last, catch 404, handle deletes/labels | medium |
| HI-3 | high | `core/google_service.py:77-79` | Rotated refresh token not persisted | `token["token"]`/`["expiry"]` updated, `["refresh_token"]` not; google-auth rotates it | store `creds.refresh_token` too | trivial |
| HI-4 | high | `core/memory_store.py:170-173`; `executor.py:436-438` | `forget("")` / whitespace deletes every fact; substring matching deletes unrelated facts; "forget my name" matches nothing | probe: 2 facts → `forget('')` → "Forgot 2" → 0 left | reject empty subject; delete by exact key/id; GUI use `delete_fact(id)` | small |
| HI-5 | high | `core/voice_loop.py:133,153` | `self._detector=None` never assigned → wake word gets no audio in continuous mode; mute/sleep not honored by continuous callback | grep: only assignment in `__init__`; legacy STT feeds detector but isn't started in continuous mode | feed global detector in callback; add muted/sleeping gates | small |
| HI-6 | high | `core/conversation_state.py:136-151`; `jarvis_core.py:204-214` | `latency.log` never written (finish() unused); RESPONSE_END marks enqueue, not playback end | grep: no production `finish()`; docs claim otherwise | flush at TTS completion, move mark there | small |
| MD-1 | medium | `run_tests.py:162` | Runner returns 0 even when pytest returns 1 → CI masks failures | `exit_code=1` in results, process exit 0 | `return code` | trivial |
| MD-2 | medium | `run_tests.py:149,158` | `test-results.json` written before history is updated with current run → history always one run late; UI never fetches `test-history.json` | code lines quoted; dashboard reads `DATA.history` only | compute history before writing both | trivial |
| MD-3 | medium | `requirements.txt` | No pytest/pytest-cov/pytest-json-report/pytest-qt/pytest-asyncio → fresh install cannot run documented tests | grep returns nothing; `AUDIT.md:14` admits manual pip install | add pinned test deps | trivial |
| MD-4 | medium | `VOICE_SETUP.md:20` | Docs say `whisper_model`; real key is `stt_model` (`core/jarvis_config.py:17,22`); defaults differ (tiny vs base) | grep both | fix doc, align defaults | trivial |
| MD-5 | low | `AUDIT.md:7-8`, `TESTS.md:8-9` | Stale numbers: ruff now 1121 (doc 1119), mypy 254 (doc 258), covered 8547/missing 18314 (doc 8546/18315) | ruff/mypy runs above; coverage.json read | re-run and update | trivial |
| MD-6 | medium | `requirements.txt:13,23,29` | `pillow` conflict with browser-use pin (12.3.0); `laya` pulls multi-GB CUDA torch transitively | `pip check` output quoted; fresh install died on disk quota | pin/drop browser-use; document CUDA footprint | medium |
| MD-7 | low | `index.html:182`, `run_tests.py:61-73` | Audit panel counts only *fixed* issues and labels them as current | counts {1,13,6,3} come from "Issues found and fixed" table | relabel or count open items | trivial |
| LO-1 | low | combined pytest invocation | One combined run crashed with a core dump at ~69%; all groups pass individually and a rerun passed | observed once: `timeout: the monitored command dumped core`; isolated reruns green | reproduce under `faulthandler`; likely Qt/library lifecycle – root cause UNVERIFIED | medium |

## 3. Earlier claims that were wrong or exaggerated

- "Voice loop / barge-in / state machine implemented and testable" — module and tests exist, but the live pipeline never drives the state; barge-in cannot fire, continuous mode cannot hear (CR-2, HI-5).
- "Latency logging per stage to `memory/latency.log`" — the first call deadlocks and `finish()` is never called, so the file is never written (CR-1, HI-6).
- "Incremental sync using historyId" — never activates after the initial sync (HI-1); history pagination/404 handling also incomplete (HI-2).
- "Multi-account GUI" — with two accounts, Remove/Sync act on the last one (CR-4).
- "Refresh tokens automatically refreshed" — the refresh branch is unreachable with the constructed credentials (CR-3).
- "Full code audit and fixes" — the audit did not catch the deadlock/disconnected state token/expiry bugs; its tool counts are already stale (MD-5).
- "Dashboard works offline" — it needs an HTTP server because it uses `fetch()`; opening via `file://` shows instructions, not results (browser test: file:// blocked).
- Accurate claims: coverage **31.8%**, **605 passed / 5 failed**, 28+ new tests, no XSS in dashboard (verified), missing/malformed results show clear messages (verified).

## 4. Manual test checklist (UNVERIFIED — requires hardware/real accounts)

1. Real Google login with **two** accounts: add both, check Accounts panel rows and that Remove targets the correct one (CR-4 currently predicts failure).
2. Wait >1 h for access-token expiry, then trigger a Gmail sync; confirm auto-refresh and that the rotated refresh token is stored (CR-3, HI-3 currently predict failure).
3. Real microphone + speakers: continuous listening, wake word from cold start, follow-up window, echo mute, barge-in while TTS plays (CR-2/HI-5 currently predict failure).
4. Wake word in a noisy room; tune `endpointing_ms` and wake sensitivity; confirm the mic indicator matches actual capture.
5. Long-session stability (8 h): thread/audio-stream/DB handle leaks, memory growth, scheduler drift.
6. Memory persistence: add facts, restart Jarvis, confirm `memory.db` survives and recall works; test "forget that exam" and "forget my name".
7. Proactive limits in real use: quiet hours, DND, max/hour, cooldown after "not now", no interruption while speaking.
8. Fresh environment install: blocked here by **disk quota exceeded** (`[Errno 122]`) — retry on a machine with quota, then run `python3 run_tests.py`.

## 5. Top 5 risks — fix order

1. **CR-1 latency deadlock** — one-line lock change; blocks every live LLM/TTS turn.
2. **CR-3 token expiry + HI-3 rotated refresh token + HI-1/HI-2 history sync** — makes multi-account Gmail silently stop working; fix as one unit.
3. **CR-4 late-binding lambdas + HI-4 `forget("")`** — data-destructive; trivial fixes, add regression tests.
4. **CR-2 wire ConversationState into live pipeline + HI-5 feed wake detector** — required for the whole voice-companion feature to actually work.
5. **MD-1/MD-2/MD-3** — runner masks failures and fresh installs can't run tests; fix before trusting any future dashboard result.

**Waiting for your approval before applying any fixes.**
