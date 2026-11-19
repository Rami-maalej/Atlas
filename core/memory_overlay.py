"""GUI panel for viewing, adding and deleting remembered facts."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.memory_store import MemoryStore
from ui import _FONT, C


class MemoryOverlay(QWidget):
    """Simple read/edit/delete view over the local fact store."""

    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Memory")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"MemoryOverlay {{ background: #000; border: 2px solid {C.ACC}; }}"
        )
        self._store = MemoryStore()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(12)

        title = QLabel("MEMORY")
        title.setFont(QFont(_FONT, 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        outer.addWidget(title)
        hint = QLabel("Facts Jarvis remembers about you. Changes are saved locally.")
        hint.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        hint.setFont(QFont(_FONT, 9))
        outer.addWidget(hint)

        add_row = QHBoxLayout()
        self._key = QLineEdit()
        self._key.setPlaceholderText("key (e.g. colour)")
        self._value = QLineEdit()
        self._value.setPlaceholderText("value (e.g. teal)")
        add = QPushButton("Add")
        add.clicked.connect(self._add)
        for w in (self._key, self._value, add):
            w.setStyleSheet(
                f"QWidget {{ background: {C.PANEL}; color: {C.TEXT}; "
                f"border: 1px solid {C.BORDER}; padding: 5px; }}"
            )
            add_row.addWidget(w)
        outer.addLayout(add_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._list = QWidget()
        self._lay = QVBoxLayout(self._list)
        self._scroll.setWidget(self._list)
        outer.addWidget(self._scroll)
        self._render()

    def _render(self) -> None:
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        facts = self._store.list_facts(limit=200)
        if not facts:
            self._lay.addWidget(QLabel("Nothing remembered yet."))
            return
        for fact in facts:
            row = QHBoxLayout()
            label = QLabel(f"{fact['category']} / {fact['key']}: {fact['value']}")
            label.setWordWrap(True)
            label.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
            row.addWidget(label, 1)
            delete = QPushButton("Delete")
            delete.clicked.connect(
                lambda _checked=False, f=fact: self._delete(f)
            )
            row.addWidget(delete)
            holder = QWidget()
            holder.setLayout(row)
            self._lay.addWidget(holder)

    def _add(self) -> None:
        key, value = self._key.text().strip(), self._value.text().strip()
        if key and value:
            self._store.add_fact("notes", key, value)
            self._key.clear()
            self._value.clear()
            self._render()
            self.changed.emit()

    def _delete(self, fact: dict) -> None:
        self._store.delete_fact(int(fact["id"]))
        self._render()
        self.changed.emit()
