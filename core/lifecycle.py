"""Clean shutdown for the assistant.

"Ultron shutdown" has to do three things, in order:

1. Stop the background subsystems (scheduler, proactive nudges, agents).
2. Flush every memory store to disk, so the next launch remembers
   everything.
3. Close the window and terminate any child process the assistant
   started, so nothing is left running behind.

The child-process sweep matters: project scaffolding opens an editor and
spawns per-role ``opencode`` sessions, the browser tools start Playwright,
and the local servers bind ports.  Without the sweep those survive a
shutdown and pile up.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import time

logger = logging.getLogger("jarvis.lifecycle")

#: Marker written into the environment of every child process we spawn.
#: Used by :func:`kill_children` to find our own processes without
#: touching anything the user started.
CHILD_ENV_MARKER = "ULTRON_CHILD"

#: Guards against the shutdown running twice: the quit signal closes the
#: window, and closing the window runs the shutdown again.
_shutdown_done = False


def mark_child_env(env: dict | None = None) -> dict:
    """Return an environment dict that tags a child as ours."""
    child_env = dict(env if env is not None else os.environ)
    child_env[CHILD_ENV_MARKER] = "1"
    return child_env


def _own_pids() -> list[int]:
    """Return the pids of processes this assistant started."""
    own: list[int] = []
    try:
        out = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except Exception as e:
        logger.debug("could not list processes: %s", e)
        return own
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        pid_str, _, args = line.partition(" ")
        if not pid_str.isdigit():
            continue
        # The marker appears in the child's environment, which shows up in
        # its /proc/<pid>/environ — ps args won't contain it, so match the
        # command line instead for processes we can attribute by name.
        if CHILD_ENV_MARKER in args:
            own.append(int(pid_str))
    return own


def _pids_with_marker() -> list[int]:
    """Find children of this process that carry our env marker."""
    found: list[int] = []
    try:
        pids = subprocess.run(
            ["pgrep", "-P", str(os.getpid())],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.split()
    except Exception:
        pids = []
    for pid_str in pids:
        try:
            with open(f"/proc/{pid_str}/environ", "rb") as fh:
                if CHILD_ENV_MARKER.encode() in fh.read():
                    found.append(int(pid_str))
        except Exception:
            continue
    return found


def kill_children(timeout: float = 3.0) -> int:
    """Terminate every child process this assistant started.

    Sends SIGTERM first so children can clean up, then SIGKILL whatever is
    still alive.  Returns the number of processes killed.
    """
    pids = set(_pids_with_marker()) | set(_own_pids())
    pids.discard(os.getpid())
    if not pids:
        return 0

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            continue
        except Exception as e:
            logger.debug("SIGTERM %s failed: %s", pid, e)

    deadline = time.time() + timeout
    while time.time() < deadline:
        alive = []
        for pid in pids:
            try:
                os.kill(pid, 0)
                alive.append(pid)
            except Exception:
                pass
        if not alive:
            return len(pids)
        time.sleep(0.1)

    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            continue
    return len(pids)


def stop_background(ui=None) -> None:
    """Stop the scheduler, proactive nudges and background agents."""
    try:
        from core.scheduler import get_scheduler
        get_scheduler().stop()
    except Exception as e:
        logger.debug("scheduler stop: %s", e)

    try:
        from agent.agent_manager import get_agent_manager
        get_agent_manager().stop_all()
    except Exception as e:
        logger.debug("agents stop: %s", e)

    try:
        from core.proactive import stop_proactive
        stop_proactive()
    except Exception as e:
        logger.debug("proactive stop: %s", e)

    try:
        from actions.wake_word import stop_wake_word
        stop_wake_word()
    except Exception as e:
        logger.debug("wake word stop: %s", e)


def flush_memory() -> None:
    """Persist every memory store so the next launch remembers everything."""
    try:
        from memory.vector_memory import _load_store, _save_store
        _save_store(_load_store())
    except Exception as e:
        logger.debug("vector memory flush: %s", e)

    try:
        from core.jarvis_memory import flush_episodes
        flush_episodes()
    except Exception as e:
        logger.debug("episodes flush: %s", e)

    try:
        from memory.memory_manager import load_memory, save_memory
        save_memory(load_memory())
    except Exception as e:
        logger.debug("long term flush: %s", e)

    # Mirror the facts into the Obsidian vault so the long-term home is
    # up to date the moment the assistant goes away.
    try:
        from memory.memory_manager import _mirror_to_vault, load_memory
        _mirror_to_vault(load_memory())
    except Exception as e:
        logger.debug("vault mirror: %s", e)

    try:
        from agent.agent_manager import get_agent_manager
        get_agent_manager()._save_agents()
    except Exception as e:
        logger.debug("agents flush: %s", e)


def shutdown(ui=None, speak_text: str = "Goodbye.") -> None:
    """Full shutdown: stop subsystems, flush memory, kill children, close UI.

    Safe to call from a worker thread — the UI close is dispatched back onto
    the Qt thread through the quit signal.  Calling it twice is a no-op.
    """
    global _shutdown_done
    if _shutdown_done:
        return
    _shutdown_done = True

    logger.info("Shutdown requested")
    try:
        if ui is not None:
            ui.write_log("SYS: Shutting down — saving memory…")
    except Exception:
        pass

    stop_background(ui)
    flush_memory()

    killed = kill_children()
    if killed:
        logger.info("Stopped %d child process(es)", killed)

    try:
        if ui is not None:
            ui.write_log(f"SYS: Memory saved. Stopped {killed} background process(es).")
    except Exception:
        pass

    try:
        if ui is not None:
            ui.speak(speak_text)
            time.sleep(1.5)
    except Exception:
        pass

    try:
        if ui is not None:
            ui._win._quit_sig.emit()
    except Exception as e:
        logger.debug("quit signal: %s", e)
        # Fall back to a hard exit when the Qt signal is unavailable.
        os._exit(0)

