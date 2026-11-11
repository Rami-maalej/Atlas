"""
Lazy pyautogui loader.

pyautogui drags in mouseinfo → tkinter at import time. This is a PyQt6
application; tkinter is only needed inside pyautogui itself and never by the
assistant directly. Importing pyautogui eagerly at boot therefore printed
"NOTE: You must install tkinter…" on every launch and slowed engine autoload.

Usage (module scope, replaces the old `try: import pyautogui` blocks):

    from actions._lazy_pya import LazyPya, pya_state_reset

    pyautogui  = LazyPya()   # proxy — the real module loads on first touch
"""
from __future__ import annotations

_module = None       # real pyautogui module once loaded, or False if unavailable
_configured = False


def _load() -> object:
    """Import pyautogui on first use. Returns the module, or False."""
    global _module, _configured
    if _module is None:
        try:
            import pyautogui
            # Old module-level blocks set FAILSAFE/PAUSE on import — keep that
            # behaviour, applied once, at actual import time.
            if not _configured:
                pyautogui.FAILSAFE = True
                pyautogui.PAUSE = 0.05
                _configured = True
            _module = pyautogui
        except Exception:
            _module = False
    return _module


class LazyPya:
    """Stand-in for `import pyautogui`. Attribute access imports for real."""

    def __getattr__(self, name: str):
        mod = _load()
        if mod is False:
            raise RuntimeError("pyautogui is not available in this environment")
        return getattr(mod, name)

    def __setattr__(self, name: str, value) -> None:
        mod = _load()
        if mod is not False:
            setattr(mod, name, value)

    def __bool__(self) -> bool:
        return _load() is not False


def pya_saved() -> bool:
    """Legacy `_PYAUTOGUI` compatibility: availability as of the last import
    attempt; imports the real module only when nothing tried yet."""
    return _load() is not False
