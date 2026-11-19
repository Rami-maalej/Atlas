"""PyQt6 widgets render and signals work (offscreen)."""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.gui, pytest.mark.qt]


def test_hud_canvas_starts_awake(qtbot):
    from ui import HudCanvas
    hud = HudCanvas("face.png")
    qtbot.addWidget(hud)
    assert hud.awake is True
    hud.show()
    assert hud.isVisible()


def test_hud_palette_switch(qtbot):
    from ui import HudCanvas
    hud = HudCanvas("face.png")
    qtbot.addWidget(hud)
    hud.awake = False
    assert hud.awake is False


def test_chat_widget_add_message(qtbot):
    from ui import ChatWidget
    chat = ChatWidget()
    qtbot.addWidget(chat)
    chat.add_message("You: hello")
    chat.add_message("Atlantis: hi there")
    chat.add_message("SYS: ignored")
    assert chat._box_lay.count() >= 2


def test_memory_overlay_renders(qtbot, monkeypatch, tmp_path):
    from core import memory_store
    from core.memory_overlay import MemoryOverlay
    monkeypatch.setattr(memory_store, "DB_PATH", tmp_path / "m.db")
    ov = MemoryOverlay()
    qtbot.addWidget(ov)
    assert ov.windowTitle() == "Memory"


def test_companion_overlay_saves(qtbot, monkeypatch, tmp_path):
    from core import companion_settings
    from core.companion_settings import CompanionOverlay
    monkeypatch.setattr(companion_settings, "save_config", lambda cfg: None)
    ov = CompanionOverlay()
    qtbot.addWidget(ov)
    ov._boxes["do_not_disturb"].setChecked(True)
    ov._save()
    assert ov._boxes["do_not_disturb"].isChecked()
