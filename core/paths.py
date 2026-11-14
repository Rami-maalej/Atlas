"""Canonical filesystem locations.

Every module that persists state used to compute its own path with
``Path(__file__).resolve().parent.parent / "memory" / ...``.  That made the
data directory impossible to redirect, so the test suite wrote straight into
the developer's real ``memory/*.json`` files (committing dozens of fake
"crud test" tasks and "test episode N" rows).

This module is the single source of truth.  ``ATLANTIS_HOME`` redirects the
whole data root — used by pytest to sandbox every write, and by anyone who
wants a portable install.

Resolution order:

1. ``ATLANTIS_HOME`` — when set, ``memory/`` and ``config/`` live beneath it.
2. Frozen build (``sys.frozen``) — the directory holding the executable.
3. The repository root — the parent of the ``core`` package.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: Environment variable that overrides the data root.
HOME_ENV = "ATLANTIS_HOME"


def base_dir() -> Path:
    """Return the data root that holds ``memory/`` and ``config/``."""
    override = os.environ.get(HOME_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def memory_dir() -> Path:
    """Return the directory holding persistent memory state."""
    return base_dir() / "memory"


def config_dir() -> Path:
    """Return the directory holding configuration (including API keys)."""
    return base_dir() / "config"


def memory_path(name: str) -> Path:
    """Return the path of a named file inside the memory directory."""
    return memory_dir() / name


def config_path(name: str) -> Path:
    """Return the path of a named file inside the config directory."""
    return config_dir() / name

