#!/usr/bin/env python3
"""Idea Bar — one line, Enter, idea saved to your Obsidian vault.

Run:  .venv/bin/python idea_bar.py
Keys: Enter = save to vault (Ideas/) · Esc = quit
"""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from actions.obsidian_vault import VAULT_DIR, save_note  # noqa: E402

BG, FG, ACC, DIM = "#101418", "#e8eef4", "#4fd1c5", "#6b7a89"
WIDTH, HEIGHT = 520, 62


class IdeaBar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Idea Bar")
        self.setWindowFlags(
            Qt.WindowType.Frameless
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedWidth(WIDTH)

        self._input = QLineEdit()
        self._input.setPlaceholderText("  Drop an idea…   Enter = save to vault   Esc = quit")
        self._input.setStyleSheet(
            f"""
            QLineEdit {{
                background: {BG}; color: {FG};
                border: 1px solid {ACC};
                padding: 14px 16px; font-size: 15px; selection-background-color: {ACC};
            }}
            QLineEdit:focus {{ border-width: 2px; }}
            """
        )
        self._input.returnPressed.connect(self._save)

        self._status = QLabel("")
        self._status.setFixedHeight(16)
        self._status.setStyleSheet(
            f"color: {DIM}; background: {BG}; font-size: 11px; padding: 0 4px; border: none;"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(self._input)
        lay.addWidget(self._status)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)

        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.timeout.connect(self._restore_hint)

        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - WIDTH) // 2, 120)

    def _restore_hint(self) -> None:
        self._status.setText(f"vault: {VAULT_DIR.name}/ · Enter saves to Ideas/")

    def _save(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        first_line = text.splitlines()[0][:60].strip()
        try:
            r = save_note(title=first_line, content=text, folder="Ideas")
        except Exception as e:
            self._status.setText(f"error: {e}")
            return
        name = Path(r["path"]).name
        self._input.clear()
        self._status.setStyleSheet(
            f"color: {ACC}; background: {BG}; font-size: 11px; padding: 0 4px; border: none;"
        )
        self._status.setText(f"✓ saved → Ideas/{name}")
        self._hint_timer.start(3000)
        self._input.setFocus()

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        self._restore_hint()
        self._input.setFocus()


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    bar = IdeaBar()
    bar.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
