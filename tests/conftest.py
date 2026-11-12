"""Shared pytest config for the Atlantis test suite.

* Forces Qt offscreen so overlay tests run without a display.
* Registers custom markers (qt / network) to avoid unknown-mark warnings.
* Sandboxes the data root so tests never touch the developer's real
  ``memory/*.json`` or ``config/api_keys.json``.

The sandbox is the important part.  Before it existed, the suite wrote
straight into the repository's memory files — committing dozens of fake
"crud test" tasks and hundreds of "test episode N" rows.  Every module that
persists state now resolves its path through ``core.paths``, so pointing
``ATLANTIS_HOME`` at a temporary directory redirects every write.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# ── Sandbox the data root ────────────────────────────────────────────────────
# Must happen before any application module is imported, because modules
# resolve their paths at import time.
_SANDBOX = Path(tempfile.mkdtemp(prefix="atlantis-test-"))
os.environ["ATLANTIS_HOME"] = str(_SANDBOX)

# Give the sandbox a minimal config dir so modules that read api_keys.json
# at import time do not explode.
(_SANDBOX / "memory").mkdir(parents=True, exist_ok=True)
(_SANDBOX / "config").mkdir(parents=True, exist_ok=True)


def pytest_configure(config) -> None:
    config.addinivalue_line("markers", "qt: requires PyQt6 (runs offscreen)")
    config.addinivalue_line("markers", "network: needs internet access")


def pytest_unconfigure(config) -> None:
    shutil.rmtree(_SANDBOX, ignore_errors=True)
