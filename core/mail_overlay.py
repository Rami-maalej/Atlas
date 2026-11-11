"""MARK XL — Gmail-style mail screen.

Three-pane inbox overlay (folders · message list · reading pane) built in
the same flat, black/white design language as ``core.provider_overlay``.

Layout::

    ┌───────────────────────────────────────────────────────────────┐
    │ ✉ MAIL   you@gmail.com              [↻]  Unread: 5  [⚙]     │
    ├────────────┬───────────────────────────┬──────────────────────┤
    │ INBOX  12  │ [search…]                 │ Subject              │
    │ Unread  5  │ ● Jane      14:03          │ From · Date          │
    │ Starred 2  │   Subject line            │ ─────────────────    │
    │ Sent       │   snippet…                │ body                 │
    │ …          │                           │ [Read] [★] [Web]     │
    └────────────┴───────────────────────────┴──────────────────────┘

All IMAP work happens in background threads; results come back through
Qt signals so the UI thread never blocks.
"""

from __future__ import annotations

import threading
from typing import Any

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from core.mail_client import (
    PROVIDERS,
    MailAccount,
    MailError,
    MailFolder,
    MailMessage,
    connect,
    delete_account,
    fetch_body,
    fetch_messages,
    list_folders,
    load_account,
    mark_folder_read,
    save_account,
    set_seen,
    set_starred,
    webmail_url,
)


def _C() -> Any:
    import ui as _ui

    return _ui.C


def _font() -> str:
    import ui as _ui

    return _ui._FONT


_LINE = "#333333"


def _btn(text: str, primary: bool = False) -> QPushButton:
    """Create a flat button matching the overlay design language."""
    C = _C()
    btn = QPushButton(text)
    btn.setFont(QFont(_font(), 9, QFont.Weight.Bold))
    btn.setFixedHeight(26)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        btn.setStyleSheet(
            f"""
            QPushButton {{ background: {C.ACC}; color: {C.WHITE}; border: none;
                            padding: 0px 12px; }}
            QPushButton:hover {{ background: {C.ACC_DIM}; }}
            """
        )
    else:
        btn.setStyleSheet(
            f"""
            QPushButton {{ background: transparent; color: {C.TEXT_DIM};
                            border: 1px solid {_LINE}; padding: 0px 10px; }}
            QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.ACC};
                                 background: {C.PRI_GHO}; }}
            """
        )
    return btn


def _field(placeholder: str, echo: bool = False) -> QLineEdit:
    """Create a styled single-line input."""
    C = _C()
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder)
    edit.setFixedHeight(26)
    if echo:
        edit.setEchoMode(QLineEdit.EchoMode.Password)
    edit.setStyleSheet(
        f"""
        QLineEdit {{ background: #1A1A1A; color: {C.TEXT}; border: 1px solid {_LINE};
                     padding: 2px 8px; font-family: '{_font()}'; font-size: 9pt; }}
        QLineEdit:focus {{ border: 1px solid {C.ACC}; }}
        """
    )
    return edit


