"""PyQt6 Accounts panel for connecting Google accounts and syncing mail."""

from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.google_auth import AccountInfo, GoogleAuthError
from core.google_service import (
    GmailClient,
    GoogleAccountManager,
    GoogleServiceError,
)
from ui import _FONT, C

logger = logging.getLogger("google_overlay")


class _Signals(QObject):
    started = pyqtSignal(str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)


class _Worker(QRunnable):
    """Runs blocking OAuth / network work off the GUI thread."""

    def __init__(self, fn, *args: Any, label: str = "Working…"):
        super().__init__()
        self.fn = fn
        self.args = args
        self.label = label
        self.signals = _Signals()

    @pyqtSlot()
    def run(self) -> None:
        self.signals.started.emit(self.label)
        try:
            self.signals.finished.emit(self.fn(*self.args))
        except (GoogleAuthError, GoogleServiceError) as e:
            self.signals.error.emit(str(e))
        except Exception as e:
            logger.warning("Google worker failed: %s", type(e).__name__)
            self.signals.error.emit(f"Unexpected error: {type(e).__name__}")


class AccountsOverlay(QWidget):
    """List connected accounts and add one account per OAuth run."""

    accounts_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Google Accounts")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"AccountsOverlay {{ background: #000; border: 2px solid {C.ACC}; }}"
        )
        self._manager = GoogleAccountManager()
        self._pool = QThreadPool.globalInstance()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("GOOGLE ACCOUNTS")
        title.setFont(QFont(_FONT, 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        header.addWidget(title)
        header.addStretch()
        connect = QPushButton("Connect Google account")
        connect.setCursor(Qt.CursorShape.PointingHandCursor)
        connect.setStyleSheet(
            f"QPushButton {{ background: {C.ACC}; color: #04141a; border: none; "
            f"padding: 7px 14px; font-weight: bold; }}"
        )
        connect.clicked.connect(self._connect)
        header.addWidget(connect)
        outer.addLayout(header)

        hint = QLabel(
            "Each sign-in authorizes one account. Repeat to add more accounts. "
            "Refresh tokens are stored in the OS keychain; email data stays local."
        )
        hint.setWordWrap(True)
        hint.setFont(QFont(_FONT, 9))
        hint.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        outer.addWidget(hint)

        self._status = QLabel("")
        self._status.setFont(QFont(_FONT, 9))
        self._status.setStyleSheet(f"color: {C.WARN}; background: transparent;")
        outer.addWidget(self._status)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("background: transparent; border: none;")
        self._list = QWidget()
        self._list_lay = QVBoxLayout(self._list)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(8)
        self._scroll.setWidget(self._list)
        outer.addWidget(self._scroll)

        self._render()

    def _render(self) -> None:
        while self._list_lay.count():
            item = self._list_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        accounts = self._manager.list_accounts()
        if not accounts:
            empty = QLabel("No accounts connected yet.")
            empty.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            self._list_lay.addWidget(empty)
            return
        for account in accounts:
            self._list_lay.addWidget(self._account_row(account))

    def _account_row(self, account: AccountInfo) -> QWidget:
        row = QWidget()
        row.setStyleSheet(
            f"QWidget {{ background: {C.PANEL}; border: 1px solid {C.BORDER}; "
            f"border-radius: 8px; }}"
        )
        lay = QHBoxLayout(row)
        lay.setContentsMargins(12, 8, 12, 8)

        avatar = QLabel((account.name or account.email)[:1].upper())
        avatar.setFixedSize(34, 34)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            f"border-radius: 17px; background: {C.ACC}; color: #04141a; "
            f"font-weight: bold;"
        )
        lay.addWidget(avatar)

        info = QVBoxLayout()
        email = QLabel(account.email)
        email.setStyleSheet(f"color: {C.TEXT}; background: transparent; font-weight: bold;")
        info.addWidget(email)
        state = "needs re-auth" if account.needs_reauth else "connected"
        detail = QLabel(f"{state} · last sync: {account.last_sync or 'never'}")
        detail.setFont(QFont(_FONT, 8))
        detail.setStyleSheet(
            f"color: {C.WARN if account.needs_reauth else C.TEXT_DIM}; background: transparent;"
        )
        info.addWidget(detail)
        lay.addLayout(info, 1)

        sync = QPushButton("Sync")
        sync.setStyleSheet(_btn_style())
        sync.clicked.connect(lambda acc=account: self._sync(acc.email))
        lay.addWidget(sync)

        remove = QPushButton("Remove")
        remove.setStyleSheet(_btn_style())
        remove.clicked.connect(lambda acc=account: self._remove(acc.email))
        lay.addWidget(remove)
        return row

    def _start(self, worker: _Worker) -> None:
        worker.signals.started.connect(
            lambda msg: self._status.setText(msg)
        )
        worker.signals.error.connect(self._on_error)
        worker.signals.finished.connect(self._on_done)
        self._pool.start(worker)

    def _connect(self) -> None:
        self._start(
            _Worker(self._manager.add_account, label="Opening browser for Google consent…")
        )

    def _sync(self, email: str) -> None:
        self._start(
            _Worker(GmailClient(email).sync, label=f"Syncing {email}…")
        )

    def _remove(self, email: str) -> None:
        self._manager.remove_account(email)
        self._render()
        self.accounts_changed.emit()
        self._status.setText(f"Removed {email}")

    def _on_error(self, message: str) -> None:
        self._status.setText(message)
        self._render()

    def _on_done(self, _result: Any) -> None:
        self._status.setText("Done.")
        self._render()
        self.accounts_changed.emit()


def _btn_style() -> str:
    return (
        f"QPushButton {{ background: transparent; color: {C.TEXT_DIM}; "
        f"border: 1px solid {C.BORDER}; padding: 5px 10px; }}"
        f"QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.ACC}; }}"
    )
