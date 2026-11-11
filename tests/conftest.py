"""Shared pytest config for MARK XL tests.

* Forces Qt offscreen so overlay tests run without a display.
* Registers custom markers (qt / network) to avoid unknown-mark warnings.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pytest_configure(config) -> None:
    config.addinivalue_line("markers", "qt: requires PyQt6 (runs offscreen)")
    config.addinivalue_line("markers", "network: needs internet access")
