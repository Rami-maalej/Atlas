"""Qt smoke tests for the Gmail-style mail screen (offscreen)."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from core import mail_overlay as mo
from core.mail_client import MailMessage


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def overlay(qapp, monkeypatch):
    """Overlay built with no saved account (settings panel opens)."""
    from core.mail_client import MailError

    monkeypatch.setattr(mo, "load_account", lambda: None)

    def _offline(*_args, **_kwargs):
        raise MailError("offline test")

    monkeypatch.setattr(mo, "connect", _offline)
    ov = mo.MailOverlay()
    ov.show()
    qapp.processEvents()
    yield ov
    ov.hide()
    ov.deleteLater()


def test_overlay_builds_three_panes(overlay) -> None:
    assert overlay._list is not None
    assert overlay._body is not None
    assert overlay._folder_btns["INBOX"] is not None
    assert overlay._search is not None


def test_no_account_opens_settings(overlay) -> None:
    assert overlay._account is None
    assert overlay._settings.isVisible()
    assert not overlay._panes.isVisible()
    assert "account" in overlay._status_lbl.text().lower()


def test_settings_close_returns_to_panes(overlay) -> None:
    overlay._close_settings()
    assert not overlay._settings.isVisible()
    assert overlay._panes.isVisible()


def test_provider_defaults_fill_host(overlay) -> None:
    overlay._prov_combo.setCurrentIndex(0)  # Gmail
    overlay._on_provider_changed()
    assert overlay._host_edit.text() == "imap.gmail.com"
    assert overlay._port_edit.text() == "993"


def test_save_requires_email_and_password(overlay) -> None:
    overlay._email_edit.clear()
    overlay._pass_edit.clear()
    overlay._save_settings()
    assert "email" in overlay._status_lbl.text().lower()


def test_render_row_and_select(overlay) -> None:
    from core.mail_client import MailAccount

    overlay._account = MailAccount(email="me@example.com", password="pw")
    msg = MailMessage(
        uid="42",
        subject="Hello there",
        sender="Jane",
        sender_address="jane@example.com",
        preview="The quick brown fox…",
        is_unread=True,
        date_text="14:03",
    )
    overlay._messages = [msg]
    overlay._render_row(msg)
    assert overlay._list.count() == 1

    overlay._list.setCurrentRow(0)
    assert overlay._subject_lbl.text() == "Hello there"
    assert "Jane" in overlay._meta_lbl.text()


def test_search_triggers_reload_guard(overlay, monkeypatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(overlay, "_reload", lambda *a, **k: called.append("x"))
    overlay._search.setText("invoice")
    overlay._on_search()
    assert called == ["x"]
    assert overlay._query == "invoice"


def test_mainwindow_wires_mail_entrypoints() -> None:
    import ui

    assert hasattr(ui.MainWindow, "_show_mail")
    assert hasattr(ui.MainWindow, "open_mail_screen")
    assert hasattr(ui.JarvisUI, "open_mail_screen")
    # menu list contains the Mail button
    import inspect

    src = inspect.getsource(ui.MainWindow._build_bottom_bar) if hasattr(
        ui.MainWindow, "_build_bottom_bar"
    ) else inspect.getsource(ui.MainWindow)
    assert '("Mail", self._show_mail)' in src