class MailOverlay(QWidget):
    """Gmail-like inbox overlay."""

    # Thread → UI bridges
    _folders_sig = pyqtSignal(list)
    _messages_sig = pyqtSignal(list, str)
    _body_sig = pyqtSignal(object)
    _error_sig = pyqtSignal(str)
    _status_sig = pyqtSignal(str)
    _unread_sig = pyqtSignal(int)
    _saved_sig = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        C = _C()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        light = C.BG.lower() in ("#ffffff", "#f8f9fa")
        bg = "rgba(240, 242, 245, 248)" if light else "rgba(10, 10, 10, 248)"
        self.setStyleSheet(
            f"MailOverlay {{ background: {bg}; border: 2px solid {C.ACC}; }}"
        )

        self._account: MailAccount | None = load_account()
        self._folder: str = "INBOX"
        self._query: str = ""
        self._unread_only: bool = False
        self._messages: list[MailMessage] = []
        self._current: MailMessage | None = None
        self._busy: bool = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        root.addWidget(self._build_header())

        body_row = QHBoxLayout()
        body_row.setSpacing(12)
        body_row.addWidget(self._build_sidebar(), stretch=0)
        body_row.addWidget(self._build_list_pane(), stretch=2)
        body_row.addWidget(self._build_read_pane(), stretch=3)
        self._panes = QWidget()
        self._panes.setStyleSheet("background: transparent; border: none;")
        self._panes.setLayout(body_row)
        root.addWidget(self._panes, stretch=1)

        self._status_lbl = QLabel("")
        self._status_lbl.setFont(QFont("Courier New", 8))
        self._status_lbl.setStyleSheet(
            f"color: {C.TEXT_MED}; background: transparent; border: none;"
        )
        root.addWidget(self._status_lbl)

        # Settings panel overlays the body panes when opened
        self._settings = self._build_settings()
        self._settings.hide()
        root.addWidget(self._settings, stretch=1)

        self._folders_sig.connect(self._on_folders)
        self._messages_sig.connect(self._on_messages)
        self._body_sig.connect(self._on_body)
        self._error_sig.connect(self._on_error)
        self._status_sig.connect(lambda text: self._status_lbl.setText(text))
        self._unread_sig.connect(lambda n: self._unread_lbl.setText(f"Unread: {n}"))
        self._saved_sig.connect(self._on_saved)

        if self._account:
            QTimer.singleShot(80, self._reload)
        else:
            self._status_lbl.setText(
                "No account yet — enter your Gmail address and app password below."
            )
            self._open_settings()

    # ── Header ─────────────────────────────────────────────────────────
    def _build_header(self) -> QWidget:
        C = _C()
        bar = QWidget()
        bar.setStyleSheet("background: transparent; border: none;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        title = QLabel("✉ MAIL")
        title.setFont(QFont(_font(), 15, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT}; background: transparent; border: none;")
        lay.addWidget(title)

        self._acct_lbl = QLabel(self._account.email if self._account else "not connected")
        self._acct_lbl.setFont(QFont("Courier New", 9))
        self._acct_lbl.setStyleSheet(
            f"color: {C.TEXT_MED}; background: transparent; border: none;"
        )
        lay.addWidget(self._acct_lbl)

        self._unread_lbl = QLabel("")
        self._unread_lbl.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._unread_lbl.setStyleSheet(
            f"color: {C.ACC}; background: transparent; border: none;"
        )
        lay.addWidget(self._unread_lbl)
        lay.addStretch()

        refresh_btn = _btn("↻ Refresh")
        refresh_btn.clicked.connect(self._reload)
        lay.addWidget(refresh_btn)

        settings_btn = _btn("⚙ Settings")
        settings_btn.clicked.connect(self._toggle_settings)
        lay.addWidget(settings_btn)

        close_btn = _btn("✕ Close")
        close_btn.clicked.connect(self.hide)
        lay.addWidget(close_btn)
        return bar

    # ── Sidebar (folders) ──────────────────────────────────────────────
    def _build_sidebar(self) -> QWidget:
        C = _C()
        side = QWidget()
        side.setFixedWidth(160)
        side.setStyleSheet(
            f"background: {C.PANEL2}; border: 1px solid {_LINE};"
        )
        lay = QVBoxLayout(side)
        lay.setContentsMargins(8, 10, 8, 10)
        lay.setSpacing(2)

        head = QLabel("FOLDERS")
        head.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        head.setStyleSheet(
            f"color: {C.TEXT_MED}; background: transparent; border: none;"
        )
        lay.addWidget(head)

        self._folder_btns: dict[str, QPushButton] = {}
        for name in ("INBOX", "Unread", "Starred", "Sent", "Drafts", "Junk", "Trash", "Archive"):
            btn = QPushButton(name)
            btn.setFixedHeight(26)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFont(QFont(_font(), 9))
            btn.setStyleSheet(
                f"""
                QPushButton {{ background: transparent; color: {C.TEXT}; border: none;
                               text-align: left; padding: 0px 6px; }}
                QPushButton:hover {{ background: {C.PRI_GHO}; }}
                """
            )
            btn.clicked.connect(lambda _c, n=name: self._select_folder(n))
            self._folder_btns[name] = btn
            lay.addWidget(btn)
        lay.addStretch()

        self._mark_read_btn = _btn("✓ Mark all read")
        self._mark_read_btn.clicked.connect(self._mark_all_read)
        lay.addWidget(self._mark_read_btn)
        return side

    def _highlight_folder(self) -> None:
        C = _C()
        for name, btn in self._folder_btns.items():
            active = (
                (name == "Unread" and self._unread_only)
                or (name == "Starred" and self._folder == "Starred")
                or (
                    name == self._folder
                    and not self._unread_only
                    and name not in ("Unread", "Starred")
                )
            )
            btn.setStyleSheet(
                f"""
                QPushButton {{
                    background: {C.ACC_GHO if active else "transparent"};
                    color: {C.TEXT}; border: none; text-align: left; padding: 0px 6px;
                    font-family: '{_font()}'; font-size: 9pt;
                    {"border-left: 2px solid " + C.ACC + ";" if active else ""}
                }}
                QPushButton:hover {{ background: {C.PRI_GHO}; }}
                """
            )

    # ── Message list ───────────────────────────────────────────────────
    def _build_list_pane(self) -> QWidget:
        C = _C()
        pane = QWidget()
        pane.setStyleSheet(f"background: {C.PANEL2}; border: 1px solid {_LINE};")
        lay = QVBoxLayout(pane)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self._search = _field("Search mail…")
        self._search.returnPressed.connect(self._on_search)
        lay.addWidget(self._search)

        self._list = QListWidget()
        self._list.setStyleSheet(
            f"""
            QListWidget {{ background: {C.PANEL}; color: {C.TEXT}; border: none; outline: none; }}
            QListWidget::item {{ border-bottom: 1px solid {_LINE}; padding: 6px 2px; }}
            QListWidget::item:selected {{ background: {C.ACC_GHO}; }}
            """
        )
        self._list.currentItemChanged.connect(self._on_select)
        lay.addWidget(self._list, stretch=1)
        return pane

    def _render_row(self, msg: MailMessage) -> QListWidgetItem:
        C = _C()
        row = QWidget()
        row.setStyleSheet("background: transparent; border: none;")
        grid = QVBoxLayout(row)
        grid.setContentsMargins(4, 2, 4, 2)
        grid.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(6)
        dot = QLabel("●" if msg.is_unread else " ")
        dot.setFont(QFont(_font(), 8))
        dot.setStyleSheet(
            f"color: {C.ACC}; background: transparent; border: none;"
        )
        dot.setFixedWidth(12)
        top.addWidget(dot)

        star = QLabel("★" if msg.is_starred else "☆")
        star.setFont(QFont(_font(), 9))
        star.setStyleSheet(
            f"color: {'#e8a838' if msg.is_starred else C.TEXT_MED};"
            " background: transparent; border: none;"
        )
        star.setFixedWidth(16)
        top.addWidget(star)

        sender = QLabel(msg.display_sender)
        weight = QFont.Weight.Bold if msg.is_unread else QFont.Weight.Normal
        sender.setFont(QFont(_font(), 9, weight))
        sender.setStyleSheet(
            f"color: {C.TEXT}; background: transparent; border: none;"
        )
        sender.setMinimumWidth(90)
        sender.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        top.addWidget(sender, stretch=1)

        date_lbl = QLabel(msg.date_text)
        date_lbl.setFont(QFont("Courier New", 7))
        date_lbl.setStyleSheet(
            f"color: {C.TEXT_MED}; background: transparent; border: none;"
        )
        top.addWidget(date_lbl)
        grid.addLayout(top)

        subject = QLabel(msg.subject)
        subject.setFont(QFont(_font(), 9, weight))
        subject.setStyleSheet(f"color: {C.TEXT}; background: transparent; border: none;")
        subject.setWordWrap(True)
        grid.addWidget(subject)

        if msg.preview:
            snippet = QLabel(msg.preview)
            snippet.setFont(QFont(_font(), 8))
            snippet.setStyleSheet(
                f"color: {C.TEXT_MED}; background: transparent; border: none;"
            )
            snippet.setWordWrap(True)
            grid.addWidget(snippet)

        item = QListWidgetItem(self._list)
        item.setData(Qt.ItemDataRole.UserRole, msg.uid)
        item.setSizeHint(row.sizeHint() + QSize(0, 24))
        self._list.setItemWidget(item, row)
        return item

    # ── Reading pane ───────────────────────────────────────────────────
    def _build_read_pane(self) -> QWidget:
        C = _C()
        pane = QWidget()
        pane.setStyleSheet(f"background: {C.PANEL2}; border: 1px solid {_LINE};")
        lay = QVBoxLayout(pane)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        self._subject_lbl = QLabel("Select a message")
        self._subject_lbl.setFont(QFont(_font(), 13, QFont.Weight.Bold))
        self._subject_lbl.setStyleSheet(
            f"color: {C.TEXT}; background: transparent; border: none;"
        )
        self._subject_lbl.setWordWrap(True)
        lay.addWidget(self._subject_lbl)

        self._meta_lbl = QLabel("")
        self._meta_lbl.setFont(QFont("Courier New", 8))
        self._meta_lbl.setStyleSheet(
            f"color: {C.TEXT_MED}; background: transparent; border: none;"
        )
        self._meta_lbl.setWordWrap(True)
        lay.addWidget(self._meta_lbl)

        sep = QLabel("─" * 60)
        sep.setStyleSheet(f"color: {_LINE}; background: transparent; border: none;")
        lay.addWidget(sep)

        self._body = QTextBrowser()
        self._body.setOpenExternalLinks(False)
        self._body.setStyleSheet(
            f"""
            QTextBrowser {{ background: {C.PANEL}; color: {C.TEXT}; border: none;
                            font-family: '{_font()}'; font-size: 10pt; }}
            """
        )
        lay.addWidget(self._body, stretch=1)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self._read_btn = _btn("Mark unread")
        self._read_btn.clicked.connect(self._toggle_read)
        actions.addWidget(self._read_btn)
        self._star_btn = _btn("☆ Star")
        self._star_btn.clicked.connect(self._toggle_star)
        actions.addWidget(self._star_btn)
        web_btn = _btn("Open in browser")
        web_btn.clicked.connect(self._open_web)
        actions.addWidget(web_btn)
        actions.addStretch()
        lay.addLayout(actions)
        return pane

    # ── Settings panel ─────────────────────────────────────────────────
    def _build_settings(self) -> QWidget:
        C = _C()
        panel = QWidget()
        panel.setStyleSheet(
            f"background: {C.PANEL2}; border: 1px solid {C.ACC};"
        )
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        head = QLabel("MAIL ACCOUNT")
        head.setFont(QFont(_font(), 13, QFont.Weight.Bold))
        head.setStyleSheet(f"color: {C.TEXT}; background: transparent; border: none;")
        lay.addWidget(head)

        hint = QLabel(
            "Gmail: Google Account ▸ Security ▸ App passwords → create one, paste it below.\n"
            "The password is stored in config/.mail_creds.json (chmod 600), never in git."
        )
        hint.setFont(QFont(_font(), 8))
        hint.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        prov_lbl = QLabel("Provider")
        prov_lbl.setFont(QFont("Courier New", 8))
        prov_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        self._prov_combo = QComboBox()
        self._prov_combo.setFixedHeight(26)
        self._prov_combo.setStyleSheet(
            f"""
            QComboBox {{ background: #1A1A1A; color: {C.TEXT}; border: 1px solid {_LINE};
                         padding: 2px 6px; font-family: '{_font()}'; font-size: 9pt; }}
            QComboBox::drop-down {{ border: none; width: 16px; }}
            QComboBox QAbstractItemView {{ background: #1A1A1A; color: {C.TEXT};
                         border: 1px solid {_LINE}; selection-background-color: {C.ACC_GHO}; }}
            """
        )
        for pid, (label, _host, _port) in PROVIDERS.items():
            self._prov_combo.addItem(label, userData=pid)
        self._prov_combo.currentIndexChanged.connect(self._on_provider_changed)
        row1.addWidget(prov_lbl)
        row1.addWidget(self._prov_combo, stretch=1)

        self._port_edit = _field("993")
        self._port_edit.setMaximumWidth(80)
        row1.addWidget(self._port_edit)
        lay.addLayout(row1)

        self._host_edit = _field("imap.gmail.com")
        lay.addWidget(self._host_edit)

        self._email_edit = _field("you@gmail.com")
        lay.addWidget(self._email_edit)

        self._pass_edit = _field("app password", echo=True)
        if self._account and self._account.password:
            self._pass_edit.setPlaceholderText("••••••••  (saved — type to replace)")
        lay.addWidget(self._pass_edit)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        save_btn = _btn("SAVE ACCOUNT", primary=True)
        save_btn.clicked.connect(self._save_settings)
        btns.addWidget(save_btn)
        test_btn = _btn("Test connection")
        test_btn.clicked.connect(self._test_connection)
        btns.addWidget(test_btn)
        del_btn = _btn("Delete account")
        del_btn.clicked.connect(self._delete_account)
        btns.addWidget(del_btn)
        btns.addStretch()
        done_btn = _btn("Close")
        done_btn.clicked.connect(self._close_settings)
        btns.addWidget(done_btn)
        lay.addLayout(btns)
        lay.addStretch()

        if self._account:
            self._email_edit.setText(self._account.email)
            self._host_edit.setText(self._account.host)
            self._port_edit.setText(str(self._account.port))
            idx = self._prov_combo.findData(self._account.provider)
            self._prov_combo.setCurrentIndex(max(idx, 0))
            self._apply_provider_defaults(self._account.provider, overwrite=False)
        else:
            self._prov_combo.setCurrentIndex(0)
            self._on_provider_changed()
        return panel

    # ── Actions ────────────────────────────────────────────────────────
    def _select_folder(self, name: str) -> None:
        if name == "Unread":
            self._unread_only = True
        elif name == "Starred":
            self._folder = "INBOX"
            self._unread_only = False
            self._query = ""
            self._search.clear()
            self._highlight_folder()
            self._reload(starred_only=True)
            return
        else:
            self._unread_only = False
            self._folder = name
        self._query = ""
        self._search.clear()
        self._highlight_folder()
        self._reload()

    def _on_search(self) -> None:
        self._query = self._search.text().strip()
        self._reload()

    def _reload(self, starred_only: bool = False) -> None:
        if self._busy:
            return
        account = self._account
        if not account or not account.password:
            self._status_lbl.setText("Set up your account first (⚙ Settings).")
            return
        self._busy = True
        self._status_lbl.setText("Loading mail…")
        folder, query, unread_only = self._folder, self._query, self._unread_only
        threading.Thread(
            target=self._load_worker,
            args=(account, folder, query, unread_only, starred_only),
            daemon=True,
        ).start()

    def _load_worker(
        self,
        account: MailAccount,
        folder: str,
        query: str,
        unread_only: bool,
        starred_only: bool,
    ) -> None:
        try:
            with connect(account) as conn:
                folders = list_folders(conn)
                messages = fetch_messages(
                    conn, folder=folder, limit=40, unread_only=unread_only, query=query
                )
                if starred_only:
                    messages = [m for m in messages if m.is_starred]
                self._folders_sig.emit(folders)
                self._messages_sig.emit(messages, folder)
                total_unread = sum(f.unread for f in folders)
                self._status_sig.emit(
                    f"Connected to {account.host} — {len(messages)} message(s) shown."
                )
                self._unread_sig.emit(total_unread)
        except MailError as exc:
            self._error_sig.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 — surface anything to the UI
            self._error_sig.emit(f"Mail error: {exc}")

    def _on_folders(self, folders: list[MailFolder]) -> None:
        for folder in folders:
            btn = self._folder_btns.get(folder.name)
            if btn is None and len(self._folder_btns) < 14:
                btn = QPushButton(folder.name)
                btn.setFixedHeight(26)
                btn.setFont(QFont(_font(), 9))
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(lambda _c, n=folder.name: self._select_folder(n))
                self._folder_btns[folder.name] = btn
            if btn is not None:
                label = folder.name
                if folder.unread:
                    label = f"{folder.name}   {folder.unread}"
                btn.setText(label)
        self._highlight_folder()

    def _on_messages(self, messages: list[MailMessage], folder: str) -> None:
        self._busy = False
        self._messages = messages
        self._list.clear()
        for msg in messages:
            self._render_row(msg)
        if not messages:
            item = QListWidgetItem("No messages here.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(item)
        self._current = None
        self._subject_lbl.setText("Select a message")
        self._meta_lbl.setText("")
        self._body.clear()

    def _on_error(self, message: str) -> None:
        self._busy = False
        self._status_lbl.setText(message)
        if "Login failed" in message or "No mail password" in message:
            self._open_settings()

    def _on_select(self, current: QListWidgetItem | None, _prev: QListWidgetItem | None) -> None:
        if current is None:
            return
        uid = current.data(Qt.ItemDataRole.UserRole)
        if not uid or not self._account:
            return
        msg = next((m for m in self._messages if m.uid == uid), None)
        if msg is None:
            return
        self._current = msg
        self._subject_lbl.setText(msg.subject)
        self._meta_lbl.setText(
            f"From: {msg.sender or msg.sender_address}   To: {msg.to or self._account.email}\n"
            f"Date: {msg.date_text or '-'}"
        )
        self._read_btn.setText("Mark unread" if msg.is_unread else "Mark read")
        self._star_btn.setText("★ Starred" if msg.is_starred else "☆ Star")
        self._body.setPlainText(msg.body or "Loading…")
        account = self._account
        folder = self._folder
        threading.Thread(
            target=self._body_worker, args=(account, uid, folder), daemon=True
        ).start()

    def _body_worker(self, account: MailAccount | None, uid: str, folder: str) -> None:
        if account is None:
            return
        try:
            with connect(account) as conn:
                full = fetch_body(conn, uid, folder=folder)
            self._body_sig.emit(full)
        except Exception as exc:  # noqa: BLE001 — read pane shows the failure
            self._error_sig.emit(f"Could not load message: {exc}")

    def _on_body(self, msg: object) -> None:
        if not isinstance(msg, MailMessage) or self._current is None:
            return
        if msg.uid != self._current.uid:
            return
        self._current = msg
        self._body.setPlainText(msg.body or "(empty message)")
        if msg.is_unread:
            msg.is_unread = False
            self._read_btn.setText("Mark unread")
            self._refresh_row(msg)
        if msg.has_attachments:
            self._meta_lbl.setText(self._meta_lbl.text() + "\n📎 Has attachments")

    def _refresh_row(self, msg: MailMessage) -> None:
        row_index = next(
            (i for i, m in enumerate(self._messages) if m.uid == msg.uid), None
        )
        if row_index is None:
            return
        self._messages[row_index] = msg
        item = self._list.item(row_index)
        if item is None:
            return
        # block signals: re-selecting the row must not re-fetch the body
        self._list.blockSignals(True)
        self._list.takeItem(row_index)
        new_item = self._render_row(msg)
        self._list.insertItem(row_index, new_item)
        self._list.setCurrentItem(new_item)
        self._list.blockSignals(False)

    def _toggle_read(self) -> None:
        msg, account = self._current, self._account
        if not msg or not account:
            return
        target = not msg.is_unread
        msg.is_unread = target
        self._read_btn.setText("Mark unread" if target else "Mark read")
        self._refresh_row(msg)
        threading.Thread(
            target=self._flag_worker, args=(account, msg.uid, target, self._folder), daemon=True
        ).start()

    def _toggle_star(self) -> None:
        msg, account = self._current, self._account
        if not msg or not account:
            return
        target = not msg.is_starred
        msg.is_starred = target
        self._star_btn.setText("★ Starred" if target else "☆ Star")
        self._refresh_row(msg)
        threading.Thread(
            target=self._star_worker, args=(account, msg.uid, target, self._folder), daemon=True
        ).start()

    @staticmethod
    def _flag_worker(account: MailAccount, uid: str, seen: bool, folder: str) -> None:
        try:
            with connect(account) as conn:
                set_seen(conn, uid, seen=seen, folder=folder)
        except Exception:
            pass

    @staticmethod
    def _star_worker(account: MailAccount, uid: str, starred: bool, folder: str) -> None:
        try:
            with connect(account) as conn:
                set_starred(conn, uid, starred=starred, folder=folder)
        except Exception:
            pass

    def _mark_all_read(self) -> None:
        account = self._account
        if not account:
            return
        folder = self._folder if self._folder not in ("Unread", "Starred") else "INBOX"
        self._status_lbl.setText(f"Marking {folder} read…")
        threading.Thread(target=self._mark_read_worker, args=(account, folder), daemon=True).start()

    def _mark_read_worker(self, account: MailAccount, folder: str) -> None:
        try:
            with connect(account) as conn:
                count = mark_folder_read(conn, folder)
            self._status_sig.emit(f"Marked {count} message(s) read in {folder}.")
            QTimer.singleShot(0, self._reload)
        except Exception as exc:  # noqa: BLE001
            self._error_sig.emit(str(exc))

    def _open_web(self) -> None:
        import webbrowser

        if self._account:
            webbrowser.open(webmail_url(self._account))

    # ── Settings handlers ──────────────────────────────────────────────
    def _toggle_settings(self) -> None:
        if self._settings.isVisible():
            self._close_settings()
        else:
            self._open_settings()

    def _open_settings(self) -> None:
        self._panes.hide()
        self._settings.show()
        self._status_lbl.setText("Editing mail account…")

    def _close_settings(self) -> None:
        self._settings.hide()
        self._panes.show()
        if self._account:
            self._reload()

    def _on_provider_changed(self) -> None:
        pid = self._prov_combo.currentData() or "gmail"
        self._apply_provider_defaults(str(pid), overwrite=True)

    def _apply_provider_defaults(self, pid: str, overwrite: bool = True) -> None:
        preset = PROVIDERS.get(pid)
        if not preset:
            return
        _label, host, port = preset
        if host and (overwrite or not self._host_edit.text().strip()):
            self._host_edit.setText(host)
        if overwrite or not self._port_edit.text().strip():
            self._port_edit.setText(str(port))

    def _collect_account(self) -> MailAccount:
        pid = str(self._prov_combo.currentData() or "gmail")
        email_addr = self._email_edit.text().strip()
        host = self._host_edit.text().strip() or (PROVIDERS.get(pid, ("", "", 993))[1])
        try:
            port = int(self._port_edit.text().strip() or PROVIDERS.get(pid, ("", "", 993))[2])
        except ValueError as exc:
            raise MailError("Port must be a number (usually 993).") from exc
        password = self._pass_edit.text().strip()
        if self._account and not password:
            password = self._account.password
        if not email_addr:
            raise MailError("Enter your email address.")
        if not password:
            raise MailError("Enter the app password.")
        return MailAccount(
            email=email_addr, password=password, provider=pid, host=host, port=port
        )

    def _save_settings(self) -> None:
        try:
            account = self._collect_account()
        except MailError as exc:
            self._status_lbl.setText(str(exc))
            return
        try:
            save_account(account)
        except MailError as exc:
            self._status_lbl.setText(str(exc))
            return
        self._saved_sig.emit()

    def _on_saved(self) -> None:
        self._account = load_account()
        if self._account:
            self._acct_lbl.setText(self._account.email)
        self._pass_edit.clear()
        self._pass_edit.setPlaceholderText("••••••••  (saved — type to replace)")
        self._status_lbl.setText("Account saved. Testing connection…")
        self._test_connection()

    def _test_connection(self) -> None:
        try:
            account = self._collect_account()
        except MailError as exc:
            self._status_lbl.setText(str(exc))
            return
        threading.Thread(target=self._test_worker, args=(account,), daemon=True).start()

    def _test_worker(self, account: MailAccount) -> None:
        try:
            with connect(account, timeout=15.0) as conn:
                conn.select("INBOX")
            self._status_sig.emit(f"✓ Connected — {account.email} on {account.host}.")
            QTimer.singleShot(0, self._close_settings)
        except Exception as exc:  # noqa: BLE001
            self._error_sig.emit(str(exc))

    def _delete_account(self) -> None:
        delete_account()
        self._account = None
        self._acct_lbl.setText("not connected")
        self._list.clear()
        self._body.clear()
        self._subject_lbl.setText("Select a message")
        self._meta_lbl.setText("")
        self._unread_lbl.setText("")
        self._status_lbl.setText("Account removed.")
        self._email_edit.clear()
        self._pass_edit.clear()
        self._pass_edit.setPlaceholderText("app password")
