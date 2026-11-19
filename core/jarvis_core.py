"""JarvisLocal — slim orchestrator.

This is the *only* place where the assistant's life-cycle lives.
Every feature is now a dedicated module in core/ (see imports below).

Extracted from main.py — same behaviour, zero semantic change.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
import traceback
from typing import Any

from actions.timer_scheduler import set_on_fire as timer_set_callback
from core.jarvis_config import reconfigure as do_reconfigure
from core.jarvis_llm import _process_message as _pm
from core.jarvis_llm import _run_async as _ra
from core.jarvis_prompt import _build_system_prompt, _load_system_prompt
from core.jarvis_script_lang import _auto_switch_language
from core.jarvis_stt import _listen_vosk as _lv
from core.jarvis_stt import _listen_whisper as _lw
from core.jarvis_stt import _text_command_loop as _tcl
from core.jarvis_tts import _tts_synth_worker, set_speaking, speak
from core.jarvis_tts import _tts_worker as _tw
from core.llm_client import ensure_ollama_running, get_llm_provider, warmup_model
from core.scheduler import get_scheduler
from core.tools.executor import execute_tool
from ui import JarvisUI


def _load_config() -> dict:
    from memory.config_manager import load_config as _lc
    return _lc()


class JarvisLocal:
    """
    Main assistant class.
    Replaces JarvisLive (Gemini Live API) with:
      STT (Whisper/Vosk) → Ollama LLM (tool calling) → TTS (Edge/Kokoro/ElevenLabs)
    """
    def __init__(self, ui: JarvisUI):
        self.ui               = ui
        self._config          = _load_config()
        self._stt             = None
        self._tts             = None
        self._tts_ready       = threading.Event()   # set when TTS engine is loaded
        self._speaking        = False
        self._speaking_lock   = threading.Lock()
        self._text_queue:     queue.Queue = queue.Queue()
        self._tts_queue:      queue.Queue = queue.Queue()
        self._tts_play_queue: queue.Queue = queue.Queue()
        self._conversation:   list[dict]  = []
        self._conv_lock = threading.Lock()
        from core.conversation_state import ConversationState, LatencyLog

        self.conversation = ConversationState(on_change=self._on_conversation_change)
        self.latency = LatencyLog()
        self.voice_loop: Any = None
        from core.chat_history import load_chat_history, register_history_provider
        self._conversation = load_chat_history()
        if not self._conversation:
            try:
                from memory.vector_memory import recent_conversations
                for turn in recent_conversations(limit=5):
                    user_text = str(turn.get("user", "")).strip()
                    assistant_text = str(turn.get("assistant", "")).strip()
                    if user_text and assistant_text:
                        self._conversation.extend((
                            {"role": "user", "content": user_text},
                            {"role": "assistant", "content": assistant_text},
                        ))
            except Exception:
                pass
        register_history_provider(lambda: list(self._conversation))
        self._generation = 0
        self._processing_lock = threading.Lock()
        self._prefetch_thread = None
        # None (not "") = "not fetched yet" so jarvis_prompt falls back to an
        # inline load instead of silently skipping semantic memory.
        self._prefetched_vec = None
        self._prefetched_skill = None
        from core import events as _events
        self._events = _events
        self._sleep_after = int(self._config.get("sleep_after_seconds", 30) or 30)
        self._last_activity = time.monotonic()
        self._sleeping = False
        self._events.subscribe(self._events.WAKE, self._on_wake_event)
        self._last_intent = None
        self.ui.on_text_command = self._on_text_command
        self._current_language = "en"
        # ── GWS logging ───────────────────────────────────────────────────
        from main import BASE_DIR
        _gws_log_dir = BASE_DIR / "logs"
        _gws_log_dir.mkdir(parents=True, exist_ok=True)
        _gws_handler = logging.FileHandler(str(_gws_log_dir / "gws.log"))
        _gws_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        _gws = logging.getLogger("gws_bridge")
        _gws.addHandler(_gws_handler)
        _gws.setLevel(logging.DEBUG)
        _gws.propagate = False
        # ── Timer / Scheduler callback ──────────────────────────────────────
        logger = logging.getLogger("jarvis")
        def _timer_fired(name_or_msg: str, action: str = "", params: dict = None):
            self.speak(f"{name_or_msg}")
            self.ui.log(f"[Timer] {name_or_msg}")
            p = params or {}
            act = p.get("action", action or "")
            if act in ("shutdown", "restart", "sleep"):
                logger.info("Timer triggered system action: %s", act)
                self.ui.log(f"[Timer] executing: {act}")
                import shlex
                import subprocess
                cmds = {"shutdown": "shutdown -h now", "restart": "shutdown -r now",
                        "sleep": "systemctl suspend"}
                subprocess.Popen(shlex.split(cmds[act]))
            elif act and act not in ("", "speak"):
                logger.info("Running scheduled action: %s", act)
        timer_set_callback(_timer_fired)

    # ------------------------------------------------------------------
    # Speech helpers (used by every core/jarvis_* module)
    # ------------------------------------------------------------------
    def speak(self, text: str) -> None:
        speak(self, text)

    def set_speaking(self, value: bool) -> None:
        set_speaking(self, value)

    # ------------------------------------------------------------------
    # Auto-detect and switch TTS language
    # ------------------------------------------------------------------
    def _auto_switch_language(self, text: str) -> None:
        _auto_switch_language(self, text)

    # ------------------------------------------------------------------
    # Tool execution — thin wrapper around core/tools/executor.py
    # ------------------------------------------------------------------
    def execute_tool(self, name: str, args: dict) -> str:
        return execute_tool(self.ui, name, args, speak=self.speak,
                            run_async=self._run_async)

    # Aliases expected by extracted core/jarvis_llm.py (kept names)
    def _execute_tool(self, name: str, args: dict) -> str:
        return self.execute_tool(name, args)

    def _run_async(self, coro):
        return _ra(coro)

    def _build_system_prompt(self, user_text: str = "") -> str:
        return _build_system_prompt(self, user_text)

    # ------------------------------------------------------------------
    # Text command entry
    # ------------------------------------------------------------------
    def _on_text_command(self, text: str) -> None:
        self._generation += 1  # invalidates any in-flight _process_message with old gen
        self._text_queue.put(text)

    # ------------------------------------------------------------------
    # Reconfiguration (from UI overlay)
    # ------------------------------------------------------------------
    def reconfigure(self, new_config: dict) -> None:
        do_reconfigure(self, new_config)

    # ------------------------------------------------------------------
    # Conversation state mirroring (Phase 1 wiring)
    # ------------------------------------------------------------------
    def _on_conversation_change(self, _old, new) -> None:
        try:
            self.ui.set_state(new.value)
        except Exception:
            pass

    def _begin_turn(self) -> None:
        from core.conversation_state import State

        self.latency.begin_turn()
        self.conversation.transition(State.TRANSCRIBING, force=True)

    def _finish_turn(self) -> None:
        from core.conversation_state import State

        target = (
            State.LISTENING
            if self.voice_loop and self.conversation.in_follow_up_window()
            else State.IDLE
        )
        self.conversation.transition(target, force=True)

    # ------------------------------------------------------------------
    # Proactive initiative (Phase 4)
    # ------------------------------------------------------------------
    def _initiative_loop(self) -> None:
        from core.initiative_engine import InitiativeEngine

        engine = InitiativeEngine()
        while True:
            time.sleep(60)
            try:
                for candidate in engine.collect():
                    ok, _ = engine.gate.allow(candidate, self.conversation)
                    if not ok:
                        continue
                    engine.gate.record_spoken()
                    if candidate.should_notify_only:
                        self.ui.write_log(f"NOTICE: {candidate.message}")
                    else:
                        self.speak(candidate.message)
                    break
            except Exception as e:
                self.ui.write_log(f"ERR: Proactive — {e}")

    # ------------------------------------------------------------------
    # Continuous voice (Phase 1)
    # ------------------------------------------------------------------
    def enable_continuous_voice(self) -> bool:
        """Start mic capture with wake word + follow-up window + barge-in."""
        if self.voice_loop is not None and getattr(self.voice_loop, "_running", False):
            return True
        from core.voice_loop import VoiceLoop

        def _on_utterance(audio, _lang):
            from core.conversation_state import State

            try:
                self.latency.mark("VAD_END")
                if self._stt is None:
                    return
                self.conversation.transition(State.TRANSCRIBING, force=True)
                text = self._stt.transcribe(audio)
                self.latency.mark("STT_DONE")
                if text and text.strip():
                    self.conversation.transition(State.THINKING, force=True)
                    self.process_message(text)
                    if self.voice_loop:
                        self.voice_loop.listen_for_follow_up()
            except Exception as e:
                self.ui.write_log(f"ERR: Voice turn — {e}")
                self.conversation.transition(State.IDLE, force=True)

        def _on_barge_in():
            from core.jarvis_tts import stop_speaking

            stop_speaking(self)
            self.conversation.barge_in()

        self.voice_loop = VoiceLoop(
            self.conversation, self.latency,
            on_utterance=_on_utterance, on_barge_in=_on_barge_in,
        )
        self.voice_loop.muted = lambda: self.ui.muted
        self.voice_loop.sleeping = lambda: self._sleeping
        ok = self.voice_loop.start()
        if ok:
            from core.conversation_state import State
            self.conversation.transition(State.LISTENING, force=True)
            self.ui.write_log("SYS: Continuous voice enabled.")
        return ok

    def disable_continuous_voice(self) -> None:
        if self.voice_loop:
            self.voice_loop.stop()
            self.voice_loop = None
            self.ui.write_log("SYS: Continuous voice disabled.")

    # ------------------------------------------------------------------
    # Wake / idle / persistence
    # ------------------------------------------------------------------
    def persist_history(self) -> None:
        from core.chat_history import save_chat_history
        save_chat_history(list(self._conversation))

    def note_activity(self) -> None:
        self._last_activity = time.monotonic()
        if self._sleeping:
            self._set_awake("activity")

    def _set_awake(self, source: str) -> None:
        if not self._sleeping:
            return
        self._sleeping = False
        from core.conversation_state import State
        self.conversation.transition(State.LISTENING, force=True)
        self._events.emit(
            self._events.STATE, state="LISTENING", awake=True, source=source
        )

    def _on_wake_event(self, ctx=None) -> None:
        self._last_activity = time.monotonic()
        was_sleeping = self._sleeping
        self._set_awake("wake")
        if was_sleeping:
            self.ui.write_log("SYS: Wake word detected — awake.")

    def _idle_watcher(self) -> None:
        while True:
            time.sleep(1)
            if self._sleeping:
                continue
            if time.monotonic() - self._last_activity >= self._sleep_after:
                self._sleeping = True
                from core.conversation_state import State
                self.conversation.transition(State.SLEEP, force=True)
                self.ui.write_log("SYS: Idle — sleeping. Say 'hey Jarvis' to wake me.")
                self._events.emit(self._events.SLEEP)
                self._events.emit(
                    self._events.STATE, state="SLEEP", awake=False
                )

    def _start_wake_word(self) -> None:
        try:
            from actions.wake_word import start_wake_word

            msg = start_wake_word(
                on_wake=lambda: self._events.emit(
                    self._events.WAKE, source="voice"
                )
            )
            self.ui.write_log(f"SYS: {msg}")
        except Exception as e:
            self.ui.write_log(f"ERR: Wake word — {e}")

    # ------------------------------------------------------------------
    # LLM turn (stream + overlapped TTS)
    # ------------------------------------------------------------------
    def process_message(self, user_text: str) -> None:
        self._begin_turn()
        self.note_activity()
        _pm(self, user_text)
        self.persist_history()

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------
    def run(self) -> None:
        """
        Startup strategy — optimised for minimum time-to-interactive:
        1. LLM warmup + STT load  →  parallel, fast (~3s)
        2. TTS load               →  parallel, slow (~20s for Kokoro)
        3. Wait only for (1)      →  go online immediately
        4. TTS finishes in BG     →  queued speech plays automatically
        """
        try:
            self.ui.on_reconfigure = self.reconfigure
            # ── Boot progress ──────────────────────────────────────────────
            # The loading screen shows real progress, so every stage reports
            # into the shared registry as it advances.
            from core.startup_progress import PROGRESS
            # Dynamic welcome — name from profile, fallback to "sir".
            try:
                import json as _json
                from pathlib import Path as _Path
                _profile = _json.loads(
                    (_Path(__file__).resolve().parent.parent / "config" / "user_profile.json")
                    .read_text(encoding="utf-8")
                )
                _who = str(_profile.get("name", "")).strip().split()[0] or "sir"
            except Exception:
                _who = "sir"
            print(f"\n  Welcome {_who} — ATLANTIS is starting up…\n", flush=True)
            self.ui.write_log(f"SYS: Welcome {_who}.")
            PROGRESS.add_many([
                ("config",   "Configuration",       0.5),
                ("provider", "AI provider",         1.5),
                ("memory",   "Memory & vault",      1.5),
                ("stt",      "Speech recognition",  3.0),
                ("llm",      "Language model",      2.0),
                ("tts",      "Voice synthesis",     2.5),
                ("services", "Background services", 1.0),
            ])
            PROGRESS.start("config")
            # ── LLM Server ───────────────────────────────────────────────
            provider = get_llm_provider()
            PROGRESS.update("provider", 0.1, f"checking {provider}")
            self.ui.write_log(f"SYS: Checking {provider}…")
            if ensure_ollama_running():
                self.ui.write_log(f"SYS: {provider} OK.")
                PROGRESS.update("provider", 1.0, "ready")
            else:
                self.ui.write_log(f"ERR: {provider} unavailable.")
                PROGRESS.update("provider", 1.0, "unavailable")
            PROGRESS.finish("provider")
            # ── Config ────────────────────────────────────────────────────
            stt_engine   = self._config.get("stt_engine",   "whisper").lower()
            stt_language = self._config.get("stt_language", "auto")
            stt_model    = self._config.get("stt_model",    "base")
            tts_engine   = self._config.get("tts_engine",   "edgetts").lower()
            PROGRESS.finish("config")
            # ── Memory & vault ────────────────────────────────────────────
            PROGRESS.start("memory", "reading memory")
            try:
                from memory.memory_manager import import_vault_facts
                import_vault_facts()
                PROGRESS.update("memory", 0.8, "memory loaded")
            except Exception:
                pass
            PROGRESS.finish("memory")
            # ── Startup progress panel ────────────────────────────────────
            self.ui.show_startup_panel()
            _warmup_done = threading.Event()
            _stt_done    = threading.Event()
            # ── LLM warmup thread ─────────────────────────────────────────
            def _do_warmup():
                try:
                    PROGRESS.update("llm", 0.2, "warming up")
                    warmup_model(system_prompt=_load_system_prompt())
                    self.ui.write_log("SYS: LLM ready.")
                    PROGRESS.finish("llm")
                except Exception as e:
                    self.ui.write_log(f"ERR: LLM warmup — {e}")
                    PROGRESS.finish("llm", error=True)
                finally:
                    _warmup_done.set()
            # ── STT load thread ───────────────────────────────────────────
            def _do_stt():
                try:
                    self.ui.write_log(f"SYS: Loading {stt_engine.upper()} STT…")
                    PROGRESS.update("stt", 0.15, "loading model")
                    if stt_engine == "vosk":
                        from core.stt import VoskSTT
                        self._stt = VoskSTT(
                            self._config.get("vosk_model_path"),
                            language=stt_language)
                    else:
                        from core.stt import WhisperSTT
                        self._stt = WhisperSTT(stt_model, language=stt_language)
                    PROGRESS.update("stt", 0.85, "warming up")
                    self.ui.write_log("SYS: STT ready.")
                    PROGRESS.finish("stt")
                except Exception as e:
                    self.ui.write_log(f"ERR: STT — {e}")
                    PROGRESS.finish("stt", error=True)
                finally:
                    _stt_done.set()
            # ── TTS load thread — does NOT block going online ─────────────
            def _do_tts():
                try:
                    self.ui.write_log(f"SYS: Loading {tts_engine.upper()} TTS…")
                    PROGRESS.update("tts", 0.15, "loading engine")
                    if tts_engine == "kokoro":
                        self.ui.write_log("SYS: Kokoro — loading model + compiling JIT…")
                        PROGRESS.update("tts", 0.4, "compiling")
                    from core.tts import create_tts_player
                    self._tts = create_tts_player(self._config)
                    self._tts_ready.set()          # unblock _tts_worker
                    self.ui.write_log("SYS: TTS ready.")
                    PROGRESS.finish("tts")
                    PROGRESS.complete()
                    self.ui.set_startup_status("● All systems ready.")
                    self.ui.hide_startup_panel()
                    self.speak(f"Welcome {_who}. I'm online and ready.")
                except Exception as e:
                    traceback.print_exc()
                    self.ui.write_log(f"ERR: TTS — {e}")
                    PROGRESS.finish("tts", error=True)
                    PROGRESS.complete()
                    self._tts_ready.set()
                    self.ui.set_startup_status("● Speech synthesis failed — text mode only.")
                    self.ui.hide_startup_panel()
            # Launch all three simultaneously
            self.ui.write_log("SYS: Loading systems in parallel…")
            threading.Thread(target=_do_warmup, daemon=True).start()
            threading.Thread(target=_do_stt,    daemon=True).start()
            threading.Thread(target=_do_tts,    daemon=True).start()
            # Watchdog — never leave the startup overlay up forever
            # (e.g. TTS blocked on network fails silently in _do_tts).
            threading.Timer(45, lambda: self.ui.hide_startup_panel()).start()
            # ── Wait ONLY for STT + LLM (fast) ────────────────────────────
            _warmup_done.wait(timeout=15)
            _stt_done.wait(timeout=60)
            # ── Start background services ──────────────────────────────────
            PROGRESS.start("services", "starting services")
            def _scheduler_executor(name: str, command: str, job_type: str):
                if job_type == "shell":
                    from actions.computer_control import computer_control
                    r = computer_control(
                        parameters={"action": "run_command", "command": command},
                        player=self.ui)
                    self.ui.write_log(f"SCHED: {name} → {r[:80]}")
                elif job_type == "agent":
                    from agent.executor import AgentExecutor
                    try:
                        r = AgentExecutor().execute(goal=command, speak=self.speak)
                        self.ui.write_log(f"SCHED-AGENT: {name} → {str(r)[:80]}")
                    except Exception as e:
                        self.ui.write_log(f"SCHED-AGENT: {name} failed: {e}")
                else:
                    self.ui.write_log(f"SCHED: Unknown job type '{job_type}' for '{name}'")
            get_scheduler().set_executor(_scheduler_executor)
            get_scheduler().start()
            self.ui.write_log("SYS: Scheduler started.")
            PROGRESS.update("services", 0.5, "scheduler running")
            # ── Autonomous proactive mind (nudges, briefings, vault journal) ──
            try:
                from core.proactive import start_proactive
                start_proactive(self.ui, self.speak)
                self.ui.write_log("SYS: Proactive mind started.")
            except Exception as pe:
                self.ui.write_log(f"ERR: Proactive — {pe}")
            PROGRESS.finish("services")
            # ── Go online immediately ──────────────────────────────────────
            self.ui.write_log("SYS: ATLANTIS online.")
            self.ui.set_state("LISTENING")
            self.ui.set_startup_status("● ATLANTIS online · Voice loading in background…")
            self._last_activity = time.monotonic()
            threading.Thread(target=self._idle_watcher, daemon=True).start()
            threading.Thread(target=self._start_wake_word, daemon=True).start()
            threading.Thread(target=self._initiative_loop, daemon=True).start()
            # ── Fetch location in background (cached for later use) ───────
            _loc_set = False
            def _init_location():
                nonlocal _loc_set
                try:
                    from actions.get_location import get_location
                    r = get_location(player=self.ui, force_refresh=True)
                    import re
                    m = re.search(r"currently in ([^,]+)", r)
                    if m:
                        self.ui.set_location(m.group(1).strip())
                        _loc_set = True
                except Exception:
                    pass
                if not _loc_set:
                    try:
                        from actions.get_location import _ip_location
                        ip_data = _ip_location()
                        if ip_data and ip_data.get("city"):
                            self.ui.set_location(ip_data["city"])
                    except Exception:
                        pass
            threading.Thread(target=_init_location, daemon=True).start()
            threading.Thread(target=self._tts_synth_worker,  daemon=True).start()
            threading.Thread(target=self._tts_worker,        daemon=True).start()
            threading.Thread(target=self._text_command_loop,  daemon=True).start()
            # STT loop — the voice loop owns the mic when enabled
            if self._config.get("continuous_listening"):
                self.enable_continuous_voice()
                while True:
                    time.sleep(1)
            elif stt_engine == "vosk":
                _lv(self)
            else:
                _lw(self)
        except Exception as e:
            self.ui.write_log(f"ERR: Init failed — {e}")
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Thread entry points (delegated from core.jarvis_*)
    # ------------------------------------------------------------------
    def _tts_synth_worker(self) -> None:
        _tts_synth_worker(self)

    def _tts_worker(self) -> None:
        _tw(self)

    def _text_command_loop(self) -> None:
        _tcl(self)
