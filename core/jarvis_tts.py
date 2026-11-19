"""Text-to-speech workers + speak helpers.

Text and voice now start TOGETHER: the chat bubble is revealed at the exact
moment playback begins, and the NEXT sentence is synthesized while the
current one is still playing (pipeline), removing the 2-3s silent gap.
"""
from __future__ import annotations

import queue


def _tts_synth_worker(self) -> None:
    """Prepare audio ahead of playback: synth N+1 while N is playing."""
    self._tts_ready.wait(timeout=120)
    while True:
        item = self._tts_queue.get()
        if item is None:
            self._tts_queue.task_done()
            break
        text, show = item
        prepared = None
        try:
            if text and self._tts and hasattr(self._tts, "prepare"):
                prepared = self._tts.prepare(text)
        except Exception as e:
            print(f"[TTS] synth error: {e}")
        self._tts_play_queue.put((text, show, prepared))
        self._tts_queue.task_done()


def _tts_worker(self) -> None:
    """Play prepared audio; reveal the matching bubble as speech begins."""
    while True:
        text, show, prepared = self._tts_play_queue.get()
        try:
            if text and prepared is not None and self._tts:
                with self._speaking_lock:
                    self._speaking = True
                _lat = getattr(self, "latency", None)
                if _lat:
                    _lat.mark("FIRST_TTS_AUDIO")
                _conv = getattr(self, "conversation", None)
                if _conv is not None:
                    from core.conversation_state import State
                    _conv.transition(State.SPEAKING, force=True)
                self.ui.set_state("SPEAKING")
                if show:
                    self.ui.write_log_instant(f"Atlantis: {text}")
                if hasattr(self._tts, "play_prepared"):
                    self._tts.play_prepared(prepared)
                else:
                    self._tts.speak(text)
            elif text and show:
                # Engine offline/muted — still show the text so the user
                # isn't left with a silent, blank turn.
                self.ui.write_log_instant(f"Atlantis: {text}")
        except Exception as e:
            print(f"[TTS] speak error: {e}")
            if text and show:
                self.ui.write_log_instant(f"Atlantis: {text}")
        finally:
            self._tts_play_queue.task_done()
            if self._tts_play_queue.empty() and self._tts_queue.empty():
                with self._speaking_lock:
                    self._speaking = False
                _lat = getattr(self, "latency", None)
                if _lat:
                    _lat.mark("RESPONSE_END")
                    _lat.finish()
                _finish = getattr(self, "_finish_turn", None)
                if _finish:
                    _finish()
                elif not self.ui.muted:
                    self.ui.set_state("LISTENING")


def set_speaking(self, value: bool) -> None:
    with self._speaking_lock:
        self._speaking = value
    if value:
        _conv = getattr(self, "conversation", None)
        if _conv is not None:
            from core.conversation_state import State
            _conv.transition(State.SPEAKING, force=True)
        self.ui.set_state("SPEAKING")
    elif not self.ui.muted:
        self.ui.set_state("LISTENING")


def speak(self, text: str, show: bool = True) -> None:
    """Queue text for speech. 'show' controls revealing the chat bubble
    when speech starts (True for conversation, False for internal notes)."""
    if not text:
        return
    if not self._tts:
        if show:
            self.ui.write_log_instant(f"Atlantis: {text}")
        return
    with self._speaking_lock:
        self._speaking = True
    self._tts_queue.put((text, show))


def speak_error(self, tool_name: str, error) -> None:
    short = str(error)[:120]
    self.ui.write_log(f"ERR: {tool_name} — {short}")
    self.speak("I'm afraid that didn't work, sir.")


def stop_speaking(self) -> None:
    """Barge-in: drop queued speech and stop playback immediately."""
    for q in (self._tts_queue, self._tts_play_queue):
        while True:
            try:
                q.get_nowait()
                q.task_done()
            except queue.Empty:
                break
    try:
        from tts import stop

        stop()
    except Exception:
        pass
    try:
        if self._tts and hasattr(self._tts, "stop"):
            self._tts.stop()
    except Exception:
        pass
    set_speaking(self, False)
