"""Companion settings overlay: voice, proactivity and anti-annoyance controls."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from memory.config_manager import load_config, save_config
from ui import _FONT, C


class CompanionOverlay(QWidget):
    """Edit the settings that shape Jarvis' companion behaviour."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Companion")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"CompanionOverlay {{ background: #000; border: 2px solid {C.ACC}; }}"
        )
        cfg = load_config()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        title = QLabel("COMPANION SETTINGS")
        title.setFont(QFont(_FONT, 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        lay.addWidget(title)

        self._boxes: dict[str, QCheckBox] = {}
        for key, label, default in (
            ("continuous_listening", "Continuous listening", False),
            ("voice_conversation_mode", "Follow-up listening after answers", True),
            ("proactive_enabled", "Proactive messages", True),
            ("do_not_disturb", "Do not disturb", False),
            ("store_raw_audio", "Store raw audio (off by default)", False),
            ("allow_cloud_before_wake", "Cloud STT before wake word", False),
        ):
            box = QCheckBox(label)
            box.setChecked(bool(cfg.get(key, default)))
            box.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
            self._boxes[key] = box
            lay.addWidget(box)

        for key, label, default, lo, hi in (
            ("endpointing_ms", "Endpointing delay (ms)", 700, 200, 3000),
            ("follow_up_seconds", "Follow-up window (s)", 12, 3, 60),
            ("max_proactive_per_hour", "Max proactive / hour", 3, 0, 20),
            ("quiet_hours_start", "Quiet hours start", 22, 0, 23),
            ("quiet_hours_end", "Quiet hours end", 8, 0, 23),
        ):
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            spin = QSpinBox()
            spin.setRange(lo, hi)
            spin.setValue(int(cfg.get(key, default)))
            spin.setStyleSheet(
                f"QSpinBox {{ background: {C.PANEL}; color: {C.TEXT}; "
                f"border: 1px solid {C.BORDER}; padding: 3px; }}"
            )
            setattr(self, f"_{key}", spin)
            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(spin)
            lay.addLayout(row)

        save = QPushButton("Save")
        save.setStyleSheet(
            f"QPushButton {{ background: {C.ACC}; color: #04141a; "
            f"border: none; padding: 7px 14px; font-weight: bold; }}"
        )
        save.clicked.connect(self._save)
        lay.addWidget(save, alignment=Qt.AlignmentFlag.AlignRight)

    def _save(self) -> None:
        cfg = {key: box.isChecked() for key, box in self._boxes.items()}
        for key in ("endpointing_ms", "follow_up_seconds", "max_proactive_per_hour",
                    "quiet_hours_start", "quiet_hours_end"):
            cfg[key] = getattr(self, f"_{key}").value()
        save_config(cfg)
